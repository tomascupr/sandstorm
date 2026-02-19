#!/usr/bin/env python3
"""Generate the Sandstorm bot icon (512x512 PNG).

Usage:
    uv run --with Pillow python scripts/generate_icon.py

Output: src/sandstorm/assets/sandstorm-icon.png
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 512
BG_COLOR = (26, 26, 46)  # #1a1a2e

# Warm sand/amber palette for swirl lines
SWIRL_COLORS = [
    (255, 152, 0),  # amber
    (255, 183, 77),  # light amber
    (255, 204, 128),  # pale gold
    (230, 126, 34),  # deep orange
    (255, 167, 38),  # mid amber
]


def draw_swirl_lines(draw: ImageDraw.ImageDraw) -> None:
    """Draw abstract sand swirl curves across the canvas."""
    cx, cy = SIZE // 2, SIZE // 2

    for i, color in enumerate(SWIRL_COLORS):
        # Each swirl has different parameters for variety
        phase = i * 1.3
        radius_base = 60 + i * 35
        amplitude = 30 + i * 12
        width = max(3, 8 - i)

        points: list[tuple[float, float]] = []
        steps = 300
        for step in range(steps):
            t = step / steps * math.pi * 3.5  # ~1.75 full rotations
            r = radius_base + amplitude * math.sin(t * 2.2 + phase)
            # Spiral outward slightly
            r += t * 12
            x = cx + r * math.cos(t + phase * 0.5)
            y = cy + r * math.sin(t + phase * 0.5)
            points.append((x, y))

        # Draw as connected line segments
        for j in range(len(points) - 1):
            # Fade opacity toward the ends
            frac = j / len(points)
            fade = math.sin(frac * math.pi)  # 0 at edges, 1 in middle
            alpha = int(200 * fade + 55)
            c = (*color, alpha)
            draw.line([points[j], points[j + 1]], fill=c, width=width)


def draw_sand_particles(draw: ImageDraw.ImageDraw) -> None:
    """Scatter small dots to give a sandy/dusty feel."""
    import random

    rng = random.Random(42)  # deterministic
    for _ in range(120):
        x = rng.randint(30, SIZE - 30)
        y = rng.randint(30, SIZE - 30)
        r = rng.randint(1, 3)
        alpha = rng.randint(80, 180)
        color_idx = rng.randint(0, len(SWIRL_COLORS) - 1)
        c = (*SWIRL_COLORS[color_idx], alpha)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=c)


def main() -> None:
    img = Image.new("RGBA", (SIZE, SIZE), (*BG_COLOR, 255))
    draw = ImageDraw.Draw(img, "RGBA")

    draw_swirl_lines(draw)
    draw_sand_particles(draw)

    # Composite onto opaque background for final PNG
    final = Image.new("RGB", (SIZE, SIZE), BG_COLOR)
    final.paste(img, mask=img.split()[3])

    out = Path(__file__).resolve().parent.parent / "src" / "sandstorm" / "assets" / "sandstorm-icon.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    final.save(out, "PNG")
    print(f"Saved {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
