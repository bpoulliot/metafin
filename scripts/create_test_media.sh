#!/usr/bin/env bash
# Generates synthetic test MKV files and placeholder poster images for Xenotag dev/testing.
# Requires: ffmpeg. Pillow optional (for poster images).

set -euo pipefail

MEDIA_DIR="${1:-$HOME/.mf-dev/media}"

mkdir -p \
  "$MEDIA_DIR/movies/Single Audio Movie (2020)" \
  "$MEDIA_DIR/movies/Dual Audio Movie (2021)" \
  "$MEDIA_DIR/movies/Multi Audio Movie (2022)" \
  "$MEDIA_DIR/tv/Anime Show (2023)/Season 01"

echo "Creating synthetic MKV files..."

# 1080p, English only
ffmpeg -y -f lavfi -i "color=c=black:s=1920x1080:r=24:d=5" \
  -f lavfi -i "sine=frequency=440:duration=5" \
  -map 0:v -map 1:a \
  -metadata:s:a:0 language=eng \
  -c:v libx264 -preset ultrafast -crf 40 \
  -c:a aac \
  "$MEDIA_DIR/movies/Single Audio Movie (2020)/Single.Audio.Movie.2020.1080p.mkv" \
  -loglevel error
echo "  [1/4] 1080p English-only MKV created"

# 720p, English + Japanese
ffmpeg -y -f lavfi -i "color=c=navy:s=1280x720:r=24:d=5" \
  -f lavfi -i "sine=frequency=440:duration=5" \
  -f lavfi -i "sine=frequency=880:duration=5" \
  -map 0:v -map 1:a -map 2:a \
  -metadata:s:a:0 language=eng \
  -metadata:s:a:1 language=jpn \
  -c:v libx264 -preset ultrafast -crf 40 \
  -c:a aac \
  "$MEDIA_DIR/movies/Dual Audio Movie (2021)/Dual.Audio.Movie.2021.720p.mkv" \
  -loglevel error
echo "  [2/4] 720p EN+JA dual-audio MKV created"

# 4K (2160p), English + Japanese + French
ffmpeg -y -f lavfi -i "color=c=darkred:s=3840x2160:r=24:d=5" \
  -f lavfi -i "sine=frequency=440:duration=5" \
  -f lavfi -i "sine=frequency=880:duration=5" \
  -f lavfi -i "sine=frequency=1320:duration=5" \
  -map 0:v -map 1:a -map 2:a -map 3:a \
  -metadata:s:a:0 language=eng \
  -metadata:s:a:1 language=jpn \
  -metadata:s:a:2 language=fre \
  -c:v libx264 -preset ultrafast -crf 40 \
  -c:a aac \
  "$MEDIA_DIR/movies/Multi Audio Movie (2022)/Multi.Audio.Movie.2022.2160p.mkv" \
  -loglevel error
echo "  [3/4] 4K EN+JA+FR multi-audio MKV created"

# Anime show episode: 1080p, EN + JA
ffmpeg -y -f lavfi -i "color=c=purple:s=1920x1080:r=24:d=5" \
  -f lavfi -i "sine=frequency=440:duration=5" \
  -f lavfi -i "sine=frequency=880:duration=5" \
  -map 0:v -map 1:a -map 2:a \
  -metadata:s:a:0 language=eng \
  -metadata:s:a:1 language=jpn \
  -c:v libx264 -preset ultrafast -crf 40 \
  -c:a aac \
  "$MEDIA_DIR/tv/Anime Show (2023)/Season 01/Anime.Show.S01E01.1080p.mkv" \
  -loglevel error
echo "  [4/4] TV episode (dual-audio) MKV created"

echo ""
echo "Creating placeholder poster images..."

export MEDIA_DIR_PY="$MEDIA_DIR"
python3 - <<'PYEOF'
import os, sys
try:
    from PIL import Image, ImageDraw
except ImportError:
    print("  Pillow not available — skipping posters (pip install Pillow to enable)")
    sys.exit(0)

MEDIA_DIR = os.environ["MEDIA_DIR_PY"]
posters = [
    (f"{MEDIA_DIR}/movies/Single Audio Movie (2020)", "#1a237e", "Single Audio\nMovie (2020)"),
    (f"{MEDIA_DIR}/movies/Dual Audio Movie (2021)", "#1b5e20", "Dual Audio\nMovie (2021)"),
    (f"{MEDIA_DIR}/movies/Multi Audio Movie (2022)", "#b71c1c", "Multi Audio\nMovie (2022)"),
    (f"{MEDIA_DIR}/tv/Anime Show (2023)", "#4a148c", "Anime Show\n(2023)"),
]
for folder, color, label in posters:
    img = Image.new("RGB", (400, 600), color)
    draw = ImageDraw.Draw(img)
    draw.text((200, 300), label, fill="white", anchor="mm")
    path = os.path.join(folder, "poster.jpg")
    img.save(path, "JPEG", quality=85)
    print(f"  Poster: {path}")
PYEOF

echo ""
echo "Dev media ready at: $MEDIA_DIR"
echo ""
find "$MEDIA_DIR" -type f | sort
