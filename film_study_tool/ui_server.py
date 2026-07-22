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
import sys
import time
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from datetime import datetime
from email.parser import BytesParser
from email.policy import default as email_policy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
from urllib.parse import unquote, urlparse

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
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
QWEN_COMPATIBLE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
GEMINI_INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
GEMINI_FILES_UPLOAD_URL = "https://generativelanguage.googleapis.com/upload/v1beta/files"
GEMINI_FILE_GET_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_INLINE_VIDEO_LIMIT_BYTES = 20 * 1024 * 1024
DEFAULT_QWEN_VIDEO_MODEL = "qwen3.7-plus"
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
OUTLINE_FILENAME = "outline.json"
OUTLINE_CSV_FILENAME = "outline.csv"
STUDY_CONTEXT_FILENAME = "study_context.txt"
LAST_LLM_RESPONSE_FILENAME = "last_llm_response.json"
LAST_LLM_ERROR_FILENAME = "last_llm_error.json"
PROJECT_META_FILENAME = "project_meta.json"
AI_SHOT_DETECTION_INSTRUCTIONS = """You are a meticulous film editor reviewing shot boundaries.
Watch the complete attached video. Identify every visual transition between distinct shots, including hard cuts,
dissolves, crossfades, fades, wipes, and transitions hidden by camera or subject motion. The visible SHOT label
shows the user's current timeline segment; it is a reference, not proof that the segment contains only one shot.
Return precise timestamps in seconds. Do not invent transitions for camera movement, reframing, animation within
one composition, lighting changes, or subject movement. Return JSON only."""

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
    candidate = (outputs_dir / project_id).resolve()
    root = outputs_dir.resolve()
    if candidate != root and root in candidate.parents:
        return candidate
    raise ValueError("Invalid project id")


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


def project_meta_path(project_dir: Path) -> Path:
    return project_dir / PROJECT_META_FILENAME


def normalize_group_path(value: object) -> list[str]:
    if isinstance(value, str):
        raw_parts = re.split(r"[\\/]+", value)
    elif isinstance(value, list):
        raw_parts = [str(part) for part in value]
    else:
        raw_parts = []
    parts = [part.strip() for part in raw_parts if str(part).strip()]
    return parts[:6]


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
    path = parsed.path.rstrip("/")
    return f"{parsed.netloc.lower()}{path}"


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
    for meta_path in outputs_dir.glob("*/project_meta.json"):
        meta = load_project_meta(meta_path.parent)
        if source_url_key(meta.get("sourceUrl")) == wanted:
            return meta_path.parent
    return None


def project_summary(project_dir: Path) -> dict[str, object]:
    rows = load_json(project_manifest_path(project_dir))
    meta = load_project_meta(project_dir)
    return {
        "id": project_dir.name,
        "name": display_project_name(project_dir.name),
        "shotCount": len(rows) if isinstance(rows, list) else 0,
        "coverUrl": cover_url_for(project_dir, rows, meta),
        "coverShot": meta.get("coverShot"),
        "coverCrop": normalize_cover_crop(meta.get("coverCrop")),
        "groupPath": normalize_group_path(meta.get("groupPath", [])),
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
    for project_dir in sorted(outputs_dir.iterdir(), key=lambda item: item.stat().st_mtime, reverse=True):
        if not project_dir.is_dir() or not (project_dir / "manifest.json").exists():
            continue
        manifest_path = project_manifest_path(project_dir)
        try:
            rows = load_json(manifest_path)
        except (OSError, json.JSONDecodeError):
            continue
        projects.append(project_summary(project_dir))
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


def update_project_metadata(outputs_dir: Path, project_id: str, payload: dict[str, object]) -> dict[str, object]:
    project_dir = safe_project_path(outputs_dir, project_id)
    if not project_dir.exists() or not project_dir.is_dir():
        raise FileNotFoundError("Project not found")
    meta = load_project_meta(project_dir)
    if "groupPath" in payload:
        meta["groupPath"] = normalize_group_path(payload.get("groupPath"))
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
    return {
        "shot": index + 1,
        "originalShot": row.get("originalShot", row.get("shot", index + 1)),
        "members": row.get("members", [row.get("shot", index + 1)]),
        "shot_title": shot_title,
        "screenshot": screenshot_name,
        "screenshotUrl": f"/media/{project_dir.name}/screenshots/{screenshot_name}",
        "screenshot_path": str((project_dir / "screenshots" / screenshot_name).resolve()),
        "start": row.get("start", ""),
        "end": row.get("end", ""),
        "duration_seconds": float(row.get("duration_seconds", 0) or 0),
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
    text = re.sub(r"<\d{1,2}:\d{2}:\d{2}\.\d{3}>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
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


def apply_caption_cues_to_rows(
    rows: list[dict[str, object]],
    cues: list[dict[str, object]],
) -> int:
    """Assign each caption cue to exactly one edited shot using the cue midpoint."""
    if not rows or not cues:
        return 0
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

    updated = 0
    for index, row in enumerate(rows):
        if is_manual_field(row, "audio_dialogue"):
            continue
        next_text = " ".join(assigned[index])
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
        "name": display_project_name(project_dir.name),
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
        "correctedManifest": str(corrected_manifest),
        "correctedCsv": str(corrected_csv),
        "correctedWorkbook": str(corrected_workbook),
    }


def update_shots_with_llm_details(outputs_dir: Path, project_id: str, payload: dict[str, object]) -> dict[str, object]:
    project_dir = safe_project_path(outputs_dir, project_id)
    shots = payload.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ValueError("No shots to analyze")

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

    normalized = []
    for index, row in enumerate(shots):
        if not isinstance(row, dict):
            raise ValueError("Shot entries must be objects")
        normalized.append(normalize_shot_row(row, index, project_dir))
    outline = normalize_outline(payload.get("outline", load_outline(project_dir, len(normalized))), len(normalized))
    source_video = find_source_video(project_id)
    if source_video is None:
        raise FileNotFoundError("Source video not found")
    low_threshold_candidates = detect_shot_boundaries(source_video, threshold=0.12)
    current_boundaries = [
        _seconds_from_timestamp(str(row.get("end", "00:00:00.000")))
        for row in normalized[:-1]
    ]

    try:
        llm_rows, llm_transitions, provider_name, provider_model = generate_shot_details_with_native_video(
            model=model,
            qwen_api_key=qwen_api_key,
            gemini_api_key=gemini_api_key,
            project_name=display_project_name(project_id),
            project_dir=project_dir,
            shots=normalized,
            outline=outline,
            user_context=user_context,
            ffmpeg_candidates=low_threshold_candidates,
        )
    except Exception as exc:
        write_llm_error(project_dir, model, exc)
        raise
    merged = merge_generated_shot_details(normalized, llm_rows)
    apply_caption_cues_to_rows(merged, load_project_caption_cues(project_dir))
    suggestions = normalize_ai_transition_suggestions(
        llm_transitions,
        normalized,
        current_boundaries,
        low_threshold_candidates,
    )
    for index, suggestion in enumerate(suggestions):
        timestamp = float(suggestion["time_seconds"])
        before = extract_project_frame(
            outputs_dir,
            project_id,
            max(0, timestamp - 0.18),
            f"analysis_cut_{index + 1}_before",
            max_width=320,
        )
        after = extract_project_frame(
            outputs_dir,
            project_id,
            timestamp + 0.18,
            f"analysis_cut_{index + 1}_after",
            max_width=320,
        )
        suggestion["beforeFrameUrl"] = before["screenshotUrl"]
        suggestion["afterFrameUrl"] = after["screenshotUrl"]
    save_result = save_corrected_project(outputs_dir, project_id, {"shots": merged, "outline": outline})
    return {
        "ok": True,
        "shots": [normalize_shot_row(row, index, project_dir) for index, row in enumerate(merged)],
        "shotCount": len(merged),
        "provider": provider_name,
        "model": provider_model,
        "suggestions": suggestions,
        "suggestionCount": len(suggestions),
        **save_result,
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
    low_threshold_candidates = detect_shot_boundaries(video_path, threshold=0.12)
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
    suggestions = normalize_ai_transition_suggestions(
        transitions,
        shots,
        current_boundaries,
        low_threshold_candidates,
    )
    for index, suggestion in enumerate(suggestions):
        timestamp = float(suggestion["time_seconds"])
        before = extract_project_frame(
            outputs_dir,
            project_id,
            max(0, timestamp - 0.18),
            f"ai_cut_{index + 1}_before",
            max_width=320,
        )
        after = extract_project_frame(
            outputs_dir,
            project_id,
            timestamp + 0.18,
            f"ai_cut_{index + 1}_after",
            max_width=320,
        )
        suggestion["beforeFrameUrl"] = before["screenshotUrl"]
        suggestion["afterFrameUrl"] = after["screenshotUrl"]

    return {
        "ok": True,
        "provider": provider,
        "model": provider_model,
        "suggestions": suggestions,
        "suggestionCount": len(suggestions),
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
        if transition_type not in gradual_types:
            nearby = [candidate for candidate in ffmpeg_candidates if abs(candidate[0] - timestamp) <= 0.75]
            if nearby:
                timestamp = max(nearby, key=lambda item: item[1])[0]
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


def merge_generated_shot_details(
    current_rows: list[dict[str, object]],
    generated_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    by_analysis_id = {}
    by_number = {}
    for index, row in enumerate(generated_rows):
        analysis_id = str(row.get("analysis_id") or row.get("row_id") or "").strip()
        if analysis_id:
            by_analysis_id[analysis_id] = row
        for key in ("current_shot", "shot", "analysis_index"):
            try:
                shot_number = int(row.get(key, 0))
            except (TypeError, ValueError):
                continue
            if shot_number:
                by_number[shot_number] = row
                break

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
        current_shot_number = safe_int(row.get("shot"), index + 1)
        analysis_id = analysis_id_for_row(index)
        if by_analysis_id:
            generated = by_analysis_id.get(analysis_id, {})
        elif len(generated_rows) == len(current_rows):
            # Models sometimes return old detector shot numbers after user edits.
            # If the row count matches, the JSON array order is safer than the number field.
            generated = generated_rows[index]
        else:
            generated = by_number.get(current_shot_number, by_number.get(index + 1, {}))
        force_refresh = True
        maybe_merge_generated_field(next_row, generated, "shot_title", index, force_refresh=True)
        for field in detail_fields:
            maybe_merge_generated_field(next_row, generated, field, index, force_refresh=force_refresh)
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
        "pending",
        "llm visual analysis pending",
        "narrative analysis pending",
        "generated by the scaffold analyzer",
        "no clear dialogue/audio available from the provided stills",
        "no clear dialogue/audio available from the attached video/captions",
    ]
    return any(phrase in normalized for phrase in placeholder_phrases)


def is_placeholder_shot_title(value: str, index: int) -> bool:
    normalized = value.strip().casefold()
    placeholder_titles = {
        "",
        "title pending",
        "shot title pending",
        f"shot {index + 1}".casefold(),
    }
    return normalized in placeholder_titles


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
) -> tuple[list[dict[str, object]], list[dict[str, object]], str, str]:
    instructions = LLM_INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    prompt = build_llm_text_prompt(
        project_name,
        shots,
        outline,
        user_context,
        ffmpeg_candidates=ffmpeg_candidates,
    )
    video_path = prepare_analysis_video(project_dir, shots=shots)
    if video_path is None:
        raise FileNotFoundError("Source video not found for native video analysis")

    errors: list[str] = []
    if qwen_api_key:
        qwen_model = normalize_qwen_model(model)
        try:
            raw_content = call_qwen_video(qwen_api_key, qwen_model, instructions, prompt, video_path)
            write_llm_response(project_dir, qwen_model, raw_content, provider="qwen")
            rows, transitions = parse_generated_analysis(raw_content)
            return rows, transitions, "qwen", qwen_model
        except Exception as exc:
            errors.append(f"Qwen failed: {exc}")
            write_llm_error(project_dir, qwen_model, exc, provider="qwen")

    if gemini_api_key:
        gemini_model = os.environ.get("GEMINI_VIDEO_MODEL", DEFAULT_GEMINI_MODEL)
        try:
            raw_content = call_gemini_video(gemini_api_key, gemini_model, instructions, prompt, video_path)
            write_llm_response(project_dir, gemini_model, raw_content, provider="gemini")
            rows, transitions = parse_generated_analysis(raw_content)
            return rows, transitions, "gemini", gemini_model
        except Exception as exc:
            errors.append(f"Gemini failed: {exc}")
            write_llm_error(project_dir, gemini_model, exc, provider="gemini")

    raise ValueError("Native video analysis failed. " + " | ".join(errors))


def parse_generated_shot_rows(raw_content: str) -> list[dict[str, object]]:
    rows, _transitions = parse_generated_analysis(raw_content)
    return rows


def parse_generated_analysis(
    raw_content: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    parsed = parse_llm_json(raw_content)
    rows = first_list_value(parsed, ["shots", "shot_details", "shotDetails", "rows", "items", "data"])
    if not isinstance(rows, list):
        keys = ", ".join(parsed.keys())
        raise ValueError(f"LLM response did not include a shots array. Returned keys: {keys or '(none)'}")
    transitions = first_list_value(parsed, ["transitions", "shot_boundaries", "boundaries", "cuts"])
    return (
        [row for row in rows if isinstance(row, dict)],
        [row for row in transitions if isinstance(row, dict)] if isinstance(transitions, list) else [],
    )


def write_llm_response(project_dir: Path, model: str, raw_content: str, provider: str = "") -> None:
    payload = {
        "provider": provider,
        "model": model,
        "savedAt": datetime.now().isoformat(timespec="seconds"),
        "contentPreview": raw_content[:4000],
    }
    (project_dir / LAST_LLM_RESPONSE_FILENAME).write_text(json.dumps(payload, indent=2), encoding="utf-8")


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
) -> str:
    compact_rows = []
    for index, shot in enumerate(shots):
        compact_rows.append(
            {
                "analysis_id": analysis_id_for_row(index),
                "shot": index + 1,
                "current_shot": index + 1,
                "was_combined_split_or_reordered": bool(shot.get("analysis_stale")) or is_structurally_edited_row(shot, index),
                "title": shot.get("shot_title", "") if is_manual_field(shot, "shot_title") else "",
                "start": shot.get("start", ""),
                "end": shot.get("end", ""),
                "duration_seconds": shot.get("duration_seconds", 0),
                "existing_visual_description": shot.get("visual_description", "") if is_manual_field(shot, "visual_description") else "",
                "existing_audio_dialogue": shot.get("audio_dialogue", ""),
                "existing_action_camera": shot.get("action_camera", "") if is_manual_field(shot, "action_camera") else "",
                "existing_camera_movement_type": shot.get("camera_movement_type", "") if is_manual_field(shot, "camera_movement_type") else "",
                "existing_camera_movement_intensity": shot.get("camera_movement_intensity", "") if is_manual_field(shot, "camera_movement_intensity") else "",
                "existing_camera_movement_confidence": shot.get("camera_movement_confidence", "") if is_manual_field(shot, "camera_movement_confidence") else "",
                "existing_camera_movement_evidence": shot.get("camera_movement_evidence", "") if is_manual_field(shot, "camera_movement_evidence") else "",
                "existing_narrative_function": shot.get("narrative_function", "") if is_manual_field(shot, "narrative_function") else "",
                "existing_notes": shot.get("notes", "") if is_manual_field(shot, "notes") else "",
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
    return (
        f"Film: {project_name}\n\n"
        "User study notes / hypotheses:\n"
        f"{user_context or '(none provided)'}\n\n"
        "Current corrected shot list. This is the only authoritative shot sequence after the user's manual edits. "
        "Use only these rows, their analysis_id values, and these start/end timestamps for analysis. "
        "Ignore any original detector numbering that may exist elsewhere; it is not part of this request. "
        "Return one output row for each input row, in the same order, with the exact same analysis_id and current_shot/shot number:\n"
        f"{json.dumps(compact_rows, ensure_ascii=False, indent=2)}\n\n"
        "Current filmic sentence / beat outline. Use it as viewer context when present:\n"
        f"{json.dumps(outline, ensure_ascii=False, indent=2)}\n\n"
        "During this same viewing, independently check the current shot boundaries. Current boundaries in seconds:\n"
        f"{json.dumps(current_boundaries)}\n\n"
        "FFmpeg low-threshold candidates are local evidence, not guaranteed cuts:\n"
        f"{json.dumps(candidate_rows, ensure_ascii=False, indent=2)}\n\n"
        "Return every real visual transition you observe in a top-level transitions array, including transitions "
        "already represented by the current boundaries. Look especially for dissolves, crossfades, fades, and "
        "other gradual transitions that FFmpeg may miss. Do not treat camera movement, subject movement, animation "
        "inside one composition, or lighting changes as cuts. Each transition object must contain time_seconds, "
        "transition_type, confidence (high, medium, or low), from_visual, to_visual, and reason. For a gradual "
        "transition, also include transition_start_seconds and transition_end_seconds.\n\n"
        "For each transition that is more than 0.45 seconds away from every current boundary, it is a possible "
        "missing cut inside one current shot. Include before_details and after_details objects for the two proposed "
        "shots on either side. Each object must contain the same descriptive fields as a shot row, including a "
        "1-to-7-word shot_title. This lets the app apply the cut and its details without another model request. "
        "Do not include before_details or after_details for an existing current boundary.\n\n"
        "The full video is attached to this request. Its top-left SHOT / row label is burned into every frame from "
        "the user's current edited timeline. Use that visible label as the authoritative mapping for every title and "
        "description; never carry an action forward or backward into a differently labeled shot. Analyze each shot "
        "using the exact start/end timestamps above. "
        "Treat those timings as the user's corrected cut boundaries. For camera movement, watch the motion inside "
        "each time range and distinguish camera movement from actor, object, or edit movement.\n\n"
        "For every shot, generate shot_title as a concise card label of 1 to 7 words. "
        "Do not include the shot number in shot_title. Prefer concrete place/action/story language over generic labels.\n\n"
        "Return exactly one JSON object with top-level keys named \"shots\" and \"transitions\". The shots value "
        "must contain one object for every input row, using the exact field names requested. Every returned shot "
        "must include analysis_id copied exactly from the input row."
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


def write_analysis_labels(path: Path, shots: list[dict[str, object]], width: int) -> None:
    events = []
    for index, row in enumerate(shots):
        try:
            start = _seconds_from_timestamp(str(row.get("start", "00:00:00.000")))
            end = _seconds_from_timestamp(str(row.get("end", "00:00:00.000")))
        except (TypeError, ValueError):
            continue
        events.append(
            f"Dialogue: 0,{ass_timestamp(start)},{ass_timestamp(end)},ShotLabel,,0,0,0,,"
            f"SHOT {index + 1:03d}  row_{index + 1:04d}"
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
    timeline_hash = hashlib.sha1(
        json.dumps(timeline_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:10] if timeline_payload else "plain"
    output_path = analysis_dir / f"{project_dir.name}_analysis_{max_width}w_{fps}fps_{timeline_hash}.mp4"
    if output_path.exists() and output_path.stat().st_mtime >= video_path.stat().st_mtime:
        return output_path

    ffmpeg = _require_binary("ffmpeg")
    filters = [f"scale='min({max_width},iw)':-2"]
    if shots:
        labels_path = analysis_dir / f"shot_labels_{timeline_hash}.ass"
        write_analysis_labels(labels_path, shots, max_width)
        filters.append(f"subtitles='{ffmpeg_filter_path(labels_path)}'")

    result = _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
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
    return output_path


def call_qwen_video(api_key: str, model: str, instructions: str, prompt: str, video_path: Path) -> str:
    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": instructions},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "video_url", "video_url": {"url": video_data_url(video_path)}, "fps": 2},
                ],
            },
        ],
        "temperature": 0.2,
        "max_tokens": 24000,
        "response_format": {"type": "json_object"},
        "enable_thinking": False,
    }
    url = os.environ.get("QWEN_COMPATIBLE_URL", QWEN_COMPATIBLE_URL)
    return call_chat_completion(url, api_key, request_body, "Qwen")


def call_gemini_video(api_key: str, model: str, instructions: str, prompt: str, video_path: Path) -> str:
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

    body = {
        "model": model,
        "input": [
            {"type": "text", "text": text_prompt},
            video_part,
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
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"Gemini error {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ValueError(f"Could not reach Gemini: {exc.reason}") from exc
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


def call_chat_completion(url: str, api_key: str, request_body: dict[str, object], provider_name: str) -> str:
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
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"{provider_name} error {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ValueError(
            f"Could not reach {provider_name} at {url}: {exc.reason}. "
            "Check your internet connection, VPN/proxy settings, and firewall permissions."
        ) from exc
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
    video_path.write_bytes(payload)

    output_dir = config.outputs_dir / upload_stem
    args = Namespace(
        video=video_path,
        output_dir=output_dir,
        threshold=0.32,
        max_minutes=10.0,
        screenshot_width=480,
    )
    breakdown_dir, workbook_path = run_breakdown(args)
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
        max_minutes=10.0,
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


def download_source_video(config: ServerConfig, ytdlp: str, source_url: str, title: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    download_stem = f"{safe_upload_stem(title or 'Imported Video')}_{stamp}"
    output_template = str(config.data_dir / f"{download_stem}.%(ext)s")
    download_result = _run(
        [
            ytdlp,
            "--no-update",
            "--no-playlist",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            "en.*,en",
            "--sub-format",
            "vtt/srt/best",
            "-f",
            "bv*[height<=720]+ba/b[height<=720]/b",
            "--merge-output-format",
            "mp4",
            "-o",
            output_template,
            source_url,
        ]
    )
    if download_result.returncode != 0:
        raise VideoToolError(download_result.stderr.strip() or "Download failed.")

    candidates = sorted(config.data_dir.glob(f"{download_stem}.*"), key=lambda path: path.stat().st_mtime, reverse=True)
    video_path = next((path for path in candidates if path.suffix.lower() in VIDEO_SUFFIXES), None)
    if video_path is None:
        raise VideoToolError("Downloaded file was not a supported video.")
    return video_path


def refresh_existing_project_captions(config: ServerConfig, ytdlp: str, project_dir: Path, source_url: str) -> dict[str, object]:
    video_path = find_source_video(project_dir.name)
    if video_path is None:
        return {"captionFiles": [], "cueCount": 0, "shotsUpdated": 0}
    result = _run(
        [
            ytdlp,
            "--no-update",
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            "en.*,en",
            "--sub-format",
            "vtt/srt/best",
            "-o",
            str(config.data_dir / f"{video_path.stem}.%(ext)s"),
            source_url,
        ]
    )
    if result.returncode != 0:
        return {"captionFiles": [], "cueCount": 0, "shotsUpdated": 0, "error": result.stderr.strip()}
    return enrich_project_with_captions(project_dir, video_path)


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
            imported.append(project_summary(existing_project))
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
            imported.append(project_summary(existing_project))
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
            imported.append(project_summary(existing_project))
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
                self.send_json({"projects": list_projects(self.config.outputs_dir)})
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
                self.send_json(update_shots_with_llm_details(self.config.outputs_dir, project_id, payload))
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
