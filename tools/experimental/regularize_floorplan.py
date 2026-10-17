#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
边界正规化：把像素级锯齿边界，变成"横平竖直的整段墙"

为什么需要：从截图提取的边界是逐格锯齿，直接挤墙会得到一片碎墙板（2026-10-17 实测）。
做法：
  1) 统计**主导墙线**：对每个房间的格集合，分别统计 x（竖线）与 y（横线）方向的出现次数，
     峰值就是真正的墙所在的位置（长墙出现次数多，锯齿只出现一两次）
  2) 把相邻近的墙线合并（容差内视为同一条）
  3) 按"墙线网格"重建房间：两线之间的矩形区域里，原格多数属于本房间就保留

输出：rooms[].rects / rooms[].edges（整段墙），坐标仍是 0–1 归一化。
用法：python3 tools/regularize_floorplan.py [--in data/floorplan.json] [--out 同文件]
"""
import argparse
import json
import os
from collections import Counter

# 实验脚本：多包了一层目录（tools/experimental/），所以往上数三层
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT = os.path.join(ROOT, 'data', 'floorplan.json')


def dominant_lines(cells, gw, gh, axis, peak_ratio=0.22, tol=2):
    """找主导墙线。axis=0 竖线（看 x），axis=1 横线（看 y）。"""
    hist = Counter()
    for (x, y) in cells:
        hist[x if axis == 0 else y] += 1
    if not hist:
        return []
    hi = max(hist.values())
    peaks = sorted(v for v, n in hist.items() if n >= hi * peak_ratio)
    merged = []
    for v in peaks:
        if merged and v - merged[-1][-1] <= tol:
            merged[-1].append(v)
        else:
            merged.append([v])
    # 每个簇取加权中心
    out = []
    for grp in merged:
        wsum = sum(hist[v] for v in grp)
        out.append(round(sum(v * hist[v] for v in grp) / wsum, 3))
    # 两端补上房间的外边界，保证闭合
    mn, mx = min(hist), max(hist) + 1
    if not out or out[0] > mn:
        out.insert(0, mn)
    if not out or out[-1] < mx:
        out.append(mx)
    return out


def rebuild(room, gw, gh):
    cells = set()
    for rx, ry, rw, rh in room['_grid_rects']:
        for x in range(int(rx), int(rx + rw)):
            for y in range(int(ry), int(ry + rh)):
                cells.add((x, y))
    if not cells:
        return room
    xs = dominant_lines(cells, gw, gh, 0)
    ys = dominant_lines(cells, gw, gh, 1)
    rects = []
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            x0, x1, y0, y1 = xs[i], xs[i + 1], ys[j], ys[j + 1]
            if x1 - x0 < 1 or y1 - y0 < 1:
                continue
            inside = total = 0
            for x in range(int(x0), int(x1)):
                for y in range(int(y0), int(y1)):
                    total += 1
                    if (x, y) in cells:
                        inside += 1
            if total and inside / total >= 0.5:            # 多数在，保留
                rects.append([x0, y0, x1 - x0, y1 - y0])
    room['_grid_rects'] = rects
    room['_regularized'] = True
    return room


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='src', default=DEFAULT)
    ap.add_argument('--out', dest='dst', default=DEFAULT)
    a = ap.parse_args()
    doc = json.load(open(a.src, encoding='utf-8'))
    gw = doc['grid']['cols']
    gh = doc['grid']['rows']

    # 从归一化 rects 还原回格坐标（工具间用格坐标交接更稳）
    for r in doc['rooms']:
        r['_grid_rects'] = [[rx * gw, ry * gh, rw * gw, rh * gh] for rx, ry, rw, rh in r['rects']]

    for r in doc['rooms']:
        before = len(r['_grid_rects'])
        rebuild(r, gw, gh)
        r['rects'] = [[round(x / gw, 4), round(y / gh, 4), round(w / gw, 4), round(h / gh, 4)]
                      for x, y, w, h in r['_grid_rects']]
        # 边界：从规整后的矩形重新算（这样墙是整段直线）
        edges = {}
        for x, y, w, h in r['_grid_rects']:
            x, y, w, h = int(x), int(y), int(w), int(h)
            for (cx, cy) in ((x, y),):
                pass
            for xx in range(x, x + w):
                for yy in range(y, y + h):
                    for p, q in (((xx, yy), (xx + 1, yy)), ((xx + 1, yy), (xx + 1, yy + 1)),
                                 ((xx + 1, yy + 1), (xx, yy + 1)), ((xx, yy + 1), (xx, yy))):
                        edges[frozenset((p, q))] = edges.get(frozenset((p, q)), 0) + 1
        border = [tuple(e) for e, n in edges.items() if n == 1]
        r['edges'] = [[[round(p[0] / gw, 4), round(p[1] / gh, 4)] for p in e] for e in border]
        del r['_grid_rects']
        r.pop('_regularized', None)
        print(f"   {r.get('name', r['kind']):6s} 行条 {before:3d} → {len(r['rects']):3d} · 边界 {len(r['edges']):4d}")

    doc['regularized'] = True
    doc['regularize_note'] = '按主导墙线重建：墙是整段直线，不再是逐格锯齿'
    json.dump(doc, open(a.dst, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'✅ 已正规化 → {os.path.relpath(a.dst, ROOT)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
