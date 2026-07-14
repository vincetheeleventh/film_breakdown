from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
STATIC_ICON_DIR = ROOT / "film_study_tool" / "ui_static" / "icons"
ASSET_DIR = ROOT / "assets"


def center_crop_square(image: Image.Image) -> Image.Image:
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    return image.crop((left, top, left + side, top + side))


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/install_icon_from_image.py path/to/icon.png")

    source = Path(sys.argv[1]).expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"Icon source not found: {source}")

    STATIC_ICON_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    image = center_crop_square(Image.open(source).convert("RGBA"))
    image.save(STATIC_ICON_DIR / "wheel-icon-source.png")

    for size in (192, 512):
        image.resize((size, size), Image.Resampling.LANCZOS).save(STATIC_ICON_DIR / f"icon-{size}.png")
    image.resize((64, 64), Image.Resampling.LANCZOS).save(STATIC_ICON_DIR / "favicon.png")

    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    ico_source = image.resize((256, 256), Image.Resampling.LANCZOS)
    ico_source.save(STATIC_ICON_DIR / "favicon.ico", sizes=ico_sizes)
    ico_source.save(ASSET_DIR / "film-study-tool.ico", sizes=ico_sizes)


if __name__ == "__main__":
    main()
