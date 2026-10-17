#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成 PWA 图标（192 / 512）

依据：docs/spec/02-视觉规范 v1.1（暖白底 + 陶土主色）· 11-代码规范 v1.1
用途：iPhone / iPad「添加到主屏幕」后的图标。
用法：python3 tools/make_icons.py
"""
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'app', 'web')
BG = (253, 251, 247)        # --hm-paper
INK = (192, 113, 63)        # --hm-warm
FONTS = ['/System/Library/Fonts/PingFang.ttc', '/System/Library/Fonts/STHeiti Medium.ttc',
         '/Library/Fonts/Arial Unicode.ttf']


def render(size):
    img = Image.new('RGB', (size, size), BG)
    d = ImageDraw.Draw(img)
    # 圆角底（iOS 会自己裁，但留一点内缩更稳）
    pad = int(size * 0.06)
    d.rounded_rectangle([pad, pad, size - pad, size - pad], radius=int(size * 0.22),
                        outline=(233, 225, 214), width=max(1, size // 128))
    font = None
    for f in FONTS:
        if os.path.exists(f):
            try:
                font = ImageFont.truetype(f, int(size * 0.52))
                break
            except OSError:
                continue
    text = '家'
    if font:
        box = d.textbbox((0, 0), text, font=font)
        d.text(((size - (box[2] - box[0])) / 2 - box[0], (size - (box[3] - box[1])) / 2 - box[1]),
               text, font=font, fill=INK)
    else:                                   # 没有中文字体就画一个圆，绝不糊
        d.ellipse([size * 0.3, size * 0.3, size * 0.7, size * 0.7], outline=INK, width=size // 24)
    return img


def main():
    for s in (192, 512):
        p = os.path.join(OUT, f'icon-{s}.png')
        render(s).save(p)
        print(f'✅ {os.path.relpath(p, ROOT)}')
    # 512 再导一张 180（iOS apple-touch-icon）
    p = os.path.join(OUT, 'apple-touch-icon.png')
    render(180).save(p)
    print(f'✅ {os.path.relpath(p, ROOT)}')


if __name__ == '__main__':
    main()
