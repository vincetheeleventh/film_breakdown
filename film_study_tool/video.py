from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .models import Shot


class VideoToolError(RuntimeError):
    pass


def _require_binary(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise VideoToolError(
            f"{name} was not found on PATH. Install FFmpeg and make sure {name} is available."
        )
    return resolved


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def probe_duration(video_path: Path) -> float:
    ffprobe = _require_binary("ffprobe")
    result = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
    )
    if result.returncode != 0:
        raise VideoToolError(result.stderr.strip() or "FFprobe could not read the video.")
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise VideoToolError("FFprobe returned an invalid duration.") from exc


def detect_shot_boundaries(video_path: Path, threshold: float = 0.32) -> list[tuple[float, float]]:
    """Return detected cut times and FFmpeg scene scores."""
    ffmpeg = _require_binary("ffmpeg")
    result = _run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            str(video_path),
            "-filter:v",
            f"select='gt(scene,{threshold})',metadata=print",
            "-an",
            "-f",
            "null",
            "-",
        ]
    )
    if result.returncode != 0:
        raise VideoToolError(result.stderr.strip() or "FFmpeg scene detection failed.")

    text = result.stdout + "\n" + result.stderr
    boundaries: list[tuple[float, float]] = []
    current_time: float | None = None

    for line in text.splitlines():
        time_match = re.search(r"pts_time[:=]([0-9.]+)", line)
        if time_match:
            current_time = float(time_match.group(1))
            continue

        score_match = re.search(r"lavfi\.scene_score=([0-9.]+)", line)
        if score_match and current_time is not None:
            boundaries.append((current_time, float(score_match.group(1))))
            current_time = None

    return boundaries


def build_shots(
    video_path: Path,
    threshold: float,
    min_gap_seconds: float = 0.25,
) -> list[Shot]:
    duration = probe_duration(video_path)
    raw_boundaries = detect_shot_boundaries(video_path, threshold=threshold)

    cuts: list[tuple[float, float]] = []
    last_time = 0.0
    for cut_time, score in raw_boundaries:
        if cut_time <= 0.05 or cut_time >= duration - 0.05:
            continue
        if cut_time - last_time < min_gap_seconds:
            continue
        cuts.append((cut_time, score))
        last_time = cut_time

    starts = [0.0] + [cut for cut, _score in cuts]
    ends = [cut for cut, _score in cuts] + [duration]
    scores: list[float | None] = [None] + [score for _cut, score in cuts]

    return [
        Shot(number=index + 1, start=start, end=end, scene_score=scores[index])
        for index, (start, end) in enumerate(zip(starts, ends))
        if end > start
    ]


def extract_screenshots(
    video_path: Path,
    shots: list[Shot],
    frames_dir: Path,
    max_width: int = 480,
) -> list[Shot]:
    ffmpeg = _require_binary("ffmpeg")
    frames_dir.mkdir(parents=True, exist_ok=True)

    for shot in shots:
        timestamp = shot.midpoint
        if shot.duration > 0.20:
            timestamp = min(shot.end - 0.05, max(shot.start + 0.05, timestamp))

        output_path = frames_dir / f"shot_{shot.number:04d}.jpg"
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
            raise VideoToolError(
                result.stderr.strip() or f"Could not extract screenshot for shot {shot.number}."
            )
        shot.screenshot_path = output_path

    return shots

