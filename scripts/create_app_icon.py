from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
STATIC_ICON_DIR = ROOT / "film_study_tool" / "ui_static" / "icons"
ASSET_DIR = ROOT / "assets"


def scaled(points: list[tuple[float, float]], scale: float) -> list[tuple[int, int]]:
    return [(round(x * scale), round(y * scale)) for x, y in points]


def rounded_rectangle(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int], radius: int, fill, outline=None, width: int = 1) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def make_icon(size: int) -> Image.Image:
    scale = size / 512
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    bg = Image.new("RGBA", (size, size), (16, 20, 26, 255))
    bg_draw = ImageDraw.Draw(bg)
    for y in range(size):
        t = y / max(size - 1, 1)
        r = round(18 + 28 * t)
        g = round(31 + 2 * t)
        b = round(42 - 22 * t)
        bg_draw.line([(0, y), (size, y)], fill=(r, g, max(b, 18), 255))

    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=round(112 * scale), fill=255)
    image.alpha_composite(bg)
    image.putalpha(mask)

    inset = round(44 * scale)
    rounded_rectangle(
        draw,
        (inset, inset, size - inset, size - inset),
        round(92 * scale),
        fill=None,
        outline=(255, 255, 255, 22),
        width=max(1, round(4 * scale)),
    )

    shadow_offset = round(16 * scale)
    rounded_rectangle(
        draw,
        (round(98 * scale), round((88 + shadow_offset) * scale), round(414 * scale), round((302 + shadow_offset) * scale)),
        round(38 * scale),
        fill=(0, 0, 0, 72),
    )

    rounded_rectangle(
        draw,
        (round(98 * scale), round(88 * scale), round(414 * scale), round(302 * scale)),
        round(38 * scale),
        fill=(12, 17, 23, 255),
        outline=(235, 171, 82, 255),
        width=max(4, round(14 * scale)),
    )

    for x, y, color in [
        (128, 122, (244, 201, 107, 255)),
        (128, 230, (244, 201, 107, 255)),
        (340, 122, (217, 123, 65, 255)),
        (340, 230, (217, 123, 65, 255)),
    ]:
        rounded_rectangle(
            draw,
            (round(x * scale), round(y * scale), round((x + 44) * scale), round((y + 38) * scale)),
            round(9 * scale),
            fill=color,
        )

    rounded_rectangle(
        draw,
        (round(193 * scale), round(121 * scale), round(319 * scale), round(269 * scale)),
        round(22 * scale),
        fill=(22, 35, 51, 255),
    )
    draw.polygon(scaled([(237, 158), (237, 232), (294, 195)], scale), fill=(244, 240, 221, 255))

    rows = [
        (326, 320, (244, 201, 107, 255)),
        (380, 238, (224, 86, 79, 255)),
        (434, 280, (116, 176, 111, 255)),
    ]
    for y, width, color in rows:
        rounded_rectangle(
            draw,
            (round(96 * scale), round(y * scale), round((96 + width) * scale), round((y + 34) * scale)),
            round(17 * scale),
            fill=color,
        )
    rounded_rectangle(
        draw,
        (round(252 * scale), round(318 * scale), round(262 * scale), round(476 * scale)),
        round(5 * scale),
        fill=(244, 240, 221, 255),
    )

    return image


def main() -> None:
    STATIC_ICON_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    icon_1024 = make_icon(1024)
    for size in (192, 512):
        icon_1024.resize((size, size), Image.Resampling.LANCZOS).save(STATIC_ICON_DIR / f"icon-{size}.png")
    icon_1024.resize((64, 64), Image.Resampling.LANCZOS).save(STATIC_ICON_DIR / "favicon.png")

    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    ico_source = icon_1024.resize((256, 256), Image.Resampling.LANCZOS)
    ico_source.save(STATIC_ICON_DIR / "favicon.ico", sizes=ico_sizes)
    ico_source.save(ASSET_DIR / "film-study-tool.ico", sizes=ico_sizes)


if __name__ == "__main__":
    main()
