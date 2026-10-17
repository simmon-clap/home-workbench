#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从米家分区图截图里提取房间轮廓（离线工具，非运行时代码）

依据：docs/spec/10-开发计划-v1.2 §P7（空间结构来源）· data/plan-vacuum-map.md
用途：网络隔离期间先把"扫地机扫出来的空间结构"拿到手 —— 这条路径用的是**它自己的扫描结果**
      （米家 App 显示的分区图就是它的建图输出），等网络通了再换成机器人原始地图数据。

做法：颜色分类 → 栅格化投票 → 取最大连通块 → 边界跟踪 → 多边形简化
输出：data/floorplan.json（归一化坐标 + 面积占比 + 来源标注）

用法：python3 tools/floorplan_from_shot.py [截图路径]
     （需要 Pillow；用 DSH 自带解释器运行）
"""
import json
import os
import sys
from collections import Counter, deque

from PIL import Image

# 实验脚本：多包了一层目录（tools/experimental/），所以往上数三层
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHOT = os.path.join(ROOT, 'data', 'reference', '米家-分区地图.webp')
OUT = os.path.join(ROOT, 'data', 'floorplan.json')
CELL = 6                                   # 栅格边长（像素）：6 精度最好（12 会把小房间和墙一起磨掉，实测）

# 米家分区图的房间配色（从截图里量出来的）
PALETTE = {
    'teal':   (80, 160, 160),      # 客厅 / 房间5
    'teal2':  (96, 150, 168),
    'olive':  (180, 150, 66),      # 房间1 / 房间2 / 房间3
    'orange': (186, 122, 84),      # 厨房 / 房间8
    # 注：截图底部的蓝色"开始"按钮与深蓝区域颜色接近，**不收进来**（避免把 UI 当房间）
}
TOL = 46                                    # 颜色容差


def classify(rgb):
    best, bd = None, 10 ** 9
    for name, ref in PALETTE.items():
        d = sum((a - b) ** 2 for a, b in zip(rgb, ref))
        if d < bd:
            best, bd = name, d
    return best if bd <= TOL * TOL * 3 else None


def grid_of(im):
    w, h = im.size
    px = im.load()
    gw, gh = w // CELL, h // CELL
    g = [[None] * gw for _ in range(gh)]
    for gy in range(gh):
        for gx in range(gw):
            c = Counter()
            for y in range(gy * CELL, gy * CELL + CELL, 2):
                for x in range(gx * CELL, gx * CELL + CELL, 2):
                    k = classify(px[x, y])
                    if k:
                        c[k] += 1
            if c:
                k, n = c.most_common(1)[0]
                if n >= (CELL * CELL) // 8:          # 该格至少有一定占比才算
                    g[gy][gx] = k
    return g


def smooth(g):
    """3×3 多数平滑：去掉逐格锯齿，让边界能合并成整段直墙（否则画出来是一片碎墙）。"""
    gh, gw = len(g), len(g[0])
    out = [[None] * gw for _ in range(gh)]
    for y in range(gh):
        for x in range(gw):
            c = Counter()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < gh and 0 <= nx < gw and g[ny][nx]:
                        c[g[ny][nx]] += 1
            out[y][x] = c.most_common(1)[0][0] if c and c.most_common(1)[0][1] >= 5 else None
    return out


def all_blobs(g, kind, min_cells=120):
    """同色的多个房间是分开的连通块，**全部取出来**（只取最大块会把厨房之类漏掉）。"""
    gh, gw = len(g), len(g[0])
    seen = [[False] * gw for _ in range(gh)]
    out = []
    for y in range(gh):
        for x in range(gw):
            if g[y][x] != kind or seen[y][x]:
                continue
            q, blob = deque([(x, y)]), []
            seen[y][x] = True
            while q:
                cx, cy = q.popleft()
                blob.append((cx, cy))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < gw and 0 <= ny < gh and not seen[ny][nx] and g[ny][nx] == kind:
                        seen[ny][nx] = True
                        q.append((nx, ny))
            if len(blob) >= min_cells:
                out.append(blob)
    return out


def runs(cells):
    """把格集合并成水平行条：[[gx, gy, 宽, 高], ...]（同宽的相邻行合并）"""
    rows = {}
    for (x, y) in cells:
        rows.setdefault(y, []).append(x)
    bars = []
    for y in sorted(rows):
        xs = sorted(rows[y])
        start = prev = xs[0]
        for x in xs[1:]:
            if x == prev + 1:
                prev = x
                continue
            bars.append([start, y, prev - start + 1, 1])
            start = prev = x
        bars.append([start, y, prev - start + 1, 1])
    # 竖向合并：同 x、同宽、上下相邻的行条并成一条
    merged = []
    for b in sorted(bars, key=lambda v: (v[0], v[1])):
        hit = None
        for m in merged:
            if m[0] == b[0] and m[2] == b[2] and m[1] + m[3] == b[1]:
                hit = m
                break
        if hit:
            hit[3] += 1
        else:
            merged.append(list(b))
    return merged


def rect_outline(cells):
    """轴对齐边界走线：户型图本来就是直角的，比通用轮廓跟踪稳得多。

    做法：每格取 4 条边；被两格共用的边是内部边，成对消掉；剩下的边自然围成一圈。
    """
    edges = {}
    for (x, y) in cells:
        for a, b in (((x, y), (x + 1, y)), ((x + 1, y), (x + 1, y + 1)),
                     ((x + 1, y + 1), (x, y + 1)), ((x, y + 1), (x, y))):
            edges[frozenset((a, b))] = edges.get(frozenset((a, b)), 0) + 1
    border = [e for e, n in edges.items() if n == 1]
    if not border:
        return []
    # 把边界边串成环（每点最多两条边界边）
    adj = {}
    for e in border:
        a, b = tuple(e)
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    start = min(adj, key=lambda p: (p[1], p[0]))
    loop, prev, cur = [start], None, start
    for _ in range(10000):
        nxts = [n for n in adj[cur] if n != prev]
        if not nxts:
            break
        nxt = nxts[0]
        loop.append(nxt)
        prev, cur = cur, nxt
        if cur == start:
            break
    # 去掉共线点
    out = []
    for i, p in enumerate(loop):
        a = loop[i - 1]
        b = loop[(i + 1) % len(loop)]
        if (a[0] == p[0] == b[0]) or (a[1] == p[1] == b[1]):
            continue
        out.append(p)
    return out


def main():
    shot = sys.argv[1] if len(sys.argv) > 1 else SHOT
    im = Image.open(shot).convert('RGB')
    g = grid_of(im)          # 平滑会磨掉细节（12px+3×3 平滑把墙和小房间都吃掉），暂不启用
    gh, gw = len(g), len(g[0])
    total = sum(1 for row in g for v in row if v)

    rooms, order = [], ['teal', 'teal2', 'olive', 'orange']
    for kind in order:
        for blob in all_blobs(g, kind):
            cells = set(blob)
            rects = runs(cells)
            edges = {}
            for (x, y) in cells:
                for a, b in (((x, y), (x + 1, y)), ((x + 1, y), (x + 1, y + 1)),
                             ((x + 1, y + 1), (x, y + 1)), ((x, y + 1), (x, y))):
                    edges[frozenset((a, b))] = edges.get(frozenset((a, b)), 0) + 1
            border = [[list(a), list(b)] for e, n in edges.items() if n == 1
                      for a, b in [tuple(e)]]
            xs = [c[0] for c in cells]
            ys = [c[1] for c in cells]
            rooms.append({'kind': kind, 'cells': len(blob),
                          'share': round(len(blob) / max(total, 1), 3),
                          'center': [round(sum(xs) / len(xs) / gw, 4), round(sum(ys) / len(ys) / gh, 4)],
                          'bbox': [round(min(xs) / gw, 4), round(min(ys) / gh, 4),
                                   round((max(xs) + 1) / gw, 4), round((max(ys) + 1) / gh, 4)],
                          'rects': rects, 'edges': border})

    # 剔除 UI：贴底或过矮的块（底部按钮条）
    # 剔 UI：地图只占截图中间一条横带（0.35–0.62），底部按钮区不在这个范围内
    rooms = [r for r in rooms if 0.34 < (r['bbox'][1] + r['bbox'][3]) / 2 < 0.62
             and (r['bbox'][3] - r['bbox'][1]) > 0.015]
    # 归一化到地图包围盒：**以格坐标为准**（rects 是格坐标，bbox/center 是 0–1，别混用）
    if rooms:
        gxs = [rx for r in rooms for rx, _, rw, _ in r['rects']]
        gys = [ry for r in rooms for _, ry, _, rh in r['rects']]
        gxe = [rx + rw for r in rooms for rx, _, rw, _ in r['rects']]
        gye = [ry + rh for r in rooms for _, ry, _, rh in r['rects']]
        gx0, gy0 = min(gxs), min(gys)
        sx = (max(gxe) - gx0) or 1
        sy = (max(gye) - gy0) or 1
        for r in rooms:
            r['rects'] = [[round((rx - gx0) / sx, 4), round((ry - gy0) / sy, 4),
                           round(rw / sx, 4), round(rh / sy, 4)] for rx, ry, rw, rh in r['rects']]
            r['edges'] = [[[round((a[0] - gx0) / sx, 4), round((a[1] - gy0) / sy, 4)],
                           [round((b[0] - gx0) / sx, 4), round((b[1] - gy0) / sy, 4)]]
                          for a, b in r['edges']]
            rs = r['rects']
            bx0 = min(x for x, _, _, _ in rs); by0 = min(y for _, y, _, _ in rs)
            bx1 = max(x + w for x, _, w, _ in rs); by1 = max(y + h for _, y, _, h in rs)
            r['bbox'] = [round(bx0, 4), round(by0, 4), round(bx1, 4), round(by1, 4)]
            r['center'] = [round((bx0 + bx1) / 2, 4), round((by0 + by1) / 2, 4)]

    # 按位置给名字（**推断**：与米家截图上的标签位置对应；网络恢复后用原始地图替换）
    def name_of(r):
        cx, cy = r['center']
        if r['share'] > 0.30: return '客厅'
        if cx < 0.25 and cy > 0.5: return '房间2'
        if cy < 0.15: return '房间1'
        if cx > 0.75 and cy < 0.35: return '房间3'
        if cx > 0.75: return '房间8'
        if cx < 0.2 and cy < 0.5: return '房间5'
        return '未命名分区'
    used = {}
    for r in rooms:
        nm = name_of(r)
        used[nm] = used.get(nm, 0) + 1
        # 重名的分区加序号：否则设置页里没法区分（两块都叫"房间8"无法映射）
        r['name'] = nm if used[nm] == 1 else f'{nm}-{used[nm]}'
        r['name_source'] = '按截图标签位置推断'

    doc = {'source': '米家 App 分区图截图（扫地机建图输出）',
           'source_file': os.path.relpath(shot, ROOT),
           'note': '房间名待与机器人原始地图对齐；此处只提取几何。网络恢复后改用原始地图数据。',
           'grid': {'cols': gw, 'rows': gh, 'cell_px': CELL},
           'rooms': rooms}
    json.dump(doc, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'✅ 提取到 {len(rooms)} 块区域 → {os.path.relpath(OUT, ROOT)}')
    for r in rooms:
        print(f"   {r['kind']:7s} 格数 {r['cells']:5d} 占比 {r['share']:.2f} 行条 {len(r['rects']):3d} "
              f"边界 {len(r['edges']):4d} 中心 {r['center']} bbox {r['bbox']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
