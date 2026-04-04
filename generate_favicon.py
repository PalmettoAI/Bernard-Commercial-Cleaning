"""Generate PNG/ICO favicons for Bernard Commercial Cleaning.

Run this script once locally, then push the 4 generated files manually:
  favicon.ico, favicon-32x32.png, favicon-192x192.png, apple-touch-icon.png

Requires a GitHub classic PAT with repo scope (the fine-grained PAT used
during setup does not have binary file write access via the git push path).

Usage:
  pip install Pillow
  python3 generate_favicon.py
  git add favicon.ico favicon-32x32.png favicon-192x192.png apple-touch-icon.png
  git commit -m 'feat: add binary favicon files'
  git push
"""
from PIL import Image, ImageDraw, ImageFont
import struct, os

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
BG_COLOR   = "#1a6dff"
FG_COLOR   = "#ffffff"
LETTERS    = "BC"

def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def make_base(size):
    img = Image.new("RGBA", (size, size), hex_to_rgb(BG_COLOR) + (255,))
    draw = ImageDraw.Draw(img)
    font = None
    font_size = int(size * 0.42)
    for path in [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]:
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, font_size)
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), LETTERS, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - w) / 2 - bbox[0]
    y = (size - h) / 2 - bbox[1]
    draw.text((x, y), LETTERS, fill=hex_to_rgb(FG_COLOR) + (255,), font=font)
    return img

def save_ico(images, path):
    num = len(images)
    image_data = []
    for img in images:
        bmp = img.tobytes("raw", "BGRA")
        w, h = img.size
        header = struct.pack("<IIIHHIIIIII", 40, w, h*2, 1, 32, 0, len(bmp), 0, 0, 0, 0)
        image_data.append(header + bmp)
    offset = 6 + num * 16
    with open(path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, num))
        for i, img in enumerate(images):
            w, h = img.size
            f.write(struct.pack("<BBBBHHII",
                w if w < 256 else 0, h if h < 256 else 0,
                0, 0, 1, 32, len(image_data[i]), offset))
            offset += len(image_data[i])
        for data in image_data:
            f.write(data)

base = make_base(512)
save_ico([base.resize((s, s), Image.LANCZOS) for s in (16, 32, 48)], os.path.join(OUTPUT_DIR, "favicon.ico"))
base.resize((32, 32), Image.LANCZOS).save(os.path.join(OUTPUT_DIR, "favicon-32x32.png"))
base.resize((192, 192), Image.LANCZOS).save(os.path.join(OUTPUT_DIR, "favicon-192x192.png"))
base.resize((180, 180), Image.LANCZOS).save(os.path.join(OUTPUT_DIR, "apple-touch-icon.png"))
print("Done. Now push the 4 favicon files with a classic PAT.")
