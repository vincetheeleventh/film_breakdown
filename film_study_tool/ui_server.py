from __future__ import annotations

import csv
import base64
import hashlib
import html as html_lib
import json
import mimetypes
import os
import posixpath
import re
import shutil
import subprocess
import sys
import threading
import time
from argparse import ArgumentParser, Namespace
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from email.parser import BytesParser
from email.policy import default as email_policy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
from urllib.parse import parse_qsl, unquote, urlencode, urlparse

from .cli import run as run_breakdown, write_manifest_csv
from .models import Shot, ShotAnalysis
from .video import VideoToolError, _require_binary, _run, detect_shot_boundaries
from .workbook import write_workbook


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = ROOT / "outputs"
DATA_DIR = ROOT / "data"
STATIC_DIR = ROOT / "film_study_tool" / "ui_static"
LLM_INSTRUCTIONS_PATH = ROOT / "film_study_tool" / "llm_instructions.md"
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}
CAPTION_LANGS = "en,en-orig,en-US,en-GB"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
QWEN_COMPATIBLE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
GEMINI_INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
GEMINI_FILES_UPLOAD_URL = "https://generativelanguage.googleapis.com/upload/v1beta/files"
GEMINI_FILE_GET_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_INLINE_VIDEO_LIMIT_BYTES = 20 * 1024 * 1024
DEFAULT_QWEN_VIDEO_MODEL = "qwen3.5-omni-plus"
DEFAULT_QWEN_NARRATIVE_MODEL = "qwen3.7-plus"
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"
OUTLINE_FILENAME = "outline.json"
OUTLINE_CSV_FILENAME = "outline.csv"
STUDY_CONTEXT_FILENAME = "study_context.txt"
LAST_LLM_RESPONSE_FILENAME = "last_llm_response.json"
LAST_LLM_ERROR_FILENAME = "last_llm_error.json"
PROJECT_META_FILENAME = "project_meta.json"
ANALYSIS_SESSION_FILENAME = "analysis_session.json"
ANALYSIS_RUNS_FILENAME = "analysis_runs.jsonl"
CUT_REVIEW_FILENAME = "cut_review.json"
FILM_CONVERSATION_FILENAME = "film_conversation.json"
AI_EXPORT_FILENAME = "film_study_for_ai.md"
FOLDER_MARKER_FILENAME = ".film-study-folder"
LIBRARY_MIGRATION_MARKER = ".directory-library-v1"
# Alibaba caps the complete encoded request, including stills and prompt, at about 10 MB.
QWEN_BASE64_VIDEO_LIMIT_BYTES = 3_500_000
QWEN_ANALYSIS_SEGMENT_SECONDS = 90.0
ANALYSIS_BATCH_MAX_SHOTS = 10
ANALYSIS_BATCH_MAX_SECONDS = 60.0
ANALYSIS_BATCH_MAX_CANDIDATE_REFERENCES = 10
MAX_VIDEO_MINUTES = 30.0
NARRATIVE_CONTINUITY_VERSION = 4
SENTENCE_OUTLINE_VERSION = 1
ANALYSIS_JOBS: dict[str, dict[str, object]] = {}
ANALYSIS_JOBS_LOCK = threading.Lock()
ANALYSIS_RUNS_LOCK = threading.Lock()
API_USAGE_CONTEXT = threading.local()
REQUIRED_ANALYSIS_FIELDS = (
    "shot_title",
    "visual_description",
    "audio_dialogue",
    "action_camera",
    "camera_movement_type",
    "camera_movement_intensity",
    "camera_movement_confidence",
    "camera_movement_evidence",
    "narrative_function",
)
AI_SHOT_DETECTION_INSTRUCTIONS = """You are a meticulous film editor reviewing shot boundaries.
Watch the complete attached video. Identify every visual transition between distinct shots, including hard cuts,
dissolves, crossfades, fades, wipes, and transitions hidden by camera or subject motion. The visible SHOT label
shows the user's current timeline segment; it is a reference, not proof that the segment contains only one shot.
Return precise timestamps in seconds. Do not invent transitions for camera movement, reframing, animation within
one composition, lighting changes, or subject movement. Return JSON only."""
NARRATIVE_CONTINUITY_INSTRUCTIONS = """You are the continuity editor and narrative analyst for a film study.
You receive a complete chronological catalogue assembled from grounded video analysis. Reconcile each requested
shot's narrative function against everything that happens before and after it. A recurring character is introduced
only at their first supported appearance. Later appearances continue, reinforce, complicate, echo, reverse, or pay
off established information. Track desire, obstacle, causality, setup/payoff, motifs, emotional turns, withheld
information, and editing logic. Downloaded English subtitles are authoritative lexical evidence for spoken meaning;
use them when explaining what information dialogue contributes, even when the original soundtrack is in another
language. Work in a closed world: franchise knowledge, face familiarity, and a name merely mentioned in dialogue
are not identity evidence. Give uncertain people stable neutral labels until the film, user notes, or a human-edited
field establishes a name. Never invent plot facts. Preserve exact analysis_id values and return JSON only."""


def update_analysis_job(project_id: str, **changes: object) -> dict[str, object]:
    with ANALYSIS_JOBS_LOCK:
        current = dict(ANALYSIS_JOBS.get(project_id, {}))
        current.update(changes)
        if current.get("status") in {"completed", "failed"}:
            started_monotonic = current.pop("_startedMonotonic", None)
            if isinstance(started_monotonic, (int, float)):
                current["elapsedSeconds"] = max(0, round(time.monotonic() - started_monotonic))
        current["projectId"] = project_id
        current["updatedAt"] = datetime.now().isoformat(timespec="seconds")
        ANALYSIS_JOBS[project_id] = current
        return dict(current)


def analysis_job_status(project_id: str) -> dict[str, object]:
    with ANALYSIS_JOBS_LOCK:
        current = dict(ANALYSIS_JOBS.get(project_id, {}))
    if not current:
        return {"projectId": project_id, "status": "idle", "progress": 0}
    started_monotonic = current.pop("_startedMonotonic", None)
    if current.get("status") == "running" and isinstance(started_monotonic, (int, float)):
        current["elapsedSeconds"] = max(0, round(time.monotonic() - started_monotonic))
    current.pop("runRecorded", None)
    return current


def begin_api_usage_collection() -> None:
    API_USAGE_CONTEXT.records = []


def record_api_usage(provider: str, model: str, payload: object) -> None:
    records = getattr(API_USAGE_CONTEXT, "records", None)
    if not isinstance(records, list):
        return
    source = payload if isinstance(payload, dict) else {}
    usage = source.get("usage")
    if not isinstance(usage, dict):
        usage = source.get("usage_metadata") or source.get("usageMetadata") or {}
    usage = usage if isinstance(usage, dict) else {}

    def number(*keys: str) -> float:
        for key in keys:
            value = usage.get(key)
            if value in (None, ""):
                value = source.get(key)
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0

    input_tokens = number(
        "input_tokens",
        "prompt_tokens",
        "inputTokenCount",
        "promptTokenCount",
    )
    output_tokens = number(
        "output_tokens",
        "completion_tokens",
        "outputTokenCount",
        "candidatesTokenCount",
    )
    total_tokens = number("total_tokens", "totalTokenCount")
    if not total_tokens:
        total_tokens = input_tokens + output_tokens
    reported_cost = number("cost", "total_cost", "totalCost")
    records.append({
        "provider": provider,
        "model": model,
        "inputTokens": round(input_tokens),
        "outputTokens": round(output_tokens),
        "totalTokens": round(total_tokens),
        "reportedCost": reported_cost,
        "usageReported": bool(usage),
    })


def finish_api_usage_collection() -> dict[str, object]:
    records = getattr(API_USAGE_CONTEXT, "records", [])
    API_USAGE_CONTEXT.records = []
    valid = [record for record in records if isinstance(record, dict)]
    input_tokens = sum(safe_int(record.get("inputTokens"), 0) for record in valid)
    output_tokens = sum(safe_int(record.get("outputTokens"), 0) for record in valid)
    total_tokens = sum(safe_int(record.get("totalTokens"), 0) for record in valid)
    reported_cost = sum(float(record.get("reportedCost") or 0) for record in valid)
    providers = {str(record.get("provider") or "") for record in valid if record.get("provider")}
    models = {str(record.get("model") or "") for record in valid if record.get("model")}
    provider = next(iter(providers)) if len(providers) == 1 else ("mixed" if providers else "")
    model = next(iter(models)) if len(models) == 1 else ("mixed" if models else "")

    estimated_cost = 0.0
    estimate_available = False
    prefix = provider.upper() if provider and provider != "mixed" else ""
    try:
        input_rate = float(os.environ.get(f"{prefix}_INPUT_COST_PER_MILLION_USD", ""))
        output_rate = float(os.environ.get(f"{prefix}_OUTPUT_COST_PER_MILLION_USD", ""))
        estimated_cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
        estimate_available = True
    except (TypeError, ValueError):
        pass

    return {
        "provider": provider,
        "model": model,
        "apiCalls": len(valid),
        "calls": [
            {
                "number": index,
                "provider": str(record.get("provider") or ""),
                "model": str(record.get("model") or ""),
                "inputTokens": safe_int(record.get("inputTokens"), 0),
                "outputTokens": safe_int(record.get("outputTokens"), 0),
                "totalTokens": safe_int(record.get("totalTokens"), 0),
            }
            for index, record in enumerate(valid, start=1)
        ],
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": total_tokens or input_tokens + output_tokens,
        "tokensReported": any(bool(record.get("usageReported")) for record in valid),
        "costUsd": reported_cost if reported_cost > 0 else (estimated_cost if estimate_available else None),
        "costSource": "provider" if reported_cost > 0 else ("configured_rates" if estimate_available else "unavailable"),
    }

TIKTOK_POPULAR_OVERRIDES: dict[str, list[dict[str, object]]] = {
    "annalaura_art": [
        {
            "title": "Leave it behind. It'll be okay",
            "url": "https://www.tiktok.com/@annalaura_art/video/7070622806387576110",
            "view_count": 8_000_000,
        },
        {
            "title": "We were together. I forget the rest",
            "url": "https://www.tiktok.com/@annalaura_art/video/7085378127077297454",
            "view_count": 7_900_000,
        },
        {
            "title": "tomato soup and grilled mooncheese",
            "url": "https://www.tiktok.com/@annalaura_art/photo/7241273050002476334",
            "view_count": 7_500_000,
            "kind": "photo",
        },
        {
            "title": "in my world the sun rises twice",
            "url": "https://www.tiktok.com/@annalaura_art/video/7593741953213271310",
            "view_count": 7_000_000,
        },
        {
            "title": "My home! My sweet home!",
            "url": "https://www.tiktok.com/@annalaura_art/video/7650609186463616269",
            "view_count": 6_900_000,
        },
        {
            "title": "see you there!",
            "url": "https://www.tiktok.com/@annalaura_art/photo/7318818410148744490",
            "view_count": 6_400_000,
            "kind": "photo",
        },
        {
            "title": "courage to be happy",
            "url": "https://www.tiktok.com/@annalaura_art/video/7092836943565835563",
            "view_count": 6_300_000,
        },
        {
            "title": "the point, being.",
            "url": "https://www.tiktok.com/@annalaura_art/photo/7352209344030870830",
            "view_count": 6_000_000,
            "kind": "photo",
        },
        {
            "title": "gratitude 4 u!",
            "url": "https://www.tiktok.com/@annalaura_art/video/7059419110102502703",
            "view_count": 4_700_000,
        },
        {
            "title": "in my world, the sun rises twice",
            "url": "https://www.tiktok.com/@annalaura_art/video/7467599787060202795",
            "view_count": 4_500_000,
        },
        {
            "title": "a reminder!",
            "url": "https://www.tiktok.com/@annalaura_art/video/7061616765444541742",
            "view_count": 4_100_000,
        },
        {
            "title": "the scenic route",
            "url": "https://www.tiktok.com/@annalaura_art/photo/7154816448198675754",
            "view_count": 3_800_000,
            "kind": "photo",
        },
    ],
}


@dataclass(frozen=True)
class ServerConfig:
    outputs_dir: Path
    static_dir: Path
    data_dir: Path


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip('"').strip("'")


def safe_project_path(outputs_dir: Path, project_id: str) -> Path:
    root = outputs_dir.resolve()
    if not project_id or Path(project_id).name != project_id:
        raise ValueError("Invalid project id")
    direct = (root / project_id).resolve()
    if direct.is_dir() and (direct / "manifest.json").exists():
        return direct
    matches = [
        manifest.parent.resolve()
        for manifest in root.rglob("manifest.json")
        if manifest.parent.name == project_id
    ] if root.exists() else []
    if len(matches) == 1 and root in matches[0].parents:
        return matches[0]
    if len(matches) > 1:
        raise ValueError("Project id is not unique")
    if direct != root and root in direct.parents:
        return direct
    raise ValueError("Invalid project id")


def open_project_directory(outputs_dir: Path, project_id: str) -> dict[str, object]:
    project_dir = safe_project_path(outputs_dir, project_id)
    if not project_dir.is_dir():
        raise FileNotFoundError("Project folder not found")
    try:
        if os.name == "nt":
            selected_path = next(
                (
                    candidate
                    for candidate in [
                        project_dir / "corrected_film_study.xlsx",
                        project_dir / "film_study.xlsx",
                    ]
                    if candidate.is_file()
                ),
                None,
            )
            command = (
                ["explorer.exe", f'/select,"{selected_path}"']
                if selected_path is not None
                else ["explorer.exe", str(project_dir)]
            )
            subprocess.Popen(command)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(project_dir)])
        else:
            subprocess.Popen(["xdg-open", str(project_dir)])
    except OSError as exc:
        raise ValueError(f"Could not open the project folder: {exc}") from exc
    return {"ok": True, "projectId": project_id}


def project_manifest_path(project_dir: Path) -> Path:
    corrected = project_dir / "corrected_manifest.json"
    if corrected.exists():
        return corrected
    return project_dir / "manifest.json"


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_http_error_message(value: object, fallback: str = "Request failed") -> str:
    text = str(value or fallback)
    text = re.sub(r"[\r\n]+", " ", text).strip()
    return text[:500] or fallback


def display_project_name(project_id: str) -> str:
    name = re.sub(r"_\d{8}_\d{6}$", "", project_id)
    return name.replace("_", " ").strip().title() or project_id


def project_display_name(project_dir: Path, meta: dict[str, object] | None = None) -> str:
    meta = meta if meta is not None else load_project_meta(project_dir)
    custom_title = str(meta.get("title") or "").strip()
    return custom_title or display_project_name(project_dir.name)


def project_meta_path(project_dir: Path) -> Path:
    return project_dir / PROJECT_META_FILENAME


def normalize_group_path(value: object) -> list[str]:
    if isinstance(value, str):
        raw_parts = re.split(r"[\\/]+", value)
    elif isinstance(value, list):
        raw_parts = [str(part) for part in value]
    else:
        raw_parts = []
    parts = []
    for raw_part in raw_parts:
        part = re.sub(r'[<>:"|?*\x00-\x1f]', "", str(raw_part)).strip().rstrip(". ")
        if part and part not in {".", ".."}:
            parts.append(part)
    return parts[:6]


def folder_path_matches(path: list[str], prefix: list[str]) -> bool:
    if len(path) < len(prefix):
        return False
    return all(path[index].casefold() == part.casefold() for index, part in enumerate(prefix))


def folder_path_key(path: list[str]) -> str:
    return "\x1f".join(part.casefold() for part in path)


def safe_library_folder(outputs_dir: Path, path: list[str]) -> Path:
    root = outputs_dir.resolve()
    candidate = root.joinpath(*normalize_group_path(path)).resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError("Invalid folder path")
    return candidate


def list_library_folders(outputs_dir: Path) -> list[list[str]]:
    if not outputs_dir.exists():
        return []
    root = outputs_dir.resolve()
    folders: list[list[str]] = []

    def walk(directory: Path) -> None:
        for child in sorted(directory.iterdir(), key=lambda item: item.name.casefold()):
            if not child.is_dir() or (child / "manifest.json").exists():
                continue
            is_library_folder = (
                (child / FOLDER_MARKER_FILENAME).exists()
                or any(child.rglob("manifest.json"))
                or any(child.rglob(FOLDER_MARKER_FILENAME))
            )
            if not is_library_folder:
                continue
            relative = child.resolve().relative_to(root)
            folders.append(list(relative.parts))
            walk(child)

    walk(root)
    return folders


def create_library_folder(outputs_dir: Path, payload: dict[str, object]) -> dict[str, object]:
    path = normalize_group_path(payload.get("path"))
    if not path:
        raise ValueError("Enter a folder name")
    folder = safe_library_folder(outputs_dir, path)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / FOLDER_MARKER_FILENAME).touch(exist_ok=True)
    return {"ok": True, "path": path, "folders": list_library_folders(outputs_dir)}


def rename_library_folder(outputs_dir: Path, payload: dict[str, object]) -> dict[str, object]:
    old_path = normalize_group_path(payload.get("path"))
    new_path = normalize_group_path(payload.get("newPath"))
    if not old_path or not new_path:
        raise ValueError("Choose a folder and enter its new name")
    if folder_path_key(old_path) == folder_path_key(new_path):
        return {"ok": True, "path": old_path, "newPath": new_path, "folders": list_library_folders(outputs_dir)}
    source = safe_library_folder(outputs_dir, old_path)
    target = safe_library_folder(outputs_dir, new_path)
    if not source.is_dir():
        raise FileNotFoundError("Folder not found")
    if target.exists():
        raise ValueError("A folder with that name already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
    changed_projects = sync_project_group_metadata(outputs_dir)
    return {
        "ok": True,
        "path": old_path,
        "newPath": new_path,
        "projectsUpdated": changed_projects,
        "folders": list_library_folders(outputs_dir),
    }


def project_group_path(outputs_dir: Path, project_dir: Path) -> list[str]:
    root = outputs_dir.resolve()
    relative_parent = project_dir.resolve().parent.relative_to(root)
    return [] if str(relative_parent) == "." else list(relative_parent.parts)


def load_project_meta(project_dir: Path) -> dict[str, object]:
    path = project_meta_path(project_dir)
    if not path.exists():
        return {}
    try:
        meta = load_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    return meta if isinstance(meta, dict) else {}


def save_project_meta(project_dir: Path, meta: dict[str, object]) -> dict[str, object]:
    cleaned = dict(meta)
    cleaned["groupPath"] = normalize_group_path(cleaned.get("groupPath", []))
    project_meta_path(project_dir).write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
    return cleaned


def move_project_directory(outputs_dir: Path, project_dir: Path, group_path: list[str]) -> Path:
    normalized = normalize_group_path(group_path)
    target_parent = outputs_dir.resolve() if not normalized else safe_library_folder(outputs_dir, normalized)
    target_parent.mkdir(parents=True, exist_ok=True)
    if normalized:
        (target_parent / FOLDER_MARKER_FILENAME).touch(exist_ok=True)
    target = target_parent / project_dir.name
    if target.resolve() == project_dir.resolve():
        return project_dir
    if target.exists():
        raise ValueError(f'A study named "{project_dir.name}" already exists in that folder')
    moved = Path(shutil.move(str(project_dir), str(target)))
    return moved.resolve()


def find_project_directories(outputs_dir: Path) -> list[Path]:
    if not outputs_dir.exists():
        return []
    return [manifest.parent for manifest in outputs_dir.rglob("manifest.json")]


def sync_project_group_metadata(outputs_dir: Path) -> list[str]:
    changed: list[str] = []
    for project_dir in find_project_directories(outputs_dir):
        actual_group = project_group_path(outputs_dir, project_dir)
        if actual_group:
            (safe_library_folder(outputs_dir, actual_group) / FOLDER_MARKER_FILENAME).touch(exist_ok=True)
        meta = load_project_meta(project_dir)
        if normalize_group_path(meta.get("groupPath")) == actual_group:
            continue
        meta["groupPath"] = actual_group
        save_project_meta(project_dir, meta)
        changed.append(project_dir.name)
    return changed


def organize_project_directories(outputs_dir: Path) -> list[str]:
    moved: list[str] = []
    root = outputs_dir.resolve()
    migration_marker = root / LIBRARY_MIGRATION_MARKER
    if not migration_marker.exists():
        for project_dir in find_project_directories(outputs_dir):
            if project_dir.resolve().parent != root:
                continue
            desired_group = normalize_group_path(load_project_meta(project_dir).get("groupPath"))
            if not desired_group:
                continue
            destination = move_project_directory(outputs_dir, project_dir, desired_group)
            meta = load_project_meta(destination)
            meta["groupPath"] = desired_group
            save_project_meta(destination, meta)
            moved.append(destination.name)
        root.mkdir(parents=True, exist_ok=True)
        migration_marker.touch(exist_ok=True)
    sync_project_group_metadata(outputs_dir)
    return moved


def analysis_session_path(project_dir: Path) -> Path:
    return project_dir / ANALYSIS_SESSION_FILENAME


def load_analysis_session(project_dir: Path) -> dict[str, object]:
    path = analysis_session_path(project_dir)
    if not path.exists():
        return {}
    try:
        session = load_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    return session if isinstance(session, dict) else {}


def save_analysis_session(project_dir: Path, session: dict[str, object]) -> dict[str, object]:
    cleaned = dict(session)
    analysis_session_path(project_dir).write_text(json.dumps(cleaned, indent=2), encoding="utf-8")
    return cleaned


def cut_review_path(project_dir: Path) -> Path:
    return project_dir / CUT_REVIEW_FILENAME


def load_cut_review(
    project_dir: Path,
    shots: list[dict[str, object]],
) -> dict[str, object]:
    path = cut_review_path(project_dir)
    if not path.exists():
        return {
            "hasScan": False,
            "stale": False,
            "pendingCount": 0,
            "suggestions": [],
        }
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    suggestions = payload.get("suggestions") if isinstance(payload.get("suggestions"), list) else []
    stale = str(payload.get("timelineRevision") or "") != timeline_revision(shots)
    return {
        **payload,
        "hasScan": True,
        "stale": stale,
        "pendingCount": 0 if stale else len(suggestions),
        "suggestions": [] if stale else suggestions,
    }


def save_cut_review(
    project_dir: Path,
    shots: list[dict[str, object]],
    suggestions: list[dict[str, object]],
    provider: str,
    model: str,
    applied_suggestions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    applied = applied_suggestions or []
    payload = {
        "version": 2,
        "scannedAt": datetime.now().isoformat(timespec="seconds"),
        "timelineRevision": timeline_revision(shots),
        "provider": provider,
        "model": model,
        "detectedCount": len(suggestions) + len(applied),
        "appliedCount": len(applied),
        "appliedSuggestions": applied,
        "suggestions": suggestions,
    }
    cut_review_path(project_dir).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return load_cut_review(project_dir, shots)


def analysis_runs_path(project_dir: Path) -> Path:
    return project_dir / ANALYSIS_RUNS_FILENAME


def append_analysis_run(project_dir: Path, record: dict[str, object]) -> dict[str, object]:
    cleaned = {key: value for key, value in record.items() if value is not None}
    project_dir.mkdir(parents=True, exist_ok=True)
    with ANALYSIS_RUNS_LOCK:
        with analysis_runs_path(project_dir).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(cleaned, ensure_ascii=True) + "\n")
    return cleaned


def legacy_analysis_runs(
    project_dir: Path,
    session: dict[str, object],
) -> list[dict[str, object]]:
    history = session.get("history") if isinstance(session.get("history"), list) else []
    runs: list[dict[str, object]] = []
    for index, raw in enumerate(history):
        if not isinstance(raw, dict):
            continue
        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        if not usage and index == len(history) - 1:
            usage = legacy_analysis_usage(project_dir, session)
        runs.append({
            "runId": f"legacy-{index + 1}",
            "status": "completed",
            "startedAt": raw.get("at"),
            "completedAt": raw.get("at"),
            "elapsedSeconds": None,
            "provider": str(raw.get("provider") or session.get("provider") or ""),
            "model": str(raw.get("model") or session.get("model") or ""),
            "mode": str(raw.get("mode") or "full"),
            "analyzedShotCount": safe_int(raw.get("analyzedShotCount"), 0),
            "totalShotCount": None,
            "batchCount": safe_int(usage.get("apiCalls"), 0),
            "message": "Earlier analysis completed before detailed run tracking was enabled.",
            "timelineRevision": str(raw.get("timelineRevision") or ""),
            "usage": usage,
            "legacy": True,
        })
    if runs:
        return runs
    usage = legacy_analysis_usage(project_dir, session)
    if not usage:
        return []
    return [{
        "runId": "legacy-1",
        "status": "completed",
        "startedAt": session.get("updatedAt") or session.get("firstAnalyzedAt"),
        "completedAt": session.get("updatedAt") or session.get("firstAnalyzedAt"),
        "elapsedSeconds": None,
        "provider": str(session.get("provider") or usage.get("provider") or ""),
        "model": str(session.get("model") or usage.get("model") or ""),
        "mode": "full",
        "analyzedShotCount": 0,
        "totalShotCount": None,
        "batchCount": safe_int(usage.get("apiCalls"), 0),
        "message": "Earlier analysis completed before detailed run tracking was enabled.",
        "timelineRevision": str(session.get("timelineRevision") or ""),
        "usage": usage,
        "legacy": True,
    }]


def load_analysis_runs(
    project_dir: Path,
    session: dict[str, object] | None = None,
    limit: int = 30,
) -> list[dict[str, object]]:
    path = analysis_runs_path(project_dir)
    runs: list[dict[str, object]] = []
    if path.exists():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                runs.append(value)
    loaded_session = session or load_analysis_session(project_dir)
    legacy_runs = legacy_analysis_runs(project_dir, loaded_session)
    if runs:
        persisted_keys = {
            (
                str(run.get("completedAt") or ""),
                str(run.get("model") or ""),
                str(run.get("mode") or ""),
            )
            for run in runs
        }
        legacy_runs = [
            run
            for run in legacy_runs
            if (
                str(run.get("completedAt") or ""),
                str(run.get("model") or ""),
                str(run.get("mode") or ""),
            ) not in persisted_keys
        ]
        runs = [*legacy_runs, *runs]
    else:
        runs = legacy_runs
    return list(reversed(runs[-max(1, limit):]))


def record_analysis_run(
    project_dir: Path,
    project_id: str,
    **details: object,
) -> dict[str, object]:
    with ANALYSIS_JOBS_LOCK:
        job = dict(ANALYSIS_JOBS.get(project_id, {}))
        if job.get("runRecorded"):
            return {}
        started_monotonic = job.get("_startedMonotonic")
        elapsed = (
            max(0, round(time.monotonic() - float(started_monotonic)))
            if isinstance(started_monotonic, (int, float))
            else job.get("elapsedSeconds")
        )
        record = {
            "version": 1,
            "runId": str(job.get("runId") or f"run-{time.time_ns()}"),
            "status": str(details.get("status") or job.get("status") or "completed"),
            "startedAt": details.get("startedAt") or job.get("startedAt"),
            "completedAt": details.get("completedAt") or job.get("completedAt")
            or datetime.now().isoformat(timespec="seconds"),
            "elapsedSeconds": details.get("elapsedSeconds", elapsed),
            "provider": str(details.get("provider") or job.get("provider") or ""),
            "model": str(details.get("model") or job.get("model") or ""),
            "mode": str(details.get("mode") or job.get("analysisMode") or ""),
            "analyzedShotCount": safe_int(details.get("analyzedShotCount"), 0),
            "totalShotCount": details.get("totalShotCount"),
            "batchCount": safe_int(details.get("batchCount", job.get("batchCount")), 0),
            "cutDetectedCount": safe_int(details.get("cutDetectedCount"), 0),
            "cutAppliedCount": safe_int(details.get("cutAppliedCount"), 0),
            "cutPendingCount": safe_int(details.get("cutPendingCount"), 0),
            "message": str(details.get("message") or job.get("message") or ""),
            "timelineRevision": str(details.get("timelineRevision") or ""),
            "usage": details.get("usage") if isinstance(details.get("usage"), dict)
            else (job.get("usage") if isinstance(job.get("usage"), dict) else {}),
            "error": str(details.get("error") or ""),
            "legacy": False,
        }
        append_analysis_run(project_dir, record)
        current = dict(ANALYSIS_JOBS.get(project_id, {}))
        current["runRecorded"] = True
        ANALYSIS_JOBS[project_id] = current
    return record


def timeline_analysis_id(row: dict[str, object], index: int = 0) -> str:
    try:
        start_ms = round(_seconds_from_timestamp(str(row.get("start", ""))) * 1000)
        end_ms = round(_seconds_from_timestamp(str(row.get("end", ""))) * 1000)
    except (TypeError, ValueError):
        start_ms = index
        end_ms = index + 1
    digest = hashlib.sha1(f"{start_ms}:{end_ms}".encode("ascii")).hexdigest()[:12]
    return f"shot_{start_ms}_{end_ms}_{digest}"


def timeline_revision(shots: list[dict[str, object]]) -> str:
    identities = [timeline_analysis_id(row, index) for index, row in enumerate(shots)]
    return hashlib.sha256(json.dumps(identities).encode("utf-8")).hexdigest()[:16]


def included_analysis_shots(shots: list[dict[str, object]]) -> list[dict[str, object]]:
    return [row for row in shots if not bool(row.get("analysis_excluded"))]


def analysis_scope_revision(shots: list[dict[str, object]]) -> str:
    identities = [
        timeline_analysis_id(row, index)
        for index, row in enumerate(shots)
        if not bool(row.get("analysis_excluded"))
    ]
    return hashlib.sha256(json.dumps(identities).encode("utf-8")).hexdigest()[:16]


def analysis_scope_intervals(shots: list[dict[str, object]]) -> list[tuple[float, float]]:
    intervals: list[tuple[float, float]] = []
    for row in shots:
        if bool(row.get("analysis_excluded")):
            continue
        start = _seconds_from_timestamp(str(row.get("start", "00:00:00.000")))
        end = _seconds_from_timestamp(str(row.get("end", "00:00:00.000")))
        if end <= start:
            continue
        if intervals and start <= intervals[-1][1] + 0.05:
            intervals[-1] = (intervals[-1][0], max(intervals[-1][1], end))
        else:
            intervals.append((start, end))
    return intervals


def source_video_fingerprint(video_path: Path) -> str:
    stat = video_path.stat()
    payload = f"{video_path.name}:{stat.st_size}:{stat.st_mtime_ns}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def shot_requires_analysis(
    row: dict[str, object],
    index: int,
    session: dict[str, object],
) -> bool:
    if bool(row.get("analysis_excluded")):
        return False
    if bool(row.get("analysis_stale")):
        return True
    analyzed = session.get("analyzedShots")
    if not isinstance(analyzed, dict):
        return True
    analysis_id = timeline_analysis_id(row, index)
    if analysis_id not in analyzed:
        return True
    required_fields = ["shot_title", "visual_description", "action_camera", "narrative_function"]
    return any(
        not is_manual_field(row, field)
        and is_placeholder_field_value(field, str(row.get(field, "")), index)
        for field in required_fields
    )


def analysis_session_summary(
    project_dir: Path,
    shots: list[dict[str, object]],
) -> dict[str, object]:
    session = load_analysis_session(project_dir)
    last_usage = session.get("lastUsage") if isinstance(session.get("lastUsage"), dict) else {}
    if not last_usage:
        last_usage = legacy_analysis_usage(project_dir, session)
    current_context_hash = hashlib.sha256(
        load_study_context(project_dir).strip().encode("utf-8")
    ).hexdigest()[:16]
    changed = [
        timeline_analysis_id(row, index)
        for index, row in enumerate(shots)
        if shot_requires_analysis(row, index, session)
    ]
    existing_outline = load_outline(project_dir, len(shots))
    included_count = len(included_analysis_shots(shots))
    scope_revision = analysis_scope_revision(shots)
    saved_scope_revision = str(session.get("analysisScopeRevision") or "")
    scope_changed = bool(session.get("hasFullAnalysis")) and (
        (bool(saved_scope_revision) and saved_scope_revision != scope_revision)
        or (not saved_scope_revision and included_count != len(shots))
    )
    return {
        "hasFullAnalysis": bool(session.get("hasFullAnalysis")),
        "provider": str(session.get("provider") or ""),
        "model": str(session.get("model") or ""),
        "narrativeProvider": str(session.get("narrativeProvider") or ""),
        "narrativeModel": str(session.get("narrativeModel") or ""),
        "firstAnalyzedAt": session.get("firstAnalyzedAt"),
        "updatedAt": session.get("updatedAt"),
        "analysisRevision": safe_int(session.get("analysisRevision"), 0),
        "timelineRevision": str(session.get("timelineRevision") or ""),
        "currentTimelineRevision": timeline_revision(shots),
        "changedShotCount": len(changed),
        "includedShotCount": included_count,
        "excludedShotCount": len(shots) - included_count,
        "analysisScopeRevision": scope_revision,
        "scopeChanged": scope_changed,
        "contextChanged": bool(session.get("hasFullAnalysis"))
        and str(session.get("userContextHash") or "") != current_context_hash,
        "needsNarrativeContinuity": bool(session.get("hasFullAnalysis"))
        and safe_int(session.get("narrativeContinuityVersion"), 0) < NARRATIVE_CONTINUITY_VERSION,
        "needsAiCutUpgrade": bool(session.get("hasFullAnalysis"))
        and safe_int(session.get("aiCutAutomationVersion"), 0) < 2,
        "needsSentenceOutline": bool(session.get("hasFullAnalysis"))
        and safe_int(session.get("sentenceOutlineVersion"), 0) < SENTENCE_OUTLINE_VERSION
        and not bool(existing_outline["sentences"]),
        "filmMemory": session.get("filmMemory") if isinstance(session.get("filmMemory"), dict) else {},
        "lastUsage": last_usage,
        "analysisHistory": load_analysis_runs(project_dir, session),
    }


def legacy_analysis_usage(project_dir: Path, session: dict[str, object]) -> dict[str, object]:
    history_path = project_dir / "llm_response_history.jsonl"
    if not history_path.exists():
        return {}
    try:
        lines = history_path.read_text(encoding="utf-8").splitlines()[-100:]
    except OSError:
        return {}
    records: list[dict[str, object]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    if not records:
        return {}
    model = str(session.get("model") or records[-1].get("model") or "")
    latest_run: list[dict[str, object]] = []
    for record in reversed(records):
        if model and str(record.get("model") or "") != model:
            break
        latest_run.append(record)
        if safe_int(record.get("batchNumber"), 1) == 1:
            break
    if not latest_run:
        return {}
    return {
        "provider": str(session.get("provider") or latest_run[0].get("provider") or ""),
        "model": model,
        "apiCalls": len(latest_run),
        "inputTokens": 0,
        "outputTokens": 0,
        "totalTokens": 0,
        "tokensReported": False,
        "costUsd": None,
        "costSource": "unavailable",
        "legacy": True,
    }


def normalize_cover_crop(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return {"x": 50.0, "y": 50.0}
    crop: dict[str, float] = {}
    for axis in ["x", "y"]:
        try:
            number = float(value.get(axis, 50))
        except (TypeError, ValueError):
            number = 50.0
        crop[axis] = max(0.0, min(100.0, number))
    return crop


def tiktok_handle_from_url(url: str) -> str:
    match = re.search(r"tiktok\.com/@([^/?#]+)", url, flags=re.IGNORECASE)
    return match.group(1).lower() if match else ""


def popular_override_entries(channel_url: str) -> list[dict[str, object]]:
    handle = tiktok_handle_from_url(channel_url)
    entries = TIKTOK_POPULAR_OVERRIDES.get(handle, [])
    return [dict(entry) for entry in entries]


def source_url_key(url: object) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/")
    query = dict(parse_qsl(parsed.query, keep_blank_values=False))

    youtube_hosts = {"youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
    if host in youtube_hosts:
        video_id = ""
        if host == "youtu.be":
            video_id = path.strip("/").split("/", 1)[0]
        elif path == "/watch":
            video_id = str(query.get("v") or "").strip()
        else:
            match = re.match(r"^/(?:shorts|embed|live)/([^/?#]+)", path)
            if match:
                video_id = match.group(1)
        if video_id:
            return f"youtube.com/watch?v={video_id}"
        return f"youtube.com{path}"

    ignored_query_keys = {
        "fbclid",
        "gclid",
        "igshid",
        "lang",
        "ref",
        "si",
        "source",
        "spm",
    }
    stable_query = [
        (key, query_value)
        for key, query_value in parse_qsl(parsed.query, keep_blank_values=False)
        if key.lower() not in ignored_query_keys and not key.lower().startswith("utm_")
    ]
    suffix = f"?{urlencode(sorted(stable_query))}" if stable_query else ""
    return f"{host}{path}{suffix}"


def extract_urls_from_text(text: object) -> list[str]:
    raw = str(text or "")
    urls: list[str] = []
    seen: set[str] = set()
    for match in re.findall(r"https?://[^\s<>)\]\"']+", raw):
        url = match.rstrip(".,;:")
        key = source_url_key(url)
        if key and key not in seen:
            seen.add(key)
            urls.append(url)
    return urls


def is_channel_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    if "tiktok.com" in host:
        return bool(re.fullmatch(r"/@[^/]+", path))
    if "youtube.com" in host:
        return path.startswith(("/@", "/channel/", "/c/", "/user/")) and not path.startswith(("/watch", "/shorts/"))
    return False


def existing_project_by_source(outputs_dir: Path, source_url: str) -> Path | None:
    wanted = source_url_key(source_url)
    if not wanted or not outputs_dir.exists():
        return None
    for meta_path in outputs_dir.rglob(PROJECT_META_FILENAME):
        meta = load_project_meta(meta_path.parent)
        if source_url_key(meta.get("sourceUrl")) == wanted:
            return meta_path.parent
    return None


def project_summary(project_dir: Path, outputs_dir: Path) -> dict[str, object]:
    rows = load_json(project_manifest_path(project_dir))
    meta = load_project_meta(project_dir)
    group_path = project_group_path(outputs_dir, project_dir)
    return {
        "id": project_dir.name,
        "name": project_display_name(project_dir, meta),
        "shotCount": len(rows) if isinstance(rows, list) else 0,
        "coverUrl": cover_url_for(project_dir, rows, meta),
        "coverShot": meta.get("coverShot"),
        "coverCrop": normalize_cover_crop(meta.get("coverCrop")),
        "groupPath": group_path,
        "sourceUrl": meta.get("sourceUrl", ""),
        "channelUrl": meta.get("channelUrl", ""),
        "channelTitle": meta.get("channelTitle", ""),
        "channelRank": meta.get("channelRank"),
        "popularityRank": meta.get("popularityRank"),
        "viewCount": meta.get("viewCount"),
        "likeCount": meta.get("likeCount"),
        "repostCount": meta.get("repostCount"),
        "commentCount": meta.get("commentCount"),
        "saveCount": meta.get("saveCount"),
        "socialStats": social_stats_from_meta(meta),
        "captionFiles": meta.get("captionFiles", []),
        "captionCueCount": meta.get("captionCueCount", 0),
        "captionShotsUpdated": meta.get("captionShotsUpdated", 0),
        "importMode": meta.get("importMode", ""),
        "screenshotOptions": screenshot_options_for(project_dir, rows),
        "hasCorrections": (project_dir / "corrected_manifest.json").exists(),
        "updatedAt": project_dir.stat().st_mtime,
    }


def screenshot_options_for(project_dir: Path, rows: object) -> list[dict[str, object]]:
    if not isinstance(rows, list):
        return []
    options: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        screenshot_name = Path(str(row.get("screenshot_path", ""))).name
        if not screenshot_name:
            continue
        shot_number = row.get("shot", index + 1)
        title = str(row.get("shot_title") or row.get("title") or f"Shot {shot_number}")
        options.append(
            {
                "shot": shot_number,
                "title": title,
                "url": f"/media/{project_dir.name}/screenshots/{screenshot_name}",
            }
        )
    return options


def social_stats_from_meta(meta: dict[str, object]) -> dict[str, object]:
    stats: dict[str, object] = {}
    for key in ["viewCount", "likeCount", "repostCount", "commentCount", "saveCount"]:
        value = meta.get(key)
        if value not in (None, ""):
            stats[key] = value
    comments = meta.get("topComments")
    if isinstance(comments, list):
        stats["topComments"] = comments[:5]
    return stats


def cover_url_for(project_dir: Path, rows: object, meta: dict[str, object] | None = None) -> str | None:
    if not isinstance(rows, list) or not rows:
        return None
    meta = meta or {}
    selected_shot = meta.get("coverShot")
    first = None
    if selected_shot is not None:
        for row in rows:
            if isinstance(row, dict) and str(row.get("shot", "")) == str(selected_shot):
                first = row
                break
    if first is None:
        first = rows[0]
    if not isinstance(first, dict):
        return None
    screenshot_name = Path(str(first.get("screenshot_path", ""))).name
    if not screenshot_name:
        return None
    return f"/media/{project_dir.name}/screenshots/{screenshot_name}"


def list_projects(outputs_dir: Path) -> list[dict[str, object]]:
    projects = []
    if not outputs_dir.exists():
        return projects
    organize_project_directories(outputs_dir)
    for project_dir in sorted(find_project_directories(outputs_dir), key=lambda item: item.stat().st_mtime, reverse=True):
        manifest_path = project_manifest_path(project_dir)
        try:
            rows = load_json(manifest_path)
        except (OSError, json.JSONDecodeError):
            continue
        projects.append(project_summary(project_dir, outputs_dir))
    return projects


def delete_project(config: ServerConfig, project_id: str) -> dict[str, object]:
    project_dir = safe_project_path(config.outputs_dir, project_id)
    if not project_dir.exists() or not project_dir.is_dir():
        raise FileNotFoundError("Project not found")

    removed = [str(project_dir)]
    shutil.rmtree(project_dir)

    data_root = config.data_dir.resolve()
    if config.data_dir.exists():
        for video_path in config.data_dir.iterdir():
            if video_path.suffix.lower() not in VIDEO_SUFFIXES or video_path.stem != project_id:
                continue
            resolved = video_path.resolve()
            if data_root == resolved.parent:
                video_path.unlink()
                removed.append(str(video_path))

    return {"ok": True, "projectId": project_id, "removed": removed}


def delete_library_folder(config: ServerConfig, payload: dict[str, object]) -> dict[str, object]:
    path = normalize_group_path(payload.get("path"))
    if not path:
        raise ValueError("Choose a folder to delete")
    folder = safe_library_folder(config.outputs_dir, path)
    if not folder.is_dir():
        raise FileNotFoundError("Folder not found")
    project_ids = [project_dir.name for project_dir in find_project_directories(folder)]
    removed: list[str] = []
    for project_id in project_ids:
        result = delete_project(config, project_id)
        removed.extend(str(item) for item in result.get("removed", []))
    if folder.exists():
        shutil.rmtree(folder)
        removed.append(str(folder))
    return {"ok": True, "path": path, "projectsDeleted": project_ids, "removed": removed}


def update_project_metadata(outputs_dir: Path, project_id: str, payload: dict[str, object]) -> dict[str, object]:
    project_dir = safe_project_path(outputs_dir, project_id)
    if not project_dir.exists() or not project_dir.is_dir():
        raise FileNotFoundError("Project not found")
    meta = load_project_meta(project_dir)
    if "title" in payload:
        title = str(payload.get("title") or "").strip()
        if not title:
            raise ValueError("Film title cannot be blank")
        meta["title"] = title[:180]
    if "groupPath" in payload:
        group_path = normalize_group_path(payload.get("groupPath"))
        project_dir = move_project_directory(outputs_dir, project_dir, group_path)
        meta["groupPath"] = group_path
    if "coverShot" in payload:
        cover_shot = payload.get("coverShot")
        meta["coverShot"] = int(cover_shot) if str(cover_shot).strip() else None
    if "coverCrop" in payload:
        meta["coverCrop"] = normalize_cover_crop(payload.get("coverCrop"))
    saved = save_project_meta(project_dir, meta)
    rows = load_json(project_manifest_path(project_dir))
    return {
        "ok": True,
        "project": {
            "id": project_dir.name,
            "name": project_display_name(project_dir, saved),
            "groupPath": saved.get("groupPath", []),
            "coverShot": saved.get("coverShot"),
            "coverCrop": normalize_cover_crop(saved.get("coverCrop")),
            "coverUrl": cover_url_for(project_dir, rows, saved),
        },
    }


def normalize_shot_row(row: dict[str, object], index: int, project_dir: Path) -> dict[str, object]:
    screenshot_path = str(row.get("screenshot_path", ""))
    screenshot_name = Path(screenshot_path).name
    shot_title = str(row.get("shot_title") or row.get("title") or _default_shot_title(row, index))
    start = str(row.get("start") or "")
    end = str(row.get("end") or "")
    try:
        duration_seconds = round(_seconds_from_timestamp(end) - _seconds_from_timestamp(start), 3)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Shot {index + 1} has invalid start or end timing") from exc
    if duration_seconds < 0:
        raise ValueError(f"Shot {index + 1} ends before it starts")
    return {
        "shot": index + 1,
        "analysis_id": timeline_analysis_id(row, index),
        "originalShot": row.get("originalShot", row.get("shot", index + 1)),
        "members": row.get("members", [row.get("shot", index + 1)]),
        "shot_title": shot_title,
        "screenshot": screenshot_name,
        "screenshotUrl": f"/media/{project_dir.name}/screenshots/{screenshot_name}",
        "screenshot_path": str((project_dir / "screenshots" / screenshot_name).resolve()),
        "start": start,
        "end": end,
        "duration_seconds": duration_seconds,
        "visual_description": row.get("visual_description", ""),
        "audio_dialogue": row.get("audio_dialogue", ""),
        "action_camera": row.get("action_camera", ""),
        "camera_movement_type": row.get("camera_movement_type", ""),
        "camera_movement_intensity": row.get("camera_movement_intensity", ""),
        "camera_movement_confidence": row.get("camera_movement_confidence", ""),
        "camera_movement_evidence": row.get("camera_movement_evidence", ""),
        "narrative_function": row.get("narrative_function", ""),
        "notes": row.get("notes", ""),
        "analysis_stale": bool(row.get("analysis_stale", False)),
        "analysis_excluded": bool(row.get("analysis_excluded", False)),
        "manual_fields": normalize_manual_fields(row.get("manual_fields")),
    }


def caption_time_to_seconds(value: str) -> float:
    cleaned = value.strip().replace(",", ".")
    parts = cleaned.split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return float(cleaned)


def clean_caption_text(text: str) -> str:
    # Karaoke/sign layers in ASS tracks can become separate SRT cues after conversion.
    if re.search(r"\{\\an7\}", text, flags=re.IGNORECASE) and "ObeliskMdITC" in text:
        return ""
    text = re.sub(r"<\d{1,2}:\d{2}:\d{2}\.\d{3}>", " ", text)
    text = re.sub(r"\{\\[^}]+\}", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if re.fullmatch(r"m(?:\s+-?\d+(?:\.\d+)?|\s+[bslpc])+[\d.\sblspc-]*", text, flags=re.IGNORECASE):
        return ""
    return text


def parse_caption_file(path: Path) -> list[dict[str, object]]:
    try:
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    cues: list[dict[str, object]] = []
    blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n").replace("\r", "\n"))
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines or lines[0].upper().startswith("WEBVTT"):
            continue
        timing_index = next((index for index, line in enumerate(lines) if "-->" in line), -1)
        if timing_index < 0:
            continue
        timing = lines[timing_index]
        match = re.match(r"([0-9:. ,]+)\s*-->\s*([0-9:. ,]+)", timing)
        if not match:
            continue
        text = clean_caption_text(" ".join(lines[timing_index + 1 :]))
        if not text:
            continue
        try:
            start = caption_time_to_seconds(match.group(1))
            end = caption_time_to_seconds(match.group(2))
        except (TypeError, ValueError):
            continue
        cues.append({"start": start, "end": end, "text": text})
    return cues


def caption_files_for_video(video_path: Path) -> list[Path]:
    patterns = [
        f"{video_path.stem}*.vtt",
        f"{video_path.stem}*.srt",
    ]
    files: list[Path] = []
    for pattern in patterns:
        files.extend(path for path in video_path.parent.glob(pattern) if path.is_file())
    return sorted(set(files), key=lambda path: (0 if ".en" in path.name.lower() else 1, path.name.lower()))


def copy_caption_files(project_dir: Path, caption_files: list[Path]) -> list[Path]:
    if not caption_files:
        return []
    captions_dir = project_dir / "captions"
    captions_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for path in caption_files:
        target = captions_dir / path.name
        try:
            shutil.copy2(path, target)
            copied.append(target)
        except OSError:
            continue
    return copied


def extract_embedded_english_subtitles(project_dir: Path, video_path: Path) -> Path | None:
    ffprobe = _require_binary("ffprobe")
    probe = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "s",
            "-show_entries",
            "stream=index,codec_name:stream_tags=language,title",
            "-of",
            "json",
            str(video_path),
        ]
    )
    if probe.returncode != 0:
        return None
    try:
        streams = json.loads(probe.stdout).get("streams", [])
    except (AttributeError, json.JSONDecodeError):
        return None
    supported_codecs = {"ass", "ssa", "subrip", "srt", "webvtt", "mov_text"}
    candidates: list[tuple[int, int]] = []
    for stream in streams if isinstance(streams, list) else []:
        if not isinstance(stream, dict):
            continue
        codec = str(stream.get("codec_name") or "").casefold()
        if codec not in supported_codecs:
            continue
        tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
        language = str(tags.get("language") or "").casefold()
        title = str(tags.get("title") or "").casefold()
        if language in {"eng", "en"} or "english" in title:
            priority = 0 if language in {"eng", "en"} else 1
            candidates.append((priority, safe_int(stream.get("index"), -1)))
    stream_index = next((index for _priority, index in sorted(candidates) if index >= 0), None)
    if stream_index is None:
        return None

    captions_dir = project_dir / "captions"
    captions_dir.mkdir(parents=True, exist_ok=True)
    output_path = captions_dir / f"{video_path.stem}.embedded.en.srt"
    ffmpeg = _require_binary("ffmpeg")
    extracted = _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video_path),
            "-map",
            f"0:{stream_index}",
            "-c:s",
            "srt",
            str(output_path),
        ]
    )
    if extracted.returncode != 0 or not output_path.is_file():
        output_path.unlink(missing_ok=True)
        return None
    return output_path


def is_placeholder_audio(value: object) -> bool:
    text = str(value or "").strip().lower()
    return not text or "audio transcription pending" in text or "future pass should align" in text


def caption_text_for_shot(cues: list[dict[str, object]], start: float, end: float) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for cue in cues:
        cue_start = float(cue.get("start", 0) or 0)
        cue_end = float(cue.get("end", 0) or 0)
        if cue_end <= start or cue_start >= end:
            continue
        text = str(cue.get("text") or "").strip()
        if text and text not in seen:
            seen.add(text)
            parts.append(text)
    return " ".join(parts)


def load_project_caption_cues(project_dir: Path) -> list[dict[str, object]]:
    captions_dir = project_dir / "captions"
    if not captions_dir.is_dir():
        return []
    caption_files = sorted(
        (path for path in captions_dir.iterdir() if path.suffix.lower() in {".vtt", ".srt"}),
        key=lambda path: (
            0 if path.name.lower().endswith(".en.vtt") else 1,
            0 if ".en-" in path.name.lower() else 1,
            path.name.lower(),
        ),
    )
    for caption_path in caption_files:
        cues = parse_caption_file(caption_path)
        if cues:
            return cues
    return []


def caption_evidence_by_analysis_id(
    rows: list[dict[str, object]],
    cues: list[dict[str, object]],
) -> dict[str, str]:
    """Map each subtitle cue to one current edited shot using the cue midpoint."""
    if not rows or not cues:
        return {}
    shot_ranges = [
        (
            _seconds_from_timestamp(str(row.get("start", "00:00:00.000"))),
            _seconds_from_timestamp(str(row.get("end", "00:00:00.000"))),
        )
        for row in rows
    ]
    assigned: list[list[str]] = [[] for _row in rows]
    seen: list[set[str]] = [set() for _row in rows]
    for cue in cues:
        cue_start = float(cue.get("start", 0) or 0)
        cue_end = float(cue.get("end", cue_start) or cue_start)
        midpoint = (cue_start + cue_end) / 2
        target_index = next(
            (
                index
                for index, (start, end) in enumerate(shot_ranges)
                if start <= midpoint < end or (index == len(shot_ranges) - 1 and midpoint == end)
            ),
            None,
        )
        if target_index is None:
            continue
        text = str(cue.get("text") or "").strip()
        if text and text not in seen[target_index]:
            seen[target_index].add(text)
            assigned[target_index].append(text)

    evidence: dict[str, str] = {}
    for index, parts in enumerate(assigned):
        if not parts:
            continue
        analysis_id = str(rows[index].get("analysis_id") or timeline_analysis_id(rows[index], index))
        evidence[analysis_id] = " ".join(parts)
    return evidence


def apply_caption_cues_to_rows(
    rows: list[dict[str, object]],
    cues: list[dict[str, object]],
) -> int:
    """Assign each caption cue to exactly one edited shot using the cue midpoint."""
    evidence = caption_evidence_by_analysis_id(rows, cues)
    updated = 0
    for index, row in enumerate(rows):
        if is_manual_field(row, "audio_dialogue"):
            continue
        analysis_id = str(row.get("analysis_id") or timeline_analysis_id(row, index))
        next_text = evidence.get(analysis_id, "")
        if str(row.get("audio_dialogue") or "") != next_text:
            row["audio_dialogue"] = next_text
            updated += 1
    return updated


def write_manifest_rows(project_dir: Path, rows: list[dict[str, object]], study_context: str = "") -> None:
    shots: list[Shot] = []
    analyses: dict[int, ShotAnalysis] = {}
    for index, row in enumerate(rows):
        number = int(row.get("shot", index + 1))
        shot = Shot(
            number=number,
            start=_seconds_from_timestamp(str(row.get("start", "00:00:00.000"))),
            end=_seconds_from_timestamp(str(row.get("end", "00:00:00.000"))),
            screenshot_path=Path(str(row.get("screenshot_path") or "")),
        )
        shots.append(shot)
        analyses[number] = ShotAnalysis(
            shot_title=str(row.get("shot_title") or "Shot Title Pending"),
            visual_description=str(row.get("visual_description") or ""),
            audio_dialogue=str(row.get("audio_dialogue") or ""),
            action_camera=str(row.get("action_camera") or ""),
            camera_movement_type=str(row.get("camera_movement_type") or ""),
            camera_movement_intensity=str(row.get("camera_movement_intensity") or ""),
            camera_movement_confidence=str(row.get("camera_movement_confidence") or ""),
            camera_movement_evidence=str(row.get("camera_movement_evidence") or ""),
            narrative_function=str(row.get("narrative_function") or ""),
            notes=str(row.get("notes") or ""),
        )
    (project_dir / "manifest.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    write_manifest_csv(project_dir / "manifest.csv", shots, analyses)
    write_workbook(project_dir / "film_study.xlsx", shots, analyses, study_context=study_context)


def enrich_project_with_captions(project_dir: Path, video_path: Path) -> dict[str, object]:
    caption_files = caption_files_for_video(video_path)
    copied_files = copy_caption_files(project_dir, caption_files)
    embedded_caption = extract_embedded_english_subtitles(project_dir, video_path)
    if embedded_caption is not None:
        copied_files.insert(0, embedded_caption)
    cues: list[dict[str, object]] = []
    for caption_path in copied_files:
        cues = parse_caption_file(caption_path)
        if cues:
            break
    if not cues:
        return {"captionFiles": [path.name for path in copied_files], "cueCount": 0, "shotsUpdated": 0}

    manifest_path = project_manifest_path(project_dir)
    rows = load_json(manifest_path)
    if not isinstance(rows, list):
        return {"captionFiles": [path.name for path in copied_files], "cueCount": len(cues), "shotsUpdated": 0}
    updated = apply_caption_cues_to_rows(rows, cues)
    if updated:
        if manifest_path.name == "corrected_manifest.json":
            save_corrected_project(
                project_dir.parent,
                project_dir.name,
                {"shots": rows, "userContext": load_study_context(project_dir), "outline": load_outline(project_dir, len(rows))},
            )
        else:
            write_manifest_rows(project_dir, rows, study_context=load_study_context(project_dir))
    return {"captionFiles": [path.name for path in copied_files], "cueCount": len(cues), "shotsUpdated": updated}


def normalize_outline(outline: object, shot_count: int) -> dict[str, object]:
    source = outline.get("sentences", []) if isinstance(outline, dict) else outline
    if not isinstance(source, list):
        source = []
    sentences = []
    for index, row in enumerate(source):
        if not isinstance(row, dict):
            continue
        raw_numbers = row.get("shotNumbers", row.get("shots", []))
        if not isinstance(raw_numbers, list):
            raw_numbers = []
        shot_numbers = []
        for value in raw_numbers:
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= number <= shot_count and number not in shot_numbers:
                shot_numbers.append(number)
        if not shot_numbers:
            continue
        sentences.append(
            {
                "id": str(row.get("id") or f"sentence-{index + 1}"),
                "beat": str(row.get("beat") or "Beat 1").strip() or "Beat 1",
                "title": str(row.get("title") or f"Sentence {index + 1}").strip() or f"Sentence {index + 1}",
                "idea": str(row.get("idea") or "").strip(),
                "shotNumbers": shot_numbers,
            }
        )
    return {"sentences": sentences}


def load_outline(project_dir: Path, shot_count: int) -> dict[str, object]:
    outline_path = project_dir / OUTLINE_FILENAME
    if not outline_path.exists():
        return {"sentences": []}
    try:
        return normalize_outline(load_json(outline_path), shot_count)
    except (OSError, json.JSONDecodeError, ValueError):
        return {"sentences": []}


def save_outline(project_dir: Path, outline: object, shot_count: int) -> dict[str, object]:
    normalized = normalize_outline(outline, shot_count)
    outline_path = project_dir / OUTLINE_FILENAME
    outline_path.write_text(json.dumps(normalized, indent=2), encoding="utf-8")

    outline_csv = project_dir / OUTLINE_CSV_FILENAME
    with outline_csv.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = ["sentence", "beat", "title", "shots", "idea"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for index, sentence in enumerate(normalized["sentences"], start=1):
            writer.writerow(
                {
                    "sentence": index,
                    "beat": sentence["beat"],
                    "title": sentence["title"],
                    "shots": ", ".join(str(number) for number in sentence["shotNumbers"]),
                    "idea": sentence["idea"],
                }
            )
    return normalized


def normalize_ai_generated_outline(
    outline: object,
    shot_count: int,
    allowed_shot_numbers: set[int] | None = None,
) -> dict[str, object]:
    normalized = normalize_outline(outline, shot_count)
    allowed = allowed_shot_numbers or set(range(1, shot_count + 1))
    repaired: list[dict[str, object]] = []
    used: set[int] = set()
    source = sorted(
        normalized["sentences"],
        key=lambda row: min(row["shotNumbers"]) if row["shotNumbers"] else shot_count + 1,
    )
    for row in source:
        available = sorted(
            number
            for number in row["shotNumbers"]
            if number in allowed and number not in used
        )
        if not available:
            continue
        runs: list[list[int]] = []
        for number in available:
            if not runs or number != runs[-1][-1] + 1:
                runs.append([number])
            else:
                runs[-1].append(number)
        for run_index, run in enumerate(runs):
            used.update(run)
            repaired.append(
                {
                    "id": str(row.get("id") or f"sentence-{len(repaired) + 1}")
                    + (f"-{run_index + 1}" if run_index else ""),
                    "beat": str(row.get("beat") or "Beat 1"),
                    "title": str(row.get("title") or f"Sentence {len(repaired) + 1}"),
                    "idea": str(row.get("idea") or ""),
                    "shotNumbers": run,
                }
            )

    for shot_number in sorted(allowed):
        if shot_number in used:
            continue
        prior_beat = repaired[-1]["beat"] if repaired else "Beat 1"
        repaired.append(
            {
                "id": f"sentence-auto-{shot_number}",
                "beat": prior_beat,
                "title": f"Shot {shot_number}",
                "idea": "",
                "shotNumbers": [shot_number],
            }
        )
    repaired.sort(key=lambda row: row["shotNumbers"][0])
    return {"sentences": repaired}


def load_study_context(project_dir: Path) -> str:
    context_path = project_dir / STUDY_CONTEXT_FILENAME
    if not context_path.exists():
        return ""
    try:
        return context_path.read_text(encoding="utf-8")
    except OSError:
        return ""


def save_study_context(project_dir: Path, value: object) -> str:
    context = str(value or "")
    (project_dir / STUDY_CONTEXT_FILENAME).write_text(context, encoding="utf-8")
    return context


def save_project_context(outputs_dir: Path, project_id: str, payload: dict[str, object]) -> dict[str, object]:
    project_dir = safe_project_path(outputs_dir, project_id)
    if not project_dir.exists():
        raise FileNotFoundError("Project not found")
    context = save_study_context(project_dir, payload.get("userContext", ""))
    return {"ok": True, "userContext": context}


def film_conversation_path(project_dir: Path) -> Path:
    return project_dir / FILM_CONVERSATION_FILENAME


def load_film_conversation(project_dir: Path) -> dict[str, object]:
    path = film_conversation_path(project_dir)
    if not path.exists():
        return {"version": 1, "messages": []}
    try:
        value = load_json(path)
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "messages": []}
    if not isinstance(value, dict) or not isinstance(value.get("messages"), list):
        return {"version": 1, "messages": []}
    return value


def save_film_conversation(project_dir: Path, conversation: dict[str, object]) -> dict[str, object]:
    cleaned = {
        "version": 1,
        "model": str(conversation.get("model") or ""),
        "updatedAt": conversation.get("updatedAt"),
        "contextRevision": str(conversation.get("contextRevision") or ""),
        "messages": [
            message
            for message in conversation.get("messages", [])
            if isinstance(message, dict)
            and str(message.get("role") or "") in {"user", "assistant"}
            and str(message.get("content") or "").strip()
        ],
    }
    film_conversation_path(project_dir).write_text(
        json.dumps(cleaned, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return cleaned


def clear_film_conversation(outputs_dir: Path, project_id: str) -> dict[str, object]:
    project_dir = safe_project_path(outputs_dir, project_id)
    path = film_conversation_path(project_dir)
    if path.exists():
        path.unlink()
    return {"ok": True, "conversation": {"version": 1, "messages": []}}


def markdown_value(value: object, fallback: str = "Not recorded.") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def format_duration_units(seconds: object) -> str:
    try:
        value = max(0.0, float(seconds))
    except (TypeError, ValueError):
        value = 0.0
    rounded = round(value + 1e-9, 2)
    hours = int(rounded // 3600)
    minutes = int((rounded - hours * 3600) // 60)
    remaining = rounded - hours * 3600 - minutes * 60
    if hours:
        return f"{hours}h {minutes:02d}m {remaining:05.2f}s"
    if minutes:
        return f"{minutes}m {remaining:05.2f}s"
    return f"{remaining:.2f}s"


def build_film_study_markdown(
    project_dir: Path,
    shots: list[dict[str, object]],
    outline: dict[str, object],
    user_context: str,
) -> str:
    meta = load_project_meta(project_dir)
    title = project_display_name(project_dir, meta)
    session = load_analysis_session(project_dir)
    included = included_analysis_shots(shots)
    excluded = [row for row in shots if bool(row.get("analysis_excluded"))]
    included_numbers = {
        safe_int(row.get("shot"), index + 1)
        for index, row in enumerate(shots)
        if not bool(row.get("analysis_excluded"))
    }
    normalized_outline = normalize_outline(outline, len(shots))
    lines = [
        f"# {title}",
        "",
        "> Film-study handoff for further analysis. Treat the user's interpretation as a hypothesis,",
        "> distinguish observation from inference, and cite shot numbers and timecodes for every claim.",
        "",
        "## Study Metadata",
        "",
        f"- Included shots: {len(included)} of {len(shots)}",
        f"- Included duration: {format_duration_units(sum(float(row.get('duration_seconds') or 0) for row in included))}",
        f"- Analysis model: {markdown_value(session.get('model'), 'Not analyzed yet.')}",
        f"- Analysis updated: {markdown_value(session.get('updatedAt'))}",
        f"- Source: {markdown_value(meta.get('sourceUrl'))}",
        "",
        "## User's Read on the Film",
        "",
        markdown_value(user_context, "No user interpretation was provided."),
        "",
        "## Accumulated Film Memory",
        "",
        "```json",
        json.dumps(session.get("filmMemory") or {}, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Filmic Sentences and Beats",
        "",
    ]
    sentence_count = 0
    for sentence in normalized_outline["sentences"]:
        shot_numbers = [
            number
            for number in sentence.get("shotNumbers", [])
            if number in included_numbers
        ]
        if not shot_numbers:
            continue
        sentence_count += 1
        sentence_rows = [
            row for row in included if safe_int(row.get("shot"), 0) in shot_numbers
        ]
        duration = sum(float(row.get("duration_seconds") or 0) for row in sentence_rows)
        lines.extend([
            f"### Sentence {sentence_count}: {markdown_value(sentence.get('title'), 'Untitled')}",
            "",
            f"- Beat: {markdown_value(sentence.get('beat'), 'Unassigned')}",
            f"- Shots: {', '.join(f'#{number}' for number in shot_numbers)}",
            f"- Duration: {format_duration_units(duration)}",
            f"- Idea: {markdown_value(sentence.get('idea'))}",
            "",
        ])
    if not sentence_count:
        lines.extend(["No filmic sentences have been organized yet.", ""])

    lines.extend(["## Included Shot Catalogue", ""])
    for row in included:
        shot_number = safe_int(row.get("shot"), 0)
        screenshot_name = Path(str(row.get("screenshot_path") or "")).name
        lines.extend([
            f"### Shot #{shot_number}: {markdown_value(row.get('shot_title'), 'Untitled shot')}",
            "",
            f"- Stable ID: `{row.get('analysis_id') or timeline_analysis_id(row, shot_number - 1)}`",
            f"- Time: {row.get('start', '')} to {row.get('end', '')}",
            f"- Duration: {format_duration_units(row.get('duration_seconds'))}",
            f"- Visual description: {markdown_value(row.get('visual_description'))}",
            f"- Audio / dialogue: {markdown_value(row.get('audio_dialogue'))}",
            f"- Action / camera: {markdown_value(row.get('action_camera'))}",
            (
                "- Camera movement: "
                f"{markdown_value(row.get('camera_movement_type'), 'Not classified')}; "
                f"intensity {markdown_value(row.get('camera_movement_intensity'), 'not classified')}; "
                f"evidence {markdown_value(row.get('camera_movement_evidence'))}"
            ),
            f"- Narrative function: {markdown_value(row.get('narrative_function'))}",
            f"- User notes: {markdown_value(row.get('notes'))}",
        ])
        if screenshot_name:
            lines.append(f"- Screenshot: `screenshots/{screenshot_name}`")
        lines.append("")

    if excluded:
        lines.extend([
            "## Excluded From Analysis",
            "",
            "These intervals remain in the source film but were intentionally omitted from AI analysis:",
            "",
        ])
        for row in excluded:
            lines.append(
                f"- Shot #{safe_int(row.get('shot'), 0)}: "
                f"{row.get('start', '')} to {row.get('end', '')} "
                f"({format_duration_units(row.get('duration_seconds'))})"
            )
        lines.append("")

    lines.extend([
        "## Questions for the Next Model",
        "",
        "1. Which parts of the user's interpretation are strongly supported, weakly supported, or contradicted?",
        "2. What editing, cinematography, sound, music, performance, and narrative techniques were missed?",
        "3. What recurring patterns connect distant shots or sentences?",
        "4. What practical lessons could a filmmaker reuse without merely copying surface details?",
        "5. Cite shot numbers and timecodes, and clearly label uncertain inferences.",
        "",
    ])
    return "\n".join(lines)


def export_film_study_for_ai(outputs_dir: Path, project_id: str) -> dict[str, object]:
    project_dir = safe_project_path(outputs_dir, project_id)
    manifest_path = project_manifest_path(project_dir)
    rows = load_json(manifest_path)
    if not isinstance(rows, list):
        raise ValueError("Project manifest must be a list")
    shots = [
        normalize_shot_row(row, index, project_dir)
        for index, row in enumerate(rows)
        if isinstance(row, dict)
    ]
    markdown = build_film_study_markdown(
        project_dir,
        shots,
        load_outline(project_dir, len(shots)),
        load_study_context(project_dir),
    )
    output_path = project_dir / AI_EXPORT_FILENAME
    output_path.write_text(markdown, encoding="utf-8")
    return {
        "ok": True,
        "markdown": markdown,
        "filename": f"{safe_upload_stem(project_display_name(project_dir))} - Film Study.md",
        "path": str(output_path),
    }


def qwen_conversation_model(session: dict[str, object]) -> str:
    saved = str(session.get("model") or "").split(" + ", 1)[0].strip()
    if saved.casefold().startswith("qwen"):
        return normalize_qwen_model(saved)
    return normalize_qwen_model(os.environ.get("QWEN_VIDEO_MODEL", DEFAULT_QWEN_VIDEO_MODEL))


def call_qwen_conversation(
    api_key: str,
    model: str,
    messages: list[dict[str, object]],
) -> str:
    request_body: dict[str, object] = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
    }
    if "omni" in model.casefold():
        request_body["stream"] = True
        request_body["stream_options"] = {"include_usage": True}
        request_body["modalities"] = ["text"]
    else:
        request_body["enable_thinking"] = False
    url = os.environ.get("QWEN_COMPATIBLE_URL", QWEN_COMPATIBLE_URL)
    if request_body.get("stream"):
        return call_chat_completion_stream(url, api_key, request_body, "Qwen")
    return call_chat_completion(url, api_key, request_body, "Qwen")


def ask_this_film(
    outputs_dir: Path,
    project_id: str,
    payload: dict[str, object],
) -> dict[str, object]:
    question = str(payload.get("question") or "").strip()
    if not question:
        raise ValueError("Enter a question about the film")
    qwen_api_key = str(
        os.environ.get("QWEN_API_KEY")
        or os.environ.get("DASHSCOPE_API_KEY")
        or os.environ.get("ALIBABA_CLOUD_API_KEY")
        or ""
    ).strip()
    if not qwen_api_key:
        raise ValueError("Set QWEN_API_KEY, DASHSCOPE_API_KEY, or ALIBABA_CLOUD_API_KEY in .env")

    project_dir = safe_project_path(outputs_dir, project_id)
    manifest_path = project_manifest_path(project_dir)
    raw_rows = load_json(manifest_path)
    if not isinstance(raw_rows, list):
        raise ValueError("Project manifest must be a list")
    shots = [
        normalize_shot_row(row, index, project_dir)
        for index, row in enumerate(raw_rows)
        if isinstance(row, dict)
    ]
    session = load_analysis_session(project_dir)
    if not session.get("hasFullAnalysis"):
        raise ValueError("Analyze the selected part of the film before starting a conversation")
    model = qwen_conversation_model(session)
    context_revision = (
        f"{timeline_revision(shots)}:{analysis_scope_revision(shots)}:"
        f"{safe_int(session.get('analysisRevision'), 0)}"
    )
    study = build_film_study_markdown(
        project_dir,
        shots,
        load_outline(project_dir, len(shots)),
        load_study_context(project_dir),
    )
    conversation = load_film_conversation(project_dir)
    stored_messages = [
        {
            "role": str(message.get("role")),
            "content": str(message.get("content")),
        }
        for message in conversation.get("messages", [])[-20:]
        if isinstance(message, dict)
    ]
    messages: list[dict[str, object]] = [
        {
            "role": "system",
            "content": (
                "You are Qwen continuing the same film-study investigation after the native video-analysis pass. "
                "The application has reconstructed your durable film memory, edited shot catalogue, filmic sentences, "
                "and the user's own interpretation below. Answer as a rigorous film-studies mentor. Cite shot numbers "
                "and timecodes. Separate direct evidence, the user's hypothesis, and your inference. Do not claim to "
                "have rewatched footage in this chat unless the saved evidence supports the statement.\n\n"
                + study
            ),
        },
        *stored_messages,
        {"role": "user", "content": question},
    ]
    begin_api_usage_collection()
    response = call_qwen_conversation(qwen_api_key, model, messages).strip()
    usage = finish_api_usage_collection()
    now = datetime.now().isoformat(timespec="seconds")
    saved_messages = [
        *[
            message
            for message in conversation.get("messages", [])
            if isinstance(message, dict)
        ],
        {"role": "user", "content": question, "at": now},
        {"role": "assistant", "content": response, "at": now, "usage": usage},
    ]
    saved = save_film_conversation(project_dir, {
        "model": model,
        "updatedAt": now,
        "contextRevision": context_revision,
        "messages": saved_messages,
    })
    return {
        "ok": True,
        "answer": response,
        "model": model,
        "usage": usage,
        "conversation": saved,
    }


def load_project(outputs_dir: Path, project_id: str) -> dict[str, object]:
    project_dir = safe_project_path(outputs_dir, project_id)
    manifest_path = project_manifest_path(project_dir)
    if not manifest_path.exists():
        raise FileNotFoundError("Project manifest not found")
    rows = load_json(manifest_path)
    if not isinstance(rows, list):
        raise ValueError("Manifest must be a list")
    normalized = [normalize_shot_row(row, index, project_dir) for index, row in enumerate(rows)]
    video_path = find_source_video(project_dir.name)
    meta = load_project_meta(project_dir)
    return {
        "id": project_dir.name,
        "name": project_display_name(project_dir, meta),
        "groupPath": project_group_path(outputs_dir, project_dir),
        "shots": normalized,
        "outline": load_outline(project_dir, len(normalized)),
        "userContext": load_study_context(project_dir),
        "coverUrl": cover_url_for(project_dir, rows, meta),
        "coverCrop": normalize_cover_crop(meta.get("coverCrop")),
        "sourceUrl": meta.get("sourceUrl", ""),
        "channelUrl": meta.get("channelUrl", ""),
        "channelTitle": meta.get("channelTitle", ""),
        "channelRank": meta.get("channelRank"),
        "popularityRank": meta.get("popularityRank"),
        "viewCount": meta.get("viewCount"),
        "likeCount": meta.get("likeCount"),
        "repostCount": meta.get("repostCount"),
        "commentCount": meta.get("commentCount"),
        "saveCount": meta.get("saveCount"),
        "socialStats": social_stats_from_meta(meta),
        "captionFiles": meta.get("captionFiles", []),
        "captionCueCount": meta.get("captionCueCount", 0),
        "captionShotsUpdated": meta.get("captionShotsUpdated", 0),
        "videoUrl": f"/video/{project_dir.name}" if video_path else None,
        "hasCorrections": manifest_path.name == "corrected_manifest.json",
        "analysisSession": analysis_session_summary(project_dir, normalized),
        "conversation": load_film_conversation(project_dir),
        "cutReview": load_cut_review(project_dir, normalized),
        "paths": {
            "manifest": str(manifest_path),
            "correctedManifest": str(project_dir / "corrected_manifest.json"),
            "correctedWorkbook": str(project_dir / "corrected_film_study.xlsx"),
            "sourceVideo": str(video_path) if video_path else None,
        },
    }


def save_corrected_project(outputs_dir: Path, project_id: str, payload: dict[str, object]) -> dict[str, object]:
    project_dir = safe_project_path(outputs_dir, project_id)
    shots = payload.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ValueError("No shots to save")
    user_context = save_study_context(project_dir, payload.get("userContext", load_study_context(project_dir)))

    corrected_rows: list[dict[str, object]] = []
    for index, row in enumerate(shots):
        if not isinstance(row, dict):
            raise ValueError("Shot entries must be objects")
        normalized = normalize_shot_row(row, index, project_dir)
        corrected_rows.append(
            {
                "shot": index + 1,
                "analysis_id": normalized["analysis_id"],
                "originalShot": normalized["originalShot"],
                "members": normalized["members"],
                "shot_title": normalized["shot_title"],
                "screenshot_path": normalized["screenshot_path"],
                "start": normalized["start"],
                "end": normalized["end"],
                "duration_seconds": round(float(normalized["duration_seconds"]), 3),
                "visual_description": normalized["visual_description"],
                "audio_dialogue": normalized["audio_dialogue"],
                "action_camera": normalized["action_camera"],
                "camera_movement_type": normalized["camera_movement_type"],
                "camera_movement_intensity": normalized["camera_movement_intensity"],
                "camera_movement_confidence": normalized["camera_movement_confidence"],
                "camera_movement_evidence": normalized["camera_movement_evidence"],
                "narrative_function": normalized["narrative_function"],
                "notes": normalized["notes"],
                "analysis_stale": normalized["analysis_stale"],
                "analysis_excluded": normalized["analysis_excluded"],
                "manual_fields": normalized["manual_fields"],
            }
        )

    apply_caption_cues_to_rows(corrected_rows, load_project_caption_cues(project_dir))

    corrected_manifest = project_dir / "corrected_manifest.json"
    corrected_manifest.write_text(json.dumps(corrected_rows, indent=2), encoding="utf-8")

    corrected_csv = project_dir / "corrected_manifest.csv"
    with corrected_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(corrected_rows[0].keys()))
        writer.writeheader()
        writer.writerows(corrected_rows)

    workbook_shots = []
    analyses = {}
    for row in corrected_rows:
        number = int(row["shot"])
        shot = Shot(
            number=number,
            start=_seconds_from_timestamp(str(row["start"])),
            end=_seconds_from_timestamp(str(row["end"])),
            screenshot_path=Path(str(row["screenshot_path"])),
        )
        workbook_shots.append(shot)
        analyses[number] = ShotAnalysis(
            shot_title=str(row["shot_title"]),
            visual_description=str(row["visual_description"]),
            audio_dialogue=str(row["audio_dialogue"]),
            action_camera=str(row["action_camera"]),
            camera_movement_type=str(row["camera_movement_type"]),
            camera_movement_intensity=str(row["camera_movement_intensity"]),
            camera_movement_confidence=str(row["camera_movement_confidence"]),
            camera_movement_evidence=str(row["camera_movement_evidence"]),
            narrative_function=str(row["narrative_function"]),
            notes=str(row["notes"]),
        )
    corrected_workbook = project_dir / "corrected_film_study.xlsx"
    write_workbook(corrected_workbook, workbook_shots, analyses, study_context=user_context)

    outline_source = payload.get("outline")
    if outline_source is None:
        outline = load_outline(project_dir, len(corrected_rows))
    else:
        outline = save_outline(project_dir, outline_source, len(corrected_rows))
    return {
        "ok": True,
        "shotCount": len(corrected_rows),
        "outline": outline,
        "userContext": user_context,
        "analysisSession": analysis_session_summary(project_dir, corrected_rows),
        "cutReview": load_cut_review(project_dir, corrected_rows),
        "correctedManifest": str(corrected_manifest),
        "correctedCsv": str(corrected_csv),
        "correctedWorkbook": str(corrected_workbook),
    }


def analysis_target_ids(
    shots: list[dict[str, object]],
    session: dict[str, object],
    force_all: bool = False,
) -> list[str]:
    return [
        timeline_analysis_id(row, index)
        for index, row in enumerate(shots)
        if not bool(row.get("analysis_excluded"))
        and (force_all or shot_requires_analysis(row, index, session))
    ]


def incremental_analysis_bounds(
    shots: list[dict[str, object]],
    target_ids: list[str],
) -> tuple[float, float] | None:
    wanted = set(target_ids)
    indexes = [
        index
        for index, row in enumerate(shots)
        if timeline_analysis_id(row, index) in wanted
    ]
    if not indexes:
        return None
    first = min(indexes)
    last = max(indexes)
    if first > 0 and not bool(shots[first - 1].get("analysis_excluded")):
        first -= 1
    if last < len(shots) - 1 and not bool(shots[last + 1].get("analysis_excluded")):
        last += 1
    start = _seconds_from_timestamp(str(shots[first].get("start", "00:00:00.000")))
    end = _seconds_from_timestamp(str(shots[last].get("end", "00:00:00.000")))
    return max(0.0, start), max(start + 0.1, end)


def update_shots_with_llm_details(outputs_dir: Path, project_id: str, payload: dict[str, object]) -> dict[str, object]:
    project_dir = safe_project_path(outputs_dir, project_id)
    shots = payload.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ValueError("No shots to analyze")
    existing_job = analysis_job_status(project_id)
    if existing_job.get("status") == "running":
        raise ValueError("Analysis is already running for this film")

    model = str(
        payload.get("model")
        or os.environ.get("QWEN_VIDEO_MODEL")
        or DEFAULT_QWEN_VIDEO_MODEL
    ).strip()
    user_context = str(payload.get("userContext") or "").strip()
    save_study_context(project_dir, user_context)
    qwen_api_key = str(
        os.environ.get("QWEN_API_KEY")
        or os.environ.get("DASHSCOPE_API_KEY")
        or os.environ.get("ALIBABA_CLOUD_API_KEY")
        or ""
    ).strip()
    gemini_api_key = str(os.environ.get("GEMINI_API_KEY") or "").strip()
    if not qwen_api_key and not gemini_api_key:
        raise ValueError(
            "Set QWEN_API_KEY, DASHSCOPE_API_KEY, or ALIBABA_CLOUD_API_KEY in .env. "
            "Set GEMINI_API_KEY for fallback."
        )
    started_at = datetime.now().isoformat(timespec="seconds")
    update_analysis_job(
        project_id,
        status="running",
        runId=f"run-{time.time_ns()}",
        runRecorded=False,
        phase="preparing",
        message="Preparing the latest edited shot timeline.",
        progress=2,
        provider="qwen" if qwen_api_key else "gemini",
        model=model,
        startedAt=started_at,
        _startedMonotonic=time.monotonic(),
        batchNumber=0,
        batchCount=0,
    )
    begin_api_usage_collection()

    def report_progress(**changes: object) -> None:
        update_analysis_job(project_id, status="running", **changes)

    normalized = []
    for index, row in enumerate(shots):
        if not isinstance(row, dict):
            raise ValueError("Shot entries must be objects")
        normalized.append(normalize_shot_row(row, index, project_dir))
    included_rows = included_analysis_shots(normalized)
    if not included_rows:
        raise ValueError("Include at least one shot before starting analysis")
    outline = normalize_outline(payload.get("outline", load_outline(project_dir, len(normalized))), len(normalized))
    source_video = find_source_video(project_id)
    if source_video is None:
        raise FileNotFoundError("Source video not found")
    session = load_analysis_session(project_dir)
    source_fingerprint = source_video_fingerprint(source_video)
    reprocess = bool(payload.get("reprocess"))
    current_scope_revision = analysis_scope_revision(normalized)
    saved_scope_revision = str(session.get("analysisScopeRevision") or "")
    scope_changed = (
        bool(session.get("hasFullAnalysis"))
        and (
            (bool(saved_scope_revision) and saved_scope_revision != current_scope_revision)
            or (not saved_scope_revision and len(included_rows) != len(normalized))
        )
    )
    full_pass = (
        reprocess
        or not bool(session.get("hasFullAnalysis"))
        or str(session.get("sourceVideoFingerprint") or "") != source_fingerprint
        or scope_changed
    )
    narrative_upgrade_only = (
        not reprocess
        and bool(session.get("hasFullAnalysis"))
        and str(session.get("sourceVideoFingerprint") or "") == source_fingerprint
        and safe_int(session.get("narrativeContinuityVersion"), 0) < NARRATIVE_CONTINUITY_VERSION
    )
    if narrative_upgrade_only:
        full_pass = False
    target_ids = (
        []
        if narrative_upgrade_only
        else analysis_target_ids(normalized, session, force_all=full_pass)
    )
    user_context_hash = hashlib.sha256(user_context.encode("utf-8")).hexdigest()[:16]
    context_changed = (
        bool(session.get("hasFullAnalysis"))
        and str(session.get("userContextHash") or "") != user_context_hash
    )
    memory_only = not target_ids and context_changed and not full_pass
    continuity_only = (
        not target_ids
        and not memory_only
        and not full_pass
        and (
            safe_int(session.get("narrativeContinuityVersion"), 0) < NARRATIVE_CONTINUITY_VERSION
            or (
                safe_int(session.get("sentenceOutlineVersion"), 0) < SENTENCE_OUTLINE_VERSION
                and not bool(outline.get("sentences"))
            )
        )
    )
    analysis_mode = (
        "full"
        if full_pass
        else ("memory" if memory_only else ("continuity" if continuity_only else "incremental"))
    )
    if continuity_only:
        update_analysis_job(project_id, analysisMode=analysis_mode)
        report_progress(
            phase="narrative_pass",
            message="Upgrading narrative context across the complete existing shot catalogue.",
            progress=35,
            batchNumber=1,
            batchCount=1,
        )
        try:
            (
                reconciled_rows,
                film_memory,
                outline,
                provider_name,
                provider_model,
            ) = reconcile_narrative_continuity(
                model=model,
                qwen_api_key=qwen_api_key,
                gemini_api_key=gemini_api_key,
                project_name=display_project_name(project_id),
                project_dir=project_dir,
                shots=normalized,
                generated_rows=normalized,
                outline=outline,
                user_context=user_context,
                film_memory=session.get("filmMemory") if isinstance(session.get("filmMemory"), dict) else {},
                history_batch_number=1,
                rewrite_all=(
                    safe_int(session.get("narrativeContinuityVersion"), 0)
                    < NARRATIVE_CONTINUITY_VERSION
                ),
            )
        except Exception as exc:
            usage = finish_api_usage_collection()
            update_analysis_job(
                project_id,
                status="failed",
                phase="failed",
                message=safe_http_error_message(exc, "Narrative continuity upgrade failed"),
                progress=0,
                usage=usage,
                completedAt=datetime.now().isoformat(timespec="seconds"),
            )
            record_analysis_run(
                project_dir,
                project_id,
                status="failed",
                mode=analysis_mode,
                analyzedShotCount=0,
                totalShotCount=len(normalized),
                usage=usage,
                timelineRevision=timeline_revision(normalized),
                error=safe_http_error_message(exc, "Narrative continuity upgrade failed"),
            )
            raise
        usage = finish_api_usage_collection()
        provider_name = provider_name or str(session.get("provider") or "")
        provider_model = provider_model or str(session.get("model") or model)
        report_progress(
            phase="saving",
            message="Narrative continuity reconciled. Saving the updated study and spreadsheet.",
            progress=94,
            provider=provider_name,
            model=provider_model,
            usage=usage,
        )
        save_result = save_corrected_project(
            outputs_dir,
            project_id,
            {"shots": reconciled_rows, "outline": outline, "userContext": user_context},
        )
        saved_at = datetime.now().isoformat(timespec="seconds")
        analyzed_count = sum(
            1 for row in normalized if not is_manual_field(row, "narrative_function")
        )
        history = session.get("history") if isinstance(session.get("history"), list) else []
        next_session = {
            **session,
            "version": 1,
            "hasFullAnalysis": True,
            "provider": str(session.get("videoProvider") or session.get("provider") or provider_name),
            "model": str(session.get("videoModel") or session.get("model") or model),
            "videoProvider": str(session.get("videoProvider") or session.get("provider") or provider_name),
            "videoModel": str(session.get("videoModel") or session.get("model") or model),
            "narrativeProvider": provider_name,
            "narrativeModel": provider_model,
            "updatedAt": saved_at,
            "analysisRevision": safe_int(session.get("analysisRevision"), 0) + 1,
            "timelineRevision": timeline_revision(reconciled_rows),
            "userContextHash": user_context_hash,
            "filmMemory": film_memory,
            "history": [*history[-19:], {
                "at": saved_at,
                "mode": analysis_mode,
                "timelineRevision": timeline_revision(reconciled_rows),
                "analyzedShotCount": analyzed_count,
                "provider": provider_name,
                "model": provider_model,
                "usage": usage,
            }],
            "lastUsage": usage,
            "narrativeContinuityVersion": NARRATIVE_CONTINUITY_VERSION,
            "sentenceOutlineVersion": SENTENCE_OUTLINE_VERSION,
            "analysisScopeRevision": current_scope_revision,
        }
        save_analysis_session(project_dir, next_session)
        update_analysis_job(
            project_id,
            status="completed",
            phase="complete",
            message="Narrative continuity upgraded without resending the video.",
            progress=100,
            provider=provider_name,
            model=provider_model,
            usage=usage,
            completedAt=saved_at,
        )
        record_analysis_run(
            project_dir,
            project_id,
            status="completed",
            mode=analysis_mode,
            analyzedShotCount=analyzed_count,
            totalShotCount=len(reconciled_rows),
            usage=usage,
            completedAt=saved_at,
            timelineRevision=timeline_revision(reconciled_rows),
        )
        return {
            **save_result,
            "ok": True,
            "shots": [
                normalize_shot_row(row, index, project_dir)
                for index, row in enumerate(reconciled_rows)
            ],
            "shotCount": len(reconciled_rows),
            "provider": provider_name,
            "model": provider_model,
            "analysisMode": analysis_mode,
            "analyzedShotCount": analyzed_count,
            "suggestions": [],
            "suggestionCount": 0,
            "usage": usage,
            "analysisJob": analysis_job_status(project_id),
            "analysisSession": analysis_session_summary(project_dir, reconciled_rows),
        }
    if not target_ids and not memory_only:
        save_result = save_corrected_project(
            outputs_dir,
            project_id,
            {"shots": normalized, "outline": outline, "userContext": user_context},
        )
        usage = finish_api_usage_collection()
        previous_usage = analysis_session_summary(project_dir, normalized).get("lastUsage", {})
        update_analysis_job(
            project_id,
            status="completed",
            analysisMode="up_to_date",
            phase="complete",
            message="Analysis was already current; no API request was sent.",
            progress=100,
            usage=previous_usage,
            completedAt=datetime.now().isoformat(timespec="seconds"),
        )
        record_analysis_run(
            project_dir,
            project_id,
            status="completed",
            mode="up_to_date",
            analyzedShotCount=0,
            totalShotCount=len(normalized),
            batchCount=0,
            usage=usage,
            provider=str(session.get("provider") or ""),
            model=str(session.get("model") or ""),
            timelineRevision=timeline_revision(normalized),
        )
        return {
            "ok": True,
            "upToDate": True,
            "analysisMode": "up_to_date",
            "shots": normalized,
            "shotCount": len(normalized),
            "analyzedShotCount": 0,
            "provider": str(session.get("provider") or ""),
            "model": str(session.get("model") or ""),
            "suggestions": [],
            "suggestionCount": 0,
            "usage": usage,
            "analysisJob": analysis_job_status(project_id),
            "analysisSession": analysis_session_summary(project_dir, normalized),
            **save_result,
        }

    update_analysis_job(project_id, analysisMode=analysis_mode)
    report_progress(
        phase="checking_timeline",
        message="Checking the edited timeline for possible missed transitions.",
        progress=5,
    )
    scope_intervals = analysis_scope_intervals(normalized)
    clip_bounds = (
        None
        if memory_only
        else (
            scope_intervals[0]
            if full_pass and len(scope_intervals) == 1
            else incremental_analysis_bounds(normalized, target_ids)
        )
    )
    low_threshold_candidates = (
        []
        if memory_only
        else prioritize_ffmpeg_candidates_for_ai(
            detect_shot_boundaries(source_video, threshold=0.12),
            normalized,
        )
    )
    if scope_intervals:
        low_threshold_candidates = [
            candidate
            for candidate in low_threshold_candidates
            if any(start <= candidate[0] <= end for start, end in scope_intervals)
        ]
    video_provider_name = ""
    video_provider_model = ""
    narrative_provider_name = ""
    narrative_provider_model = ""
    base_timeline = normalized
    detected_suggestions: list[dict[str, object]] = []
    applied_cuts: list[dict[str, object]] = []
    pending_suggestions: list[dict[str, object]] = []
    cut_review = load_cut_review(project_dir, normalized)
    try:
        if memory_only:
            report_progress(
                phase="waiting_api",
                message="Sending your updated film notes to the model using saved film memory.",
                progress=25,
                batchNumber=1,
                batchCount=1,
            )
            llm_rows, film_memory, provider_name, provider_model = generate_analysis_from_film_memory(
                model=model,
                qwen_api_key=qwen_api_key,
                gemini_api_key=gemini_api_key,
                project_name=display_project_name(project_id),
                project_dir=project_dir,
                shots=normalized,
                outline=outline,
                user_context=user_context,
                film_memory=session.get("filmMemory") if isinstance(session.get("filmMemory"), dict) else {},
            )
            llm_transitions = []
        else:
            llm_rows, llm_transitions, film_memory, provider_name, provider_model = generate_shot_details_with_native_video(
                model=model,
                qwen_api_key=qwen_api_key,
                gemini_api_key=gemini_api_key,
                project_name=display_project_name(project_id),
                project_dir=project_dir,
                shots=normalized,
                outline=outline,
                user_context=user_context,
                ffmpeg_candidates=low_threshold_candidates,
                target_analysis_ids=target_ids,
                film_memory=(
                    {}
                    if full_pass
                    else (session.get("filmMemory") if isinstance(session.get("filmMemory"), dict) else {})
                ),
                full_pass=full_pass,
                clip_bounds=clip_bounds,
                progress_callback=report_progress,
            )
            video_provider_name = provider_name
            video_provider_model = provider_model
            base_timeline = merge_generated_shot_details(normalized, llm_rows)
            apply_caption_cues_to_rows(base_timeline, load_project_caption_cues(project_dir))
            current_boundaries = [
                _seconds_from_timestamp(str(row.get("end", "00:00:00.000")))
                for row in base_timeline[:-1]
            ]
            detected_suggestions = normalize_ai_transition_suggestions(
                llm_transitions,
                base_timeline,
                current_boundaries,
                low_threshold_candidates,
            )
            if detected_suggestions:
                report_progress(
                    phase="applying_cuts",
                    message=(
                        f"Applying {len(detected_suggestions)} missing "
                        f"{'cut' if len(detected_suggestions) == 1 else 'cuts'} before narrative continuity."
                    ),
                    progress=90,
                    provider=provider_name,
                    model=provider_model,
                )
                (
                    base_timeline,
                    outline,
                    applied_cuts,
                    pending_suggestions,
                ) = apply_ai_cuts_to_timeline(
                    outputs_dir,
                    project_id,
                    base_timeline,
                    outline,
                    detected_suggestions,
                )
                apply_caption_cues_to_rows(
                    base_timeline,
                    load_project_caption_cues(project_dir),
                )
            cut_review = save_cut_review(
                project_dir,
                base_timeline,
                pending_suggestions,
                video_provider_name,
                video_provider_model,
                applied_suggestions=applied_cuts,
            )

            rewrite_all_narrative = (
                safe_int(session.get("narrativeContinuityVersion"), 0)
                < NARRATIVE_CONTINUITY_VERSION
            )
            target_intervals = [
                (
                    _seconds_from_timestamp(str(row.get("start", "00:00:00.000"))),
                    _seconds_from_timestamp(str(row.get("end", "00:00:00.000"))),
                )
                for index, row in enumerate(normalized)
                if timeline_analysis_id(row, index) in set(target_ids)
            ]
            narrative_targets = [
                row
                for row in base_timeline
                if not bool(row.get("analysis_excluded"))
                and (
                    rewrite_all_narrative
                    or any(
                        _seconds_from_timestamp(str(row.get("start", "00:00:00.000"))) < target_end
                        and _seconds_from_timestamp(str(row.get("end", "00:00:00.000"))) > target_start
                        for target_start, target_end in target_intervals
                    )
                )
            ]
            if len(base_timeline) > 1:
                report_progress(
                    phase="narrative_pass",
                    message=(
                        "Auditing character identity and reconciling narrative functions "
                        "against the complete chronological film."
                    ),
                    progress=92,
                    provider=provider_name,
                    model=provider_model,
                )
                narrative_batch_number = len(plan_analysis_batches(normalized, target_ids)) + 1
                (
                    llm_rows,
                    film_memory,
                    outline,
                    narrative_provider,
                    narrative_model,
                ) = reconcile_narrative_continuity(
                    model=model,
                    qwen_api_key=qwen_api_key,
                    gemini_api_key=gemini_api_key,
                    project_name=display_project_name(project_id),
                    project_dir=project_dir,
                    shots=base_timeline,
                    generated_rows=narrative_targets,
                    outline=outline,
                    user_context=user_context,
                    film_memory=film_memory,
                    history_batch_number=narrative_batch_number,
                    rewrite_all=rewrite_all_narrative,
                )
                narrative_provider_name = narrative_provider
                narrative_provider_model = narrative_model
                if narrative_provider and narrative_provider != provider_name:
                    provider_name = "mixed"
                if narrative_model and narrative_model != provider_model:
                    provider_model = f"{provider_model} + {narrative_model}"
    except Exception as exc:
        usage = finish_api_usage_collection()
        update_analysis_job(
            project_id,
            status="failed",
            phase="failed",
            message=safe_http_error_message(exc, "Analysis failed"),
            progress=0,
            usage=usage,
            completedAt=datetime.now().isoformat(timespec="seconds"),
        )
        record_analysis_run(
            project_dir,
            project_id,
            status="failed",
            mode=analysis_mode,
            analyzedShotCount=0,
            totalShotCount=len(normalized),
            usage=usage,
            timelineRevision=timeline_revision(normalized),
            error=safe_http_error_message(exc, "Analysis failed"),
        )
        write_llm_error(project_dir, model, exc)
        raise
    usage = finish_api_usage_collection()
    report_progress(
        phase="saving",
        message="The model responded. Saving shot details and rebuilding the spreadsheet.",
        progress=94,
        provider=provider_name,
        model=provider_model,
        usage=usage,
    )
    merged = merge_generated_shot_details(base_timeline, llm_rows)
    apply_caption_cues_to_rows(merged, load_project_caption_cues(project_dir))
    suggestions = pending_suggestions
    save_result = save_corrected_project(
        outputs_dir,
        project_id,
        {"shots": merged, "outline": outline, "userContext": user_context},
    )
    generated_ids = {
        str(row.get("analysis_id") or row.get("row_id") or "").strip()
        for row in llm_rows
        if isinstance(row, dict)
    }
    analyzed_shots = {} if full_pass else dict(session.get("analyzedShots") or {})
    saved_at = datetime.now().isoformat(timespec="seconds")
    for index, row in enumerate(merged):
        analysis_id = timeline_analysis_id(row, index)
        if analysis_id in generated_ids and not memory_only:
            analyzed_shots[analysis_id] = {
                "start": row.get("start", ""),
                "end": row.get("end", ""),
                "analyzedAt": saved_at,
            }
    current_ids = {timeline_analysis_id(row, index) for index, row in enumerate(merged)}
    analyzed_shots = {
        key: value for key, value in analyzed_shots.items() if key in current_ids
    }
    history = session.get("history") if isinstance(session.get("history"), list) else []
    history = [*history[-19:], {
        "at": saved_at,
        "mode": analysis_mode,
        "timelineRevision": timeline_revision(merged),
        "analyzedShotCount": len(generated_ids),
        "provider": provider_name,
        "model": provider_model,
        "usage": usage,
        "cutDetectedCount": len(detected_suggestions),
        "cutAppliedCount": len(applied_cuts),
        "cutPendingCount": len(pending_suggestions),
    }]
    next_session = {
        "version": 1,
        "hasFullAnalysis": True,
        "sourceVideoFingerprint": source_fingerprint,
        "provider": (
            video_provider_name
            or str(session.get("videoProvider") or session.get("provider") or provider_name)
        ),
        "model": (
            video_provider_model
            or str(session.get("videoModel") or session.get("model") or model)
        ),
        "videoProvider": (
            video_provider_name
            or str(session.get("videoProvider") or session.get("provider") or provider_name)
        ),
        "videoModel": (
            video_provider_model
            or str(session.get("videoModel") or session.get("model") or model)
        ),
        "narrativeProvider": narrative_provider_name or str(session.get("narrativeProvider") or ""),
        "narrativeModel": narrative_provider_model or str(session.get("narrativeModel") or ""),
        "firstAnalyzedAt": saved_at if full_pass or not session.get("firstAnalyzedAt") else session.get("firstAnalyzedAt"),
        "updatedAt": saved_at,
        "analysisRevision": safe_int(session.get("analysisRevision"), 0) + 1,
        "timelineRevision": timeline_revision(merged),
        "userContextHash": user_context_hash,
        "filmMemory": film_memory,
        "analyzedShots": analyzed_shots,
        "history": history,
        "lastUsage": usage,
        "lastCutSummary": {
            "detectedCount": len(detected_suggestions),
            "appliedCount": len(applied_cuts),
            "pendingCount": len(pending_suggestions),
        },
        "narrativeContinuityVersion": NARRATIVE_CONTINUITY_VERSION,
        "aiCutAutomationVersion": 2,
        "sentenceOutlineVersion": SENTENCE_OUTLINE_VERSION,
        "analysisScopeRevision": analysis_scope_revision(merged),
    }
    save_analysis_session(project_dir, next_session)
    update_analysis_job(
        project_id,
        status="completed",
        phase="complete",
        message=(
            f"Analysis complete. {len(applied_cuts)} missing "
            f"{'cut was' if len(applied_cuts) == 1 else 'cuts were'} applied automatically. "
            "Shot details and spreadsheet are ready."
            if applied_cuts
            else "Analysis complete. Shot details and spreadsheet are ready."
        ),
        progress=100,
        provider=provider_name,
        model=provider_model,
        usage=usage,
        completedAt=datetime.now().isoformat(timespec="seconds"),
    )
    record_analysis_run(
        project_dir,
        project_id,
        status="completed",
        mode=analysis_mode,
        analyzedShotCount=len(generated_ids),
        totalShotCount=len(merged),
        usage=usage,
        completedAt=saved_at,
        timelineRevision=timeline_revision(merged),
        cutDetectedCount=len(detected_suggestions),
        cutAppliedCount=len(applied_cuts),
        cutPendingCount=len(pending_suggestions),
    )
    return {
        **save_result,
        "ok": True,
        "shots": [normalize_shot_row(row, index, project_dir) for index, row in enumerate(merged)],
        "shotCount": len(merged),
        "provider": provider_name,
        "model": provider_model,
        "analysisMode": analysis_mode,
        "analyzedShotCount": len(generated_ids),
        "suggestions": suggestions,
        "suggestionCount": len(suggestions),
        "detectedCutCount": len(detected_suggestions),
        "appliedCutCount": len(applied_cuts),
        "cutReview": cut_review,
        "usage": usage,
        "analysisJob": analysis_job_status(project_id),
        "analysisSession": analysis_session_summary(project_dir, merged),
    }


def ai_shot_boundary_suggestions(
    outputs_dir: Path,
    project_id: str,
    payload: dict[str, object],
) -> dict[str, object]:
    project_dir = safe_project_path(outputs_dir, project_id)
    raw_shots = payload.get("shots")
    if not isinstance(raw_shots, list) or not raw_shots:
        raise ValueError("No current shots to review")
    shots = [
        normalize_shot_row(row, index, project_dir)
        for index, row in enumerate(raw_shots)
        if isinstance(row, dict)
    ]
    if len(shots) != len(raw_shots):
        raise ValueError("Shot entries must be objects")

    qwen_api_key = str(
        os.environ.get("QWEN_API_KEY")
        or os.environ.get("DASHSCOPE_API_KEY")
        or os.environ.get("ALIBABA_CLOUD_API_KEY")
        or ""
    ).strip()
    gemini_api_key = str(os.environ.get("GEMINI_API_KEY") or "").strip()
    if not qwen_api_key and not gemini_api_key:
        raise ValueError("Add an Alibaba/Qwen key to .env, or add GEMINI_API_KEY for fallback.")

    model = normalize_qwen_model(str(payload.get("model") or DEFAULT_QWEN_VIDEO_MODEL))
    video_path = find_source_video(project_id)
    if video_path is None:
        raise FileNotFoundError("Source video not found")
    low_threshold_candidates = prioritize_ffmpeg_candidates_for_ai(
        detect_shot_boundaries(video_path, threshold=0.12),
        shots,
    )
    current_boundaries = [
        _seconds_from_timestamp(str(row.get("end", "00:00:00.000")))
        for row in shots[:-1]
    ]
    prompt = build_ai_shot_detection_prompt(shots, current_boundaries, low_threshold_candidates)
    analysis_video = prepare_analysis_video(project_dir, shots=shots)
    if analysis_video is None:
        raise FileNotFoundError("Source video not found for AI shot review")

    errors: list[str] = []
    provider = ""
    provider_model = ""
    raw_content = ""
    if qwen_api_key:
        try:
            raw_content = call_qwen_video(
                qwen_api_key,
                model,
                AI_SHOT_DETECTION_INSTRUCTIONS,
                prompt,
                analysis_video,
            )
            provider = "qwen"
            provider_model = model
        except Exception as exc:
            errors.append(f"Qwen failed: {exc}")
    if not raw_content and gemini_api_key:
        gemini_model = os.environ.get("GEMINI_VIDEO_MODEL", DEFAULT_GEMINI_MODEL)
        try:
            raw_content = call_gemini_video(
                gemini_api_key,
                gemini_model,
                AI_SHOT_DETECTION_INSTRUCTIONS,
                prompt,
                analysis_video,
            )
            provider = "gemini"
            provider_model = gemini_model
        except Exception as exc:
            errors.append(f"Gemini failed: {exc}")
    if not raw_content:
        raise ValueError("AI shot review failed. " + " | ".join(errors))

    (project_dir / "last_shot_detection_response.json").write_text(
        json.dumps(
            {
                "provider": provider,
                "model": provider_model,
                "savedAt": datetime.now().isoformat(timespec="seconds"),
                "content": raw_content,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    transitions = parse_ai_transitions(raw_content)
    cut_review = build_cut_review(
        outputs_dir,
        project_id,
        shots,
        transitions,
        low_threshold_candidates,
        provider,
        provider_model,
    )
    suggestions = cut_review["suggestions"]

    return {
        "ok": True,
        "provider": provider,
        "model": provider_model,
        "suggestions": suggestions,
        "suggestionCount": len(suggestions),
        "cutReview": cut_review,
        "currentBoundaryCount": len(current_boundaries),
        "ffmpegCandidateCount": len(low_threshold_candidates),
    }


def build_ai_shot_detection_prompt(
    shots: list[dict[str, object]],
    current_boundaries: list[float],
    ffmpeg_candidates: list[tuple[float, float]],
) -> str:
    timeline = [
        {
            "shot": index + 1,
            "analysis_id": analysis_id_for_row(index),
            "start": row.get("start", ""),
            "end": row.get("end", ""),
        }
        for index, row in enumerate(shots)
    ]
    candidates = [
        {"time_seconds": round(timestamp, 3), "scene_score": round(score, 4)}
        for timestamp, score in ffmpeg_candidates
    ]
    return (
        "Perform an independent editorial pass over the full video. The user's current boundaries and FFmpeg's "
        "low-threshold candidates are supplied as evidence, but neither list is guaranteed complete or correct. "
        "Look especially for gradual dissolves and crossfades that scene-score detection often misses.\n\n"
        f"Current edited timeline:\n{json.dumps(timeline, indent=2)}\n\n"
        f"Current boundary times in seconds:\n{json.dumps(current_boundaries)}\n\n"
        f"Low-threshold FFmpeg candidates:\n{json.dumps(candidates, indent=2)}\n\n"
        "Return every real transition you observe, including ones already represented by current boundaries. "
        "Use one object per transition with: time_seconds, transition_type, confidence (high, medium, or low), "
        "from_visual, to_visual, and reason. For a dissolve or crossfade, also include transition_start_seconds "
        "and transition_end_seconds, and set time_seconds to its editorial midpoint. Return exactly "
        '{"transitions": [...]}.'
    )


def parse_ai_transitions(raw_content: str) -> list[dict[str, object]]:
    parsed = parse_llm_json(raw_content)
    rows = first_list_value(parsed, ["transitions", "shot_boundaries", "boundaries", "cuts"])
    if not isinstance(rows, list):
        raise ValueError("AI shot review did not return a transitions array")
    return [row for row in rows if isinstance(row, dict)]


def transition_seconds(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return _seconds_from_timestamp(text) if ":" in text else float(text)
    except (TypeError, ValueError):
        return None


def normalize_ai_confidence(value: object) -> tuple[str, float]:
    if isinstance(value, (int, float)):
        score = max(0.0, min(1.0, float(value)))
        return ("high" if score >= 0.78 else "medium" if score >= 0.52 else "low", score)
    label = str(value or "medium").strip().lower()
    if label not in {"high", "medium", "low"}:
        label = "medium"
    return label, {"high": 0.9, "medium": 0.65, "low": 0.35}[label]


def normalize_split_details(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    fields = [
        "shot_title",
        "visual_description",
        "audio_dialogue",
        "action_camera",
        "camera_movement_type",
        "camera_movement_intensity",
        "camera_movement_confidence",
        "camera_movement_evidence",
        "narrative_function",
        "notes",
    ]
    details = {
        field: str(value.get(field) or "").strip()
        for field in fields
        if str(value.get(field) or "").strip()
    }
    if "shot_title" in details:
        details["shot_title"] = compact_shot_title(details["shot_title"])
    return details


def normalize_ai_transition_suggestions(
    transitions: list[dict[str, object]],
    shots: list[dict[str, object]],
    current_boundaries: list[float],
    ffmpeg_candidates: list[tuple[float, float]],
) -> list[dict[str, object]]:
    suggestions: list[dict[str, object]] = []
    seen_times: list[float] = []
    gradual_types = {"crossfade", "cross-fade", "dissolve", "fade", "fade_in", "fade_out", "wipe"}
    for row in transitions:
        timestamp = transition_seconds(
            row.get("time_seconds") or row.get("timestamp") or row.get("time")
        )
        if timestamp is None or timestamp <= 0:
            continue
        transition_type = str(row.get("transition_type") or row.get("type") or "cut").strip().lower()
        if any(abs(timestamp - boundary) <= 0.45 for boundary in current_boundaries):
            continue
        source_index = next(
            (
                index
                for index, shot in enumerate(shots)
                if _seconds_from_timestamp(str(shot["start"])) + 0.25 < timestamp
                < _seconds_from_timestamp(str(shot["end"])) - 0.25
            ),
            None,
        )
        if source_index is None:
            continue
        detector_source = "ai"
        if transition_type not in gradual_types:
            nearby = [candidate for candidate in ffmpeg_candidates if abs(candidate[0] - timestamp) <= 1.1]
            if nearby:
                timestamp = max(nearby, key=lambda item: item[1])[0]
                detector_source = "ai+ffmpeg"
        shot_start = _seconds_from_timestamp(str(shots[source_index]["start"]))
        shot_end = _seconds_from_timestamp(str(shots[source_index]["end"]))
        if not shot_start + 0.25 < timestamp < shot_end - 0.25:
            continue
        if any(abs(timestamp - boundary) <= 0.45 for boundary in current_boundaries):
            continue
        if any(abs(timestamp - prior) <= 0.35 for prior in seen_times):
            continue
        seen_times.append(timestamp)
        confidence_label, confidence_score = normalize_ai_confidence(row.get("confidence"))
        suggestions.append(
            {
                "id": f"ai-cut-{len(suggestions) + 1}",
                "time_seconds": round(timestamp, 3),
                "transition_type": transition_type.replace("_", " "),
                "confidence": confidence_label,
                "confidence_score": confidence_score,
                "detectorSource": detector_source,
                "sourceShot": source_index + 1,
                "from_visual": str(row.get("from_visual") or "").strip(),
                "to_visual": str(row.get("to_visual") or "").strip(),
                "reason": str(row.get("reason") or "").strip(),
                "transition_start_seconds": transition_seconds(row.get("transition_start_seconds")),
                "transition_end_seconds": transition_seconds(row.get("transition_end_seconds")),
                "before_details": normalize_split_details(
                    row.get("before_details") or row.get("before_shot")
                ),
                "after_details": normalize_split_details(
                    row.get("after_details") or row.get("after_shot")
                ),
            }
        )
    return sorted(suggestions, key=lambda item: float(item["time_seconds"]))


def timestamp_from_seconds(value: float) -> str:
    safe_value = max(0.0, float(value))
    hours = int(safe_value // 3600)
    minutes = int((safe_value % 3600) // 60)
    seconds = safe_value - hours * 3600 - minutes * 60
    return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"


def update_outline_for_server_split(
    outline: dict[str, object],
    original_shot_number: int,
    shot_count: int,
) -> dict[str, object]:
    updated = deepcopy(outline)
    for sentence in updated.get("sentences", []):
        if not isinstance(sentence, dict):
            continue
        next_numbers: list[int] = []
        for value in sentence.get("shotNumbers", []):
            number = safe_int(value, 0)
            if number < original_shot_number:
                next_numbers.append(number)
            elif number == original_shot_number:
                next_numbers.extend([number, number + 1])
            else:
                next_numbers.append(number + 1)
        sentence["shotNumbers"] = next_numbers
    return normalize_outline(updated, shot_count)


def apply_ai_cuts_to_timeline(
    outputs_dir: Path,
    project_id: str,
    shots: list[dict[str, object]],
    outline: dict[str, object],
    suggestions: list[dict[str, object]],
) -> tuple[
    list[dict[str, object]],
    dict[str, object],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    project_dir = safe_project_path(outputs_dir, project_id)
    timeline = [dict(row) for row in shots]
    updated_outline = normalize_outline(outline, len(timeline))
    applied: list[dict[str, object]] = []
    pending: list[dict[str, object]] = []
    detail_fields = [
        "shot_title",
        "visual_description",
        "audio_dialogue",
        "action_camera",
        "camera_movement_type",
        "camera_movement_intensity",
        "camera_movement_confidence",
        "camera_movement_evidence",
        "narrative_function",
        "notes",
    ]

    for suggestion_index, suggestion in enumerate(
        sorted(suggestions, key=lambda item: float(item.get("time_seconds") or 0)),
        start=1,
    ):
        cut = float(suggestion.get("time_seconds") or 0)
        source_index = next(
            (
                index
                for index, row in enumerate(timeline)
                if _seconds_from_timestamp(str(row.get("start", ""))) + 0.25 < cut
                < _seconds_from_timestamp(str(row.get("end", ""))) - 0.25
            ),
            None,
        )
        if source_index is None:
            continue
        source = timeline[source_index]
        start = _seconds_from_timestamp(str(source["start"]))
        end = _seconds_from_timestamp(str(source["end"]))
        label = f"ai_{int(time.time())}_{suggestion_index}"
        try:
            first_frame = extract_project_frame(
                outputs_dir,
                project_id,
                (start + cut) / 2,
                f"{label}_{source_index + 1}_a",
            )
            second_frame = extract_project_frame(
                outputs_dir,
                project_id,
                (cut + end) / 2,
                f"{label}_{source_index + 1}_b",
            )
        except (OSError, ValueError, VideoToolError):
            pending.append(dict(suggestion))
            continue

        halves: list[dict[str, object]] = []
        for half_index, (half_start, half_end, frame, detail_key) in enumerate([
            (start, cut, first_frame, "before_details"),
            (cut, end, second_frame, "after_details"),
        ]):
            half = dict(source)
            half.update(frame)
            half["start"] = timestamp_from_seconds(half_start)
            half["end"] = timestamp_from_seconds(half_end)
            half["duration_seconds"] = round(half_end - half_start, 3)
            for field in detail_fields:
                half[field] = ""
            half["shot_title"] = "Title Pending"
            details = normalize_split_details(suggestion.get(detail_key))
            half.update(details)
            half["manual_fields"] = []
            half["analysis_stale"] = any(
                not str(half.get(field) or "").strip()
                for field in ("shot_title", "visual_description", "action_camera")
            )
            half["analysis_id"] = timeline_analysis_id(half, source_index + half_index)
            halves.append(half)

        timeline[source_index:source_index + 1] = halves
        for index, row in enumerate(timeline):
            row["shot"] = index + 1
            row["analysis_id"] = timeline_analysis_id(row, index)
        updated_outline = update_outline_for_server_split(
            updated_outline,
            source_index + 1,
            len(timeline),
        )
        applied.append({
            **suggestion,
            "appliedAt": datetime.now().isoformat(timespec="seconds"),
        })

    return timeline, updated_outline, applied, pending


def build_cut_review(
    outputs_dir: Path,
    project_id: str,
    shots: list[dict[str, object]],
    transitions: list[dict[str, object]],
    ffmpeg_candidates: list[tuple[float, float]],
    provider: str,
    model: str,
) -> dict[str, object]:
    project_dir = safe_project_path(outputs_dir, project_id)
    current_boundaries = [
        _seconds_from_timestamp(str(row.get("end", "00:00:00.000")))
        for row in shots[:-1]
    ]
    suggestions = normalize_ai_transition_suggestions(
        transitions,
        shots,
        current_boundaries,
        ffmpeg_candidates,
    )
    return save_cut_review(project_dir, shots, suggestions, provider, model)


def merge_generated_shot_details(
    current_rows: list[dict[str, object]],
    generated_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    by_analysis_id = {}
    for row in generated_rows:
        analysis_id = str(row.get("analysis_id") or row.get("row_id") or "").strip()
        if analysis_id:
            by_analysis_id[analysis_id] = row

    merged = []
    detail_fields = [
        "visual_description",
        "audio_dialogue",
        "action_camera",
        "camera_movement_type",
        "camera_movement_intensity",
        "camera_movement_confidence",
        "camera_movement_evidence",
        "narrative_function",
        "notes",
    ]
    for index, row in enumerate(current_rows):
        next_row = dict(row)
        analysis_id = str(row.get("analysis_id") or analysis_id_for_row(index)).strip()
        generated = by_analysis_id.get(analysis_id, {})
        force_refresh = True
        maybe_merge_generated_field(next_row, generated, "shot_title", index, force_refresh=True)
        for field in detail_fields:
            maybe_merge_generated_field(next_row, generated, field, index, force_refresh=force_refresh)
        if generated:
            if (
                not is_manual_field(next_row, "notes")
                and is_placeholder_field_value("notes", str(next_row.get("notes", "")), index)
            ):
                next_row["notes"] = ""
            next_row["analysis_stale"] = False
        merged.append(next_row)
    return merged


def maybe_merge_generated_field(
    current_row: dict[str, object],
    generated_row: dict[str, object],
    field: str,
    index: int,
    force_refresh: bool = False,
) -> None:
    value = generated_row.get(field)
    if not isinstance(value, str) or not value.strip():
        return
    current_value = str(current_row.get(field, ""))
    if should_merge_generated_field(current_row, field, current_value, value, index, force_refresh):
        if field == "shot_title":
            current_row[field] = compact_shot_title(value)
        else:
            current_row[field] = value.strip()


def should_merge_generated_field(
    current_row: dict[str, object],
    field: str,
    current_value: str,
    generated_value: str,
    index: int,
    force_refresh: bool,
) -> bool:
    if is_manual_field(current_row, field):
        return False
    if field == "shot_title":
        return force_refresh or is_placeholder_shot_title(current_value, index)
    if field == "notes":
        return is_placeholder_field_value(field, current_value, index)
    if is_placeholder_field_value(field, current_value, index):
        return True
    if not force_refresh:
        return False
    if field == "audio_dialogue":
        return not looks_like_no_clear_audio(generated_value)
    return True


def looks_like_no_clear_audio(value: str) -> bool:
    normalized = value.strip().casefold()
    no_clear_phrases = [
        "no clear dialogue",
        "no dialogue",
        "no discernible dialogue",
        "no clear audio",
        "audio unavailable",
    ]
    return any(phrase in normalized for phrase in no_clear_phrases)


def compact_shot_title(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.strip().strip("\"'`")).strip()
    cleaned = re.sub(r"^(shot\s*)?#?\d+\s*[-:.]\s*", "", cleaned, flags=re.IGNORECASE).strip()
    words = [word for word in cleaned.split(" ") if word]
    if len(words) > 7:
        cleaned = " ".join(words[:7]).rstrip(" ,;:")
    return cleaned or "Title Pending"


def normalize_manual_fields(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    fields = []
    for item in value:
        field = str(item).strip()
        if field and field not in fields:
            fields.append(field)
    return fields


def is_manual_field(row: dict[str, object], field: str) -> bool:
    return field in normalize_manual_fields(row.get("manual_fields"))


def source_members_for_row(row: dict[str, object]) -> list[int]:
    members = row.get("members")
    if isinstance(members, list):
        parsed_members = []
        for member in members:
            parsed = safe_int(member, 0)
            if parsed:
                parsed_members.append(parsed)
        if parsed_members:
            return parsed_members
    original = safe_int(row.get("originalShot"), 0)
    current = safe_int(row.get("shot"), 0)
    return [original or current] if (original or current) else []


def is_structurally_edited_row(row: dict[str, object], index: int) -> bool:
    current = safe_int(row.get("shot"), index + 1)
    members = source_members_for_row(row)
    if len(members) != 1:
        return True
    original = safe_int(row.get("originalShot"), members[0] if members else current)
    return original != current or members[0] != current


def safe_int(value: object, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def analysis_id_for_row(index: int) -> str:
    return f"row_{index + 1:04d}"


def is_placeholder_field_value(field: str, value: str, index: int) -> bool:
    if field == "shot_title":
        return is_placeholder_shot_title(value, index)
    normalized = value.strip().casefold()
    if not normalized:
        return True
    placeholder_phrases = [
        "llm visual analysis pending",
        "audio transcription pending",
        "future pass should align dialogue",
        "narrative analysis pending",
        "generated by the scaffold analyzer",
        "no clear dialogue/audio available from the provided stills",
        "no clear dialogue/audio available from the attached video/captions",
    ]
    return normalized == "pending" or any(phrase in normalized for phrase in placeholder_phrases)


def is_placeholder_shot_title(value: str, index: int) -> bool:
    normalized = value.strip().casefold()
    placeholder_titles = {
        "",
        "title pending",
        "shot title pending",
        f"shot {index + 1}".casefold(),
    }
    return normalized in placeholder_titles


def build_memory_update_prompt(
    project_name: str,
    shots: list[dict[str, object]],
    outline: dict[str, object],
    user_context: str,
    film_memory: dict[str, object],
) -> str:
    catalogue = [
        {
            "analysis_id": str(row.get("analysis_id") or timeline_analysis_id(row, index)),
            "shot": index + 1,
            "start": row.get("start", ""),
            "end": row.get("end", ""),
            "shot_title": row.get("shot_title", ""),
            "visual_description": row.get("visual_description", ""),
            "audio_dialogue": row.get("audio_dialogue", ""),
            "action_camera": row.get("action_camera", ""),
            "narrative_function": row.get("narrative_function", ""),
            "notes": row.get("notes", ""),
            "manual_fields": normalize_manual_fields(row.get("manual_fields")),
        }
        for index, row in enumerate(shots)
    ]
    return (
        f"Film: {project_name}\n\n"
        "This is a memory-only continuation. The video is intentionally not attached because it was already "
        "processed in the full-film pass. Reconsider the user's hypotheses using only the durable film memory, "
        "current shot catalogue, captions, and outline below. Do not invent new visual or audible evidence.\n\n"
        f"Updated user study notes / hypotheses:\n{user_context or '(none provided)'}\n\n"
        f"Durable film memory:\n{json.dumps(film_memory, ensure_ascii=False, indent=2)}\n\n"
        f"Current shot catalogue:\n{json.dumps(catalogue, ensure_ascii=False, indent=2)}\n\n"
        f"Current outline:\n{json.dumps(outline, ensure_ascii=False, indent=2)}\n\n"
        "Return JSON with top-level keys shots, transitions, and film_memory. transitions must be an empty array. "
        "Return one shots row per catalogue row with its exact analysis_id and only narrative_function and notes. "
        "Use narrative_function to validate, refine, or reject the user's ideas against the saved evidence. "
        "Do not replace fields named in manual_fields. Return a compact updated film_memory with synopsis, "
        "characters, locations, motifs, narrative_progression, editing_patterns, cinematography_patterns, and "
        "unanswered_questions."
    )


def generate_analysis_from_film_memory(
    model: str,
    qwen_api_key: str,
    gemini_api_key: str,
    project_name: str,
    project_dir: Path,
    shots: list[dict[str, object]],
    outline: dict[str, object],
    user_context: str,
    film_memory: dict[str, object],
) -> tuple[list[dict[str, object]], dict[str, object], str, str]:
    instructions = LLM_INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    prompt = build_memory_update_prompt(project_name, shots, outline, user_context, film_memory)
    errors: list[str] = []
    if qwen_api_key:
        qwen_model = os.environ.get("QWEN_NARRATIVE_MODEL", DEFAULT_QWEN_NARRATIVE_MODEL)
        try:
            raw_content = call_qwen_text(qwen_api_key, qwen_model, instructions, prompt)
            write_llm_response(project_dir, qwen_model, raw_content, provider="qwen")
            rows, _transitions, next_memory = parse_generated_analysis_bundle(raw_content)
            return rows, next_memory or dict(film_memory), "qwen", qwen_model
        except Exception as exc:
            errors.append(f"Qwen failed: {exc}")
            write_llm_error(project_dir, qwen_model, exc, provider="qwen")
    if gemini_api_key:
        gemini_model = os.environ.get("GEMINI_VIDEO_MODEL", DEFAULT_GEMINI_MODEL)
        try:
            raw_content = call_gemini_text(gemini_api_key, gemini_model, f"{instructions}\n\n{prompt}")
            write_llm_response(project_dir, gemini_model, raw_content, provider="gemini")
            rows, _transitions, next_memory = parse_generated_analysis_bundle(raw_content)
            return rows, next_memory or dict(film_memory), "gemini", gemini_model
        except Exception as exc:
            errors.append(f"Gemini failed: {exc}")
            write_llm_error(project_dir, gemini_model, exc, provider="gemini")
    raise ValueError("Film-memory update failed. " + " | ".join(errors))


def plan_analysis_batches(
    shots: list[dict[str, object]],
    target_analysis_ids: list[str] | None,
) -> list[list[int]]:
    wanted = set(target_analysis_ids or [
        timeline_analysis_id(row, index) for index, row in enumerate(shots)
    ])
    target_indices = [
        index
        for index, row in enumerate(shots)
        if str(row.get("analysis_id") or timeline_analysis_id(row, index)) in wanted
    ]
    batches: list[list[int]] = []
    current: list[int] = []
    for index in target_indices:
        start = _seconds_from_timestamp(str(shots[index].get("start", "")))
        end = _seconds_from_timestamp(str(shots[index].get("end", "")))
        proposed_start = (
            _seconds_from_timestamp(str(shots[current[0]].get("start", "")))
            if current
            else start
        )
        exceeds_shots = len(current) >= ANALYSIS_BATCH_MAX_SHOTS
        exceeds_duration = bool(current) and end - proposed_start > ANALYSIS_BATCH_MAX_SECONDS
        crosses_excluded_gap = bool(current) and any(
            bool(shots[gap_index].get("analysis_excluded"))
            for gap_index in range(current[-1] + 1, index)
        )
        if current and (exceeds_shots or exceeds_duration or crosses_excluded_gap):
            batches.append(current)
            current = []
        current.append(index)
    if current:
        batches.append(current)
    return batches


def analysis_batch_context(
    shots: list[dict[str, object]],
    target_indices: list[int],
) -> tuple[list[dict[str, object]], tuple[float, float]]:
    first = target_indices[0]
    last = target_indices[-1]
    if first > 0 and not bool(shots[first - 1].get("analysis_excluded")):
        first -= 1
    if last < len(shots) - 1 and not bool(shots[last + 1].get("analysis_excluded")):
        last += 1
    context_rows = shots[first:last + 1]
    start = _seconds_from_timestamp(str(context_rows[0].get("start", "")))
    end = _seconds_from_timestamp(str(context_rows[-1].get("end", "")))
    return context_rows, (max(0.0, start), max(start + 0.1, end))


def shot_reference_images(
    project_dir: Path,
    shots: list[dict[str, object]],
    target_indices: list[int],
) -> list[tuple[str, Path]]:
    references: list[tuple[str, Path]] = []
    for index in target_indices:
        row = shots[index]
        analysis_id = str(row.get("analysis_id") or timeline_analysis_id(row, index))
        raw_path = str(row.get("screenshot_path") or "").strip()
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.is_absolute():
            path = project_dir / path
        if not path.is_file():
            continue
        label = (
            f"Representative still for SHOT {safe_int(row.get('shot'), index + 1):03d}; "
            f"analysis_id={analysis_id}; source={row.get('start', '')}-{row.get('end', '')}."
        )
        references.append((label, path))
    return references


def candidate_reference_images(
    project_dir: Path,
    timeline_rows: list[dict[str, object]],
    ffmpeg_candidates: list[tuple[float, float]],
) -> list[tuple[str, Path]]:
    current_boundaries = [
        _seconds_from_timestamp(str(row.get("end", "00:00:00.000")))
        for row in timeline_rows[:-1]
    ]
    candidates = deduplicate_transition_candidates([
        (timestamp, score)
        for timestamp, score in ffmpeg_candidates
        if not any(abs(timestamp - boundary) <= 0.45 for boundary in current_boundaries)
    ])
    candidates = sorted(
        sorted(candidates, key=lambda item: item[1], reverse=True)[
            :ANALYSIS_BATCH_MAX_CANDIDATE_REFERENCES
        ],
        key=lambda item: item[0],
    )
    if not candidates:
        return []
    video_path = find_source_video(project_dir.name)
    if video_path is None:
        return []
    evidence_dir = project_dir / "analysis_video" / "candidate_evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = _require_binary("ffmpeg")
    references: list[tuple[str, Path]] = []
    for timestamp, score in candidates:
        output_path = evidence_dir / f"candidate_{int(round(timestamp * 1000)):09d}_compact.jpg"
        if not output_path.exists() or output_path.stat().st_mtime < video_path.stat().st_mtime:
            start = max(0.0, timestamp - 0.4)
            result = _run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    f"{start:.3f}",
                    "-i",
                    str(video_path),
                    "-t",
                    "0.8",
                    "-vf",
                    "fps=10,scale=160:-2,tile=4x2",
                    "-frames:v",
                    "1",
                    "-q:v",
                    "5",
                    str(output_path),
                ]
            )
            if result.returncode != 0 or not output_path.exists():
                continue
        references.append(
            (
                f"Candidate transition at {timestamp:.3f}s (scene score {score:.4f}). "
                "Eight consecutive frames run left-to-right, then top-to-bottom, spanning about "
                "0.4s before through 0.4s after the candidate. Use this strip to decide cut or reject.",
                output_path,
            )
        )
    return references


def deduplicate_transition_candidates(
    candidates: list[tuple[float, float]],
    merge_window_seconds: float = 0.12,
) -> list[tuple[float, float]]:
    """Collapse adjacent-frame detector hits while retaining genuinely rapid cuts."""
    ordered = sorted(
        (
            (float(timestamp), float(score))
            for timestamp, score in candidates
            if timestamp >= 0
        ),
        key=lambda item: item[0],
    )
    if not ordered:
        return []
    clusters: list[list[tuple[float, float]]] = [[ordered[0]]]
    for candidate in ordered[1:]:
        if candidate[0] - clusters[-1][-1][0] <= merge_window_seconds:
            clusters[-1].append(candidate)
        else:
            clusters.append([candidate])
    return [max(cluster, key=lambda item: item[1]) for cluster in clusters]


def prioritize_ffmpeg_candidates_for_ai(
    candidates: list[tuple[float, float]],
    shots: list[dict[str, object]],
    max_per_shot: int = 2,
) -> list[tuple[float, float]]:
    """Keep useful detector evidence without flooding the multimodal request."""
    clustered = deduplicate_transition_candidates(candidates, merge_window_seconds=0.4)
    current_boundaries = [
        _seconds_from_timestamp(str(row.get("end", "00:00:00.000")))
        for row in shots[:-1]
    ]
    unmatched = [
        candidate
        for candidate in clustered
        if not any(abs(candidate[0] - boundary) <= 0.45 for boundary in current_boundaries)
    ]
    selected: list[tuple[float, float]] = []
    for row in shots:
        start = _seconds_from_timestamp(str(row.get("start", "00:00:00.000")))
        end = _seconds_from_timestamp(str(row.get("end", "00:00:00.000")))
        inside = [
            candidate
            for candidate in unmatched
            if start + 0.25 < candidate[0] < end - 0.25
        ]
        selected.extend(
            sorted(inside, key=lambda item: item[1], reverse=True)[:max_per_shot]
        )
    return sorted(selected, key=lambda item: item[0])


def build_narrative_continuity_prompt(
    project_name: str,
    shots: list[dict[str, object]],
    generated_rows: list[dict[str, object]],
    outline: dict[str, object],
    user_context: str,
    film_memory: dict[str, object],
    caption_cues: list[dict[str, object]] | None = None,
    rewrite_all: bool = False,
) -> tuple[str, list[str], bool]:
    generated_by_id = {
        str(row.get("analysis_id") or row.get("row_id") or "").strip(): row
        for row in generated_rows
        if isinstance(row, dict)
    }
    subtitle_by_id = caption_evidence_by_analysis_id(shots, caption_cues or [])
    rewrite_ids: list[str] = []
    catalogue: list[dict[str, object]] = []
    for index, source in enumerate(shots):
        if bool(source.get("analysis_excluded")):
            continue
        analysis_id = str(source.get("analysis_id") or timeline_analysis_id(source, index))
        generated = generated_by_id.get(analysis_id, {})
        combined = {**source, **generated}
        rewrite = rewrite_all or bool(generated)
        if rewrite:
            rewrite_ids.append(analysis_id)
        catalogue.append({
            "analysis_id": analysis_id,
            "shot": safe_int(source.get("shot"), index + 1),
            "start": source.get("start", ""),
            "end": source.get("end", ""),
            "rewrite_row": rewrite,
            "rewrite_narrative_function": (
                rewrite and not is_manual_field(source, "narrative_function")
            ),
            "manual_fields": normalize_manual_fields(source.get("manual_fields")),
            "shot_title": combined.get("shot_title", ""),
            "visual_description": combined.get("visual_description", ""),
            "downloaded_subtitle_dialogue": subtitle_by_id.get(analysis_id, ""),
            "audio_soundtrack_observation": combined.get("audio_dialogue", ""),
            "action_camera": combined.get("action_camera", ""),
            "current_narrative_function": (
                source.get("narrative_function", "")
                if is_manual_field(source, "narrative_function")
                else (
                    ""
                    if rewrite
                    else generated.get("narrative_function", source.get("narrative_function", ""))
                )
            ),
            "narrative_is_human_edited": is_manual_field(source, "narrative_function"),
        })
    normalized_outline = normalize_outline(outline, len(shots))
    generate_outline = not bool(normalized_outline["sentences"])
    sentence_instruction = (
        "Create the filmic-sentence and beat outline now. A filmic sentence is one or more contiguous shots that "
        "work together to convey one action, causal step, emotional turn, comparison, or idea. A beat is a larger "
        "story step that may contain several consecutive sentences. Assign every shot exactly once, keep every "
        "sentence contiguous, and preserve chronological order. Never merge edited shots into one shot merely "
        "because they form a montage: group the individual montage shots inside one or more sentences. Use concise "
        "titles, a short beat label shared by related consecutive sentences, and an idea sentence explaining what "
        "the group conveys. Return shotNumbers using the current catalogue numbers."
        if generate_outline
        else
        "The existing filmic-sentence outline was edited or previously saved. Use it as context but do not redesign "
        "or replace it; return an empty sentences array."
    )
    prompt = (
        f"Film: {project_name}\n\n"
        "This is the final narrative-continuity pass after video-grounded shot extraction. The complete corrected "
        "timeline is below in chronological order. Read it from shot 1 through the end before writing any answer. "
        "Use earlier rows to decide whether a person, place, object, desire, obstacle, or motif is new or recurring. "
        "Do not call a character introduced, established, or revealed if an earlier row already supports their presence. "
        "For later appearances, name the actual continuation: reinforcement, escalation, contrast, callback, causal "
        "consequence, emotional shift, setup, payoff, transition, compression, or reversal.\n\n"
        "Write narrative_function as one or two coherent sentences that explain what this exact shot contributes at "
        "this exact point in the film. Ground the claim in visible action, dialogue, or other audible information and "
        "connect it to the established story when relevant. downloaded_subtitle_dialogue is timed English subtitle "
        "evidence and is the preferred source for the words being spoken; audio_soundtrack_observation supplements it "
        "with delivery, music, ambience, and effects. Explicitly account for important dialogue when it changes what "
        "the viewer knows, wants, expects, or fears. Do not ignore subtitles because the original soundtrack uses "
        "another language. When downloaded_subtitle_dialogue is nonempty and carries story information, the rewritten "
        "narrative_function must explain that information's function, not merely describe the visible composition or "
        "reaction. Blank current_narrative_function means the previous model prose was deliberately withheld; write "
        "a fresh interpretation rather than trying to recover it. Avoid generic phrases such as 'moves the story "
        "forward.' Do not replace human-edited narrative functions.\n\n"
        "IDENTITY SAFETY: Treat this film as a closed world. Do not use franchise knowledge or recognize an actor, "
        "costume, or face from outside the supplied evidence. A proper name in subtitles may refer to an offscreen "
        "person and does not identify the speaker or visible subject. A proper name is established only by a "
        "self-introduction, unambiguous direct address plus visible response, on-screen label, user note, or a "
        "human-edited field. Otherwise use a stable neutral label based on role and appearance, such as 'the kneeling "
        "recruit' or 'the senior officer,' and reuse it across matching appearances. For each rewritten row, return "
        "a concise identity-safe shot_title and list any unsupported or mismatched character names already present "
        "in that row under identity_replacements. Each replacement must include the exact existing text in from and "
        "the supported stable label in to. Do not replace words inside downloaded subtitles. Preserve any field named "
        "in manual_fields.\n\n"
        "User study notes are hypotheses to validate, refine, or reject:\n"
        f"{user_context or '(none provided)'}\n\n"
        "Filmic sentences and beats:\n"
        f"{json.dumps(normalized_outline, ensure_ascii=False, indent=2)}\n\n"
        f"{sentence_instruction}\n\n"
        "Accumulated film memory from the video batches. It may contain mistaken names or duplicate aliases. Audit "
        "it against the closed-world identity rules, consolidate recurring appearances, and replace unsupported "
        "canonical names with stable neutral labels. Each character entry should keep a character_id, display_label, "
        "canonical_name only when established, identity_evidence, confidence, aliases, and first_seen_shot:\n"
        f"{json.dumps(film_memory, ensure_ascii=False, indent=2)}\n\n"
        "Complete chronological catalogue for the user-selected analysis scope:\n"
        f"{json.dumps(catalogue, ensure_ascii=False, indent=2)}\n\n"
        "Return one shots row for every row where rewrite_row is true, and no others. Each row must "
        "contain analysis_id, narrative_function, an identity-safe shot_title of one to seven words, and "
        "identity_replacements (an empty array when none are needed). Also return a clean, consolidated film_memory for the "
        "complete film. Its synopsis must describe the whole story rather than only the last batch. Its characters "
        "must use one closed-world identity entry per recurring character, with aliases/costume changes kept inside "
        "that entry and first_seen_shot recorded. Its narrative_progression must retain chronological causality. Also return "
        "the requested sentences array. Use this shape:\n"
        '{"shots":[{"analysis_id":"...","shot_title":"...","identity_replacements":'
        '[{"from":"unsupported name","to":"stable neutral label"}],"narrative_function":"..."}],'
        '"sentences":[{"id":"sentence-1","beat":"Beat 1","title":"...","idea":"...",'
        '"shotNumbers":[1,2,3]}],'
        '"film_memory":{"synopsis":"...","characters":[],"locations":[],"motifs":[],'
        '"narrative_progression":[],"editing_patterns":[],"cinematography_patterns":[],'
        '"unanswered_questions":[]}}'
    )
    return prompt, rewrite_ids, generate_outline


def parse_narrative_continuity(
    raw_content: str,
    rewrite_ids: list[str],
    shot_count: int,
    generate_outline: bool,
    allowed_shot_numbers: set[int] | None = None,
    allow_missing: bool = False,
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object]]:
    parsed = parse_llm_json(raw_content)
    raw_rows = first_list_value(parsed, ["shots", "rows", "items"])
    rows = [row for row in raw_rows if isinstance(row, dict)] if isinstance(raw_rows, list) else []
    wanted = set(rewrite_ids)
    by_id: dict[str, dict[str, object]] = {}
    for row in rows:
        analysis_id = str(row.get("analysis_id") or "").strip()
        narrative = str(row.get("narrative_function") or "").strip()
        shot_title = compact_shot_title(str(row.get("shot_title") or "").strip())
        if analysis_id not in wanted:
            continue
        if analysis_id in by_id:
            raise ValueError(f"Narrative pass returned duplicate analysis_id {analysis_id}")
        if not narrative:
            raise ValueError(f"Narrative pass omitted narrative_function for {analysis_id}")
        replacements = []
        raw_replacements = row.get("identity_replacements")
        if isinstance(raw_replacements, list):
            for replacement in raw_replacements:
                if not isinstance(replacement, dict):
                    continue
                source_text = str(replacement.get("from") or "").strip()
                target_text = str(replacement.get("to") or "").strip()
                if source_text and target_text and source_text.casefold() != target_text.casefold():
                    replacements.append({"from": source_text, "to": target_text})
        by_id[analysis_id] = {
            "analysis_id": analysis_id,
            "shot_title": shot_title,
            "identity_replacements": replacements,
            "narrative_function": narrative,
        }
    missing = [analysis_id for analysis_id in rewrite_ids if analysis_id not in by_id]
    if missing and not allow_missing:
        raise ValueError(
            "Narrative continuity pass omitted requested analysis IDs: " + ", ".join(missing)
        )
    memory = parsed.get("film_memory") or parsed.get("filmMemory") or {}
    generated_outline = {"sentences": []}
    if generate_outline:
        raw_sentences = parsed.get("sentences")
        if not isinstance(raw_sentences, list):
            raw_outline = parsed.get("outline")
            raw_sentences = (
                raw_outline.get("sentences", [])
                if isinstance(raw_outline, dict)
                else []
            )
        generated_outline = normalize_ai_generated_outline(
            {"sentences": raw_sentences},
            shot_count,
            allowed_shot_numbers=allowed_shot_numbers,
        )
    return (
        [by_id[analysis_id] for analysis_id in rewrite_ids if analysis_id in by_id],
        memory if isinstance(memory, dict) else {},
        generated_outline,
    )


def apply_identity_replacements(
    row: dict[str, object],
    replacements: object,
) -> dict[str, object]:
    cleaned = dict(row)
    if not isinstance(replacements, list):
        return cleaned
    fields = [
        "shot_title",
        "visual_description",
        "action_camera",
        "camera_movement_evidence",
        "narrative_function",
    ]
    for replacement in replacements:
        if not isinstance(replacement, dict):
            continue
        source_text = str(replacement.get("from") or "").strip()
        target_text = str(replacement.get("to") or "").strip()
        if not source_text or not target_text:
            continue
        pattern = re.compile(rf"(?<!\w){re.escape(source_text)}(?!\w)", flags=re.IGNORECASE)
        for field in fields:
            if is_manual_field(cleaned, field):
                continue
            cleaned[field] = pattern.sub(target_text, str(cleaned.get(field) or ""))
    return cleaned


def reconcile_narrative_continuity(
    model: str,
    qwen_api_key: str,
    gemini_api_key: str,
    project_name: str,
    project_dir: Path,
    shots: list[dict[str, object]],
    generated_rows: list[dict[str, object]],
    outline: dict[str, object],
    user_context: str,
    film_memory: dict[str, object],
    history_batch_number: int,
    rewrite_all: bool = False,
) -> tuple[list[dict[str, object]], dict[str, object], dict[str, object], str, str]:
    prompt, rewrite_ids, generate_outline = build_narrative_continuity_prompt(
        project_name,
        shots,
        generated_rows,
        outline,
        user_context,
        film_memory,
        caption_cues=load_project_caption_cues(project_dir),
        rewrite_all=rewrite_all,
    )
    allowed_shot_numbers = {
        safe_int(row.get("shot"), index + 1)
        for index, row in enumerate(shots)
        if not bool(row.get("analysis_excluded"))
    }
    if not rewrite_ids and not generate_outline:
        return generated_rows, film_memory, outline, "", ""

    raw_content = ""
    provider_name = ""
    provider_model = ""
    errors: list[str] = []
    if qwen_api_key:
        qwen_model = os.environ.get("QWEN_NARRATIVE_MODEL", DEFAULT_QWEN_NARRATIVE_MODEL)
        try:
            raw_content = call_qwen_text(
                qwen_api_key,
                qwen_model,
                NARRATIVE_CONTINUITY_INSTRUCTIONS,
                prompt,
            )
            provider_name = "qwen"
            provider_model = qwen_model
        except Exception as exc:
            errors.append(f"Qwen narrative pass failed: {exc}")
            write_llm_error(project_dir, qwen_model, exc, provider="qwen")
    if not raw_content and gemini_api_key:
        gemini_model = os.environ.get("GEMINI_VIDEO_MODEL", DEFAULT_GEMINI_MODEL)
        try:
            raw_content = call_gemini_text(
                gemini_api_key,
                gemini_model,
                f"{NARRATIVE_CONTINUITY_INSTRUCTIONS}\n\n{prompt}",
            )
            provider_name = "gemini"
            provider_model = gemini_model
        except Exception as exc:
            errors.append(f"Gemini narrative pass failed: {exc}")
            write_llm_error(project_dir, gemini_model, exc, provider="gemini")
    if not raw_content:
        raise ValueError("Narrative continuity pass failed. " + " | ".join(errors))

    write_llm_response(
        project_dir,
        provider_model,
        raw_content,
        provider=provider_name,
        batch_number=history_batch_number,
        batch_count=history_batch_number,
        analysis_stage="narrative_continuity",
    )
    try:
        narrative_rows, consolidated_memory, generated_outline = parse_narrative_continuity(
            raw_content,
            rewrite_ids,
            len(shots),
            generate_outline,
            allowed_shot_numbers=allowed_shot_numbers,
        )
    except ValueError as validation_error:
        retry_prompt = (
            f"{prompt}\n\nVALIDATION RETRY: The previous response could not be attached safely: "
            f"{validation_error}. Return the complete response again with every requested analysis_id exactly once. "
            "Do not renumber, summarize, omit, or merge rows. Preserve the requested sentences and film_memory "
            "objects in the same JSON response."
        )
        write_llm_error(project_dir, provider_model, validation_error, provider=provider_name)
        if provider_name == "qwen":
            raw_content = call_qwen_text(
                qwen_api_key,
                provider_model,
                NARRATIVE_CONTINUITY_INSTRUCTIONS,
                retry_prompt,
            )
        elif provider_name == "gemini":
            raw_content = call_gemini_text(
                gemini_api_key,
                provider_model,
                f"{NARRATIVE_CONTINUITY_INSTRUCTIONS}\n\n{retry_prompt}",
            )
        else:
            raise
        write_llm_response(
            project_dir,
            provider_model,
            raw_content,
            provider=provider_name,
            batch_number=history_batch_number,
            batch_count=history_batch_number,
            analysis_stage="narrative_continuity",
        )
        try:
            narrative_rows, consolidated_memory, generated_outline = parse_narrative_continuity(
                raw_content,
                rewrite_ids,
                len(shots),
                generate_outline,
                allowed_shot_numbers=allowed_shot_numbers,
            )
        except ValueError as final_validation_error:
            write_llm_error(
                project_dir,
                provider_model,
                final_validation_error,
                provider=provider_name,
            )
            narrative_rows, consolidated_memory, generated_outline = parse_narrative_continuity(
                raw_content,
                rewrite_ids,
                len(shots),
                generate_outline,
                allowed_shot_numbers=allowed_shot_numbers,
                allow_missing=True,
            )
    narrative_by_id = {str(row["analysis_id"]): row for row in narrative_rows}
    reconciled_rows: list[dict[str, object]] = []
    for row in generated_rows:
        next_row = dict(row)
        analysis_id = str(row.get("analysis_id") or row.get("row_id") or "").strip()
        if analysis_id in narrative_by_id:
            repaired = narrative_by_id[analysis_id]
            if not is_manual_field(next_row, "narrative_function"):
                next_row["narrative_function"] = repaired["narrative_function"]
            if repaired.get("shot_title") and not is_manual_field(next_row, "shot_title"):
                next_row["shot_title"] = repaired["shot_title"]
            next_row = apply_identity_replacements(
                next_row,
                repaired.get("identity_replacements"),
            )
        reconciled_rows.append(next_row)
    return (
        reconciled_rows,
        consolidated_memory or film_memory,
        generated_outline if generate_outline else outline,
        provider_name,
        provider_model,
    )


def generate_shot_details_with_native_video(
    model: str,
    qwen_api_key: str,
    gemini_api_key: str,
    project_name: str,
    project_dir: Path,
    shots: list[dict[str, object]],
    outline: dict[str, object],
    user_context: str,
    ffmpeg_candidates: list[tuple[float, float]],
    target_analysis_ids: list[str] | None = None,
    film_memory: dict[str, object] | None = None,
    full_pass: bool = True,
    clip_bounds: tuple[float, float] | None = None,
    progress_callback=None,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object], str, str]:
    instructions = LLM_INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    batches = plan_analysis_batches(shots, target_analysis_ids)
    if not batches:
        raise ValueError("No current shot intervals were selected for analysis")

    all_rows: list[dict[str, object]] = []
    all_transitions: list[dict[str, object]] = []
    next_memory = dict(film_memory or {})
    provider_name = ""
    provider_model = ""
    caption_cues = load_project_caption_cues(project_dir)

    for batch_number, target_indices in enumerate(batches, start=1):
        batch_progress_start = 8 + ((batch_number - 1) / len(batches)) * 82
        batch_progress_span = 82 / len(batches)

        def batch_progress(fraction: float) -> int:
            return min(90, round(batch_progress_start + batch_progress_span * fraction))

        if progress_callback:
            progress_callback(
                phase="preparing_batch",
                message=(
                    f"Preparing batch {batch_number} of {len(batches)} "
                    f"for shots {target_indices[0] + 1}-{target_indices[-1] + 1}."
                ),
                progress=batch_progress(0),
                batchNumber=batch_number,
                batchCount=len(batches),
            )
        context_rows, batch_bounds = analysis_batch_context(shots, target_indices)
        if len(batches) == 1 and clip_bounds is not None:
            batch_bounds = clip_bounds
        target_ids = [
            str(shots[index].get("analysis_id") or timeline_analysis_id(shots[index], index))
            for index in target_indices
        ]
        batch_candidates = [
            candidate
            for candidate in ffmpeg_candidates
            if batch_bounds[0] <= candidate[0] <= batch_bounds[1]
        ]
        prompt = build_llm_text_prompt(
            project_name,
            context_rows,
            outline,
            user_context,
            ffmpeg_candidates=batch_candidates,
            target_analysis_ids=target_ids,
            film_memory=next_memory,
            full_pass=full_pass,
            clip_bounds=batch_bounds,
            batch_number=batch_number,
            batch_count=len(batches),
            caption_cues=caption_cues,
        )
        shot_references = shot_reference_images(project_dir, shots, target_indices)
        candidate_references = candidate_reference_images(
            project_dir,
            context_rows,
            batch_candidates,
        )
        references = [*shot_references, *candidate_references]
        errors: list[str] = []
        raw_content = ""
        video_paths: list[Path] = []
        gemini_video_path: Path | None = None

        if qwen_api_key:
            qwen_model = normalize_qwen_model(model)
            try:
                video_paths = prepare_qwen_analysis_videos(
                    project_dir,
                    shots=context_rows,
                    clip_bounds=batch_bounds,
                )
                if not video_paths:
                    raise FileNotFoundError("Source video not found for native video analysis")
                if progress_callback:
                    progress_callback(
                        phase="waiting_api",
                        message=f"Batch {batch_number} of {len(batches)} sent to Qwen. Waiting for its response.",
                        progress=batch_progress(0.2),
                        batchNumber=batch_number,
                        batchCount=len(batches),
                        provider="qwen",
                        model=qwen_model,
                    )
                max_attempts = 4
                for attempt in range(max_attempts):
                    attempt_number = attempt + 1
                    attempt_references = references if attempt == 0 else shot_references
                    try:
                        raw_content = call_qwen_video(
                            qwen_api_key,
                            qwen_model,
                            instructions,
                            prompt,
                            video_paths,
                            reference_images=attempt_references,
                            response_callback=(
                                lambda current_attempt=attempt_number: progress_callback(
                                    phase="streaming",
                                    message=(
                                        f"Qwen accepted batch {batch_number} of {len(batches)}. "
                                        "Receiving its response."
                                        if current_attempt == 1
                                        else (
                                            f"Qwen accepted compact retry {current_attempt - 1} of "
                                            f"{max_attempts - 1} for batch {batch_number}."
                                        )
                                    ),
                                    progress=batch_progress(0.45 if current_attempt == 1 else 0.5),
                                    batchNumber=batch_number,
                                    batchCount=len(batches),
                                )
                            ) if progress_callback else None,
                        )
                        break
                    except Exception as transport_error:
                        if (
                            not is_retryable_qwen_transport_error(transport_error)
                            or attempt_number >= max_attempts
                        ):
                            raise
                        if progress_callback:
                            progress_callback(
                                phase="retrying",
                                message=(
                                    f"Qwen interrupted batch {batch_number}. "
                                    f"Retrying with compact evidence "
                                    f"({attempt_number} of {max_attempts - 1} retries used)."
                                ),
                                progress=batch_progress(0.3),
                                batchNumber=batch_number,
                                batchCount=len(batches),
                            )
                        time.sleep(min(2 * attempt_number, 6))
                provider_name = "qwen"
                provider_model = qwen_model
                if progress_callback:
                    progress_callback(
                        phase="validating",
                        message=f"Qwen responded for batch {batch_number} of {len(batches)}. Validating every shot.",
                        progress=batch_progress(0.65),
                        batchNumber=batch_number,
                        batchCount=len(batches),
                    )
            except Exception as exc:
                errors.append(f"Qwen failed: {exc}")
                write_llm_error(project_dir, qwen_model, exc, provider="qwen")

        if not raw_content and gemini_api_key:
            gemini_model = os.environ.get("GEMINI_VIDEO_MODEL", DEFAULT_GEMINI_MODEL)
            try:
                gemini_video_path = prepare_analysis_video(
                    project_dir,
                    max_width=640,
                    fps=8,
                    shots=context_rows,
                    clip_bounds=batch_bounds,
                )
                if gemini_video_path is None:
                    raise FileNotFoundError("Source video not found for native video analysis")
                if progress_callback:
                    progress_callback(
                        phase="waiting_api",
                        message=f"Batch {batch_number} of {len(batches)} sent to Gemini. Waiting for its response.",
                        progress=batch_progress(0.2),
                        batchNumber=batch_number,
                        batchCount=len(batches),
                        provider="gemini",
                        model=gemini_model,
                    )
                raw_content = call_gemini_video(
                    gemini_api_key,
                    gemini_model,
                    instructions,
                    prompt,
                    gemini_video_path,
                    reference_images=references,
                    response_callback=(
                        lambda: progress_callback(
                            phase="streaming",
                            message=f"Gemini accepted batch {batch_number} of {len(batches)}. Receiving its response.",
                            progress=batch_progress(0.45),
                            batchNumber=batch_number,
                            batchCount=len(batches),
                        )
                    ) if progress_callback else None,
                )
                provider_name = "gemini"
                provider_model = gemini_model
                if progress_callback:
                    progress_callback(
                        phase="validating",
                        message=f"Gemini responded for batch {batch_number} of {len(batches)}. Validating every shot.",
                        progress=batch_progress(0.65),
                        batchNumber=batch_number,
                        batchCount=len(batches),
                    )
            except Exception as exc:
                errors.append(f"Gemini failed: {exc}")
                write_llm_error(project_dir, gemini_model, exc, provider="gemini")

        if not raw_content:
            raise ValueError(
                f"Native video analysis failed in batch {batch_number} of {len(batches)}. "
                + " | ".join(errors)
            )

        write_llm_response(
            project_dir,
            provider_model,
            raw_content,
            provider=provider_name,
            batch_number=batch_number,
            batch_count=len(batches),
        )
        audio_fallbacks = {
            str(shots[index].get("analysis_id") or timeline_analysis_id(shots[index], index)): str(
                shots[index].get("audio_dialogue") or ""
            ).strip()
            for index in target_indices
        }
        try:
            rows, transitions, returned_memory = parse_generated_analysis_bundle(raw_content)
            grounded_rows = validate_grounded_analysis_rows(rows, target_ids)
            transitions = reconcile_candidate_decisions(
                raw_content,
                grounded_rows,
                transitions,
                context_rows,
                batch_candidates,
            )
        except ValueError as validation_error:
            if progress_callback:
                progress_callback(
                    phase="retrying",
                    message=(
                        f"Batch {batch_number} was incomplete. Asking {provider_name.title()} "
                        "for the missing shot fields once more."
                    ),
                    progress=batch_progress(0.75),
                    batchNumber=batch_number,
                    batchCount=len(batches),
                )
            retry_prompt = (
                f"{prompt}\n\nVALIDATION RETRY: Your previous response could not be attached safely: "
                f"{validation_error}. Return the complete batch again. Include every required field for every exact "
                "analyze_now analysis_id, even when the correct audio value is simply that no dialogue is heard. "
                "Do not omit fields and do not return only the corrected row."
            )
            write_llm_error(project_dir, provider_model, validation_error, provider=provider_name)
            if provider_name == "qwen" and video_paths:
                raw_content = call_qwen_video(
                    qwen_api_key,
                    provider_model,
                    instructions,
                    retry_prompt,
                    video_paths,
                    reference_images=references,
                    response_callback=(
                        lambda: progress_callback(
                            phase="streaming",
                            message=f"Qwen accepted the repair request for batch {batch_number}. Receiving its response.",
                            progress=batch_progress(0.85),
                            batchNumber=batch_number,
                            batchCount=len(batches),
                        )
                    ) if progress_callback else None,
                )
            elif provider_name == "gemini" and gemini_video_path is not None:
                raw_content = call_gemini_video(
                    gemini_api_key,
                    provider_model,
                    instructions,
                    retry_prompt,
                    gemini_video_path,
                    reference_images=references,
                    response_callback=(
                        lambda: progress_callback(
                            phase="streaming",
                            message=f"Gemini accepted the repair request for batch {batch_number}. Receiving its response.",
                            progress=batch_progress(0.85),
                            batchNumber=batch_number,
                            batchCount=len(batches),
                        )
                    ) if progress_callback else None,
                )
            else:
                raise
            write_llm_response(
                project_dir,
                provider_model,
                raw_content,
                provider=provider_name,
                batch_number=batch_number,
                batch_count=len(batches),
            )
            rows, transitions, returned_memory = parse_generated_analysis_bundle(raw_content)
            grounded_rows = validate_grounded_analysis_rows(
                rows,
                target_ids,
                audio_fallbacks=audio_fallbacks,
            )
            transitions = reconcile_candidate_decisions(
                raw_content,
                grounded_rows,
                transitions,
                context_rows,
                batch_candidates,
            )
        all_rows.extend(grounded_rows)
        all_transitions.extend(transitions)
        if returned_memory:
            next_memory = merge_film_memory(next_memory, returned_memory)
        if progress_callback:
            progress_callback(
                phase="batch_complete",
                message=f"Batch {batch_number} of {len(batches)} complete.",
                progress=batch_progress(1),
                batchNumber=batch_number,
                batchCount=len(batches),
            )

    return all_rows, all_transitions, next_memory, provider_name, provider_model


def validate_grounded_analysis_rows(
    rows: list[dict[str, object]],
    target_ids: list[str],
    audio_fallbacks: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    wanted = set(target_ids)
    by_id: dict[str, dict[str, object]] = {}
    for row in rows:
        analysis_id = str(row.get("analysis_id") or row.get("row_id") or "").strip()
        if analysis_id not in wanted:
            continue
        if analysis_id in by_id:
            raise ValueError(f"LLM returned duplicate analysis_id {analysis_id}")
        normalized_row = dict(row)
        missing_fields = [
            field
            for field in REQUIRED_ANALYSIS_FIELDS
            if not isinstance(normalized_row.get(field), str) or not str(normalized_row.get(field)).strip()
        ]
        if missing_fields == ["audio_dialogue"] and audio_fallbacks is not None:
            fallback = str(audio_fallbacks.get(analysis_id) or "").strip()
            if is_placeholder_audio(fallback):
                fallback = "No clear dialogue or audio detail was returned for this interval."
            normalized_row["audio_dialogue"] = fallback
            missing_fields = []
        if missing_fields:
            raise ValueError(
                f"LLM row {analysis_id} omitted required fields: {', '.join(missing_fields)}"
            )
        by_id[analysis_id] = normalized_row

    missing_ids = [analysis_id for analysis_id in target_ids if analysis_id not in by_id]
    if missing_ids:
        raise ValueError(
            "LLM response omitted requested analysis IDs: " + ", ".join(missing_ids)
        )
    return [by_id[analysis_id] for analysis_id in target_ids]


def merge_film_memory(
    current: dict[str, object],
    returned: dict[str, object],
) -> dict[str, object]:
    merged = dict(current)
    returned_summary = str(returned.get("synopsis") or "").strip()
    if returned_summary:
        merged["synopsis"] = returned_summary
    merged.pop("sequence_summaries", None)

    for key, value in returned.items():
        if key in {"synopsis", "sequence_summaries"}:
            continue
        if isinstance(value, list):
            combined: list[object] = []
            seen: set[str] = set()
            for item in value:
                identity = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, (dict, list)) else str(item).strip().casefold()
                if not identity or identity in seen:
                    continue
                seen.add(identity)
                combined.append(item)
            merged[key] = combined
        elif isinstance(value, dict):
            existing = merged.get(key)
            merged[key] = {**(existing if isinstance(existing, dict) else {}), **value}
        elif value not in (None, ""):
            merged[key] = value
    return merged


def parse_generated_shot_rows(raw_content: str) -> list[dict[str, object]]:
    rows, _transitions = parse_generated_analysis(raw_content)
    return rows


def parse_generated_analysis(
    raw_content: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    rows, transitions, _film_memory = parse_generated_analysis_bundle(raw_content)
    return rows, transitions


def parse_generated_analysis_bundle(
    raw_content: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    parsed = parse_llm_json(raw_content)
    rows = first_list_value(parsed, ["shots", "shot_details", "shotDetails", "rows", "items", "data"])
    if not isinstance(rows, list):
        keys = ", ".join(parsed.keys())
        raise ValueError(f"LLM response did not include a shots array. Returned keys: {keys or '(none)'}")
    transitions = first_list_value(parsed, ["transitions", "shot_boundaries", "boundaries", "cuts"])
    memory = parsed.get("film_memory") or parsed.get("filmMemory") or {}
    return (
        [row for row in rows if isinstance(row, dict)],
        [row for row in transitions if isinstance(row, dict)] if isinstance(transitions, list) else [],
        memory if isinstance(memory, dict) else {},
    )


def candidate_decisions_from_response(raw_content: str) -> list[dict[str, object]]:
    parsed = parse_llm_json(raw_content)
    decisions = first_list_value(
        parsed,
        ["candidate_decisions", "candidateDecisions", "ffmpeg_candidate_decisions"],
    )
    return [row for row in decisions if isinstance(row, dict)] if isinstance(decisions, list) else []


def ai_confirms_internal_edits(row: dict[str, object]) -> bool:
    evidence = " ".join(
        str(row.get(field) or "")
        for field in ("shot_title", "visual_description", "action_camera", "notes")
    ).casefold()
    cues = (
        "multiple rapid cuts",
        "multiple hard cuts",
        "internal cuts",
        "internal edits",
        "contains internal edits",
        "comprises several distinct scenes",
        "several distinct scenes edited",
        "transitions are hard cuts",
        "hard cuts connecting them",
        "mini-montage",
    )
    return any(cue in evidence for cue in cues)


def reconcile_candidate_decisions(
    raw_content: str,
    generated_rows: list[dict[str, object]],
    transitions: list[dict[str, object]],
    timeline_rows: list[dict[str, object]],
    ffmpeg_candidates: list[tuple[float, float]],
) -> list[dict[str, object]]:
    current_boundaries = [
        _seconds_from_timestamp(str(row.get("end", "00:00:00.000")))
        for row in timeline_rows[:-1]
    ]
    unmatched_candidates = [
        candidate
        for candidate in ffmpeg_candidates
        if not any(abs(candidate[0] - boundary) <= 0.45 for boundary in current_boundaries)
    ]
    if not unmatched_candidates:
        return transitions

    reconciled = list(transitions)
    generated_by_id = {
        str(row.get("analysis_id") or row.get("row_id") or "").strip(): row
        for row in generated_rows
    }
    montage_ranges: list[tuple[float, float, dict[str, object]]] = []
    for index, timeline_row in enumerate(timeline_rows):
        analysis_id = str(
            timeline_row.get("analysis_id") or timeline_analysis_id(timeline_row, index)
        ).strip()
        generated = generated_by_id.get(analysis_id)
        if generated and ai_confirms_internal_edits(generated):
            montage_ranges.append(
                (
                    _seconds_from_timestamp(str(timeline_row.get("start", ""))),
                    _seconds_from_timestamp(str(timeline_row.get("end", ""))),
                    generated,
                )
            )

    decisions = candidate_decisions_from_response(raw_content)
    missing: list[float] = []
    for timestamp, score in unmatched_candidates:
        if any(
            abs((transition_seconds(row.get("time_seconds")) or -999.0) - timestamp) <= 0.45
            for row in reconciled
        ):
            continue
        decision = next(
            (
                row
                for row in decisions
                if abs(
                    (transition_seconds(
                        row.get("time_seconds") or row.get("timestamp") or row.get("time")
                    ) or -999.0)
                    - timestamp
                ) <= 0.45
            ),
            None,
        )
        decision_label = str(
            (decision or {}).get("decision")
            or (decision or {}).get("verdict")
            or (decision or {}).get("result")
            or ""
        ).strip().casefold()
        if decision_label in {"cut", "accept", "accepted", "transition", "real_cut", "real transition"}:
            reconciled.append(
                {
                    "time_seconds": timestamp,
                    "transition_type": str(
                        decision.get("transition_type") or decision.get("type") or "hard_cut"
                    ),
                    "confidence": str(decision.get("confidence") or "high"),
                    "from_visual": str(decision.get("from_visual") or ""),
                    "to_visual": str(decision.get("to_visual") or ""),
                    "reason": str(
                        decision.get("reason")
                        or f"AI accepted FFmpeg candidate at {timestamp:.3f}s."
                    ),
                }
            )
            continue
        if decision_label in {"reject", "rejected", "not_a_cut", "no_cut", "continuous"}:
            continue

        montage = next(
            (
                item
                for item in montage_ranges
                if item[0] + 0.25 < timestamp < item[1] - 0.25
            ),
            None,
        )
        if montage is not None:
            generated = montage[2]
            reconciled.append(
                {
                    "time_seconds": timestamp,
                    "transition_type": "hard_cut",
                    "confidence": "high" if score >= 0.18 else "medium",
                    "from_visual": "",
                    "to_visual": "",
                    "reason": (
                        "The model identified this interval as a montage with internal hard cuts; "
                        f"FFmpeg localized this edit at {timestamp:.3f}s."
                    ),
                    "analysis_id": str(generated.get("analysis_id") or ""),
                }
            )
            continue
        missing.append(timestamp)

    if missing:
        formatted = ", ".join(f"{timestamp:.3f}s" for timestamp in missing)
        raise ValueError(
            "The model did not accept or reject every unmatched FFmpeg candidate: "
            f"{formatted}. Return one candidate_decisions entry for each timestamp."
        )
    return reconciled


def write_llm_response(
    project_dir: Path,
    model: str,
    raw_content: str,
    provider: str = "",
    batch_number: int = 1,
    batch_count: int = 1,
    analysis_stage: str = "video_batch",
) -> None:
    payload = {
        "provider": provider,
        "model": model,
        "savedAt": datetime.now().isoformat(timespec="seconds"),
        "batchNumber": batch_number,
        "batchCount": batch_count,
        "analysisStage": analysis_stage,
        "contentPreview": raw_content[:4000],
        "content": raw_content,
    }
    (project_dir / LAST_LLM_RESPONSE_FILENAME).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with (project_dir / "llm_response_history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_llm_error(project_dir: Path, model: str, exc: Exception, provider: str = "") -> None:
    payload = {
        "provider": provider,
        "model": model,
        "savedAt": datetime.now().isoformat(timespec="seconds"),
        "error": str(exc),
    }
    (project_dir / LAST_LLM_ERROR_FILENAME).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def first_list_value(payload: dict[str, object], keys: list[str]) -> object:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return None


def build_llm_text_prompt(
    project_name: str,
    shots: list[dict[str, object]],
    outline: dict[str, object],
    user_context: str,
    ffmpeg_candidates: list[tuple[float, float]] | None = None,
    target_analysis_ids: list[str] | None = None,
    film_memory: dict[str, object] | None = None,
    full_pass: bool = True,
    clip_bounds: tuple[float, float] | None = None,
    batch_number: int = 1,
    batch_count: int = 1,
    caption_cues: list[dict[str, object]] | None = None,
) -> str:
    target_ids = set(target_analysis_ids or [
        timeline_analysis_id(shot, index) for index, shot in enumerate(shots)
    ])
    subtitle_by_id = caption_evidence_by_analysis_id(shots, caption_cues or [])
    compact_rows = []
    for index, shot in enumerate(shots):
        analysis_id = str(shot.get("analysis_id") or timeline_analysis_id(shot, index))
        current_shot = safe_int(shot.get("shot"), index + 1)
        manual_fields = normalize_manual_fields(shot.get("manual_fields"))

        def trusted_existing(field: str) -> str:
            if field not in manual_fields:
                return ""
            return str(shot.get(field, ""))

        compact_rows.append(
            {
                "analysis_id": analysis_id,
                "shot": current_shot,
                "current_shot": current_shot,
                "analyze_now": analysis_id in target_ids,
                "was_combined_split_or_reordered": bool(shot.get("analysis_stale")) or is_structurally_edited_row(shot, index),
                "manual_fields": manual_fields,
                "human_edited_title": trusted_existing("shot_title"),
                "start": shot.get("start", ""),
                "end": shot.get("end", ""),
                "duration_seconds": shot.get("duration_seconds", 0),
                "human_edited_visual_description": trusted_existing("visual_description"),
                "human_edited_audio_dialogue": trusted_existing("audio_dialogue"),
                "downloaded_subtitle_dialogue": subtitle_by_id.get(analysis_id, ""),
                "human_edited_action_camera": trusted_existing("action_camera"),
                "human_edited_camera_movement_type": trusted_existing("camera_movement_type"),
                "human_edited_camera_movement_intensity": trusted_existing("camera_movement_intensity"),
                "human_edited_camera_movement_confidence": trusted_existing("camera_movement_confidence"),
                "human_edited_camera_movement_evidence": trusted_existing("camera_movement_evidence"),
                "human_edited_narrative_function": trusted_existing("narrative_function"),
                "human_edited_notes": trusted_existing("notes"),
            }
        )
    current_boundaries = [
        round(_seconds_from_timestamp(str(row.get("end", "00:00:00.000"))), 3)
        for row in shots[:-1]
    ]
    candidate_rows = [
        {"time_seconds": round(timestamp, 3), "scene_score": round(score, 4)}
        for timestamp, score in (ffmpeg_candidates or [])
    ]
    if batch_count > 1:
        mode_label = (
            f"{'full-film first pass' if full_pass else 'incremental update'}, "
            f"chronological evidence batch {batch_number} of {batch_count}"
        )
    else:
        mode_label = "full-film first pass" if full_pass else "incremental update of edited shots"
    return (
        f"Film: {project_name}\n\n"
        f"Analysis mode: {mode_label}\n"
        f"Attached video range in original film time: {clip_bounds if clip_bounds else 'complete film'}\n\n"
        "Persistent film memory from the prior pass. Treat this as context, not as visual evidence for a changed shot:\n"
        f"{json.dumps(film_memory or {}, ensure_ascii=False, indent=2)}\n\n"
        "On batches after the first, this memory represents the story already seen. Use its canonical character "
        "identities and first appearances. Do not introduce a recurring character again because their wardrobe, age, "
        "camera angle, or wording differs. The returned film_memory must be one compact cumulative account of the "
        "story through the end of this batch, not a summary of this clip alone.\n\n"
        "User study notes / hypotheses:\n"
        f"{user_context or '(none provided)'}\n\n"
        "Current edited timeline containers. Their order, analysis_id values, and start/end timestamps are "
        "authoritative for mapping descriptions back to the interface, but a container may still contain two or "
        "more edited shots. Use only these rows for analysis. "
        "Ignore any original detector numbering that may exist elsewhere; it is not part of this request. "
        "Return output rows only for rows where analyze_now is true, in their current order, with the exact same "
        "analysis_id and current_shot/shot number. Rows where analyze_now is false are context only and must not be regenerated:\n"
        f"{json.dumps(compact_rows, ensure_ascii=False, indent=2)}\n\n"
        "Only human_edited_* values are trusted prior annotations. Empty human_edited_* fields mean the prior value "
        "was model-generated or absent and has intentionally been withheld. Do not reconstruct, guess, or preserve a "
        "withheld prior description. Generate it fresh from the attached evidence. downloaded_subtitle_dialogue is "
        "different: it is timestamp-aligned English source evidence extracted from the video or source captions. "
        "Treat it as the preferred evidence for the words being spoken, even when the audible language is not English. "
        "Use the soundtrack to add speaker delivery, music, ambience, silence, and effects. Preserve the subtitle's "
        "meaning in audio_dialogue, and use consequential dialogue when writing narrative_function and film_memory.\n\n"
        "Current filmic sentence / beat outline. Use it as viewer context when present:\n"
        f"{json.dumps(outline, ensure_ascii=False, indent=2)}\n\n"
        "During this same viewing, independently check shot boundaries visible in the attached video range. Current boundaries in seconds:\n"
        f"{json.dumps(current_boundaries)}\n\n"
        "FFmpeg low-threshold candidates are local evidence, not guaranteed cuts:\n"
        f"{json.dumps(candidate_rows, ensure_ascii=False, indent=2)}\n\n"
        "For each unmatched candidate, a labeled eight-frame evidence strip follows the representative stills. "
        "Read each strip left-to-right, then top-to-bottom. Compare subject position, background continuity, object "
        "placement, motion trajectory, and camera setup across its midpoint before deciding.\n\n"
        "Explicitly inspect every FFmpeg candidate that is more than 0.45 seconds from a current boundary. FFmpeg "
        "does not decide the edit; you do. For every such candidate, return one candidate_decisions object with "
        "time_seconds, decision ('cut' or 'reject'), confidence, transition_type, from_visual, to_visual, and reason. "
        "A rejected candidate must explain the continuous action or artifact. Also return each accepted candidate "
        "in transitions. Do not silently skip a candidate because it is absent from the current timeline.\n\n"
        "Return every real visual transition you observe in a top-level transitions array, including transitions "
        "already represented by the current boundaries. Look especially for dissolves, crossfades, fades, and "
        "other gradual transitions that FFmpeg may miss. Do not treat camera movement, subject movement, animation "
        "inside one composition, or lighting changes as cuts. Each transition object must contain time_seconds, "
        "transition_type, confidence (high, medium, or low), from_visual, to_visual, and reason. For a gradual "
        "transition, also include transition_start_seconds and transition_end_seconds.\n\n"
        "Audit every analyze_now interval explicitly by comparing its beginning, middle, and end. If the ending "
        "composition cannot be reached continuously from the opening composition, inspect that interval for a cut, "
        "dissolve, crossfade, fade, wipe, or other edit. Do not return an empty transitions array merely because the "
        "current boundaries look plausible. A montage is a filmic sentence made from multiple individual shots, "
        "not a single shot type: return every internal edit in a montage as its own transition.\n\n"
        "For each transition that is more than 0.45 seconds away from every current boundary, it is a missing cut "
        "inside one current shot that the app will apply automatically. Include before_details and after_details objects for the two proposed "
        "shots on either side. Each object must contain the same descriptive fields as a shot row, including a "
        "1-to-7-word shot_title. This lets the app apply the cut and its details without another model request. "
        "Do not include before_details or after_details for an existing current boundary.\n\n"
        "A continuous video clip is attached to this request. On a long first pass, the app processes the film in "
        "chronological batches and carries the film memory forward; on later passes it sends only the changed region "
        "plus neighboring shots. Its top-left SHOT label and timestamp-derived analysis_id are burned into every frame from "
        "the user's current edited timeline. Use that visible label as the authoritative mapping for every title and "
        "description; never carry an action forward or backward into a differently labeled shot. Analyze each shot "
        "using the exact start/end timestamps above. "
        "Treat those timings as current analysis containers, not proof that no internal edit exists. If one label "
        "contains multiple compositions joined by edits, return those edits in transitions even though the label "
        "does not change. For camera movement, watch the motion inside "
        "each time range and distinguish camera movement from actor, object, or edit movement. Compare fixed "
        "background anchors at the beginning, middle, and end. A person, bicycle, vehicle, prop, gate, shadow, "
        "foreground object, or animated drawing moving through a fixed composition is subject movement, not a pan "
        "or track. In side-scrolling animation, call a move tracking only when stable framing or parallax clearly "
        "supports it; otherwise use static or unclear. Never infer handheld operation in animation without "
        "unmistakable whole-frame shake.\n\n"
        "After the video, the request includes one labeled representative still for every analyze_now shot. The label "
        "immediately before each image names its exact analysis_id and source interval. Treat that still as a visual "
        "anchor: the returned visual_description for that ID must visibly match it. The video supplies motion, timing, "
        "expression changes, and camera evidence. Ignore remembered knowledge of this film when it conflicts with the "
        "attached evidence. Do not mention characters, settings, props, or events from neighboring or later shots.\n\n"
        "Name a recurring character only when this exact interval supports the identity. Similar staging, paired "
        "riders, an adult beside a child, or a repeated silhouette may be a visual rhyme rather than the same people. "
        "Use neutral labels such as 'an adult cyclist', 'a child', or 'two riders' when identity is uncertain.\n\n"
        "For every shot, generate shot_title as a concise card label of 1 to 7 words. "
        "Do not include the shot number in shot_title. Prefer concrete place/action/story language over generic labels.\n\n"
        "Write visual_description as a rich image-prompt-like record grounded in the representative still and video: "
        "shot type; every important subject and object; character wardrobe, pose, gaze, and facial expression; foreground, "
        "middle ground, background, and setting details; composition and screen position; depth; lighting; color palette; "
        "texture; and atmosphere. Aim for 70-140 words when evidence supports it.\n\n"
        "Write action_camera as a chronological record of only this interval. Include major and secondary physical actions, "
        "gaze and expression changes, object/environment/lighting changes, and camera movement. Use approximate offsets "
        "relative to the shot start, for example '0.0-1.2s', when observable. End with a Camera statement. Aim for "
        "40-110 words when evidence supports it.\n\n"
        "Write narrative_function in relation to the story already established. Use 'introduces' or 'establishes' only "
        "for a genuinely first supported appearance or fact. Otherwise identify how the shot continues, reinforces, "
        "escalates, contrasts, recalls, causes, delays, reverses, or pays off earlier information. A final continuity "
        "pass will compare these provisional judgments against the complete chronological catalogue.\n\n"
        "Return exactly one JSON object with top-level keys named \"shots\", \"transitions\", "
        "\"candidate_decisions\", and \"film_memory\". "
        "The shots value must contain one object for every analyze_now row, using the exact field names requested. "
        "Every returned shot must include analysis_id copied exactly from the input row. film_memory must be a compact "
        "updated object with synopsis, characters, locations, motifs, narrative_progression, editing_patterns, "
        "cinematography_patterns, and unanswered_questions. Preserve still-valid prior memory while incorporating the new evidence."
    )


def image_data_url(path: Path) -> str | None:
    if not path.is_file():
        return None
    mime_type, _encoding = mimetypes.guess_type(path)
    if not (mime_type or "").startswith("image/"):
        mime_type = "image/jpeg"
    return f"data:{mime_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def video_data_url(path: Path) -> str:
    mime_type, _encoding = mimetypes.guess_type(path)
    if not (mime_type or "").startswith("video/"):
        mime_type = "video/mp4"
    return f"data:{mime_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def normalize_qwen_model(model: str) -> str:
    cleaned = (model or "").strip()
    if cleaned.startswith("qwen/"):
        cleaned = cleaned.split("/", 1)[1]
    if cleaned == "qwen3.5-plus-20260420":
        return os.environ.get("QWEN_VIDEO_MODEL", DEFAULT_QWEN_VIDEO_MODEL)
    return cleaned or os.environ.get("QWEN_VIDEO_MODEL", DEFAULT_QWEN_VIDEO_MODEL)


def ass_timestamp(seconds: float) -> str:
    safe_seconds = max(0.0, seconds)
    hours = int(safe_seconds // 3600)
    minutes = int((safe_seconds % 3600) // 60)
    remainder = safe_seconds - hours * 3600 - minutes * 60
    return f"{hours}:{minutes:02d}:{remainder:05.2f}"


def write_analysis_labels(
    path: Path,
    shots: list[dict[str, object]],
    width: int,
    offset_seconds: float = 0.0,
    clip_end_seconds: float | None = None,
) -> None:
    events = []
    for index, row in enumerate(shots):
        try:
            start = _seconds_from_timestamp(str(row.get("start", "00:00:00.000")))
            end = _seconds_from_timestamp(str(row.get("end", "00:00:00.000")))
        except (TypeError, ValueError):
            continue
        if end <= offset_seconds or (clip_end_seconds is not None and start >= clip_end_seconds):
            continue
        label_start = max(0.0, start - offset_seconds)
        visible_end = min(end, clip_end_seconds) if clip_end_seconds is not None else end
        label_end = max(label_start + 0.01, visible_end - offset_seconds)
        analysis_id = str(row.get("analysis_id") or timeline_analysis_id(row, index))
        shot_number = safe_int(row.get("shot"), index + 1)
        events.append(
            f"Dialogue: 0,{ass_timestamp(label_start)},{ass_timestamp(label_end)},ShotLabel,,0,0,0,,"
            f"SHOT {shot_number:03d}  {analysis_id}  SOURCE {start:.3f}-{end:.3f}s"
        )
    content = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            "PlayResY: 360",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
            "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            "Style: ShotLabel,Arial,19,&H00FFFFFF,&H000000FF,&H00000000,&H99000000,"
            "-1,0,0,0,100,100,0,0,3,1,0,7,18,18,16,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            *events,
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")


def ffmpeg_filter_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def prepare_analysis_video(
    project_dir: Path,
    max_width: int = 640,
    fps: int = 8,
    shots: list[dict[str, object]] | None = None,
    clip_bounds: tuple[float, float] | None = None,
    max_bytes: int | None = None,
) -> Path | None:
    video_path = find_source_video(project_dir.name)
    if video_path is None:
        return None

    analysis_dir = project_dir / "analysis_video"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    timeline_payload = [
        {
            "start": str(row.get("start", "")),
            "end": str(row.get("end", "")),
        }
        for row in (shots or [])
    ]
    if clip_bounds is not None:
        timeline_payload.append({"clip_start": clip_bounds[0], "clip_end": clip_bounds[1]})
    timeline_hash = hashlib.sha1(
        json.dumps(timeline_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:10] if timeline_payload else "plain"
    output_path = analysis_dir / f"{project_dir.name}_analysis_{max_width}w_{fps}fps_{timeline_hash}.mp4"
    if (
        output_path.exists()
        and output_path.stat().st_mtime >= video_path.stat().st_mtime
        and (not max_bytes or output_path.stat().st_size <= max_bytes)
    ):
        return output_path

    ffmpeg = _require_binary("ffmpeg")
    filters = [f"scale='min({max_width},iw)':-2"]
    if shots:
        labels_path = analysis_dir / f"shot_labels_{timeline_hash}.ass"
        write_analysis_labels(
            labels_path,
            shots,
            max_width,
            offset_seconds=clip_bounds[0] if clip_bounds else 0.0,
            clip_end_seconds=clip_bounds[1] if clip_bounds else None,
        )
        filters.append(f"subtitles='{ffmpeg_filter_path(labels_path)}'")

    input_args = []
    if clip_bounds is not None:
        input_args = ["-ss", f"{clip_bounds[0]:.3f}", "-t", f"{clip_bounds[1] - clip_bounds[0]:.3f}"]
    result = _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *input_args,
            "-i",
            str(video_path),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-vf",
            ",".join(filters),
            "-r",
            str(fps),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-ac",
            "1",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    if result.returncode != 0 or not output_path.exists():
        raise VideoToolError(result.stderr.strip() or "Could not prepare native video analysis copy.")
    if max_bytes and output_path.stat().st_size > max_bytes:
        duration = (
            clip_bounds[1] - clip_bounds[0]
            if clip_bounds
            else max(
                0.1,
                _seconds_from_timestamp(str((shots or [{}])[-1].get("end", "00:00:00.100"))),
            )
        )
        total_kbps = max(56, int((max_bytes * 8 / duration / 1000) * 0.9))
        audio_kbps = 24
        video_kbps = max(32, total_kbps - audio_kbps)
        capped_path = output_path.with_name(f"{output_path.stem}_capped.mp4")
        capped = _run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(output_path),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-b:v",
                f"{video_kbps}k",
                "-maxrate",
                f"{video_kbps}k",
                "-bufsize",
                f"{video_kbps * 2}k",
                "-c:a",
                "aac",
                "-b:a",
                f"{audio_kbps}k",
                "-ac",
                "1",
                "-movflags",
                "+faststart",
                str(capped_path),
            ]
        )
        if capped.returncode != 0 or not capped_path.exists():
            raise VideoToolError(capped.stderr.strip() or "Could not fit video inside the Qwen upload limit.")
        capped_path.replace(output_path)
    if max_bytes and output_path.stat().st_size > max_bytes:
        raise VideoToolError("Prepared analysis video is still too large for Qwen Base64 input.")
    return output_path


def prepare_qwen_analysis_videos(
    project_dir: Path,
    shots: list[dict[str, object]],
    clip_bounds: tuple[float, float] | None = None,
) -> list[Path]:
    if clip_bounds is not None:
        bounds = [clip_bounds]
    else:
        film_end = max(
            (_seconds_from_timestamp(str(row.get("end", ""))) for row in shots),
            default=0.0,
        )
        if film_end <= 0:
            bounds = [None]
        else:
            bounds = []
            segment_start = 0.0
            while segment_start < film_end:
                segment_end = min(film_end, segment_start + QWEN_ANALYSIS_SEGMENT_SECONDS)
                bounds.append((segment_start, segment_end))
                segment_start = segment_end

    paths: list[Path] = []
    for bounds_item in bounds:
        path = prepare_analysis_video(
            project_dir,
            max_width=512,
            fps=4,
            shots=shots,
            clip_bounds=bounds_item,
            max_bytes=QWEN_BASE64_VIDEO_LIMIT_BYTES,
        )
        if path is None:
            return []
        paths.append(path)
    return paths


def call_qwen_video(
    api_key: str,
    model: str,
    instructions: str,
    prompt: str,
    video_paths: Path | list[Path],
    reference_images: list[tuple[str, Path]] | None = None,
    response_callback=None,
) -> str:
    is_omni = "omni" in model.casefold()
    paths = [video_paths] if isinstance(video_paths, Path) else video_paths
    video_parts = [
        {"type": "video_url", "video_url": {"url": video_data_url(path)}, "fps": 2}
        for path in paths
    ]
    reference_parts: list[dict[str, object]] = []
    for label, path in reference_images or []:
        data_url = image_data_url(path)
        if not data_url:
            continue
        reference_parts.extend([
            {"type": "text", "text": label},
            {"type": "image_url", "image_url": {"url": data_url}},
        ])
    if len(paths) > 1:
        prompt = (
            f"The {len(paths)} attached videos are consecutive transport segments of one film, "
            "in chronological order. A file boundary is not a cinematic cut. Use the burned-in "
            "SOURCE timestamps and SHOT labels as the canonical timeline.\n\n"
            + prompt
        )
    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": instructions},
            {
                "role": "user",
                "content": [
                    *video_parts,
                    *reference_parts,
                    {"type": "text", "text": prompt},
                ],
            },
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    if is_omni:
        request_body["stream"] = True
        request_body["stream_options"] = {"include_usage": True}
        request_body["modalities"] = ["text"]
    else:
        request_body["enable_thinking"] = False
    url = os.environ.get("QWEN_COMPATIBLE_URL", QWEN_COMPATIBLE_URL)
    if is_omni:
        return call_chat_completion_stream(url, api_key, request_body, "Qwen", response_callback=response_callback)
    return call_chat_completion(url, api_key, request_body, "Qwen", response_callback=response_callback)


def is_retryable_qwen_transport_error(exc: Exception) -> bool:
    message = str(exc).casefold()
    return any(
        marker in message
        for marker in (
            "could not reach qwen",
            "connection reset",
            "connection was forcibly closed",
            "remote end closed",
            "timed out",
            "winerror 10054",
            "stream ended before completion",
        )
    )


def call_qwen_text(api_key: str, model: str, instructions: str, prompt: str) -> str:
    is_omni = "omni" in model.casefold()
    request_body: dict[str, object] = {
        "model": model,
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 32768,
        "response_format": {"type": "json_object"},
    }
    if is_omni:
        request_body["stream"] = True
        request_body["stream_options"] = {"include_usage": True}
        request_body["modalities"] = ["text"]
    else:
        request_body["enable_thinking"] = False
    url = os.environ.get("QWEN_COMPATIBLE_URL", QWEN_COMPATIBLE_URL)
    if is_omni:
        return call_chat_completion_stream(url, api_key, request_body, "Qwen")
    return call_chat_completion(url, api_key, request_body, "Qwen")


def call_gemini_video(
    api_key: str,
    model: str,
    instructions: str,
    prompt: str,
    video_path: Path,
    reference_images: list[tuple[str, Path]] | None = None,
    response_callback=None,
) -> str:
    text_prompt = f"{instructions}\n\n{prompt}"
    if video_path.stat().st_size > GEMINI_INLINE_VIDEO_LIMIT_BYTES:
        file_uri, mime_type = upload_gemini_video_file(api_key, video_path)
        video_part = {"type": "video", "uri": file_uri, "mime_type": mime_type}
    else:
        video_part = {
            "type": "video",
            "data": base64.b64encode(video_path.read_bytes()).decode("ascii"),
            "mime_type": "video/mp4",
        }

    reference_parts: list[dict[str, object]] = []
    for label, path in reference_images or []:
        mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        reference_parts.extend([
            {"type": "text", "text": label},
            {
                "type": "image",
                "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                "mime_type": mime_type,
            },
        ])
    body = {
        "model": model,
        "input": [
            video_part,
            *reference_parts,
            {"type": "text", "text": text_prompt},
        ],
    }
    request = Request(
        os.environ.get("GEMINI_INTERACTIONS_URL", GEMINI_INTERACTIONS_URL),
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(request, timeout=240) as response:
            if response_callback:
                response_callback()
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"Gemini error {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ValueError(f"Could not reach Gemini: {exc.reason}") from exc
    record_api_usage("gemini", model, payload)
    return extract_text_response(payload, "Gemini")


def call_gemini_text(api_key: str, model: str, prompt: str) -> str:
    body = {"model": model, "input": [{"type": "text", "text": prompt}]}
    request = Request(
        os.environ.get("GEMINI_INTERACTIONS_URL", GEMINI_INTERACTIONS_URL),
        data=json.dumps(body).encode("utf-8"),
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(request, timeout=240) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"Gemini error {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ValueError(f"Could not reach Gemini: {exc.reason}") from exc
    record_api_usage("gemini", model, payload)
    return extract_text_response(payload, "Gemini")


def upload_gemini_video_file(api_key: str, video_path: Path) -> tuple[str, str]:
    mime_type = mimetypes.guess_type(video_path.name)[0] or "video/mp4"
    size = video_path.stat().st_size
    opener = build_opener(ProxyHandler({}))
    start_request = Request(
        os.environ.get("GEMINI_FILES_UPLOAD_URL", GEMINI_FILES_UPLOAD_URL),
        data=json.dumps({"file": {"display_name": video_path.name}}).encode("utf-8"),
        headers={
            "x-goog-api-key": api_key,
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(size),
            "X-Goog-Upload-Header-Content-Type": mime_type,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with opener.open(start_request, timeout=60) as response:
            upload_url = response.headers.get("x-goog-upload-url")
            if not upload_url:
                raise ValueError("Gemini did not return an upload URL.")

        upload_request = Request(
            upload_url,
            data=video_path.read_bytes(),
            headers={
                "Content-Length": str(size),
                "X-Goog-Upload-Offset": "0",
                "X-Goog-Upload-Command": "upload, finalize",
                "Content-Type": mime_type,
            },
            method="POST",
        )
        with opener.open(upload_request, timeout=300) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"Gemini file upload error {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ValueError(f"Could not upload video to Gemini: {exc.reason}") from exc

    file_info = payload.get("file") if isinstance(payload, dict) else None
    if not isinstance(file_info, dict):
        file_info = payload if isinstance(payload, dict) else {}

    file_uri = str(file_info.get("uri") or "")
    file_name = str(file_info.get("name") or "")
    response_mime = str(file_info.get("mimeType") or file_info.get("mime_type") or mime_type)
    if not file_uri:
        raise ValueError("Gemini file upload did not return a file URI.")
    if not file_name:
        return file_uri, response_mime

    get_base = os.environ.get("GEMINI_FILE_GET_URL", GEMINI_FILE_GET_URL).rstrip("/")
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        status_request = Request(
            f"{get_base}/{file_name}",
            headers={"x-goog-api-key": api_key},
            method="GET",
        )
        try:
            with opener.open(status_request, timeout=60) as response:
                status_payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ValueError(f"Gemini file status error {exc.code}: {detail}") from exc
        except URLError as exc:
            raise ValueError(f"Could not check Gemini file status: {exc.reason}") from exc

        state = str(status_payload.get("state") or "").upper()
        if state == "ACTIVE":
            return str(status_payload.get("uri") or file_uri), str(
                status_payload.get("mimeType") or status_payload.get("mime_type") or response_mime
            )
        if state == "FAILED":
            raise ValueError("Gemini file processing failed.")
        time.sleep(5)

    raise ValueError("Gemini file processing timed out.")


def call_chat_completion(
    url: str,
    api_key: str,
    request_body: dict[str, object],
    provider_name: str,
    response_callback=None,
) -> str:
    body = json.dumps(request_body).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://127.0.0.1:8765",
            "X-Title": "Film Study Tool",
        },
        method="POST",
    )
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(request, timeout=240) as response:
            if response_callback:
                response_callback()
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"{provider_name} error {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ValueError(
            f"Could not reach {provider_name} at {url}: {exc.reason}. "
            "Check your internet connection, VPN/proxy settings, and firewall permissions."
        ) from exc
    record_api_usage(provider_name.casefold(), str(request_body.get("model") or ""), payload)
    return extract_text_response(payload, provider_name)


def call_chat_completion_stream(
    url: str,
    api_key: str,
    request_body: dict[str, object],
    provider_name: str,
    response_callback=None,
) -> str:
    request = Request(
        url,
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "HTTP-Referer": "http://127.0.0.1:8765",
            "X-Title": "Film Study Tool",
        },
        method="POST",
    )
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(request, timeout=600) as response:
            if response_callback:
                response_callback()
            raw = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"{provider_name} error {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ValueError(
            f"Could not reach {provider_name} at {url}: {exc.reason}. "
            "Check your internet connection, VPN/proxy settings, and firewall permissions."
        ) from exc

    chunks: list[str] = []
    usage_payload: dict[str, object] | None = None
    finish_reason = ""
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(
            payload.get("usage") or payload.get("usage_metadata") or payload.get("usageMetadata"),
            dict,
        ):
            usage_payload = payload
        choices = payload.get("choices") if isinstance(payload, dict) else None
        if not isinstance(choices, list) or not choices:
            continue
        choice = choices[0] if isinstance(choices[0], dict) else {}
        returned_finish_reason = choice.get("finish_reason")
        if isinstance(returned_finish_reason, str) and returned_finish_reason:
            finish_reason = returned_finish_reason
        delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
        content = delta.get("content")
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    chunks.append(str(item["text"]))
    if chunks:
        content_text = "".join(chunks)
        if finish_reason not in {"stop", "tool_calls"}:
            response_format = request_body.get("response_format")
            complete_json_without_marker = False
            if (
                not finish_reason
                and isinstance(response_format, dict)
                and response_format.get("type") == "json_object"
            ):
                try:
                    parse_llm_json(content_text)
                    complete_json_without_marker = True
                except (json.JSONDecodeError, ValueError):
                    pass
            if not complete_json_without_marker:
                reason_detail = f" (finish_reason={finish_reason})" if finish_reason else ""
                raise ValueError(
                    f"{provider_name} stream ended before completion{reason_detail}; "
                    "the partial response was discarded."
                )
        record_api_usage(
            provider_name.casefold(),
            str(request_body.get("model") or ""),
            usage_payload or {},
        )
        return content_text
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{provider_name} returned an empty or invalid streaming response.") from exc
    record_api_usage(
        provider_name.casefold(),
        str(request_body.get("model") or ""),
        payload,
    )
    return extract_text_response(payload, provider_name)


def call_openrouter(api_key: str, request_body: dict[str, object]) -> str:
    return call_chat_completion(OPENROUTER_URL, api_key, request_body, "OpenRouter")


def extract_text_response(payload: dict[str, object], provider_name: str) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    steps = payload.get("steps")
    if isinstance(steps, list):
        step_texts: list[str] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            content = step.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        step_texts.append(part["text"])
        if step_texts:
            return "\n".join(step_texts)

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [part.get("text", "") for part in content if isinstance(part, dict)]
                return "\n".join(part for part in parts if part)

    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates:
        content = candidates[0].get("content")
        if isinstance(content, dict):
            parts = content.get("parts")
            if isinstance(parts, list):
                texts = [part.get("text", "") for part in parts if isinstance(part, dict)]
                if texts:
                    return "\n".join(texts)

    raise ValueError(f"{provider_name} response content was empty")


def parse_llm_json(text: str) -> dict[str, object]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        parsed = json.loads(cleaned[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("LLM response must be a JSON object")
    return parsed


def reset_corrected_project(outputs_dir: Path, project_id: str) -> dict[str, object]:
    project_dir = safe_project_path(outputs_dir, project_id)
    removed = []
    backed_up = []
    backup_dir = project_dir / "recovery_backups" / f"reset_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    for name in [
        "corrected_manifest.json",
        "corrected_manifest.csv",
        "corrected_film_study.xlsx",
        OUTLINE_FILENAME,
        OUTLINE_CSV_FILENAME,
    ]:
        path = project_dir / name
        if path.exists():
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / name
            shutil.copy2(path, backup_path)
            backed_up.append(str(backup_path))
            path.unlink()
            removed.append(str(path))
    return {"ok": True, "removed": removed, "backedUp": backed_up}


def _default_shot_title(row: dict[str, object], index: int) -> str:
    blocked_phrases = [
        "LLM visual analysis pending",
        "Narrative analysis pending",
        "Generated by the scaffold analyzer",
    ]
    text_sources = [
        str(row.get("visual_description", "")),
        str(row.get("narrative_function", "")),
        str(row.get("notes", "")),
    ]
    for text in text_sources:
        if not text or any(phrase in text for phrase in blocked_phrases):
            continue
        sentence = text.split(".")[0].split("\n")[0].strip()
        words = [word.strip(" ,;:") for word in sentence.split() if word.strip(" ,;:")]
        if words:
            return " ".join(words[:5]).title()
    members = row.get("members")
    if isinstance(members, list) and len(members) > 1:
        return "Combined Shot"
    return "Title Pending"


def find_source_video(project_id: str) -> Path | None:
    if not DATA_DIR.exists():
        return None
    videos = sorted(
        DATA_DIR.glob("*.*"),
        key=lambda item: len(item.stem),
        reverse=True,
    )
    for path in videos:
        if path.suffix.lower() not in VIDEO_SUFFIXES:
            continue
        if project_id.startswith(path.stem):
            return path.resolve()
    return None


def safe_upload_stem(filename: str) -> str:
    stem = Path(filename).stem or "film"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    return stem or "film"


def uploaded_video_from_multipart(headers: object, body: bytes) -> tuple[str, bytes]:
    content_type = headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        raise ValueError("Upload must be multipart form data")
    message = BytesParser(policy=email_policy).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
    )
    for part in message.iter_parts():
        if part.get_param("name", header="content-disposition") != "video":
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True)
        if not filename or not payload:
            raise ValueError("No video file was uploaded")
        return Path(filename).name, payload
    raise ValueError("No video file was uploaded")


def create_project_from_upload(config: ServerConfig, filename: str, payload: bytes) -> dict[str, object]:
    suffix = Path(filename).suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        raise ValueError("Use an MP4, MOV, MKV, or WebM video file")

    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.outputs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    upload_stem = f"{safe_upload_stem(filename)}_{stamp}"
    video_path = config.data_dir / f"{upload_stem}{suffix}"
    output_dir = config.outputs_dir / upload_stem
    video_path.write_bytes(payload)
    try:
        args = Namespace(
            video=video_path,
            output_dir=output_dir,
            threshold=0.32,
            max_minutes=MAX_VIDEO_MINUTES,
            screenshot_width=480,
        )
        breakdown_dir, workbook_path = run_breakdown(args)
        caption_info = enrich_project_with_captions(breakdown_dir, video_path)
    except Exception:
        video_path.unlink(missing_ok=True)
        if output_dir.is_dir():
            shutil.rmtree(output_dir, ignore_errors=True)
        raise
    if caption_info.get("captionFiles"):
        meta = load_project_meta(breakdown_dir)
        meta["captionFiles"] = caption_info.get("captionFiles")
        meta["captionCueCount"] = caption_info.get("cueCount", 0)
        meta["captionShotsUpdated"] = caption_info.get("shotsUpdated", 0)
        save_project_meta(breakdown_dir, meta)
    return {
        "ok": True,
        "project": load_project(config.outputs_dir, breakdown_dir.name),
        "workbook": str(workbook_path),
    }


def create_project_from_video_path(
    config: ServerConfig,
    video_path: Path,
    group_path: list[str] | None = None,
    meta: dict[str, object] | None = None,
) -> dict[str, object]:
    output_dir = config.outputs_dir / video_path.stem
    args = Namespace(
        video=video_path,
        output_dir=output_dir,
        threshold=0.32,
        max_minutes=MAX_VIDEO_MINUTES,
        screenshot_width=480,
    )
    breakdown_dir, workbook_path = run_breakdown(args)
    caption_info = enrich_project_with_captions(breakdown_dir, video_path)
    project_meta = dict(meta or {})
    if group_path is not None:
        project_meta["groupPath"] = group_path
    if caption_info.get("captionFiles"):
        project_meta["captionFiles"] = caption_info.get("captionFiles")
        project_meta["captionCueCount"] = caption_info.get("cueCount", 0)
        project_meta["captionShotsUpdated"] = caption_info.get("shotsUpdated", 0)
    if project_meta:
        save_project_meta(breakdown_dir, project_meta)
    if group_path:
        breakdown_dir = move_project_directory(config.outputs_dir, breakdown_dir, group_path)
        project_meta["groupPath"] = normalize_group_path(group_path)
        save_project_meta(breakdown_dir, project_meta)
        workbook_path = breakdown_dir / workbook_path.name
    return {
        "ok": True,
        "project": load_project(config.outputs_dir, breakdown_dir.name),
        "workbook": str(workbook_path),
    }


def entry_video_url(entry: dict[str, object]) -> str | None:
    for key in ["webpage_url", "url"]:
        value = entry.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    entry_id = str(entry.get("id") or "").strip()
    ie_key = str(entry.get("ie_key") or "").lower()
    if entry_id and ("youtube" in ie_key or re.fullmatch(r"[A-Za-z0-9_-]{11}", entry_id)):
        return f"https://www.youtube.com/watch?v={entry_id}"
    return None


def download_source_captions(
    config: ServerConfig,
    ytdlp: str,
    source_url: str,
    output_stem: str,
) -> str:
    result = _run(
        [
            ytdlp,
            "--no-update",
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            CAPTION_LANGS,
            "--sub-format",
            "vtt/srt/best",
            "-o",
            str(config.data_dir / f"{output_stem}.%(ext)s"),
            source_url,
        ]
    )
    return result.stderr.strip() if result.returncode != 0 else ""


def downloaded_video_has_audio(video_path: Path) -> bool:
    ffprobe = _require_binary("ffprobe")
    probe = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
            str(video_path),
        ]
    )
    if probe.returncode != 0:
        return False
    try:
        streams = json.loads(probe.stdout).get("streams", [])
    except (AttributeError, json.JSONDecodeError):
        return False
    stream_types = {
        str(stream.get("codec_type") or "")
        for stream in streams
        if isinstance(stream, dict)
    }
    return "video" in stream_types and "audio" in stream_types


def downloaded_video_candidate(data_dir: Path, download_stem: str) -> Path | None:
    candidates = sorted(
        data_dir.glob(f"{download_stem}.*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return next(
        (path for path in candidates if path.suffix.lower() in VIDEO_SUFFIXES),
        None,
    )


def download_source_video(config: ServerConfig, ytdlp: str, source_url: str, title: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    download_stem = f"{safe_upload_stem(title or 'Imported Video')}_{stamp}"
    output_template = str(config.data_dir / f"{download_stem}.%(ext)s")
    host = (urlparse(source_url).hostname or "").casefold()
    is_tiktok = host == "tiktok.com" or host.endswith(".tiktok.com")
    format_selectors = (
        [
            (
                "b[format_id^=h264][acodec!=none][height<=720]/"
                "b[format_id^=h264][acodec!=none]"
            ),
            "download",
        ]
        if is_tiktok
        else [
            "bv*[height<=720]+ba/b[acodec!=none][height<=720]/b[acodec!=none]",
            "b[acodec!=none][height<=720]/b[acodec!=none]",
        ]
    )
    errors: list[str] = []
    video_path: Path | None = None
    for selector in format_selectors:
        download_result = _run(
            [
                ytdlp,
                "--no-update",
                "--no-playlist",
                "--force-overwrites",
                "-f",
                selector,
                "--merge-output-format",
                "mp4",
                "-o",
                output_template,
                source_url,
            ]
        )
        if download_result.returncode != 0:
            errors.append(download_result.stderr.strip() or f"Format {selector} failed.")
            continue
        candidate = downloaded_video_candidate(config.data_dir, download_stem)
        if candidate is None:
            errors.append(f"Format {selector} did not produce a supported video file.")
            continue
        if downloaded_video_has_audio(candidate):
            video_path = candidate
            break
        errors.append(f"Format {selector} produced a file without an audio stream.")
        candidate.unlink(missing_ok=True)
    if video_path is None:
        detail = " | ".join(error for error in errors if error)
        raise VideoToolError(
            "The source did not provide a usable video with audio."
            + (f" {detail}" if detail else "")
        )
    download_source_captions(config, ytdlp, source_url, download_stem)
    return video_path


def refresh_existing_project_captions(config: ServerConfig, ytdlp: str, project_dir: Path, source_url: str) -> dict[str, object]:
    video_path = find_source_video(project_dir.name)
    if video_path is None:
        return {"captionFiles": [], "cueCount": 0, "shotsUpdated": 0}
    error = download_source_captions(config, ytdlp, source_url, video_path.stem)
    caption_info = enrich_project_with_captions(project_dir, video_path)
    if error:
        caption_info["error"] = error
    return caption_info


def video_meta_from_info(info: dict[str, object], source_url: str, import_mode: str) -> dict[str, object]:
    meta: dict[str, object] = {
        "sourceUrl": str(info.get("webpage_url") or source_url),
        "viewCount": int(info.get("view_count") or 0),
        "importMode": import_mode,
    }
    for source_key, target_key in [
        ("like_count", "likeCount"),
        ("repost_count", "repostCount"),
        ("comment_count", "commentCount"),
        ("save_count", "saveCount"),
    ]:
        value = info.get(source_key)
        if value not in (None, ""):
            meta[target_key] = int(value or 0)
    uploader_url = info.get("uploader_url")
    uploader = info.get("uploader")
    if isinstance(uploader_url, str) and uploader_url:
        meta["channelUrl"] = uploader_url
    if isinstance(uploader, str) and uploader:
        meta["channelTitle"] = uploader
    return meta


def import_url_projects(config: ServerConfig, payload: dict[str, object]) -> dict[str, object]:
    urls = extract_urls_from_text(payload.get("text") or payload.get("url") or payload.get("urls"))
    if not urls and isinstance(payload.get("urls"), list):
        urls = extract_urls_from_text("\n".join(str(item) for item in payload["urls"]))
    if not urls:
        raise ValueError("Paste one or more TikTok, YouTube, or other video URLs.")

    requested_group_path = normalize_group_path(payload.get("groupPath"))
    group_path = requested_group_path
    if not group_path:
        handles = {tiktok_handle_from_url(url) for url in urls}
        handles.discard("")
        group_path = [next(iter(handles)), "Selected Videos"] if len(handles) == 1 else ["Imported URLs"]

    ytdlp = _require_binary("yt-dlp")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.outputs_dir.mkdir(parents=True, exist_ok=True)
    imported: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []

    for index, url in enumerate(urls, start=1):
        if is_channel_url(url):
            skipped.append({"url": url, "reason": "Channel URL skipped here; use channel import for most-popular channel scans."})
            continue
        if "/photo/" in url:
            skipped.append({"url": url, "reason": "Photo post skipped; studies currently need video files."})
            continue

        existing_project = existing_project_by_source(config.outputs_dir, url)
        if existing_project is not None:
            meta = load_project_meta(existing_project)
            caption_info = refresh_existing_project_captions(config, ytdlp, existing_project, url)
            if caption_info.get("captionFiles"):
                meta["captionFiles"] = caption_info.get("captionFiles")
                meta["captionCueCount"] = caption_info.get("cueCount", 0)
                meta["captionShotsUpdated"] = caption_info.get("shotsUpdated", 0)
            if caption_info.get("error"):
                meta["captionError"] = caption_info.get("error")
            if requested_group_path:
                meta["groupPath"] = requested_group_path
            meta.setdefault("sourceUrl", url)
            meta["selectionRank"] = index
            meta["importMode"] = str(meta.get("importMode") or "selected_url")
            save_project_meta(existing_project, meta)
            imported.append(project_summary(existing_project, config.outputs_dir))
            continue

        info_result = _run([ytdlp, "--no-update", "--dump-single-json", "--skip-download", url])
        if info_result.returncode != 0:
            skipped.append({"url": url, "reason": info_result.stderr.strip() or "Could not read video metadata."})
            continue
        try:
            info = json.loads(info_result.stdout)
        except json.JSONDecodeError:
            skipped.append({"url": url, "reason": "Video metadata was unreadable."})
            continue
        if not isinstance(info, dict):
            skipped.append({"url": url, "reason": "Video metadata was empty."})
            continue

        source_url = str(info.get("webpage_url") or url)
        title = str(info.get("title") or info.get("fulltitle") or f"Selected Video {index}").strip()
        meta = video_meta_from_info(info, source_url, "selected_url")
        meta["sourceUrl"] = source_url
        meta["selectionRank"] = index
        existing_project = existing_project_by_source(config.outputs_dir, source_url)
        if existing_project is not None:
            saved_meta = load_project_meta(existing_project)
            caption_info = refresh_existing_project_captions(config, ytdlp, existing_project, source_url)
            if caption_info.get("captionFiles"):
                saved_meta["captionFiles"] = caption_info.get("captionFiles")
                saved_meta["captionCueCount"] = caption_info.get("cueCount", 0)
                saved_meta["captionShotsUpdated"] = caption_info.get("shotsUpdated", 0)
            if caption_info.get("error"):
                saved_meta["captionError"] = caption_info.get("error")
            saved_meta.update({key: value for key, value in meta.items() if value not in (None, "")})
            if requested_group_path:
                saved_meta["groupPath"] = requested_group_path
            save_project_meta(existing_project, saved_meta)
            imported.append(project_summary(existing_project, config.outputs_dir))
            continue

        try:
            video_path = download_source_video(config, ytdlp, source_url, title)
            result = create_project_from_video_path(config, video_path, group_path=group_path, meta=meta)
        except Exception as exc:
            skipped.append({"url": source_url, "title": title, "reason": str(exc)})
            continue
        imported.append(result["project"])

    return {
        "ok": True,
        "groupPath": group_path,
        "inputCount": len(urls),
        "imported": imported,
        "skipped": skipped,
    }


def import_channel_projects(config: ServerConfig, payload: dict[str, object]) -> dict[str, object]:
    channel_url = str(payload.get("url") or "").strip()
    if not channel_url.startswith(("http://", "https://")):
        raise ValueError("Paste a YouTube or TikTok channel link.")
    limit = int(payload.get("limit") or 5)
    limit = 10 if limit > 5 else 5
    scan_limit = int(payload.get("scanLimit") or 100)
    scan_limit = max(limit, min(scan_limit, 200))

    ytdlp = _require_binary("yt-dlp")
    override_entries = popular_override_entries(channel_url)
    if override_entries:
        ranked_entries = override_entries
        channel_title = tiktok_handle_from_url(channel_url) or "Imported Channel"
    else:
        list_result = _run(
            [
                ytdlp,
                "--no-update",
                "--dump-single-json",
                "--flat-playlist",
                "--playlist-end",
                str(scan_limit),
                channel_url,
            ]
        )
        if list_result.returncode != 0:
            raise VideoToolError(list_result.stderr.strip() or "Could not read that channel link.")

        try:
            channel_info = json.loads(list_result.stdout)
        except json.JSONDecodeError as exc:
            raise VideoToolError("yt-dlp returned an unreadable channel response.") from exc

        entries = channel_info.get("entries") if isinstance(channel_info, dict) else []
        if not isinstance(entries, list) or not entries:
            raise ValueError("No videos were found for that channel link.")
        ranked_entries = sorted(
            [entry for entry in entries if isinstance(entry, dict)],
            key=lambda entry: int(entry.get("view_count") or 0),
            reverse=True,
        )
        channel_title = str(channel_info.get("title") or channel_info.get("uploader") or "Imported Channel").strip()
    group_path = normalize_group_path(payload.get("groupPath") or channel_title)
    if not group_path:
        group_path = ["Imported Channel"]

    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.outputs_dir.mkdir(parents=True, exist_ok=True)
    imported: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []

    for index, entry in enumerate(ranked_entries, start=1):
        if len(imported) >= limit:
            break
        video_url = entry_video_url(entry)
        title = str(entry.get("title") or f"Channel Video {index}").strip()
        view_count = int(entry.get("view_count") or 0)
        like_count = int(entry.get("like_count") or 0)
        repost_count = int(entry.get("repost_count") or 0)
        comment_count = int(entry.get("comment_count") or 0)
        save_count = int(entry.get("save_count") or 0)
        if not video_url:
            skipped.append({"title": title, "reason": "No playable video URL found."})
            continue
        if str(entry.get("kind") or "").lower() == "photo" or "/photo/" in video_url:
            skipped.append({"title": title, "url": video_url, "reason": "Photo post skipped; studies currently need video files."})
            continue

        meta_update = {
            "sourceUrl": video_url,
            "channelUrl": channel_url,
            "channelTitle": channel_title,
            "channelRank": len(imported) + 1,
            "popularityRank": index,
            "viewCount": view_count,
            "importMode": "most_popular_confirmed" if override_entries else "most_popular",
        }
        for source, target in [
            (like_count, "likeCount"),
            (repost_count, "repostCount"),
            (comment_count, "commentCount"),
            (save_count, "saveCount"),
        ]:
            if source:
                meta_update[target] = source
        existing_project = existing_project_by_source(config.outputs_dir, video_url)
        if existing_project is not None:
            meta = load_project_meta(existing_project)
            meta.update({key: value for key, value in meta_update.items() if value not in (None, "")})
            meta["groupPath"] = group_path
            save_project_meta(existing_project, meta)
            imported.append(project_summary(existing_project, config.outputs_dir))
            continue

        try:
            video_path = download_source_video(config, ytdlp, video_url, title)
            result = create_project_from_video_path(
                config,
                video_path,
                group_path=group_path,
                meta=meta_update,
            )
        except Exception as exc:
            skipped.append({"title": title, "reason": str(exc)})
            continue
        imported.append(result["project"])

    return {
        "ok": True,
        "channelTitle": channel_title,
        "groupPath": group_path,
        "scanCount": len(ranked_entries),
        "sort": "most_popular",
        "imported": imported,
        "skipped": skipped,
    }


def extract_project_frame(
    outputs_dir: Path,
    project_id: str,
    timestamp: float,
    label: str,
    max_width: int = 480,
) -> dict[str, object]:
    project_dir = safe_project_path(outputs_dir, project_id)
    video_path = find_source_video(project_id)
    if video_path is None:
        raise FileNotFoundError("Source video not found")
    if timestamp < 0:
        raise ValueError("Frame time must be after the start of the video")

    safe_label = re.sub(r"[^A-Za-z0-9._-]+", "_", label).strip("._-") or "split"
    frames_dir = project_dir / "screenshots"
    frames_dir.mkdir(parents=True, exist_ok=True)
    output_path = frames_dir / f"{safe_label}_{int(timestamp * 1000):09d}.jpg"
    ffmpeg = _require_binary("ffmpeg")
    result = _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            f"scale='min({max_width},iw)':-2",
            "-q:v",
            "3",
            str(output_path),
        ]
    )
    if result.returncode != 0 or not output_path.exists():
        raise VideoToolError(result.stderr.strip() or "Could not extract split screenshot.")
    return {
        "screenshot": output_path.name,
        "screenshotUrl": f"/media/{project_dir.name}/screenshots/{output_path.name}",
        "screenshot_path": str(output_path.resolve()),
    }


def _seconds_from_timestamp(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


class FilmStudyRequestHandler(BaseHTTPRequestHandler):
    config: ServerConfig

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path == "/" or path == "/index.html":
                self.send_file(self.config.static_dir / "index.html")
            elif path == "/favicon.ico":
                self.send_file(self.config.static_dir / "icons" / "wheel-favicon.png")
            elif path.startswith("/static/"):
                self.send_file(self.config.static_dir / path.removeprefix("/static/"))
            elif path == "/api/projects":
                projects = list_projects(self.config.outputs_dir)
                self.send_json({
                    "projects": projects,
                    "folders": list_library_folders(self.config.outputs_dir),
                })
            elif path.startswith("/api/projects/") and path.endswith("/analysis-status"):
                project_id = path.removeprefix("/api/projects/").removesuffix("/analysis-status").strip("/")
                project_dir = safe_project_path(self.config.outputs_dir, project_id)
                status = analysis_job_status(project_id)
                if status.get("status") == "idle":
                    session = load_analysis_session(project_dir)
                    usage = session.get("lastUsage") if isinstance(session.get("lastUsage"), dict) else {}
                    if not usage:
                        usage = legacy_analysis_usage(project_dir, session)
                    if usage:
                        status["usage"] = usage
                self.send_json(status)
            elif path.startswith("/api/projects/") and path.endswith("/conversation"):
                project_id = path.removeprefix("/api/projects/").removesuffix("/conversation").strip("/")
                project_dir = safe_project_path(self.config.outputs_dir, project_id)
                self.send_json(load_film_conversation(project_dir))
            elif path.startswith("/api/projects/"):
                project_id = path.removeprefix("/api/projects/").strip("/")
                self.send_json(load_project(self.config.outputs_dir, project_id))
            elif path.startswith("/media/"):
                self.send_media(path)
            elif path.startswith("/video/"):
                project_id = path.removeprefix("/video/").strip("/")
                self.send_video(project_id)
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except ValueError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, safe_http_error_message(exc))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path.startswith("/api/projects/") and path.endswith("/corrections"):
                project_id = path.removeprefix("/api/projects/").removesuffix("/corrections").strip("/")
                payload = self.read_json()
                self.send_json(save_corrected_project(self.config.outputs_dir, project_id, payload))
            elif path.startswith("/api/projects/") and path.endswith("/generate-details"):
                project_id = path.removeprefix("/api/projects/").removesuffix("/generate-details").strip("/")
                payload = self.read_json()
                try:
                    result = update_shots_with_llm_details(self.config.outputs_dir, project_id, payload)
                except Exception as exc:
                    current = analysis_job_status(project_id)
                    if current.get("status") == "running":
                        usage = (
                            current.get("usage")
                            if isinstance(current.get("usage"), dict)
                            else finish_api_usage_collection()
                        )
                        update_analysis_job(
                            project_id,
                            status="failed",
                            phase="failed",
                            message=safe_http_error_message(exc, "Analysis failed"),
                            progress=0,
                            usage=usage,
                            completedAt=datetime.now().isoformat(timespec="seconds"),
                        )
                    try:
                        project_dir = safe_project_path(self.config.outputs_dir, project_id)
                        record_analysis_run(
                            project_dir,
                            project_id,
                            status="failed",
                            totalShotCount=len(payload.get("shots") or []),
                            usage=analysis_job_status(project_id).get("usage", {}),
                            error=safe_http_error_message(exc, "Analysis failed"),
                        )
                    except (FileNotFoundError, ValueError, OSError):
                        pass
                    raise
                self.send_json(result)
            elif path.startswith("/api/projects/") and path.endswith("/ask"):
                project_id = path.removeprefix("/api/projects/").removesuffix("/ask").strip("/")
                payload = self.read_json()
                self.send_json(ask_this_film(self.config.outputs_dir, project_id, payload))
            elif path.startswith("/api/projects/") and path.endswith("/export-ai"):
                project_id = path.removeprefix("/api/projects/").removesuffix("/export-ai").strip("/")
                self.send_json(export_film_study_for_ai(self.config.outputs_dir, project_id))
            elif path.startswith("/api/projects/") and path.endswith("/conversation/clear"):
                project_id = path.removeprefix("/api/projects/").removesuffix("/conversation/clear").strip("/")
                self.send_json(clear_film_conversation(self.config.outputs_dir, project_id))
            elif path.startswith("/api/projects/") and path.endswith("/suggest-shot-boundaries"):
                project_id = path.removeprefix("/api/projects/").removesuffix("/suggest-shot-boundaries").strip("/")
                payload = self.read_json()
                self.send_json(ai_shot_boundary_suggestions(self.config.outputs_dir, project_id, payload))
            elif path.startswith("/api/projects/") and path.endswith("/frame"):
                project_id = path.removeprefix("/api/projects/").removesuffix("/frame").strip("/")
                payload = self.read_json()
                timestamp = float(payload.get("timestamp", 0))
                label = str(payload.get("label", "split"))
                self.send_json(extract_project_frame(self.config.outputs_dir, project_id, timestamp, label))
            elif path.startswith("/api/projects/") and path.endswith("/reset"):
                project_id = path.removeprefix("/api/projects/").removesuffix("/reset").strip("/")
                self.send_json(reset_corrected_project(self.config.outputs_dir, project_id))
            elif path.startswith("/api/projects/") and path.endswith("/context"):
                project_id = path.removeprefix("/api/projects/").removesuffix("/context").strip("/")
                payload = self.read_json()
                self.send_json(save_project_context(self.config.outputs_dir, project_id, payload))
            elif path.startswith("/api/projects/") and path.endswith("/metadata"):
                project_id = path.removeprefix("/api/projects/").removesuffix("/metadata").strip("/")
                payload = self.read_json()
                self.send_json(update_project_metadata(self.config.outputs_dir, project_id, payload))
            elif path.startswith("/api/projects/") and path.endswith("/open-folder"):
                project_id = path.removeprefix("/api/projects/").removesuffix("/open-folder").strip("/")
                self.send_json(open_project_directory(self.config.outputs_dir, project_id))
            elif path.startswith("/api/projects/") and path.endswith("/delete"):
                project_id = path.removeprefix("/api/projects/").removesuffix("/delete").strip("/")
                self.send_json(delete_project(self.config, project_id))
            elif path == "/api/projects/upload":
                filename, payload = self.read_upload()
                self.send_json(create_project_from_upload(self.config, filename, payload))
            elif path == "/api/urls/import":
                payload = self.read_json()
                self.send_json(import_url_projects(self.config, payload))
            elif path == "/api/channels/import":
                payload = self.read_json()
                self.send_json(import_channel_projects(self.config, payload))
            elif path == "/api/folders/create":
                payload = self.read_json()
                self.send_json(create_library_folder(self.config.outputs_dir, payload))
            elif path == "/api/folders/rename":
                payload = self.read_json()
                self.send_json(rename_library_folder(self.config.outputs_dir, payload))
            elif path == "/api/folders/delete":
                payload = self.read_json()
                self.send_json(delete_library_folder(self.config, payload))
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except FileNotFoundError as exc:
            self.send_error(HTTPStatus.NOT_FOUND, safe_http_error_message(exc, "Not found"))
        except (ValueError, json.JSONDecodeError, VideoToolError) as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, safe_http_error_message(exc))

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path.startswith("/api/projects/"):
                project_id = path.removeprefix("/api/projects/").strip("/")
                self.send_json(delete_project(self.config, project_id))
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
        except FileNotFoundError as exc:
            self.send_error(HTTPStatus.NOT_FOUND, safe_http_error_message(exc, "Not found"))
        except ValueError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, safe_http_error_message(exc))

    def read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object")
        return payload

    def read_upload(self) -> tuple[str, bytes]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        return uploaded_video_from_multipart(self.headers, body)

    def send_json(self, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path) -> None:
        resolved = path.resolve()
        static_root = self.config.static_dir.resolve()
        if resolved != static_root and static_root not in resolved.parents:
            raise FileNotFoundError
        if not resolved.is_file():
            raise FileNotFoundError
        if resolved.suffix == ".webmanifest":
            mime_type = "application/manifest+json"
        else:
            mime_type, _encoding = mimetypes.guess_type(resolved)
        body = resolved.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type or "application/octet-stream")
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_media(self, path: str) -> None:
        parts = [part for part in posixpath.normpath(path).split("/") if part]
        if len(parts) < 4 or parts[0] != "media":
            raise FileNotFoundError
        project_id = parts[1]
        relative = Path(*parts[2:])
        project_dir = safe_project_path(self.config.outputs_dir, project_id)
        resolved = (project_dir / relative).resolve()
        if project_dir.resolve() not in resolved.parents:
            raise FileNotFoundError
        if not resolved.is_file():
            raise FileNotFoundError
        mime_type, _encoding = mimetypes.guess_type(resolved)
        body = resolved.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type or "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_video(self, project_id: str) -> None:
        video_path = find_source_video(project_id)
        if video_path is None or not video_path.is_file():
            raise FileNotFoundError
        data_root = self.config.data_dir.resolve()
        if data_root not in video_path.resolve().parents:
            raise FileNotFoundError

        file_size = video_path.stat().st_size
        mime_type, _encoding = mimetypes.guess_type(video_path)
        range_header = self.headers.get("Range")
        start = 0
        end = file_size - 1
        status = HTTPStatus.OK

        if range_header:
            units, _, requested_range = range_header.partition("=")
            if units.strip().lower() == "bytes":
                range_start, _, range_end = requested_range.partition("-")
                if range_start:
                    start = int(range_start)
                if range_end:
                    end = int(range_end)
                end = min(end, file_size - 1)
                status = HTTPStatus.PARTIAL_CONTENT

        if start < 0 or start >= file_size or end < start:
            self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            return

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", mime_type or "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.end_headers()

        with video_path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


def make_handler(config: ServerConfig) -> type[FilmStudyRequestHandler]:
    class ConfiguredFilmStudyRequestHandler(FilmStudyRequestHandler):
        pass

    ConfiguredFilmStudyRequestHandler.config = config
    return ConfiguredFilmStudyRequestHandler


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")

    parser = ArgumentParser(description="Run the local Film Study Tool UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--outputs-dir", type=Path, default=OUTPUTS_DIR)
    args = parser.parse_args(argv)

    config = ServerConfig(
        outputs_dir=args.outputs_dir.resolve(),
        static_dir=STATIC_DIR.resolve(),
        data_dir=DATA_DIR.resolve(),
    )
    handler = make_handler(config)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Film Study UI running at http://{args.host}:{args.port}")
    print(f"Reading outputs from {config.outputs_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Film Study UI")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
