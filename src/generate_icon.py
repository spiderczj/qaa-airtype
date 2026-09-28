"""
生成应用程序图标

输出：
  assets/icon.png     高分辨率源图（默认 1024x1024）
  assets/icon.ico     多尺寸 Windows 图标（保留，跨平台用）
  assets/icon.iconset  iconutil 需要的分尺寸 PNG
  assets/icon.icns    macOS 图标（仅 macOS 上生成）
"""
import os
import shutil
import subprocess
import sys
from PIL import Image, ImageDraw

# 所有坐标基于 BASE=256 设计，渲染时按 size/BASE 等比放大
BASE = 256

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(PROJECT_ROOT, 'assets')

# iconutil 要求的完整尺寸表（名字里的 @2x 表示 Retina 用的 2 倍图）
ICNS_SIZES = [
    ('icon_16x16.png', 16), ('icon_16x16@2x.png', 32),
    ('icon_32x32.png', 32), ('icon_32x32@2x.png', 64),
    ('icon_128x128.png', 128), ('icon_128x128@2x.png', 256),
    ('icon_256x256.png', 256), ('icon_256x256@2x.png', 512),
    ('icon_512x512.png', 512), ('icon_512x512@2x.png', 1024),
]


def _draw_icon(size: int) -> Image.Image:
    s = size / BASE
    img = Image.new('RGB', (size, size), color='#007AFF')
    draw = ImageDraw.Draw(img)

    # 圆角矩形背景
    margin = int(20 * s)
    draw.rounded_rectangle(
        [(margin, margin), (size - margin, size - margin)],
        radius=int(30 * s),
        fill='#007AFF'
    )

    key_color = 'white'
    key_margin = 50 * s
    key_height = 25 * s
    key_spacing = 10 * s
    key_width = 30 * s

    # 键盘：三行各 5 个键
    y = 60 * s
    for _row in range(3):
        for i in range(5):
            x = key_margin + i * (key_width + key_spacing)
            draw.rounded_rectangle(
                [(x, y), (x + key_width, y + key_height)],
                radius=int(5 * s),
                fill=key_color
            )
        y += key_height + key_spacing

    # 手机
    phone_width = 50 * s
    phone_height = 80 * s
    phone_x = size / 2 - phone_width / 2
    phone_y = 150 * s

    draw.rounded_rectangle(
        [(phone_x, phone_y), (phone_x + phone_width, phone_y + phone_height)],
        radius=int(8 * s),
        fill='white',
        outline='white',
        width=max(1, int(2 * s))
    )

    screen_margin = 5 * s
    draw.rounded_rectangle(
        [(phone_x + screen_margin, phone_y + screen_margin),
         (phone_x + phone_width - screen_margin,
          phone_y + phone_height - screen_margin - 10 * s)],
        radius=int(5 * s),
        fill='#E8F4FF'
    )

    # 箭头：从手机指向上方键盘
    arrow_x = size / 2
    arrow_y1 = phone_y - 10 * s
    arrow_y2 = y + key_height + 15 * s
    draw.line([(arrow_x, arrow_y1), (arrow_x, arrow_y2)],
              fill='white', width=max(2, int(4 * s)))

    arrow_size = 10 * s
    draw.polygon([
        (arrow_x, arrow_y2),
        (arrow_x - arrow_size, arrow_y2 + arrow_size),
        (arrow_x + arrow_size, arrow_y2 + arrow_size)
    ], fill='white')

    return img


def _build_icns(img: Image.Image):
    """把源图切成 iconset 并用 iconutil 打成 .icns（仅 macOS 有 iconutil）"""
    if sys.platform != 'darwin':
        print("跳过 icon.icns：iconutil 仅 macOS 提供")
        return

    iconset = os.path.join(ASSETS_DIR, 'icon.iconset')
    if os.path.isdir(iconset):
        shutil.rmtree(iconset)
    os.makedirs(iconset)

    for name, size in ICNS_SIZES:
        img.resize((size, size), Image.LANCZOS).save(
            os.path.join(iconset, name), 'PNG')

    icns_path = os.path.join(ASSETS_DIR, 'icon.icns')
    result = subprocess.run(
        ['iconutil', '-c', 'icns', iconset, '-o', icns_path],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"iconutil 失败: {result.stderr.strip()}")
    print(f"macOS 图标已生成: {icns_path}")


def create_icon(size: int = 1024):
    os.makedirs(ASSETS_DIR, exist_ok=True)

    img = _draw_icon(size)
    png_path = os.path.join(ASSETS_DIR, 'icon.png')
    img.save(png_path, 'PNG')
    print(f"图标已生成: {png_path} ({size}x{size})")

    ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    ico_path = os.path.join(ASSETS_DIR, 'icon.ico')
    img.save(ico_path, format='ICO', sizes=ico_sizes)
    print(f"Windows 图标已生成: {ico_path}")

    _build_icns(img)


if __name__ == '__main__':
    create_icon()
