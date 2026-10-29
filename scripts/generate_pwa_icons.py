#!/usr/bin/env python3
"""Generate PWA and Apple Touch Icon assets for 瘋狗流運彩決策台."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

def generate_icon(size: int = 512) -> Image.Image:
    # 1. Base canvas with dark modern aesthetic
    img = Image.new("RGBA", (size, size), color=(14, 17, 26, 255))
    draw = ImageDraw.Draw(img)

    margin = int(size * 0.06)
    corner_radius = int(size * 0.22)
    
    # 2. Rounded rectangle with gradient feel
    # Draw outer glow/border
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=corner_radius,
        fill=(22, 26, 42, 255),
        outline=(255, 110, 40, 255),
        width=max(2, int(size * 0.02)),
    )
    
    # Inner decorative subtle ring
    inner_margin = margin + int(size * 0.035)
    draw.rounded_rectangle(
        [inner_margin, inner_margin, size - inner_margin, size - inner_margin],
        radius=int(corner_radius * 0.85),
        fill=None,
        outline=(255, 75, 75, 80),
        width=max(1, int(size * 0.01)),
    )

    # 3. Text & Emblem
    font_dog = None
    font_sub = None
    
    try:
        font_dog = ImageFont.truetype(r"C:\Windows\Fonts\msjh.ttc", int(size * 0.32))
        font_sub = ImageFont.truetype(r"C:\Windows\Fonts\msjh.ttc", int(size * 0.12))
    except Exception:
        try:
            font_dog = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", int(size * 0.30))
            font_sub = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", int(size * 0.12))
        except Exception:
            font_dog = ImageFont.load_default()
            font_sub = ImageFont.load_default()

    # Draw main text: 瘋狗
    main_text = "瘋狗"
    bbox_main = draw.textbbox((0, 0), main_text, font=font_dog)
    w_main = bbox_main[2] - bbox_main[0]
    h_main = bbox_main[3] - bbox_main[1]
    x_main = (size - w_main) // 2
    y_main = int(size * 0.22)

    # Gradient-style shadow & highlight
    draw.text((x_main + 2, y_main + 3), main_text, font=font_dog, fill=(180, 40, 0, 180))
    draw.text((x_main, y_main), main_text, font=font_dog, fill=(255, 145, 0, 255))

    # Badge pill for "PARLAY" / "高倍串關"
    pill_w = int(size * 0.62)
    pill_h = int(size * 0.16)
    pill_x1 = (size - pill_w) // 2
    pill_y1 = int(size * 0.62)
    pill_x2 = pill_x1 + pill_w
    pill_y2 = pill_y1 + pill_h
    draw.rounded_rectangle(
        [pill_x1, pill_y1, pill_x2, pill_y2],
        radius=int(pill_h * 0.4),
        fill=(255, 75, 75, 230),
        outline=(255, 200, 100, 255),
        width=max(1, int(size * 0.01)),
    )

    sub_text = "運彩決策台"
    bbox_sub = draw.textbbox((0, 0), sub_text, font=font_sub)
    w_sub = bbox_sub[2] - bbox_sub[0]
    h_sub = bbox_sub[3] - bbox_sub[1]
    x_sub = (size - w_sub) // 2
    y_sub = pill_y1 + (pill_h - h_sub) // 2 - int(size * 0.015)
    draw.text((x_sub, y_sub), sub_text, font=font_sub, fill=(255, 255, 255, 255))

    return img

def main():
    img_512 = generate_icon(512)
    img_512.save(STATIC_DIR / "icon-512.png", format="PNG")
    
    img_192 = img_512.resize((192, 192), Image.Resampling.LANCZOS)
    img_192.save(STATIC_DIR / "icon-192.png", format="PNG")

    img_180 = img_512.resize((180, 180), Image.Resampling.LANCZOS)
    img_180.save(STATIC_DIR / "apple-touch-icon.png", format="PNG")

    img_32 = img_512.resize((32, 32), Image.Resampling.LANCZOS)
    img_32.save(STATIC_DIR / "favicon.png", format="PNG")

    print(f"Generated icons in {STATIC_DIR}:")
    for f in STATIC_DIR.glob("*.png"):
        print(f" - {f.name} ({f.stat().st_size} bytes)")

if __name__ == "__main__":
    main()
