#!/usr/bin/env python3
"""Generate the BetVector app icon — a dark circle with a stylised
upward arrow (the 'vector') and 'BV' monogram."""

from PIL import Image, ImageDraw, ImageFont
import math
import os

SIZE = 512
CENTER = SIZE // 2
BG = (13, 17, 23)          # #0D1117
GREEN = (63, 185, 80)      # #3FB950
BLUE = (88, 166, 255)      # #58a6ff
SURFACE = (22, 27, 34)     # #161B22
WHITE = (230, 237, 243)    # #E6EDF3


def lerp_color(c1, c2, t):
    """Linear interpolation between two RGB colors."""
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def create_icon():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # --- Background circle ---
    padding = 8
    draw.ellipse(
        [padding, padding, SIZE - padding, SIZE - padding],
        fill=BG,
    )

    # --- Inner subtle ring ---
    ring_width = 3
    ring_pad = padding + 12
    draw.ellipse(
        [ring_pad, ring_pad, SIZE - ring_pad, SIZE - ring_pad],
        outline=(48, 54, 61),  # #30363D
        width=ring_width,
    )

    # --- Upward arrow (the "vector") ---
    # Draw a bold upward-pointing arrow in the center-right area
    arrow_cx = CENTER + 60
    arrow_bottom = CENTER + 100
    arrow_top = CENTER - 130
    arrow_width = 50
    shaft_width = 20

    # Arrow shaft (gradient from blue at bottom to green at top)
    shaft_height = arrow_bottom - arrow_top - 60
    for y in range(shaft_height):
        t = 1.0 - (y / shaft_height)
        color = lerp_color(BLUE, GREEN, t)
        yy = arrow_bottom - y
        draw.rectangle(
            [arrow_cx - shaft_width // 2, yy,
             arrow_cx + shaft_width // 2, yy + 1],
            fill=color,
        )

    # Arrowhead (triangle) — green
    head_top = arrow_top
    head_bottom = arrow_top + 80
    head_half_width = 55
    draw.polygon(
        [
            (arrow_cx, head_top),
            (arrow_cx - head_half_width, head_bottom),
            (arrow_cx + head_half_width, head_bottom),
        ],
        fill=GREEN,
    )

    # --- "BV" text ---
    # Try to use a bold system font
    font = None
    font_size = 160
    font_paths = [
        "/System/Library/Fonts/SFCompact-Bold.otf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
    ]
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, font_size)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()

    # Position BV on the left side
    text = "BV"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = CENTER - 100 - tw // 2
    ty = CENTER - th // 2 - 10

    # Draw text with slight shadow
    draw.text((tx + 2, ty + 2), text, fill=(0, 0, 0, 120), font=font)
    draw.text((tx, ty), text, fill=WHITE, font=font)

    # --- Small chart bars at bottom (subtle accent) ---
    bar_base_y = CENTER + 110
    bar_x_start = CENTER - 110
    bar_heights = [30, 50, 40, 65, 55, 75]
    bar_width = 14
    bar_gap = 6

    for i, h in enumerate(bar_heights):
        x = bar_x_start + i * (bar_width + bar_gap)
        t = i / (len(bar_heights) - 1)
        color = lerp_color(BLUE, GREEN, t)
        # Fade opacity
        draw.rectangle(
            [x, bar_base_y - h, x + bar_width, bar_base_y],
            fill=color,
        )

    return img


def main():
    icon = create_icon()

    # Save as PNG
    out_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(out_dir)
    png_path = os.path.join(project_root, "betvector_icon.png")
    icon.save(png_path, "PNG")
    print(f"PNG saved: {png_path}")

    # Create .icns for macOS
    iconset_dir = os.path.join(project_root, "betvector.iconset")
    os.makedirs(iconset_dir, exist_ok=True)

    # macOS iconset requires specific sizes
    sizes = [16, 32, 64, 128, 256, 512]
    for s in sizes:
        resized = icon.resize((s, s), Image.LANCZOS)
        resized.save(os.path.join(iconset_dir, f"icon_{s}x{s}.png"))
        # @2x versions
        if s <= 256:
            resized2x = icon.resize((s * 2, s * 2), Image.LANCZOS)
            resized2x.save(os.path.join(iconset_dir, f"icon_{s}x{s}@2x.png"))

    print(f"Iconset created: {iconset_dir}")
    print("Run: iconutil -c icns betvector.iconset -o betvector.icns")


if __name__ == "__main__":
    main()
