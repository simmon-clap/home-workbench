#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RoomPlan 扫描 → 归一化真实几何 + 俯视平面 + 静态 3D 背景对照页。
依据：02 §13 空间视图（iso 正投影 / 暖白纸底 / --line 描边 / 静态 SVG，不用写实材质）
      11 §13 已声明生成物（离线生成 / 同目录 *.build.md / ≤1.5MB / 运行期零第三方 / 非唯一真相源）
本文件不做：等距渲染器（由 app/prototype/scan-room-editor/build-room.mjs 那条线负责）、
            实时数据、可编辑交互、写实材质、渐变光效（scan-room.html 仅作静态背景对照）。
输入：data/3d/scans/<name>.json（OpenPlan3D/RoomPlan 导出，单位 cm）
输出：data/3d/rooms/<name>.json（归一化几何，m，schema=scan_room/v2；可读可替换）
      data/3d/rooms/<name>.plan.svg（俯视平面，带尺寸）
      app/web/space/scan-room.html（静态背景对照页，读取 data/3d/rooms/*.json 重建）
schema v1 → v2（只增不改）：新增 schema / source_file / bounds / rooms / floor / pending，
openings[].type，furniture[].catalog / arms，meta.floors_raw；其余字段名、单位（m）与数值不变。
用法：python3 tools/scan_room.py "客厅餐厅-20261017"
      python3 tools/scan_room.py --all        # 只按已有 rooms/*.json 重建对照页
"""
import argparse
import glob
import json
import math
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCANS = os.path.join(ROOT, 'data', '3d', 'scans')
ROOMS = os.path.join(ROOT, 'data', '3d', 'rooms')
WEB = os.path.join(ROOT, 'app', 'web', 'space')
SCHEMA = 'scan_room/v2'
LABEL = {'sofa': '沙发', 'table': '餐桌', 'chair': '椅子', 'cabinet': '柜子',
         'tv': '电视', 'bed': '床', 'other': '其他'}
NAME_MAP = {'Living Room': '客厅', 'Dining Room': '餐厅', 'Bedroom': '卧室', 'Kitchen': '厨房',
            'Bathroom': '卫生间', 'Office': '书房', 'Study': '书房', 'Balcony': '阳台'}
BRAND = dict(wall='#F6EBD9', wall_a='#E3D0B2', wall_b='#DCC7A6', line='#DDC8AC',
             floor='#F7EEDF', base='#EFE3D2', glass='#EAF1EE')
MAT = {'sofa': ('#F5EDE1', '#E8D7BF', '#DFCBAD'), 'table': ('#EFDCC0', '#DCC29B', '#D2B58C'),
       'chair': ('#F8F1E6', '#E8D7BF', '#DFCBAD'), 'cabinet': ('#EFE0C8', '#DCC29B', '#D2B58C'),
       'tv': ('#8A8175', '#7A7164', '#6E6659'), 'other': ('#EDE7DC', '#D3CABD', '#C9BFB1')}
SPX = 150.0
CUT = 0.55
COS30 = math.cos(math.pi / 6)
def cm(v):
    return round(float(v) / 100.0, 3)
def classify(f, attrs):
    a = attrs.get(f.get('id'), {}) if isinstance(attrs, dict) else {}
    if 'SofaType' in a:
        return 'sofa'
    if 'TableType' in a or 'TableShapeType' in a:
        return 'table'
    if 'ChairType' in a or 'ChairBackType' in a:
        return 'chair'
    if 'StorageType' in a:
        return 'cabinet'
    if f.get('depth', 0) < 20 and f.get('height', 0) > 90:
        return 'tv'
    return 'other'
# ---------- 二维几何（地面轮廓 / 房间多边形 / 缺口） ----------
def seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - x1 - t * dx, py - y1 - t * dy)
def sarea(pts):
    n = len(pts)
    return sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n)) / 2.0
def rdp(pts, eps):
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            d = seg_dist(pts[i][0], pts[i][1], pts[a][0], pts[a][1], pts[b][0], pts[b][1])
            if d > best:
                best, idx = d, i
        if best > eps:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]
def gap_closers(model):
    """RoomPlan 常把门洞留成墙体缺口；找出未闭合端点并虚拟闭合（不修改几何，只用于泛洪与提示）。"""
    ends = {}
    for w in model['walls']:
        for p in ((w['x1'], w['y1']), (w['x2'], w['y2'])):
            ends.setdefault((round(p[0], 2), round(p[1], 2)), []).append(w['id'])
    dangling = [p for p, ids in ends.items() if len(ids) == 1]
    shared = [p for p, ids in ends.items() if len(ids) > 1]
    pairs = []
    for i in range(len(dangling)):
        for j in range(i + 1, len(dangling)):
            d = math.hypot(dangling[i][0] - dangling[j][0], dangling[i][1] - dangling[j][1])
            if d < 1.6:
                pairs.append((d, i, j))
    pairs.sort()
    used, out = set(), []
    for _, i, j in pairs:
        if i in used or j in used:
            continue
        used.update((i, j))
        out.append((dangling[i], dangling[j]))
    for i, p in enumerate(dangling):
        if i in used:
            continue
        near = min(shared, key=lambda q: math.hypot(p[0] - q[0], p[1] - q[1])) if shared else None
        if near and math.hypot(p[0] - near[0], p[1] - near[1]) < 0.7:
            out.append((p, near))
    return out
def floor_mask(model, cell=0.05):
    """栅格 + 泛洪求室内区域（含缺口虚拟闭合）；返回 (占位集合, 原点, 格子尺寸)。"""
    xs = [w['x1'] for w in model['walls']] + [w['x2'] for w in model['walls']]
    ys = [w['y1'] for w in model['walls']] + [w['y2'] for w in model['walls']]
    minx, maxx = min(xs) - 0.3, max(xs) + 0.3
    miny, maxy = min(ys) - 0.3, max(ys) + 0.3
    nx, ny = int((maxx - minx) / cell) + 1, int((maxy - miny) / cell) + 1
    blocked = [[False] * ny for _ in range(nx)]
    def block(x1, y1, x2, y2, t):
        i0 = max(0, int((min(x1, x2) - t / 2 - minx) / cell))
        i1 = min(nx - 1, int((max(x1, x2) + t / 2 - minx) / cell) + 1)
        j0 = max(0, int((min(y1, y2) - t / 2 - miny) / cell))
        j1 = min(ny - 1, int((max(y1, y2) + t / 2 - miny) / cell) + 1)
        for i in range(i0, i1 + 1):
            cx = minx + (i + 0.5) * cell
            for j in range(j0, j1 + 1):
                if seg_dist(cx, miny + (j + 0.5) * cell, x1, y1, x2, y2) <= t / 2 + cell * 0.6:
                    blocked[i][j] = True
    for w in model['walls']:
        block(w['x1'], w['y1'], w['x2'], w['y2'], w['t'])
    for a, b in gap_closers(model):
        block(a[0], a[1], b[0], b[1], 0.12)
    seen = set()
    seeds = [(int((f['x'] - minx) / cell), int((f['y'] - miny) / cell)) for f in model['furniture']]
    seeds.append((int(((min(xs) + max(xs)) / 2 - minx) / cell), int(((min(ys) + max(ys)) / 2 - miny) / cell)))
    for seed in seeds:
        stack = [seed]
        while stack:
            i, j = stack.pop()
            if not (0 <= i < nx and 0 <= j < ny) or (i, j) in seen or blocked[i][j]:
                continue
            seen.add((i, j))
            stack += [(i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)]
    return seen, minx, miny, cell
def mask_polygon(seen, minx, miny, cell):
    """把泛洪区域的外边界连成多边形，再抽稀。方向不做保证（面积取绝对值）。"""
    q = lambda x, y: (round(x, 6), round(y, 6))
    edges = []
    for i, j in seen:
        x0, y0 = minx + i * cell, miny + j * cell
        if (i, j - 1) not in seen:
            edges.append((q(x0, y0), q(x0 + cell, y0)))
        if (i, j + 1) not in seen:
            edges.append((q(x0, y0 + cell), q(x0 + cell, y0 + cell)))
        if (i - 1, j) not in seen:
            edges.append((q(x0, y0), q(x0, y0 + cell)))
        if (i + 1, j) not in seen:
            edges.append((q(x0 + cell, y0), q(x0 + cell, y0 + cell)))
    nbr = {}
    for a, b in edges:
        nbr.setdefault(a, []).append(b)
        nbr.setdefault(b, []).append(a)
    loops, used = [], set()
    for a, b in edges:
        if (a, b) in used:
            continue
        used.update(((a, b), (b, a)))
        loop, prev, cur = [a, b], a, b
        while True:
            nxt = [p for p in nbr.get(cur, []) if p != prev and (cur, p) not in used]
            if not nxt:
                break
            p = nxt[0]
            used.update(((cur, p), (p, cur)))
            if p == loop[0]:
                break
            loop.append(p)
            prev, cur = cur, p
        if len(loop) > 3:
            loops.append(loop)
    if not loops: return []
    d, out = (lambda i: (pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])), []
    for pts in (p for p in loops if abs(sarea(p)) > 0.02):
        # 从边中间起步会留下首尾重复点；旋到最尖的拐角再按闭合环抽稀
        k = max(range(len(pts)), key=lambda i: abs(d(i)[0] * d((i + 1) % len(pts))[1]
                                                   - d(i)[1] * d((i + 1) % len(pts))[0]))
        pts = pts[k:] + pts[:k]
        simp = rdp(pts + [pts[0]], cell * 2.5)
        if len(simp) > 4:
            out.append(simp[:-1])
    return sorted(out, key=lambda p: -abs(sarea(p)))
def room_polygon(walls, ids):
    """把 rooms[].walls（墙 id 列表）按首尾相接拼成多边形；拼不上返回 None（扫描不完整）。"""
    segs = [w for w in walls if w['id'] in set(ids)]
    if len(segs) < 3:
        return None
    key = lambda p: (round(p[0], 2), round(p[1], 2))
    first = segs[0]
    pts, used, end = [(first['x1'], first['y1']), (first['x2'], first['y2'])], {first['id']}, (first['x2'], first['y2'])
    while len(used) < len(segs):
        nxt = None
        for s in segs:
            if s['id'] in used:
                continue
            if key((s['x1'], s['y1'])) == key(end):
                nxt, end = s, (s['x2'], s['y2']); pts.append(end); break
            if key((s['x2'], s['y2'])) == key(end):
                nxt, end = s, (s['x1'], s['y1']); pts.append(end); break
        if nxt is None:
            return None
        used.add(nxt['id'])
    if key(pts[0]) != key(pts[-1]):
        return None
    return pts[:-1] if len(pts) - 1 >= 3 else None
def build(raw_path):
    d = json.load(open(raw_path, encoding='utf-8'))
    floors = d.get('floors') or []
    floor = floors[0] if floors else {}
    attrs = (d.get('interchange') or {}).get('attributes') or {}
    walls = []
    for w in floor.get('walls') or []:
        x1, y1 = cm(w['start']['x']), cm(w['start']['y'])
        x2, y2 = cm(w['end']['x']), cm(w['end']['y'])
        L = math.hypot(x2 - x1, y2 - y1)
        walls.append({'id': w.get('id'), 'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2, 'length': round(L, 3),
                      't': cm(w.get('thickness', 15)), 'h': cm(w.get('height', 240)), 'openings': []})
    widx = {w['id']: w for w in walls}
    def attach(items, kind):
        for it in items or []:
            w = widx.get(it.get('wallId'))
            if not w:
                continue
            t = float(it.get('position', 0)) * w['length']
            width = cm(it.get('width', 80))
            w['openings'].append({
                'kind': kind, 'type': it.get('type'), 'start': round(max(0.0, t - width / 2), 3),
                'end': round(min(w['length'], t + width / 2), 3), 'width': width,
                'height': cm(it.get('height', 210)), 'sill': cm(it.get('sillHeight', 0)) if kind == 'window' else 0.0,
                'swing': it.get('swingDirection'), 'flip': bool(it.get('flipSide'))})
    attach(floor.get('doors'), 'door')
    attach(floor.get('windows'), 'window')
    furn = []
    for f in floor.get('furniture') or []:
        a = attrs.get(f.get('id'), {}) if isinstance(attrs, dict) else {}
        k = classify(f, attrs)
        pos = f.get('position') or {}
        furn.append({'id': f.get('id'), 'kind': k, 'label': LABEL.get(k, '其他'),
                     'x': cm(pos.get('x', 0)), 'y': cm(pos.get('y', 0)),
                     'rot': round(float(f.get('rotation', 0) or 0), 1),
                     'w': cm(f.get('width', 0)), 'd': cm(f.get('depth', 0)), 'h': cm(f.get('height', 0)),
                     'catalog': f.get('catalogId'), 'arms': bool(a.get('ChairArmType') == 'existing')})
    model = {'schema': SCHEMA, 'source': 'Room Capture（OpenPlan3D/RoomPlan）· %s' % os.path.basename(raw_path),
             'source_file': os.path.basename(raw_path), 'units': 'm',
             'wall_height': max((w['h'] for w in walls), default=2.4),
             'walls': walls, 'furniture': furn, 'room_labels': [],
             'meta': {'project': d.get('name'), 'created': d.get('createdAt'), 'floors_raw': len(floors)}}
    xs = [w['x1'] for w in walls] + [w['x2'] for w in walls]
    ys = [w['y1'] for w in walls] + [w['y2'] for w in walls]
    model['bounds'] = {'min_x': round(min(xs), 3), 'min_y': round(min(ys), 3),
                       'max_x': round(max(xs), 3), 'max_y': round(max(ys), 3)}  # noqa: E501
    rooms = []
    for r in floor.get('rooms') or []:
        poly = room_polygon(walls, r.get('walls') or [])
        rooms.append({'id': r.get('id'), 'name_raw': r.get('name'),
                      'name': NAME_MAP.get(r.get('name'), r.get('name') or '房间'),
                      'wall_ids': list(r.get('walls') or []),
                      'polygon': [[round(x, 3), round(y, 3)] for x, y in poly] if poly else None,
                      'area': round(abs(sarea(poly)), 2) if poly else (round(float(r.get('area') or 0), 2) or None)})
    seen, minx, miny, cell = floor_mask(model, 0.025); model['rooms'] = rooms
    polys = mask_polygon(seen, minx, miny, cell)
    model['floor'] = {'polygon': [[round(x, 3), round(y, 3)] for x, y in polys[0]] if polys else [],
                      'polygons': [[[round(x, 3), round(y, 3)] for x, y in p] for p in polys],
                      'area': round(sum(abs(sarea(p)) for p in polys), 2),
                      'gaps': [[[round(a[0], 3), round(a[1], 3)], [round(b[0], 3), round(b[1], 3)]]
                               for a, b in gap_closers(model)]}
    # 房间标签：有房间多边形就用中心；否则按家具推断（开放空间常见，命名待用户确认）
    labels = []
    for r in rooms:
        if r['polygon']:
            labels.append({'label': r['name'], 'x': round(sum(p[0] for p in r['polygon']) / len(r['polygon']), 2),
                           'y': round(sum(p[1] for p in r['polygon']) / len(r['polygon']), 2)})
    if not labels:
        for k, lab in (('sofa', '客厅'), ('table', '餐厅')):
            cand = [x for x in furn if x['kind'] == k]
            if cand:
                labels.append({'label': lab, 'x': cand[0]['x'], 'y': cand[0]['y']})
    model['room_labels'] = labels
    model['pending'] = pending_items(model)
    return model
def pending_items(model):
    """把「必须用户确认、不许我们编」的问题显式落进产物（09 §1 真话优先）。"""
    items = []
    if not any(r['polygon'] for r in model['rooms']):
        items.append('分区位置：扫描的 RoomPlan rooms 没有各自墙体（rooms[].walls 为空），'
                     '客厅/餐厅按「沙发」「餐桌」家具位置推断，命名与照片对应关系需用户确认')
    gaps = model['floor'].get('gaps') or []
    if gaps:
        items.append('墙体有 %d 处未闭合缺口（平面图与数据里已标注，泛洪时按最近端点虚拟闭合）：'
                     '可能是门洞/落地窗未识别，需现场确认' % len(gaps))
    hs = sorted({w['h'] for w in model['walls']})
    if hs and hs[-1] - hs[0] > 0.05:
        items.append('墙高不一致（%s m）：扫描误差还是真实不同墙高，需确认' % ' / '.join('%.2f' % h for h in hs))
    nd = sum(1 for w in model['walls'] for o in w['openings'] if o['kind'] == 'door')
    nw = sum(1 for w in model['walls'] for o in w['openings'] if o['kind'] == 'window')
    items.append('门窗洞：%d 个门 + %d 个窗（位置/朝向/门后通向哪里、窗外是什么）需现场核对' % (nd, nw))
    for f in model['furniture']:
        if min(f['w'], f['d']) < 0.1 and f['h'] > 2.0:
            items.append('有一件 %.2f × %.2f × %.2f m 的「%s」横跨隔断/窗墙，形态可疑'
                         '（可能是窗帘、移门或立式柜），需确认' % (f['w'], f['d'], f['h'], f['label']))
    if model['meta'].get('floors_raw', 1) > 1:
        items.append('扫描含 %d 个楼层，当前只处理第 1 层' % model['meta']['floors_raw'])
    items.append('扫描方位：入户 / 阳台 / 走廊各在哪一面（当前按扫描坐标系摆放，未旋转）')
    return items
def metrics(model):
    b = model['bounds']
    return {'bbox_m': (round(b['max_x'] - b['min_x'], 2), round(b['max_y'] - b['min_y'], 2)),
            'wall_height_m': round(model['wall_height'], 2), 'walls': len(model['walls']),
            'openings': sum(len(w['openings']) for w in model['walls']),
            'furniture': len(model['furniture']), 'floor_area': model['floor']['area']}
def effective_model(rooms_dir, name):
    """基础几何 + .edited.json 家具覆盖（编辑器只改家具；其余字段以最新基础数据为准）。"""
    base = json.load(open(os.path.join(rooms_dir, name + '.json'), encoding='utf-8'))
    ep = os.path.join(rooms_dir, name + '.edited.json')
    if not os.path.exists(ep):
        return base
    ed = json.load(open(ep, encoding='utf-8'))
    if isinstance(ed.get('furniture'), list) and ed['furniture']:
        base['furniture'] = ed['furniture']
        base['edit_overlay'] = {'file': os.path.basename(ep), 'scope': 'furniture'}  # 只读合并：不改编辑器文件
    return base
# ---------- 俯视平面图 ----------
def plan_svg(model):
    xs, ys = [], []
    for w in model['walls']:
        xs += [w['x1'], w['x2']]
        ys += [w['y1'], w['y2']]
    for f in model['furniture']:
        xs += [f['x'] - f['w'] / 2, f['x'] + f['w'] / 2]
        ys += [f['y'] - f['d'] / 2, f['y'] + f['d'] / 2]
    minx, maxx = min(xs) - 0.6, max(xs) + 0.6
    miny, maxy = min(ys) - 0.6, max(ys) + 0.6
    S = 120
    W, H = (maxx - minx) * S, (maxy - miny) * S
    P = lambda x, y: ((x - minx) * S, (y - miny) * S)
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="%.0f" height="%.0f" viewBox="0 0 %.0f %.0f" '
           'font-family="-apple-system,PingFang SC,sans-serif">' % (W, H, W, H),
           '<rect width="100%" height="100%" fill="#FDFBF7"/>']
    COL = {'sofa': '#EADCC8', 'table': '#EFE0C8', 'chair': '#F3E9DC', 'cabinet': '#E4D2B8',
           'tv': '#7A7164', 'bed': '#EADCC8', 'other': '#E8E2D6'}
    for f in model['furniture']:
        cx, cy = P(f['x'], f['y'])
        w, d = f['w'] * S, f['d'] * S
        out.append('<g transform="translate(%.1f,%.1f) rotate(%.1f)">'
                   '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="%s" stroke="#D8C4A8" '
                   'stroke-width="1"/></g>' % (cx, cy, -f['rot'], -w / 2, -d / 2, w, d,
                                               COL.get(f['kind'], '#EEE')))
        out.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="12" fill="#6B6156" '
                   'font-weight="600">%s</text>' % (cx, cy + 4, f['label']))
    for w in model['walls']:
        L = w['length'] or 1
        ux, uy = (w['x2'] - w['x1']) / L, (w['y2'] - w['y1']) / L
        pos, segs = 0.0, []
        for o in sorted(w['openings'], key=lambda o: o['start']):
            if o['start'] > pos:
                segs.append((pos, o['start'], 'wall', None))
            segs.append((o['start'], o['end'], o['kind'], o))
            pos = max(pos, o['end'])
        if pos < L:
            segs.append((pos, L, 'wall', None))
        for a, b, kind, o in segs:
            p1 = (w['x1'] + ux * a, w['y1'] + uy * a)
            p2 = (w['x1'] + ux * b, w['y1'] + uy * b)
            if kind == 'wall':
                (ax, ay), (bx, by) = P(*p1), P(*p2)
                ddx, ddy = bx - ax, by - ay
                L2 = math.hypot(ddx, ddy) or 1e-6
                nx, ny = -ddy / L2 * w['t'] * S / 2, ddx / L2 * w['t'] * S / 2
                out.append('<polygon points="%s" fill="#4E463C" opacity="0.86"/>'
                           % ' '.join('%.1f,%.1f' % (x, y) for x, y in
                                      ((ax + nx, ay + ny), (bx + nx, by + ny), (bx - nx, by - ny), (ax - nx, ay - ny))))
            elif kind == 'window':
                (x1, y1), (x2, y2) = P(*p1), P(*p2)
                out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#8FB3C9" '
                           'stroke-width="%.1f"/>' % (x1, y1, x2, y2, max(2, w['t'] * S * 0.4)))
            else:
                (x1, y1), (x2, y2) = P(*p1), P(*p2)
                r = o['width'] * S
                out.append('<path d="M%.1f,%.1f A%.1f,%.1f 0 0 1 %.1f,%.1f" fill="none" stroke="#B98A3E" '
                           'stroke-width="1.5" stroke-dasharray="4 4" opacity="0.8"/>' % (x1, y1, r, r, x2, y2))
        mx, my = (w['x1'] + w['x2']) / 2, (w['y1'] + w['y2']) / 2
        px, py = P(mx, my)
        ang = math.degrees(math.atan2(w['y2'] - w['y1'], w['x2'] - w['x1']))
        ang = ang - 180 if ang > 90 else (ang + 180 if ang < -90 else ang)
        out.append('<text transform="translate(%.1f,%.1f) rotate(%.1f)" text-anchor="middle" '
                   'font-size="13" fill="#B4643A" dy="-6">%d cm</text>'
                   % (px, py, ang, round(w['length'] * 100)))
    for a, b in model['floor'].get('gaps') or []:
        (x1, y1), (x2, y2) = P(a[0], a[1]), P(b[0], b[1])
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#C9BFB1" stroke-width="1.4" '
                   'stroke-dasharray="5 5"/>' % (x1, y1, x2, y2))
    for lp in model.get('room_labels') or []:
        px, py = P(lp['x'], lp['y'])
        out.append('<text x="%.1f" y="%.1f" text-anchor="middle" font-size="20" font-weight="700" '
                   'fill="#C0713F" opacity="0.85">%s</text>' % (px, py, lp['label']))
    out.append('</svg>')
    return '\n'.join(out)
# ---------- 静态等距 3D（旧背景对照；等距产品渲染器不在这里） ----------
def iso_quad(p, fill, stroke=BRAND['line'], sw=0.9, extra=''):
    pts = ' '.join('%.1f,%.1f' % (x, y) for x, y in p)
    return '<polygon points="%s" fill="%s" stroke="%s" stroke-width="%.1f" %s/>' % (pts, fill, stroke, sw, extra)
def iso_box_corners(corners, z0, h, cols):
    top, a, b = cols
    P = lambda x, y, z: ((x - y) * COS30 * SPX, (x + y) * 0.5 * SPX - z * SPX)
    base = [P(x, y, z0) for x, y in corners]
    up = [P(x, y, z0 + h) for x, y in corners]
    faces = [[base[k], base[(k + 1) % 4], up[(k + 1) % 4], up[k]] for k in range(4)]
    return iso_quad(faces[1], b, stroke='none') + iso_quad(faces[2], a, stroke='none') + iso_quad(up, top)
def floor_tiles(model, cell=0.4):
    seen, minx, miny, c = floor_mask(model)
    xs = [w['x1'] for w in model['walls']] + [w['x2'] for w in model['walls']]
    ys = [w['y1'] for w in model['walls']] + [w['y2'] for w in model['walls']]
    P = lambda x, y: ((x - y) * COS30 * SPX, (x + y) * 0.5 * SPX)
    out = []
    i0, i1 = int(min(xs) / cell) - 1, int(max(xs) / cell) + 1
    j0, j1 = int(min(ys) / cell) - 1, int(max(ys) / cell) + 1
    for i in range(i0, i1):
        for j in range(j0, j1):
            cx, cy = (i + 0.5) * cell, (j + 0.5) * cell
            if (int((cx - minx) / c), int((cy - miny) / c)) in seen:
                out.append(iso_quad([P(cx - cell / 2, cy - cell / 2), P(cx + cell / 2, cy - cell / 2),
                                     P(cx + cell / 2, cy + cell / 2), P(cx - cell / 2, cy + cell / 2)],
                                    BRAND['floor'], stroke='none'))
    return ''.join(out)
def iso_svg(model):
    Hc = min(model['wall_height'], CUT)
    P = lambda x, y, z=0: ((x - y) * COS30 * SPX, (x + y) * 0.5 * SPX - z * SPX)
    P0 = lambda x, y: ((x - y) * COS30 * SPX, (x + y) * 0.5 * SPX)
    shadows = ''
    for f in model['furniture']:
        ang = math.radians(f['rot'])
        ca, sa = math.cos(ang), math.sin(ang)
        q = []
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            lx, ly = sx * (f['w'] / 2 + 0.04), sy * (f['d'] / 2 + 0.04)
            q.append((f['x'] + lx * ca - ly * sa, f['y'] + lx * sa + ly * ca))
        shadows += iso_quad([P0(*p) for p in q], '#B9A488', stroke='none', extra='opacity="0.12"')
    xs = [w['x1'] for w in model['walls']] + [w['x2'] for w in model['walls']]
    ys = [w['y1'] for w in model['walls']] + [w['y2'] for w in model['walls']]
    bxp = 0.15
    base_corners = [(min(xs) - bxp, min(ys) - bxp), (max(xs) + bxp, min(ys) - bxp),
                    (max(xs) + bxp, max(ys) + bxp), (min(xs) - bxp, max(ys) + bxp)]
    base = iso_box_corners(base_corners, -0.08, 0.08, (BRAND['base'], '#E4D4BE', '#DCC9AE'))
    parts = [(None, base + floor_tiles(model) + shadows)]
    for f in model['furniture']:
        h = min(f['h'], 1.35)
        ang = math.radians(f['rot'])
        ca, sa = math.cos(ang), math.sin(ang)
        corners = []
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            lx, ly = sx * f['w'] / 2, sy * f['d'] / 2
            corners.append((f['x'] + lx * ca - ly * sa, f['y'] + lx * sa + ly * ca))
        parts.append((f['x'] + f['y'], iso_box_corners(corners, 0, h, MAT.get(f['kind'], MAT['other']))))
    for w in model['walls']:
        L = w['length'] or 1
        ux, uy = (w['x2'] - w['x1']) / L, (w['y2'] - w['y1']) / L
        nx, ny = -uy, ux
        pos, segs = 0.0, []
        for o in sorted(w['openings'], key=lambda o: o['start']):
            if o['start'] > pos:
                segs.append((pos, o['start'], 'wall', None))
            segs.append((o['start'], o['end'], o['kind'], o))
            pos = max(pos, o['end'])
        if pos < L:
            segs.append((pos, L, 'wall', None))
        def piece(a, b, z0, z1):
            if z1 - z0 <= 0.001:
                return
            n = max(1, int(math.ceil((b - a) / 0.4)))
            for k in range(n):
                aa = a + (b - a) * k / n
                bb = a + (b - a) * (k + 1) / n
                p1 = (w['x1'] + ux * aa, w['y1'] + uy * aa)
                p2 = (w['x1'] + ux * bb, w['y1'] + uy * bb)
                corners = [(p1[0] + nx * w['t'] / 2, p1[1] + ny * w['t'] / 2),
                           (p2[0] + nx * w['t'] / 2, p2[1] + ny * w['t'] / 2),
                           (p2[0] - nx * w['t'] / 2, p2[1] - ny * w['t'] / 2),
                           (p1[0] - nx * w['t'] / 2, p1[1] - ny * w['t'] / 2)]
                parts.append(((p1[0] + p2[0] + p1[1] + p2[1]) / 2,
                              iso_box_corners(corners, z0, z1 - z0, (BRAND['wall'], BRAND['wall_a'], BRAND['wall_b']))))
        for a, b, kind, o in segs:
            if kind == 'wall':
                piece(a, b, 0, Hc)
            elif kind == 'window':
                top = min(Hc, o['sill'] + o['height'])
                piece(a, b, 0, min(o['sill'], Hc))
                if Hc > o['sill']:
                    p1 = (w['x1'] + ux * a, w['y1'] + uy * a)
                    p2 = (w['x1'] + ux * b, w['y1'] + uy * b)
                    q = [P(p1[0], p1[1], min(o['sill'], Hc)), P(p2[0], p2[1], min(o['sill'], Hc)),
                         P(p2[0], p2[1], top), P(p1[0], p1[1], top)]
                    parts.append(((p1[0] + p2[0] + p1[1] + p2[1]) / 2,
                                  iso_quad(q, BRAND['glass'], extra='opacity="0.85"')))
                if Hc > top:
                    piece(a, b, top, Hc)
    parts.sort(key=lambda t: (-1 if t[0] is None else t[0]))
    xsP = [P(w['x1'], w['y1'])[0] for w in model['walls']] + [P(w['x2'], w['y2'])[0] for w in model['walls']]
    ysP = [P(w['x1'], w['y1'])[1] for w in model['walls']] + [P(w['x2'], w['y2'])[1] for w in model['walls']]
    pad = 80
    vb = '%.0f %.0f %.0f %.0f' % (min(xsP) - pad, min(ysP) - pad,
                                  (max(xsP) - min(xsP)) + 2 * pad, (max(ysP) - min(ysP)) + 2 * pad)
    labels = ''
    for lp in model.get('room_labels') or []:
        q = P(lp['x'], lp['y'], 0.2)
        labels += ('<text x="%.0f" y="%.0f" text-anchor="middle" font-size="18" font-weight="700" '
                   'fill="#C0713F">%s</text>' % (q[0], q[1], lp['label']))
    body = ''.join(svg for _, svg in parts)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="%s" width="100%%" '
            'font-family="-apple-system,PingFang SC,sans-serif">%s%s</svg>' % (vb, body, labels))
# ---------- 静态背景对照页 ----------
CSS = ('body{margin:0;background:#FDFBF7;color:#4E463C;font:14px/1.5 -apple-system,"PingFang SC",sans-serif;'
       'padding:20px}h1{font-size:16px;margin:0 0 4px}h2{font-size:15px;margin:22px 0 6px}'
       'p.sub{margin:0 0 14px;color:#9C9184;font-size:12px}.card{background:#FFFDF9;border:1px solid #E2D5C2;'
       'border-radius:14px;padding:14px;margin-bottom:14px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}'
       '@media(max-width:860px){.grid{grid-template-columns:1fr}}table{border-collapse:collapse;font-size:12.5px;width:100%}'
       'td{padding:4px 8px;border-bottom:1px solid #F1E5D4}.k{color:#9C9184}.v{font-weight:600}'
       'svg{display:block;width:100%;height:auto}.pending ul{margin:0;padding-left:18px;font-size:12.5px;color:#6B6156}')  # noqa: E501
def section_html(model, name):
    m = metrics(model)
    rows = ''.join('<tr><td>%s</td><td>%d×%d cm</td><td>%d cm</td><td>%s°</td></tr>'
                   % (f['label'], round(f['w'] * 100), round(f['d'] * 100), round(f['h'] * 100), ('%g' % f['rot']))
                   for f in model['furniture'])
    pend = ''.join('<li>%s</li>' % p for p in model.get('pending') or [])
    return ('<h2>扫描房间 · %s</h2><p class="sub">来源：%s · 真实尺寸（扫描，cm 转 m）· 本页只是静态背景对照，'
            '产品级 3D 见 scan-room-model.html</p>'
            '<div class="card"><span class="k">外轮廓</span> <span class="v">%.2f m × %.2f m</span>'
            ' &nbsp;·&nbsp; <span class="k">地面</span> <span class="v">%.1f m²</span>'
            ' &nbsp;·&nbsp; <span class="k">墙高</span> <span class="v">%.2f m</span>'
            ' &nbsp;·&nbsp; <span class="k">墙</span> <span class="v">%d</span>'
            ' &nbsp;·&nbsp; <span class="k">门窗洞</span> <span class="v">%d</span>'
            ' &nbsp;·&nbsp; <span class="k">家具</span> <span class="v">%d</span></div>'
            '<div class="grid"><div class="card"><div class="k" style="margin-bottom:6px">'
            '等距 3D（背景对照：墙截到 %.2f m，家具截到 1.35 m）</div>%s</div>'
            '<div class="card"><div class="k" style="margin-bottom:6px">俯视平面（尺寸 cm）</div>%s</div></div>'
            '<div class="card"><div class="k" style="margin-bottom:6px">家具清单（扫描识别）</div>'
            '<table><tr><td class="k">类型</td><td class="k">占地</td><td class="k">高</td><td class="k">旋转</td></tr>'
            '%s</table></div>%s'
            % (name, model.get('source', ''), m['bbox_m'][0], m['bbox_m'][1], m['floor_area'],
               m['wall_height_m'], m['walls'], m['openings'], m['furniture'], CUT, iso_svg(model), plan_svg(model),
               rows, ('<div class="card pending"><div class="k" style="margin-bottom:6px">待用户确认</div>'
                      '<ul>%s</ul></div>' % pend if pend else '')))
def page_html(models):
    head = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="generated-by" content="tools/scan_room.py">'
            '<meta name="generated-src" content="data/3d/rooms/*.json">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>扫描房间 · 背景对照</title><style>%s</style></head><body>' % CSS)
    body = ('<h1>扫描房间 · 背景对照</h1><p class="sub">RoomPlan 真实测量 · 共 %d 间/空间 · 几何来自 '
            'data/3d/rooms/*.json（可替换后重新生成）· 运行期零第三方 · 产品级 3D 见 '
            '<a href="scan-room-model.html">scan-room-model.html</a></p>' % len(models))
    for model in models:
        body += section_html(model, model.get('source_file', '').replace('.json', ''))
    return head + body + '</body></html>'
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('name', nargs='?', help='扫描名（data/3d/scans/<name>.json）')
    ap.add_argument('--all', action='store_true', help='只按已有 rooms/*.json 重建对照页')
    ap.add_argument('--scans-dir', default=SCANS); ap.add_argument('--rooms-dir', default=ROOMS)
    ap.add_argument('--web-dir', default=WEB); a = ap.parse_args()
    if not a.name and not a.all:
        ap.error('需要 <name> 或 --all')
    os.makedirs(a.rooms_dir, exist_ok=True)
    if a.name:
        raw = os.path.join(a.scans_dir, a.name + '.json')
        model = build(raw)
        with open(os.path.join(a.rooms_dir, a.name + '.json'), 'w', encoding='utf-8') as fp:
            json.dump(model, fp, ensure_ascii=False, indent=1)
        with open(os.path.join(a.rooms_dir, a.name + '.plan.svg'), 'w', encoding='utf-8') as fp:
            fp.write(plan_svg(model))
        m = metrics(model)
        print('✓ %s：%d 墙 · %d 门窗洞 · %d 家具 · 地面 %.1f m² · 待确认 %d 项 · 缺口 %d 处'
              % (a.name, m['walls'], m['openings'], m['furniture'], m['floor_area'],
                 len(model['pending']), len(model['floor']['gaps'])))
        print('  外轮廓 %.2f × %.2f m · 墙高 %.2f m' % (m['bbox_m'][0], m['bbox_m'][1], m['wall_height_m']))
    models = []
    for p in sorted(glob.glob(os.path.join(a.rooms_dir, '*.json'))):
        if p.endswith('.edited.json'):
            continue
        name = os.path.basename(p)[:-5]
        try:
            json.load(open(p, encoding='utf-8'))
        except (ValueError, OSError):
            continue
        models.append(effective_model(a.rooms_dir, name))
    os.makedirs(a.web_dir, exist_ok=True)
    page = page_html(models)
    with open(os.path.join(a.web_dir, 'scan-room.html'), 'w', encoding='utf-8') as fp:
        fp.write(page)
    print('  → app/web/space/scan-room.html（%d 间/空间，%.0f KB）' % (len(models), len(page) / 1024.0))
if __name__ == '__main__':
    main()
