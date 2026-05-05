from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageFilter

_WIDTH = 300
_HEIGHT = 450
_QUALITY = 88

_SAMPLES: list[dict] = [
    {"filename": "sample_dark.jpg", "label": "Dark navy"},
    {"filename": "sample_light.jpg", "label": "Light warm"},
    {"filename": "sample_vibrant.jpg", "label": "Vibrant orange-purple"},
    {"filename": "sample_busy.jpg", "label": "Busy textured"},
    {"filename": "sample_crimson.jpg", "label": "Crimson dramatic"},
    {"filename": "sample_teal.jpg", "label": "Teal cinematic"},
    {"filename": "sample_mono.jpg", "label": "High-contrast mono"},
    {"filename": "sample_forest.jpg", "label": "Forest green"},
]


def _make_dark() -> Image.Image:
    """Dark navy-to-black vertical gradient."""
    img = Image.new("RGB", (_WIDTH, _HEIGHT))
    pixels = img.load()
    for y in range(_HEIGHT):
        t = y / (_HEIGHT - 1)
        r = int((18 - 0) * (1 - t))
        g = int((24 - 0) * (1 - t))
        b = int((48 - 0) * (1 - t))
        for x in range(_WIDTH):
            pixels[x, y] = (r, g, b)
    return img


def _make_light() -> Image.Image:
    """Warm cream-to-white vertical gradient."""
    img = Image.new("RGB", (_WIDTH, _HEIGHT))
    pixels = img.load()
    for y in range(_HEIGHT):
        t = y / (_HEIGHT - 1)
        r = int(245 + (255 - 245) * t)
        g = int(235 + (255 - 235) * t)
        b = int(210 + (255 - 210) * t)
        for x in range(_WIDTH):
            pixels[x, y] = (r, g, b)
    return img


def _make_vibrant() -> Image.Image:
    """Bold orange-to-purple diagonal gradient."""
    img = Image.new("RGB", (_WIDTH, _HEIGHT))
    pixels = img.load()
    for y in range(_HEIGHT):
        for x in range(_WIDTH):
            t = (x / (_WIDTH - 1) + y / (_HEIGHT - 1)) / 2.0
            r = int(230 * (1 - t) + 80 * t)
            g = int(90 * (1 - t) + 20 * t)
            b = int(20 * (1 - t) + 200 * t)
            pixels[x, y] = (r, g, b)
    return img


def _make_busy() -> Image.Image:
    """Sinusoidal color variation + gaussian blur to simulate a busy poster."""
    rng = random.Random(42)
    img = Image.new("RGB", (_WIDTH, _HEIGHT))
    pixels = img.load()
    for y in range(_HEIGHT):
        for x in range(_WIDTH):
            wave_r = math.sin(x * 0.08 + y * 0.05) * 0.5 + 0.5
            wave_g = math.sin(x * 0.05 - y * 0.09 + 1.0) * 0.5 + 0.5
            wave_b = math.sin(x * 0.11 + y * 0.07 + 2.5) * 0.5 + 0.5
            noise = rng.randint(-30, 30)
            r = max(0, min(255, int(wave_r * 200 + 30) + noise))
            g = max(0, min(255, int(wave_g * 180 + 40) + noise))
            b = max(0, min(255, int(wave_b * 220 + 20) + noise))
            pixels[x, y] = (r, g, b)
    return img.filter(ImageFilter.GaussianBlur(radius=1.5))


def _make_crimson() -> Image.Image:
    """Deep crimson-to-black radial vignette — dramatic film poster feel."""
    img = Image.new("RGB", (_WIDTH, _HEIGHT))
    pixels = img.load()
    cx, cy = _WIDTH / 2, _HEIGHT * 0.4
    max_d = math.sqrt(cx**2 + (_HEIGHT - cy) ** 2)
    for y in range(_HEIGHT):
        for x in range(_WIDTH):
            d = math.sqrt((x - cx) ** 2 + (y - cy) ** 2) / max_d
            r = int(180 * (1 - d * 0.85))
            g = int(15 * (1 - d * 0.9))
            b = int(20 * (1 - d * 0.9))
            pixels[x, y] = (max(0, r), max(0, g), max(0, b))
    return img


def _make_teal() -> Image.Image:
    """Cool teal-to-navy vertical gradient — cinematic blue-green."""
    img = Image.new("RGB", (_WIDTH, _HEIGHT))
    pixels = img.load()
    for y in range(_HEIGHT):
        t = y / (_HEIGHT - 1)
        r = int(0 + 8 * (1 - t))
        g = int(120 * (1 - t) + 40 * t)
        b = int(130 * (1 - t) + 80 * t)
        for x in range(_WIDTH):
            pixels[x, y] = (r, g, b)
    return img


def _make_mono() -> Image.Image:
    """High-contrast greyscale — tests pill visibility at all tonal ranges."""
    img = Image.new("RGB", (_WIDTH, _HEIGHT))
    pixels = img.load()
    for y in range(_HEIGHT):
        for x in range(_WIDTH):
            # Cross-hatch tonal bands
            wave = math.sin(y * 0.025) * 0.5 + 0.5
            stripe = 0.5 + 0.5 * math.sin(x * 0.04 + y * 0.015)
            v = int((wave * 0.6 + stripe * 0.4) * 240 + 8)
            v = max(0, min(255, v))
            pixels[x, y] = (v, v, v)
    return img.filter(ImageFilter.GaussianBlur(radius=0.8))


def _make_forest() -> Image.Image:
    """Lush dark-green to olive gradient with diagonal texture."""
    rng = random.Random(17)
    img = Image.new("RGB", (_WIDTH, _HEIGHT))
    pixels = img.load()
    for y in range(_HEIGHT):
        for x in range(_WIDTH):
            t = x / (_WIDTH - 1) * 0.3 + y / (_HEIGHT - 1) * 0.7
            wave = math.sin(x * 0.1 + y * 0.07) * 0.15
            r = int((30 + 20 * t + wave * 30) + rng.randint(-8, 8))
            g = int((90 - 40 * t + wave * 40) + rng.randint(-8, 8))
            b = int((20 + 10 * t) + rng.randint(-6, 6))
            pixels[x, y] = (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))
    return img.filter(ImageFilter.GaussianBlur(radius=1.2))


_GENERATORS = {
    "sample_dark.jpg": _make_dark,
    "sample_light.jpg": _make_light,
    "sample_vibrant.jpg": _make_vibrant,
    "sample_busy.jpg": _make_busy,
    "sample_crimson.jpg": _make_crimson,
    "sample_teal.jpg": _make_teal,
    "sample_mono.jpg": _make_mono,
    "sample_forest.jpg": _make_forest,
}


def ensure_sample_posters(output_dir: Path) -> list[dict]:
    """Generate missing sample poster images in output_dir.

    Returns the fixed ordered list of {"filename": str, "label": str} dicts.
    Images are only written if they don't already exist.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    for sample in _SAMPLES:
        dest = output_dir / sample["filename"]
        if not dest.exists():
            img = _GENERATORS[sample["filename"]]()
            img.save(str(dest), format="JPEG", quality=_QUALITY)
    return list(_SAMPLES)
