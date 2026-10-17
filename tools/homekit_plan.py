#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
苹果侧曝露面清单（05 v1.1 §9-2 · 08 v1.2 §7）

依据（已批准）：
  · 05 §9-2 四条不变量：HA 唯一中枢 / **安全域永不暴露** / 命名房间权威不变（单向同步）/ 外部改动如实入账
  · 08 §7：曝露面**只允许 A 类**（灯、窗帘、空调、插座、温湿度、烟感/水浸/燃气读数）；
    **B 类（在家/离家、作息）与 C 类（门锁、摄像头）永不暴露**

做什么：把"哪些实体可以给苹果侧"算成一张**机器可读的清单**，并生成 HA `homekit:` 配置片段（迁移后直接用）。
不做：不直接改 HA 配置（迁移后才配）；不把安全域混进来。

红线（由门禁 Q32 机械守着）：清单里**出现安全域/门锁/摄像头/在家状态 = 直接红**。

用法：
  python3 tools/homekit_plan.py                 # 生成 data/homekit-exposure.json + 摘要
  python3 tools/homekit_plan.py --yaml          # 额外打印 HA homekit: 配置片段
"""
import argparse
import datetime
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
OUT = os.environ.get('SMART_HOME_HOMEKIT_PLAN') or os.path.join(DATA, 'homekit-exposure.json')
TZ = datetime.timezone(datetime.timedelta(hours=8))

# A 类可暴露的实体域（有状态、能开能关或有读数）
A_DOMAINS = ('light', 'cover', 'climate', 'fan', 'switch', 'media_player', 'sensor', 'binary_sensor')
# 永不暴露：C 类与安全域
NEVER_DOMAINS = ('lock', 'camera', 'device_tracker', 'person', 'vacuum')      # 扫地机启停未实测，不暴露
# 名字里出现这些 → 视为安全/行为类，绝不暴露（保险丝，防止安全域属性漏标）
# 注意：英文词必须加词边界 —— 曾把"电饭煲 keepw**arm**"误判成布防（arm）而拦下正常设备
NEVER_NAME = re.compile(r'门锁|摄像|监控|在家|离家|人体|存在|门窗|布防|燃气阀|'
                        r'\block\b|\bcamera\b|\boccupancy\b|\bpresence\b|\bdoor\b|\bwindow\b|'
                        r'\barm(ed|ing)?\b|\bvalve\b')
# 安全类**读数**（烟感/水浸/燃气）是 A 类且**应当**暴露 → 用苹果的通知做"必须送达"
SAFETY_READING = re.compile(r'烟感|烟雾|smoke|水浸|漏水|水漏|water|燃气|天然气|gas|一氧化碳|煤气|\bco\b')

# 不进苹果侧的两类（不是安全域，但对 Siri 无意义或涉隐私）：
#  · 动作/存在类 → 会暴露"在家/离家"，属 08 §7 B 类，红线
#  · 基础设施（网关/中枢/路由）与按钮（无线开关）→ 不是给人开的设备
MOTION_NAME = re.compile(r'动作|人体|存在|occupancy|presence|\bmotion\b')
INFRA_NAME = re.compile(r'网关|中枢|路由|\bmesh\b|网桥|无线开关')
# 苹果侧显示名的清洗规则（只影响 HomeKit 里的名字，不改米家、不改我们的台账）
BRANDS = ('Yeelight', 'NOVO', 'Xiaomi', 'xiaomi', '米家', '小米', 'Mijia', 'PTXZN', 'Ai')
MODEL_TOKEN = re.compile(r'^(Q\d+|MAX|Pro|Lite|4L|VRF)$')
ROOMS_ALL = ('客厅', '主卧', '厨房', '餐厅', '次卧', '客卫', '主卫', '书房', '阳台', '办公室')


def siri_name(name, room):
    """把米家名清洗成适合 Siri 念的短名：去品牌、去本房间重复、去型号后缀。

    规则（只影响 HomeKit 显示名，不改米家、不改台账）：
      · 品牌前缀（Yeelight/NOVO/Xiaomi/米家/小米/PTXZN/Ai…）反复剥到稳定
      · 去掉开头的"智能"
      · 开关类：`开关-阳台顶灯` → `顶灯`；`开关双开零火版3` → `开关3`
      · 型号/容量后缀（Q800 / 4 MAX / 4L / VRF / Pro / Lite）去掉
      · 只去**本房间**的房间名前缀/后缀（别的房间名保留，用来区分同一台灯的归属）
    """
    s = name or ''
    while True:
        hit = False
        for b in BRANDS:
            if s.startswith(b):
                s = s[len(b):].lstrip()
                hit = True
        if not hit:
            break
    s = re.sub(r'^智能', '', s)
    s = s.replace('玄幻', '玄关')
    s = s.replace('（', ' ').replace('）', ' ').replace('(', ' ').replace(')', ' ')
    s = re.sub(r'[-_/]+', ' ', s)
    toks = []
    for t in s.split():
        if not t or t == room or MODEL_TOKEN.match(t):
            continue
        t = re.sub(r'Q\d+$', '', t)                 # 即热净水器Q800 → 即热净水器
        if t.startswith('开关双开'):
            digits = re.sub(r'\D', '', t)
            t = '开关' + digits
        elif t.startswith('开关') and '灯' in t and t != '开关':
            t = t[2:]
        if room and t.startswith(room) and len(t) > len(room):
            t = t[len(room):]
        if t:
            toks.append(t)
    out = ''.join(toks) if all(re.fullmatch(r'[\u4e00-\u9fa5\d]+', t) for t in toks) else ' '.join(toks)
    out = out.strip()
    if '窗帘' in out and len(out) > 2:
        out = '窗帘'
    if '空气净化器' in out:
        out = '净化器'
    return out or name



def classify(device):
    """把一台设备判成 A / B / C，并给出理由（可回溯）。"""
    name = device.get('name') or ''
    ents = device.get('entities') or []
    if device.get('security_domain'):
        # 安全域里要再分一层（05 v1.1 §9-2 原话：安全类**读数**应当暴露做"必须送达"，
        # 门锁/摄像头/在家状态不暴露）。所以：只放"读数"，绝不放任何可执行动作。
        if SAFETY_READING.search(name) and any(e.startswith(('sensor.', 'binary_sensor.')) for e in ents):
            return 'A-readonly', '安全类**读数**（烟感/水浸/燃气）：只暴露只读实体（苹果侧可通知，不可操作）'
        return 'C', '安全域：宪章第六条 + 08 §7 C 类，永不暴露'
    if NEVER_NAME.search(name):
        return 'C', '名字命中安全/行为类关键词，永不暴露（保险丝）'
    if MOTION_NAME.search(name):
        return 'B', '动作/存在类：给苹果侧等于暴露"在家状态"（08 §7 B 类），永不暴露'
    if INFRA_NAME.search(name):
        return 'X', '基础设施/按钮：不是给人开的设备，进苹果侧只会让 Siri 混乱'
    doms = {e.split('.')[0] for e in ents}
    if doms & {'lock', 'camera', 'device_tracker', 'person'}:
        return 'C', f"含 {sorted(doms & {'lock', 'camera', 'device_tracker', 'person'})} 实体：08 §7 C/B 类"
    if SAFETY_READING.search(name):
        return 'A', '安全类**读数**（烟感/水浸/燃气）：A 类，且应当暴露给苹果侧做"必须送达"通知'
    if device.get('type') in ('lock', 'camera', 'vacuum'):
        return 'C', f"设备类型 {device.get('type')}：不暴露"
    return 'A', '普通可控/可读设备：A 类'


def pick_entity(device):
    """挑一个适合暴露给 HomeKit 的实体（优先有状态的域）。"""
    ents = device.get('entities') or []
    for dom in ('light', 'cover', 'climate', 'fan', 'media_player', 'switch'):
        for e in ents:
            if e.startswith(dom + '.'):
                return e
    for e in ents:
        if e.startswith(('sensor.', 'binary_sensor.')):
            return e
    return None


def pick_readonly_entity(device):
    """安全类读数：**只挑只读实体**（sensor/binary_sensor），绝不挑 switch/valve/button。"""
    for e in device.get('entities') or []:
        if e.startswith(('sensor.', 'binary_sensor.')):
            return e
    return None


def build(state=None):
    st = state or json.load(open(os.path.join(DATA, 'state.json'), encoding='utf-8'))
    include, exclude, skipped = [], [], []
    for d in st.get('devices') or []:
        cls, why = classify(d)
        if cls not in ('A', 'A-readonly'):           # A-readonly 也是要暴露的（只读）
            exclude.append({'device': d['name'], 'room': d.get('room'), 'class': cls, 'reason': why})
            continue
        if cls == 'A-readonly':
            ent = pick_readonly_entity(d)
        else:
            ent = pick_entity(d)
        if not ent:
            skipped.append({'device': d['name'], 'reason': '没有可暴露的实体（只有按钮/事件）'})
            continue
        include.append({'device': d['name'], 'room': d.get('room'), 'entity_id': ent,
                        'domain': ent.split('.')[0], 'name': siri_name(d.get('short_name') or d['name'], d.get('room')),
                        'class': cls, 'readonly': cls == 'A-readonly'})
    doc = {'generated_at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
           'rule': '05 v1.1 §9-2 + 08 v1.2 §7：曝露面只允许 A 类；B/C 类永不暴露',
           'naming': '单向同步：名称取自我们这一层（short_name/米家名），苹果侧改名不回流',
           'include': sorted(include, key=lambda x: (x['room'] or '', x['device'])),
           'exclude': sorted(exclude, key=lambda x: x['device']),
           'skipped': skipped,
           'counts': {'include': len(include), 'exclude': len(exclude), 'skipped': len(skipped)}}
    return doc


def to_yaml(doc, port=21064, pin_hint=True):
    """生成 HA `homekit:` 配置片段（迁移后粘贴即可）。"""
    lines = ['# 由 tools/homekit_plan.py 生成 —— 依据 05 v1.1 §9-2 / 08 v1.2 §7',
             '# 只用 include_entities 白名单：不在名单里的一律不暴露（比黑名单安全）',
             'homekit:',
             '  - name: 家庭工作台',
             f'    port: {port}',
             '    filter:',
             '      include_entities:']
    for x in doc['include']:
        lines.append(f"        - {x['entity_id']}")
    lines += ['    entity_config:']
    for x in doc['include']:
        nm = x['name'].replace("'", '')
        lines.append(f"      {x['entity_id']}:")
        lines.append(f"        name: '{nm}'")
    if pin_hint:
        lines += ['', '# 配对码在 HA 首次启动 homekit 时生成，在 HA 通知里看；']
        lines += ['# 配对时只勾选上表实体 —— **安全域（门锁/摄像头）不在表里，勾不到**。']
    return '\n'.join(lines) + '\n'


def violations(doc):
    """红线自检：清单里不得出现安全域/门锁/摄像头/在家类实体或名字。"""
    bad = []
    for x in doc['include']:
        dom = x['entity_id'].split('.')[0]
        if dom in NEVER_DOMAINS:
            bad.append(f"{x['device']} → {x['entity_id']}（域不该暴露）")
        if NEVER_NAME.search(x['device']) or NEVER_NAME.search(x['entity_id']):
            bad.append(f"{x['device']} → {x['entity_id']}（名字命中安全/行为类）")
        # 安全类读数**只能**是只读实体：任何可执行域出现即红
        if x.get('class') == 'A-readonly' and dom not in ('sensor', 'binary_sensor'):
            bad.append(f"{x['device']} → {x['entity_id']}（安全类只能暴露读数，不能暴露可执行实体）")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--yaml', action='store_true')
    a = ap.parse_args()
    doc = build()
    bad = violations(doc)
    if bad:
        print('❌ 红线自检失败：清单里出现了不该暴露的东西：')
        for b in bad:
            print('   ', b)
        return 1
    os.makedirs(DATA, exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    c = doc['counts']
    print(f"曝露面清单已生成：{OUT}")
    print(f"  可暴露 {c['include']} 台（A 类）· 不暴露 {c['exclude']} 台 · 无可暴露实体 {c['skipped']} 台")
    by_cls = {}
    for x in doc['exclude']:
        by_cls[x['class']] = by_cls.get(x['class'], 0) + 1
    print(f"  排除原因分布：{by_cls}")
    print('  红线自检：通过（无安全域/门锁/摄像头/在家类）')
    if a.yaml:
        print()
        print(to_yaml(doc))
    return 0


if __name__ == '__main__':
    sys.exit(main())
