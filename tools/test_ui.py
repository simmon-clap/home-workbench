#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
界面与接口测试（三层交互链路）

依据：docs/spec/03-功能与交互规范 v1.2 §1C（三层渐进交互）· 09 §2（复验要真实：真浏览器、真点击）

用法：python3 tools/test_ui.py    退出码 0 = 全过
前置：家庭工作台服务已在 127.0.0.1:8300 运行（否则本测试会明确报「服务未启动」）
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = 'http://127.0.0.1:8300'
def _find_chrome():
    """优先用 Playwright 的 headless shell（干净、不受系统 Chrome 登录态/升级影响），
    找不到再退回系统 Chrome。可用 SMART_HOME_CHROME 覆盖。"""
    env = os.environ.get('SMART_HOME_CHROME')
    if env and os.path.exists(env):
        return env
    import glob
    pats = [
        os.path.expanduser('~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-mac-arm64/chrome-headless-shell'),
        os.path.expanduser('~/Library/Caches/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-mac-x64/chrome-headless-shell'),
        os.path.expanduser('~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell'),
    ]
    for pat in pats:
        m = sorted(glob.glob(pat))
        if m:
            return m[-1]
    return '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'


CHROME = _find_chrome()
ROOMS = ['客厅', '主卧', '厨房', '餐厅', '次卧', '客卫', '主卫', '书房', '阳台', '办公室']
OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=8) as r:
            return r.status, r.read().decode('utf-8', 'ignore')
    except Exception as e:  # noqa
        return None, str(e)


def dom(url):
    if not os.path.exists(CHROME):
        return None
    try:
        out = subprocess.run(
            [CHROME, '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-breakpad',
             '--disable-crash-reporter', '--crash-dumps-dir=/tmp/crash',
             '--user-data-dir=/tmp/test-chrome', '--virtual-time-budget=5000', '--dump-dom', url],
            capture_output=True, text=True, timeout=90)
        return out.stdout or None
    except Exception:  # noqa
        return None


def all_js_text():
    parts = []
    for base, _, fs in os.walk(os.path.join(ROOT, 'app', 'web')):
        for f in fs:
            if f.endswith('.js'):
                parts.append(open(os.path.join(base, f), encoding='utf-8').read())
    return ' '.join(parts)


def main():
    st, body = get('/')
    if st is None:
        check('服务已启动', False, f'无法访问 {BASE}（先运行 app/server.py）')
        return summary()
    check('主屏返回 200', st == 200, str(st))
    check('主屏含 2.5D 容器', 'id="house"' in body)
    check('样式与脚本可加载', get('/app.css')[0] == 200 and get('/app.js')[0] == 200)

    st2, api = get('/api/state')
    check('/api/state 可用', st2 == 200)
    data = json.loads(api) if st2 == 200 else {}
    check('状态含设备明细', bool(data.get('devices')), f"{len(data.get('devices') or [])} 台")

    # 历史接口：取一个数值实体验证
    ent = None
    for d in data.get('devices') or []:
        for r in d.get('readings') or []:
            if r.get('unit') and re.match(r'^-?[0-9.]+$', str(r.get('value'))):
                ent = r['entity_id']
                break
        if ent:
            break
    if ent:
        st3, hist = get('/api/history?entity_id=' + urllib.parse.quote(ent) + '&hours=24')
        h = json.loads(hist) if st3 == 200 else {}
        check('历史接口可用且返回结构正确', st3 == 200 and 'points' in h,
              f"{h.get('count', '?')} 个点 · 单位 {h.get('unit', '')}")
    else:
        check('历史接口可用', False, '找不到数值实体')

    # 渲染期检查：真浏览器
    d1 = dom(BASE + '/')
    if d1 is None:
        check('渲染期检查（真浏览器）', False, 'Chrome 不可用')
    else:
        missing = [r for r in ROOMS if r not in d1]
        check('主屏渲染出十个房间', not missing, f'缺 {missing}' if missing else '10/10')
        check('主屏渲染出页脚计数', '台设备' in d1 and '台异常' in d1)
        check('主屏未出现表格/列表', not any(t in d1.split('id="roomPanel"')[0] for t in ('<table', '<ul', '<ol')))

    # 三层链路：深链接直达设备详情，必须出现状态证据与安全域标注
    q = urllib.parse.urlencode({'room': '厨房', 'device': '小米天然气卫士'})
    d2 = dom(BASE + '/?' + q)
    if d2 is None:
        check('设备详情渲染（真浏览器）', False, 'Chrome 不可用')
    else:
        check('设备详情含读数时间（状态证据可追）', '读数时间' in d2)
        check('设备详情含来源', '来源' in d2)
        check('安全域设备被标注', '安全域' in d2)
        check('安全域设备给出「需本机确认」', '需本机确认' in d2)
        check('安全域设备不出现可执行按钮', 'data-act=' not in d2)
        check('未接通清单仍显式标注', '未接通' in d2)

    # PWA（P6 多端）：manifest 与图标必须真的能取到
    st_m, body_m = get('/manifest.webmanifest')
    ok_m = st_m == 200
    if ok_m:
        try:
            man = json.loads(body_m)
            ok_m = man.get('display') == 'standalone' and len(man.get('icons') or []) >= 2
        except ValueError:
            ok_m = False
    check('PWA manifest 可用（standalone + 图标）', ok_m)
    check('PWA 图标可访问', get('/icon-192.png')[0] == 200 and get('/apple-touch-icon.png')[0] == 200)

    # 简报 / 审计 / 额度接口（04 §3·§6）
    st_b, body_b = get('/api/briefing')
    check('简报接口可用', st_b == 200, str(st_b))
    if st_b == 200:
        txt_b = json.loads(body_b).get('text', '')
        check('简报含四段口径', all(k in txt_b for k in ('家里', '需要你注意', '它今天做了', '出声额度')))
    st_a, body_a = get('/api/audit?limit=5')
    check('审计查询接口可用', st_a == 200 and 'summary' in body_a and 'rows' in body_a)
    st_q, body_q = get('/api/quota')
    check('额度接口可用', st_q == 200 and 'level' in body_q)
    check('「更多」已接动作历史（不再是死按钮）', 'api/audit' in all_js_text(), '')

    # 动作按钮分流（03 §1C 第 4 条）
    import json as _json
    devices = data.get('devices') or []
    # 面板兜底可用（02 §8）：可控设备必须真的能点，且能力表来自服务端
    st_c, body_c = get('/api/capabilities')
    caps = json.loads(body_c) if st_c == 200 else {}
    check('能力表接口可用（逐设备单一来源）',
          st_c == 200 and isinstance(caps.get('devices'), dict) and len(caps['devices']) > 0)
    ctrl = next((x for x in devices if x['type'] == 'light' and not x['security_domain']
                 and x['confidence'] == 'online'), None)
    if ctrl:
        q = urllib.parse.urlencode({'room': ctrl['room'], 'device': ctrl['name']})
        page = dom(BASE + '/?' + q)
        check('可控设备在面板上有可执行按钮（02 §8 兜底）', 'data-act=' in page, ctrl['name'])
    ro = next((x for x in devices if x['type'] == 'sensor' and not x['security_domain']), None)
    if ro:
        q = urllib.parse.urlencode({'room': ro['room'], 'device': ro['name']})
        page = dom(BASE + '/?' + q)
        check('只读设备没有开/关按钮', 'data-act=' not in page, ro['name'])

    # 场景：列表 + 预告 + 面板 chips（03 §7 场景可执行、02 §8 兜底）
    st_s, body_s = get('/api/scenes')
    scs = (json.loads(body_s).get('scenes') if st_s == 200 else []) or []
    check('场景接口可用', st_s == 200 and len(scs) >= 3, f'{len(scs)} 个')
    check('场景带影响面（步数/拦截）', all('executable' in x and 'blocked' in x for x in scs))
    try:
        req = urllib.request.Request(BASE + '/api/scene',
                                     data=json.dumps({'scene_id': 'goodnight', 'dry': True}).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=8) as rr:
            pv = json.loads(rr.read().decode())
        check('场景预告说明影响面且不执行', pv.get('dry') is True and '将执行' in (pv.get('preview') or ''))
    except Exception as e:  # noqa
        check('场景预告说明影响面且不执行', False, str(e))
    room0 = next((x['room'] for x in devices if x['room']), None)
    if room0:
        pg = dom(BASE + '/?' + urllib.parse.urlencode({'room': room0}))
        check('房间面板有场景入口（兜底）', 'data-scene=' in pg, room0)

    # 演练接口：安全域必须被拒（不执行）
    try:
        req = urllib.request.Request(BASE + '/api/device-action',
                                     data=json.dumps({'name': '小米天然气卫士', 'action': 'turn_off', 'dry': True}).encode(),
                                     headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=8) as rr:
            out = json.loads(rr.read().decode())
        check('面板接口拒绝安全域设备', out.get('blocked') is True and '安全域' in (out.get('reason') or ''))
    except Exception as e:  # noqa
        check('面板接口拒绝安全域设备', False, str(e))

    sensor = next((d for d in devices if d['type'] == 'sensor' and not d['security_domain']), None)
    if sensor:
        q = urllib.parse.urlencode({'room': sensor['room'], 'device': sensor['name']})
        page = dom(BASE + '/?' + q)
        ok = ('操作（未接通）' not in page) and ('需本机确认' not in page)
        check('只读设备（传感器）不出现开/关动作', ok, sensor['name'])
    sec = next((d for d in devices if d['security_domain']), None)
    if sec:
        q = urllib.parse.urlencode({'room': sec['room'], 'device': sec['name']})
        page = dom(BASE + '/?' + q)
        check('安全域设备显示「需本机确认」', '需本机确认' in page, sec['name'])

    return summary()


def summary():
    # ── 2.5D 空间视图（规范 03 §1/§8 的硬要求）──────────────────────────
    js = open(os.path.join(ROOT, 'app', 'web', 'app.js'), encoding='utf-8').read()
    check('2.5D：标签放房子外侧并带引线（03 §1）', 'function drawOuterLabels' in js
          and 'stroke-dasharray' in js)
    check('2.5D：渲染失败能退回等价列表（03 §8）', 'function drawHouseSafe' in js
          and 'no-3d' in js)
    check('2.5D：房间/设备状态来自实时接口（不是写死）',
          "fetch('/api/state')" in js and 'drawHouseSafe()' in js)
    check('2.5D：选中状态有唯一来源（SEL）', 'SEL.room' in js and 'SEL.device' in js)
    # 生成物页面：几何来自 floorplan，状态运行时读 /api/state
    sp = os.path.join(ROOT, 'app', 'web', 'space', 'index.html')
    check('空间视图是声明生成物（带 generated-by 标记）',
          os.path.exists(sp) and 'name="generated-by"' in open(sp, encoding='utf-8').read())
    check('空间视图不当唯一真相源：运行时读 /api/state',
          os.path.exists(sp) and "/api/state" in open(sp, encoding='utf-8').read())

    # ── 离线壳（P6）：断网诚实页 + SW 注册 + 不吃 API ──────────────────
    idx = open(os.path.join(ROOT, 'app', 'web', 'index.html'), encoding='utf-8').read()
    swp = os.path.join(ROOT, 'app', 'web', 'sw.js')
    offp = os.path.join(ROOT, 'app', 'web', 'offline.html')
    sw = open(swp, encoding='utf-8').read() if os.path.exists(swp) else ''
    off = open(offp, encoding='utf-8').read() if os.path.exists(offp) else ''
    check('离线壳：首页注册 service worker', 'serviceWorker.register' in idx)
    check('离线壳：断网页不显示任何家庭数据', bool(off) and '/api/state' not in off and '离线壳' in off)
    check('离线壳：SW 不缓存 /api 与首页', "startsWith('/api/')" in sw)

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
