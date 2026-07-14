from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from film_study_tool.ui_server import DATA_DIR, OUTPUTS_DIR, STATIC_DIR, ServerConfig, import_channel_projects


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import popular videos from a YouTube or TikTok channel.")
    parser.add_argument("url", help="YouTube or TikTok channel URL")
    parser.add_argument("--limit", type=int, default=10, choices=[5, 10], help="Number of videos to import")
    parser.add_argument("--scan-limit", type=int, default=100, help="Number of channel entries to scan before sorting")
    parser.add_argument("--group", default="", help="Optional folder path, separated with /")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload: dict[str, object] = {
        "url": args.url,
        "limit": args.limit,
        "scanLimit": args.scan_limit,
    }
    if args.group:
        payload["groupPath"] = args.group
    result = import_channel_projects(
        ServerConfig(
            outputs_dir=OUTPUTS_DIR.resolve(),
            static_dir=STATIC_DIR.resolve(),
            data_dir=DATA_DIR.resolve(),
        ),
        payload,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
