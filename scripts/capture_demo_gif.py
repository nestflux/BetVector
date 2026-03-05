"""
BetVector — Demo GIF Capture Script
=====================================
Captures screenshots of every demo app page via Playwright, then
assembles them into an animated GIF using variable frame durations
(one frame per unique view, long hold durations instead of repeat frames).

Usage:
    python scripts/capture_demo_gif.py

Output:
    demo_walkthrough.gif  (in project root)
"""

import asyncio
import io
import sys
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_URL = "http://localhost:8502"
OUT_GIF = PROJECT_ROOT / "demo_walkthrough.gif"

# (page label partial text, hold_ms at top, scroll_steps, hold_ms at bottom)
PAGES = [
    ("Fixtures",        2000, 3, 1500),
    ("Today's Picks",   2000, 3, 1500),
    ("Performance",     2000, 3, 1500),
    ("League Explorer", 2000, 4, 1500),
    ("Model Health",    2000, 3, 1500),
    ("Bankroll Manager",2000, 2, 1500),
    ("Match Deep Dive", 2000, 3, 1500),
]

SCROLL_STEP = 380       # pixels per scroll step
SCROLL_PAUSE_MS = 600   # hold between scroll steps (shows transition)
TRANSITION_MS = 400     # brief flash between pages


async def capture_demo() -> None:
    from playwright.async_api import async_playwright

    # Each entry: (PIL.Image, duration_ms)
    frames: list[tuple[Image.Image, int]] = []

    def snap(png_bytes: bytes, duration_ms: int) -> None:
        img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        img = img.resize((960, 600), Image.LANCZOS)
        frames.append((img, duration_ms))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await ctx.new_page()

        print(f"→ Opening {DEMO_URL} …")
        await page.goto(DEMO_URL, wait_until="networkidle", timeout=30_000)
        await page.wait_for_timeout(3000)

        for label, top_hold, n_scroll, bot_hold in PAGES:
            print(f"  → {label}")

            # Click the sidebar nav item
            try:
                radio = page.get_by_text(label, exact=False).first
                await radio.click()
                await page.wait_for_timeout(1800)
            except Exception as e:
                print(f"    ⚠ click failed: {e}")

            # Scroll to top
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(300)

            # Hold at top
            png = await page.screenshot(full_page=False)
            snap(png, top_hold)

            # Scroll down step by step
            for _ in range(n_scroll):
                await page.evaluate(f"window.scrollBy(0, {SCROLL_STEP})")
                await page.wait_for_timeout(300)
                png = await page.screenshot(full_page=False)
                snap(png, SCROLL_PAUSE_MS)

            # Hold at bottom
            png = await page.screenshot(full_page=False)
            snap(png, bot_hold)

            # Brief flash before next page
            png = await page.screenshot(full_page=False)
            snap(png, TRANSITION_MS)

        await browser.close()

    if not frames:
        print("✗ No frames captured — aborting.")
        sys.exit(1)

    imgs, durations = zip(*frames)
    print(f"→ {len(imgs)} frames  |  total duration ~{sum(durations)/1000:.0f}s")

    # Quantise all frames to a shared 256-colour palette derived from first frame
    palette_src = imgs[0].quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=0)
    pal_frames = [
        img.quantize(colors=256, palette=palette_src, dither=0)
        for img in imgs
    ]

    print(f"→ Writing {OUT_GIF.name} …")
    pal_frames[0].save(
        OUT_GIF,
        format="GIF",
        save_all=True,
        append_images=pal_frames[1:],
        duration=list(durations),   # per-frame durations in ms
        loop=0,
        optimize=False,
    )

    size_mb = OUT_GIF.stat().st_size / 1_048_576
    print(f"✓ Saved → {OUT_GIF}  ({size_mb:.1f} MB, {len(imgs)} frames)")


if __name__ == "__main__":
    asyncio.run(capture_demo())
