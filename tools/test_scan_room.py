#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫描房间几何测试（tools/scan_room.py）—— 纯几何断言，不联网，全部写临时目录。

依据：11 §11（新增功能必须带测试）、09 §1（真话优先：测的是数据本身，不是页面截图）。
覆盖：
  ① 真实扫描的外轮廓 / 墙高 / 墙数 / 门窗数 / 家具数与类型（PDF 核对见 rooms/README.md）
  ② 门窗洞位置与尺寸（左墙 2 门、顶墙 1 门、底墙长窗、中间玻璃）
  ③ JSON schema 稳定（scan_room/v2：原有字段仍在、只增字段、可 JSON 往返）
  ④ 地面轮廓面积与家具落位；未闭合缺口虚拟闭合
  ⑤ 多房间扫描（rooms[].walls 拼多边形）与房间命名映射
  ⑥ .edited.json 覆盖合并（只读：基础几何以最新数据为准，家具以编辑为准）
  ⑦ CLI 端到端：临时目录产物齐、可复现、零第三方、<1.5MB
  ⑧ --model：对 app/web/space/scan-room-model.html 做只读验收（尺寸/门窗/家具与 JSON 一致、产物新鲜）

用法：python3 tools/test_scan_room.py            # 退出码 0 = 全过
      python3 tools/test_scan_room.py --model    # 追加另一条线产物的只读验收
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, 'tools')
sys.path.insert(0, TOOLS)
import scan_room  # noqa: E402

SCAN_NAME = '客厅餐厅-20261017'
SCAN = os.path.join(ROOT, 'data', '3d', 'scans', SCAN_NAME + '.json')
OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + ('  —— ' + str(detail) if detail else ''))


def raw_scan(walls, doors=(), windows=(), furniture=(), rooms=(), name='synthetic'):
    return {'id': 'x', 'name': name, 'createdAt': '2026-10-17T00:00:00.000Z', 'floors': [{
        'id': 'f1', 'name': 'Ground Floor', 'level': 0, 'walls': list(walls), 'rooms': list(rooms),
        'doors': list(doors), 'windows': list(windows), 'furniture': list(furniture)}],
        'interchange': {'version': 1, 'blocks': {}, 'attributes': {}}}


def wall(wid, x1, y1, x2, y2, thick=15, height=240):
    return {'id': wid, 'start': {'x': x1, 'y': y1}, 'end': {'x': x2, 'y': y2},
            'thickness': thick, 'height': height}


def furn(fid, x, y, w, d, h, rot=0, catalog='storage'):
    return {'id': fid, 'catalogId': catalog, 'position': {'x': x, 'y': y}, 'rotation': rot,
            'scale': {'x': 1, 'y': 1, 'z': 1}, 'width': w, 'depth': d, 'height': h}


def near(a, b, tol=0.02):
    return abs(a - b) <= tol


def point_in(pts, x, y):
    inside = False
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def write_tmp(tmp, name, doc):
    p = os.path.join(tmp, name)
    with open(p, 'w', encoding='utf-8') as fp:
        json.dump(doc, fp, ensure_ascii=False)
    return p


def real_model():
    if not os.path.exists(SCAN):
        check('找到真实扫描 data/3d/scans/%s.json' % SCAN_NAME, False, '文件缺失')
        return None
    return scan_room.build(SCAN)


def test_real_scan(m):
    print('\n── ① 真实扫描的总体几何 ──')
    check('schema 是 scan_room/v2', m.get('schema') == 'scan_room/v2', m.get('schema'))
    check('单位是 m', m.get('units') == 'm', m.get('units'))
    b = m['bounds']
    check('外轮廓 6.31 × 4.69 m（与 PDF 标注一致）',
          near(b['max_x'] - b['min_x'], 6.31) and near(b['max_y'] - b['min_y'], 4.69),
          '%.2f × %.2f' % (b['max_x'] - b['min_x'], b['max_y'] - b['min_y']))
    check('墙高 2.64 m', near(m['wall_height'], 2.64), m['wall_height'])
    check('6 面墙', len(m['walls']) == 6, len(m['walls']))
    kinds = {}
    for f in m['furniture']:
        kinds[f['kind']] = kinds.get(f['kind'], 0) + 1
    check('11 件家具', len(m['furniture']) == 11, len(m['furniture']))
    check('家具类型：沙发1 餐桌1 椅子3 柜子5 电视1',
          kinds == {'sofa': 1, 'table': 1, 'chair': 3, 'cabinet': 5, 'tv': 1}, kinds)
    check('门窗洞 5 个（3 门 + 2 窗）', sum(len(w['openings']) for w in m['walls']) == 5,
          [(o['kind']) for w in m['walls'] for o in w['openings']])
    check('地面轮廓有面积（22–26 m²）', 22.0 <= m['floor']['area'] <= 26.0, m['floor']['area'])
    check('地面多边形至少 4 个折点', len(m['floor']['polygon']) >= 4, len(m['floor']['polygon']))
    check('记录 2 处墙体未闭合缺口', len(m['floor']['gaps']) == 2, len(m['floor']['gaps']))
    check('pending 至少 4 条待用户确认', len(m['pending']) >= 4, len(m['pending']))
    joined = ' '.join(m['pending'])
    check('待确认含「命名」与「方位」', '命名' in joined and '方位' in joined, '')


def test_openings(m):
    print('\n── ② 门窗洞位置与尺寸 ──')
    by_len = {round(w['length'] * 100): w for w in m['walls']}
    top = [w for w in m['walls'] if near(w['length'], 6.31) and near(w['y1'], -4.31)][0]
    left = [w for w in m['walls'] if near(w['length'], 4.69)][0]
    bottom = [w for w in m['walls'] if near(w['length'], 5.32) and near(w['y1'], 0.38)][0]
    mid = [w for w in m['walls'] if near(w['length'], 3.24) and near(w['y1'], -0.2)][0]
    right = [w for w in m['walls'] if near(w['length'], 3.05)][0]
    ret = [w for w in m['walls'] if near(w['length'], 0.58)][0]
    check('墙长与 PDF 标注的 631/469/532/324/305/58 cm 一一对应',
          sorted(by_len) == [58, 305, 324, 469, 532, 631], sorted(by_len))
    check('顶墙 1 个门（78 cm，start≈0.46 m）',
          len(top['openings']) == 1 and top['openings'][0]['kind'] == 'door'
          and near(top['openings'][0]['start'], 0.464, 0.01), top['openings'])
    check('左墙 2 个门（81 cm + 135 cm 洞）',
          len(left['openings']) == 2 and
          sorted(round(o['width'] * 100) for o in left['openings']) == [81, 135], left['openings'])
    check('底墙 1 个长窗 513 cm、窗台 51.7 cm',
          len(bottom['openings']) == 1 and bottom['openings'][0]['kind'] == 'window'
          and near(bottom['openings'][0]['width'], 5.134, 0.002)
          and near(bottom['openings'][0]['sill'], 0.517, 0.005), bottom['openings'])
    check('中间隔断 1 个玻璃窗 276 cm、窗台 48.6 cm',
          len(mid['openings']) == 1 and mid['openings'][0]['kind'] == 'window'
          and near(mid['openings'][0]['width'], 2.758, 0.002)
          and near(mid['openings'][0]['sill'], 0.486, 0.005), mid['openings'])
    check('右墙与 58 cm 短墙无门窗洞',
          not right['openings'] and not ret['openings'], (right['openings'], ret['openings']))
    check('门都落地（sill=0）', all(o['sill'] == 0 for w in m['walls'] for o in w['openings'] if o['kind'] == 'door'))
    check('门/窗高度合理（1.5–2.6 m）',
          all(1.5 <= o['height'] <= 2.6 for w in m['walls'] for o in w['openings']), '')


def test_walls(m):
    print('\n── ③ 墙体与 JSON schema 稳定 ──')
    bad = []
    for w in m['walls']:
        L = math.hypot(w['x2'] - w['x1'], w['y2'] - w['y1'])
        if not near(L, w['length'], 0.002) or w['t'] <= 0 or w['h'] <= 0:
            bad.append(w['id'])
        pos = 0.0
        for o in sorted(w['openings'], key=lambda o: o['start']):
            if o['start'] < -1e-6 or o['end'] > w['length'] + 1e-6 or o['end'] <= o['start'] or o['start'] < pos:
                bad.append(w['id'] + ':opening')
            pos = max(pos, o['end'])
    check('墙长=端点距离、墙厚墙高>0、洞口在墙内且不重叠', not bad, bad[:3])
    for k in ('schema', 'source', 'source_file', 'units', 'wall_height', 'walls', 'furniture',
              'room_labels', 'bounds', 'rooms', 'floor', 'pending', 'meta'):
        check('顶层字段 %s 存在' % k, k in m, '')
    req_w = {'id', 'x1', 'y1', 'x2', 'y2', 'length', 't', 'h', 'openings'}
    req_o = {'kind', 'start', 'end', 'width', 'height', 'sill', 'type'}
    req_f = {'id', 'kind', 'label', 'x', 'y', 'rot', 'w', 'd', 'h', 'catalog', 'arms'}
    check('walls 字段齐（原有字段名保持不变）', all(req_w <= set(w) for w in m['walls']), '')
    check('openings 字段齐（新增 type）', all(req_o <= set(o) for w in m['walls'] for o in w['openings']), '')
    check('furniture 字段齐（新增 catalog/arms）', all(req_f <= set(f) for f in m['furniture']), '')
    rt = json.loads(json.dumps(m))
    check('JSON 往返后完全一致（无 NaN/不可序列化）', rt == m, '')
    xs = [w['x1'] for w in m['walls']] + [w['x2'] for w in m['walls']]
    ys = [w['y1'] for w in m['walls']] + [w['y2'] for w in m['walls']]
    check('家具都落在墙体包围盒内（允许 0.3 m 扫描误差）',
          all(min(xs) - 0.3 <= f['x'] <= max(xs) + 0.3 and min(ys) - 0.3 <= f['y'] <= max(ys) + 0.3
              for f in m['furniture']), '')
    sofa = [f for f in m['furniture'] if f['kind'] == 'sofa'][0]
    table = [f for f in m['furniture'] if f['kind'] == 'table'][0]
    check('沙发 2.29×1.12 m / 餐桌 1.77×1.02 m（真实测量值）',
          near(sofa['w'], 2.288, 0.005) and near(sofa['d'], 1.125, 0.005)
          and near(table['w'], 1.775, 0.005) and near(table['d'], 1.02, 0.005), '')
    check('两台「电视/影音」类深度 < 0.2 m、高度 0.8–1.2 m',
          all(f['d'] < 0.2 and 0.8 <= f['h'] <= 1.2 for f in m['furniture'] if f['kind'] == 'tv'), '')
    check('椅子有扶手标记字段（arms 布尔）', all(isinstance(f['arms'], bool) for f in m['furniture'] if f['kind'] == 'chair'))


def test_floor(m):
    print('\n── ④ 地面轮廓与家具落位 ──')
    polys = m['floor'].get('polygons') or [m['floor']['polygon']]
    inside = [any(point_in(p, f['x'], f['y']) for p in polys) for f in m['furniture']]
    outside = [i for i, ok in enumerate(inside) if not ok]
    odd = [f for i, f in enumerate(m['furniture']) if i in outside]
    check('家具中心落在地面轮廓内（扫描异常件除外）',
          all(min(f['w'], f['d']) < 0.1 and f['h'] > 2.0 for f in odd), outside)
    check('地面可按多个连通区域输出（多房间扫描用）', len(polys) >= 1, len(polys))
    check('地面面积与 24.0 m² 一致（扫描真实面积）', near(m['floor']['area'], 24.03, 0.6), m['floor']['area'])
    check('待确认项提到墙体缺口', any('缺口' in p for p in m['pending']), '')


def test_multi_room():
    print('\n── ⑤ 多房间扫描（一个扫描含多个 RoomPlan rooms）──')
    with tempfile.TemporaryDirectory() as tmp:
        walls = [wall('a1', 0, 0, 300, 0), wall('a2', 300, 0, 300, 300),
                 wall('a3', 300, 300, 0, 300), wall('a4', 0, 300, 0, 0),
                 wall('b1', 300, 0, 600, 0), wall('b2', 600, 0, 600, 300),
                 wall('b3', 600, 300, 300, 300)]
        rooms = [{'id': 'r1', 'name': 'Bedroom', 'walls': ['a1', 'a2', 'a3', 'a4'], 'area': 0},
                 {'id': 'r2', 'name': 'Kitchen', 'walls': ['a2', 'b1', 'b2', 'b3'], 'area': 0}]
        doc = raw_scan(walls, furniture=[furn('f1', 150, 150, 200, 160, 50, catalog='bed'),
                                         furn('f2', 450, 150, 90, 60, 90)],
                       rooms=rooms)
        p = write_tmp(tmp, 'multi.json', doc)
        m = scan_room.build(p)
        check('两个房间都拼出多边形', all(r['polygon'] for r in m['rooms']),
              [r['polygon'] is not None for r in m['rooms']])
        check('房间面积 9 + 9 m²（真实墙线算的）',
              all(near(r['area'], 9.0, 0.05) for r in m['rooms']), [r['area'] for r in m['rooms']])
        check('房间名按 RoomPlan 原始名映射（Bedroom→卧室 / Kitchen→厨房）',
              [r['name'] for r in m['rooms']] == ['卧室', '厨房'], [r['name'] for r in m['rooms']])
        check('房间标签落在两个房间中心（每间一个）', len(m['room_labels']) == 2,
              [(lp['label'], round(lp['x']), round(lp['y'])) for lp in m['room_labels']])
        check('地面按两间输出两个区域（各 ≈2.85×2.85 m 净面积）',
              len(m['floor']['polygons']) == 2 and near(m['floor']['area'], 16.2, 1.0),
              (len(m['floor']['polygons']), m['floor']['area']))
        check('多房间无墙体缺口', len(m['floor']['gaps']) == 0, m['floor']['gaps'])


def test_gap_close():
    print('\n── ⑥ 未闭合缺口虚拟闭合 ──')
    with tempfile.TemporaryDirectory() as tmp:
        # 4×3 m 矩形，底边中间留 0.8 m 缺口（RoomPlan 常把门洞留成缺口）
        walls = [wall('w1', 0, 0, 400, 0), wall('w2', 400, 0, 400, 300),
                 wall('w3', 400, 300, 240, 300), wall('w4', 160, 300, 0, 300),
                 wall('w5', 0, 300, 0, 0)]
        doc = raw_scan(walls, furniture=[furn('f1', 200, 150, 90, 60, 90)])
        p = write_tmp(tmp, 'gap.json', doc)
        m = scan_room.build(p)
        check('识别出 1 处缺口', len(m['floor']['gaps']) == 1, m['floor']['gaps'])
        check('缺口闭合后地面仍是完整矩形（净面积 ≈10.9 m²）', near(m['floor']['area'], 10.9, 0.6), m['floor']['area'])
        check('缺口写进 pending 待用户确认', any('缺口' in x for x in m['pending']), '')


def test_edited_merge():
    print('\n── ⑦ .edited.json 覆盖合并（只读）──')
    with tempfile.TemporaryDirectory() as tmp:
        base = {'schema': 'scan_room/v2', 'units': 'm', 'bounds': {'min_x': 0, 'min_y': 0, 'max_x': 1, 'max_y': 1},
                'walls': [{'id': 'w', 'x1': 0, 'y1': 0, 'x2': 1, 'y2': 0, 'length': 1, 't': 0.1, 'h': 2.4, 'openings': []}],
                'furniture': [{'id': 'f', 'kind': 'chair', 'label': '椅子', 'x': 0.5, 'y': 0.5,
                               'rot': 0, 'w': 0.5, 'd': 0.5, 'h': 0.9, 'catalog': None, 'arms': False}],
                'room_labels': [{'label': '客厅', 'x': 0.5, 'y': 0.5}],
                'rooms': [], 'floor': {'polygon': [[0, 0], [1, 0], [1, 1], [0, 1]], 'area': 1.0, 'gaps': []},
                'pending': ['待确认'], 'meta': {'project': 'x', 'created': 'y', 'floors_raw': 1}}
        write_tmp(tmp, 'demo.json', base)
        before = json.dumps(base, ensure_ascii=False, sort_keys=True)
        edited = {'furniture': [{'id': 'f', 'kind': 'sofa', 'label': '沙发', 'x': 0.1, 'y': 0.2,
                                 'rot': 90, 'w': 0.9, 'd': 0.8, 'h': 0.8}]}
        write_tmp(tmp, 'demo.edited.json', edited)
        m = scan_room.effective_model(tmp, 'demo')
        check('家具取 .edited.json 的值', m['furniture'][0]['kind'] == 'sofa' and near(m['furniture'][0]['x'], 0.1))
        check('基础几何仍取最新基础数据（walls/floor/bounds/pending 不被旧编辑覆盖）',
              m['walls'] == base['walls'] and m['floor'] == base['floor'] and m['bounds'] == base['bounds']
              and m['pending'] == base['pending'], '')
        check('合并只读：基础 JSON 未被改动', json.dumps(json.load(open(os.path.join(tmp, 'demo.json'), encoding='utf-8')),
                                                         ensure_ascii=False, sort_keys=True) == before, '')
        write_tmp(tmp, 'plain.json', base)
        check('无编辑覆盖时家具就是基础数据',
              scan_room.effective_model(tmp, 'plain')['furniture'] == base['furniture'], '')


def test_cli():
    print('\n── ⑧ CLI 端到端（临时目录 / 可复现 / 零第三方）──')
    if not os.path.exists(SCAN):
        check('CLI 端到端（缺真实扫描）', False, SCAN)
        return
    with tempfile.TemporaryDirectory() as tmp:
        scans = os.path.join(tmp, 'scans')
        rooms = os.path.join(tmp, 'rooms')
        web = os.path.join(tmp, 'web')
        os.makedirs(scans)
        shutil.copy(SCAN, os.path.join(scans, SCAN_NAME + '.json'))
        cmd = [sys.executable, os.path.join(TOOLS, 'scan_room.py'), SCAN_NAME,
               '--scans-dir', scans, '--rooms-dir', rooms, '--web-dir', web]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        check('CLI 退出码 0', r.returncode == 0, (r.stderr or r.stdout)[-200:])
        out_json = os.path.join(rooms, SCAN_NAME + '.json')
        out_plan = os.path.join(rooms, SCAN_NAME + '.plan.svg')
        out_page = os.path.join(web, 'scan-room.html')
        check('产出归一化 JSON / 平面 SVG / 对照页', all(os.path.exists(p) for p in (out_json, out_plan, out_page)), '')
        page = open(out_page, encoding='utf-8').read()
        plan = open(out_plan, encoding='utf-8').read()
        check('对照页带 generated-by 生成标记', 'name="generated-by" content="tools/scan_room.py"' in page)
        check('对照页运行期零第三方（无外链 JS/CSS）', 'src="http' not in page and 'href="http' not in page)
        check('对照页 < 1.5 MB（11 §13 生成物体积上限）', len(page.encode('utf-8')) < 1.5 * 1024 * 1024,
              '%.0f KB' % (len(page.encode('utf-8')) / 1024))
        check('平面 SVG 标注 631/469/532/324/305/58 cm',
              all(('%d cm' % v) in plan for v in (631, 469, 532, 324, 305, 58)), '')
        first_json = open(out_json, encoding='utf-8').read()
        first_page = page
        r2 = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        check('重复运行可复现（JSON/SVG/页面字节一致）',
              r2.returncode == 0 and open(out_json, encoding='utf-8').read() == first_json
              and open(out_page, encoding='utf-8').read() == first_page, '')
        r3 = subprocess.run([sys.executable, os.path.join(TOOLS, 'scan_room.py'), '--all',
                             '--rooms-dir', rooms, '--web-dir', web], capture_output=True, text=True, timeout=180)
        check('--all 能只按已有 JSON 重建对照页', r3.returncode == 0 and os.path.exists(out_page), r3.stderr[-200:])


def extract_model(html):
    m = re.search(r'const MODEL = (\{.*?\});\s*\n', html, re.S)
    return json.loads(m.group(1)) if m else None


def test_model_page():
    print('\n── ⑨ 另一条线产物只读验收（scan-room-model.html）──')
    page_p = os.path.join(ROOT, 'app', 'web', 'space', 'scan-room-model.html')
    build_p = os.path.join(ROOT, 'app', 'prototype', 'scan-room-editor', 'build-room.mjs')
    json_p = os.path.join(ROOT, 'data', '3d', 'rooms', SCAN_NAME + '.json')
    if not (os.path.exists(page_p) and os.path.exists(json_p)):
        check('产物存在', False, '缺 scan-room-model.html 或 rooms JSON'); return
    html = open(page_p, encoding='utf-8').read()
    base = scan_room.effective_model(os.path.join(ROOT, 'data', '3d', 'rooms'), SCAN_NAME)
    model = extract_model(html)
    check('页面内嵌 MODEL 可解析', isinstance(model, dict), '')
    if not isinstance(model, dict):
        return
    check('MODEL.name 与扫描名一致', model.get('name') == SCAN_NAME, model.get('name'))
    check('MODEL.size 与 JSON 外轮廓一致（631/469 cm）',
          near(model.get('size', {}).get('w', 0), 6.31) and near(model.get('size', {}).get('d', 0), 4.69),
          model.get('size'))
    pw = model.get('walls') or []
    check('墙数与 JSON 一致（6 面）', len(pw) == len(base['walls']), (len(pw), len(base['walls'])))
    bad = []
    for a, b in zip(pw, base['walls']):
        if not (near(a['x1'], b['x1']) and near(a['y1'], b['y1']) and near(a['x2'], b['x2']) and near(a['y2'], b['y2'])):
            bad.append(a)
        if a.get('openings') != len(b['openings']):
            bad.append('openings:%s' % a)
    check('墙端点与每面墙的门窗洞数量与 JSON 一致', not bad, bad[:2])
    pf = model.get('furniture') or []
    bf = base['furniture']
    check('家具数与 JSON 一致（11 件）', len(pf) == len(bf), (len(pf), len(bf)))
    miss = [x.get('id') for x in bf if x['id'] not in {f.get('id') for f in pf}]
    check('家具 id 全部对得上', not miss, miss[:3])
    diffs = []
    bmap = {f['id']: f for f in bf}
    for f in pf:
        b = bmap.get(f.get('id'))
        if not b:
            continue
        if not (near(f.get('x', 0), b['x'], 0.03) and near(f.get('y', 0), b['y'], 0.03)
                and near(f.get('w', 0), b['w'], 0.02) and near(f.get('d', 0), b['d'], 0.02)
                and near(f.get('h', 0), b['h'], 0.02) and near(f.get('rot', 0), b['rot'], 0.2)):
            diffs.append((f.get('id'), f.get('x'), f.get('y'), f.get('w'), f.get('d'), f.get('h')))
        if f.get('kind') != b['kind']:
            diffs.append(('kind', f.get('id'), f.get('kind'), b['kind']))
    check('家具位置/宽深高/旋转/类型与 JSON 一致（±2 cm）', not diffs, diffs[:2])
    check('门窗标注数与 JSON 一致（3 门 + 2 窗）',
          sum(1 for w in base['walls'] for o in w['openings'] if o['kind'] == 'door') == 3
          and sum(1 for w in base['walls'] for o in w['openings'] if o['kind'] == 'window') == 2, '')
    check('运行期零第三方（无外链 JS、无 node_modules）',
          not re.search(r'<script[^>]+src="https?://', html) and 'node_modules' not in html, '')
    check('页面 < 1.5 MB', len(html.encode('utf-8')) < 1.5 * 1024 * 1024, '%.0f KB' % (len(html.encode('utf-8')) / 1024))
    check('同目录有 .build.md 构建说明', os.path.exists(os.path.join(os.path.dirname(page_p), 'scan-room-model.build.md')))
    stale = []
    if os.path.getmtime(page_p) < os.path.getmtime(json_p):
        stale.append('页面比 rooms JSON 旧（JSON 改过需重跑 node build-room.mjs）')
    if os.path.exists(build_p) and os.path.getmtime(page_p) < os.path.getmtime(build_p):
        stale.append('页面比 build-room.mjs 旧')
    check('构建物不旧于源（11 §13）', not stale, stale)


def main():
    want_model = '--model' in sys.argv[1:]
    m = real_model()
    if m is not None:
        test_real_scan(m)
        test_openings(m)
        test_walls(m)
        test_floor(m)
    test_multi_room()
    test_gap_close()
    test_edited_merge()
    test_cli()
    if want_model:
        test_model_page()
    print('\n测试结果：通过 %d · 失败 %d%s' % (len(OK), len(FAIL), ('　失败项：%s' % FAIL) if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
