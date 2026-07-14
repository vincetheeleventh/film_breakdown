from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

from .analyzer import analyze_shots
from .models import Shot, ShotAnalysis, format_timestamp
from .video import VideoToolError, build_shots, extract_screenshots, probe_duration
from .workbook import write_manifest_json, write_workbook


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a shot-by-shot film study workbook from a short video."
    )
    parser.add_argument("video", type=Path, help="Path to a video file.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output folder. Defaults to outputs/<video-name>_<timestamp>.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.32,
        help="FFmpeg scene-change threshold. Lower finds more cuts; higher finds fewer.",
    )
    parser.add_argument(
        "--max-minutes",
        type=float,
        default=10.0,
        help="Maximum video duration to process in minutes.",
    )
    parser.add_argument(
        "--screenshot-width",
        type=int,
        default=480,
        help="Maximum screenshot width in pixels.",
    )
    return parser.parse_args(argv)


def default_output_dir(video_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path("outputs") / f"{video_path.stem}_{stamp}"


def write_manifest_csv(
    output_path: Path,
    shots: list[Shot],
    analyses: dict[int, ShotAnalysis],
) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "shot",
                "screenshot_path",
                "start",
                "end",
                "duration_seconds",
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
            ],
        )
        writer.writeheader()
        for shot in shots:
            analysis = analyses[shot.number]
            writer.writerow(
                {
                    "shot": shot.number,
                    "screenshot_path": shot.screenshot_path or "",
                    "start": format_timestamp(shot.start),
                    "end": format_timestamp(shot.end),
                    "duration_seconds": f"{shot.duration:.2f}",
                    **analysis.as_dict(),
                }
            )


def run(args: argparse.Namespace) -> tuple[Path, Path]:
    video_path = args.video.expanduser().resolve()
    if not video_path.exists():
        raise FileNotFoundError(f"Video file does not exist: {video_path}")

    duration = probe_duration(video_path)
    max_seconds = args.max_minutes * 60
    if duration > max_seconds:
        raise ValueError(
            f"This prototype is capped at {args.max_minutes:g} minutes. "
            f"The input is {duration / 60:.2f} minutes."
        )

    output_dir = (args.output_dir or default_output_dir(video_path)).resolve()
    frames_dir = output_dir / "screenshots"
    output_dir.mkdir(parents=True, exist_ok=True)

    shots = build_shots(video_path, threshold=args.threshold)
    shots = extract_screenshots(
        video_path,
        shots,
        frames_dir=frames_dir,
        max_width=args.screenshot_width,
    )
    analyses = analyze_shots(shots, output_dir / "analysis_packets.jsonl")

    workbook_path = output_dir / "film_study.xlsx"
    write_workbook(workbook_path, shots, analyses)
    write_manifest_json(output_dir / "manifest.json", shots, analyses)
    write_manifest_csv(output_dir / "manifest.csv", shots, analyses)
    return output_dir, workbook_path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        output_dir, workbook_path = run(args)
    except (FileNotFoundError, ValueError, VideoToolError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Output folder: {output_dir}")
    print(f"Workbook: {workbook_path}")
    return 0
