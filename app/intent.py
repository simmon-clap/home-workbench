#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L3 意图与执行层

依据：
  docs/spec/03-功能与交互规范 v1.1 §2（标准链路）· §3（意图分级）· §4（回执）· §5（部分成功）· §6（撤销）
  docs/spec/04-主动性与出声规范 v1.0 §2（动作轴）· docs/spec/08-安全与隐私规范 v1.1 §2·§3（安全域）
  docs/spec/11-代码规范 v1.0（标准库、无裸 except、凭证不入代码）

做什么：
  一句话 → 意图（单动作/场景/模糊/歧义/安全域/只读查询）
        → 计划（步骤清单，含期望值）
        → 守门（安全域与只读设备一律拒绝自动执行）
        → 执行 + **回读**（执行器可注入；真实执行器见 app/ha.py）
        → 三段式回执（做了什么｜现在什么样｜要不要撤销）
        → 撤销（可逆动作反向执行，并再次回读）

不做什么：
  不自建连接层（执行一律经执行器接口）；不猜设备（歧义就问一句）；不自动动安全域。
"""
import json
import os
import re
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
STATE = os.path.join(DATA, 'state.json')
SCENES = os.path.join(DATA, 'scenes.json')
ACTIONS = os.path.join(DATA, 'actions.json')

# 动作 → (实体域, 服务, 期望状态)；逆动作用于撤销
ACTION_MAP = {
    'turn_on':  ('light', 'turn_on', 'on',   'turn_off'),
    'turn_off': ('light', 'turn_off', 'off', 'turn_on'),
    'open':     ('cover', 'open_cover', 'open', 'close'),
    'close':    ('cover', 'close_cover', 'closed', 'open'),
    'lock':     ('lock', 'lock', 'locked', 'unlock'),
    'unlock':   ('lock', 'unlock', 'unlocked', 'lock'),
}
READONLY_TYPES = {'sensor', 'camera'}
INVERSE_EXPECT = {'turn_on': 'on', 'turn_off': 'off', 'open_cover': 'open',
                  'close_cover': 'closed', 'lock': 'locked', 'unlock': 'unlocked'}
TYPE_WORDS = {
    'light': ['灯', '灯带', '吸顶灯', '筒射灯', '台灯'],
    'cover': ['窗帘', '帘'],
    'ac': ['空调'],
    'plug': ['插座', '开关'],
    'tv': ['电视'],
    'vacuum': ['扫地', '扫地机'],
    'speaker': ['音箱'],
}
SCENE_WORDS = [
    ('goodnight', ['我要睡了', '晚安', '睡觉', '睡了']),
    ('morning', ['早安', '早上好', '起床']),
    ('away', ['我出门了', '离家', '出门', '上班']),
    ('home', ['我回来了', '回家', '到家']),
]
VAGUE_WORDS = ['有点闷', '闷', '有点热', '好热', '太热', '有点冷', '好冷', '太潮', '有点干',
               '有点暗', '太暗', '好暗', '有点亮', '太亮', '刺眼', '晃眼']
SECURITY_WORDS = ['门锁', '开锁', '锁门', '解锁', '摄像头', '监控', '燃气', '天然气', '水浸', '烟感', '布防', '撤防']
QUERY_WORDS = ['怎么样', '什么情况', '如何', '在不在', '状态', '看一下', '家里']


# ═══════════ 载入 ═══════════
def load_state():
    try:
        return json.load(open(STATE, encoding='utf-8'))
    except FileNotFoundError:
        return {'devices': [], 'attention': [], 'summary': {}}


def load_scenes():
    try:
        return json.load(open(SCENES, encoding='utf-8'))
    except FileNotFoundError:
        return {'version': 1, 'scenes': default_scenes()}


def default_scenes():
    """默认场景（结构化、可见、可改）。安全域步骤一律标记为“仅提醒”。"""
    return [
        {'id': 'goodnight', 'name': '晚安', 'enabled': True,
         'steps': [{'selector': {'type': 'light'}, 'action': 'turn_off'},
                   {'selector': {'type': 'cover'}, 'action': 'close'},
                   {'selector': {'type': 'lock'}, 'action': 'lock', 'remind_only': True},
                   {'selector': {'type': 'ac'}, 'action': 'turn_off'}]},
        {'id': 'morning', 'name': '早安', 'enabled': True,
         'steps': [{'selector': {'type': 'cover'}, 'action': 'open'},
                   {'selector': {'type': 'speaker'}, 'action': None}]},
        {'id': 'away', 'name': '离家', 'enabled': True,
         'steps': [{'selector': {'type': 'light'}, 'action': 'turn_off'},
                   {'selector': {'type': 'lock'}, 'action': 'lock', 'remind_only': True}]},
        {'id': 'home', 'name': '回家', 'enabled': True,
         'steps': [{'selector': {'type': 'light'}, 'action': 'turn_on'}]},
    ]


def save_scenes(doc):
    json.dump(doc, open(SCENES, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


# ═══════════ 意图解析 ═══════════
def resolve(text, devices):
    """把一句话解析成目标设备候选。返回 (candidates, matched_room, matched_type)。

    精度顺序：**完整设备名 > 房间+类型 > 房间 > 类型**。
    （否则"把客厅主灯关掉"会被房间里其他灯拉成歧义 —— 2026-10-16 测试抓到的坑。）
    """
    hits = [d for d in devices if d.get('name') and d['name'] in text]
    if hits:
        longest = max(len(d['name']) for d in hits)
        return [d for d in hits if len(d['name']) == longest], None, None
    room = next((r for r in {d['room'] for d in devices} if r and r in text), None)
    mtype = next((t for t, words in TYPE_WORDS.items() if any(w in text for w in words)), None)
    cands = devices
    if room:
        cands = [d for d in cands if d['room'] == room]
    if mtype:
        cands = [d for d in cands if d['type'] == mtype]
    return cands, room, mtype


VAGUE_RULES = [
    (('闷', '热', '不透气', '憋'), ('空气净化器', '新风'), 'turn_on', '我先把空气净化器打开（最轻、可逆的一步）'),
    (('冷', '凉'), ('空调',), 'turn_off', '我先把空调关掉（最轻、可逆的一步）'),
    (('暗', '黑', '看不清'), ('顶灯', '灯带', '灯'), 'turn_on', '我先开一盏灯（最轻、可逆的一步）'),
    (('亮', '刺眼', '晃'), ('顶灯', '灯'), 'turn_off', '我先关掉主灯（最轻、可逆的一步）'),
]


def resolve_vague(text, devices):
    """模糊意图 → 最保守的一步（03 §3）。找不到合适的就返回 None（只问不动手）。"""
    room = next((r for r in {d['room'] for d in devices} if r and r in text), None)
    for words, name_keys, action, note in VAGUE_RULES:
        if not any(w in text for w in words):
            continue
        pool = [d for d in devices if not d.get('security_domain') and d.get('type') not in READONLY_TYPES
                and '网关' not in (d.get('name') or '')]   # 网关是控制中枢，动它影响一片，谈不上"最轻"
        if room:
            pool = [d for d in pool if d['room'] == room]
        for key in name_keys:
            hit = next((d for d in pool if key in (d.get('name') or '')), None)
            if hit:
                verb = {'turn_on': '打开', 'turn_off': '关掉'}.get(action, action)
                return {'target': hit['name'], 'action': action,
                        'note': f"我先把「{hit['name']}」{verb}（最轻、可逆的一步）"}
    return None


def parse(text, state=None):
    """解析一句话。返回结构化意图（不执行任何动作）。"""
    state = state or load_state()
    devices = state.get('devices') or []
    raw = (text or '').strip()
    intent = {'raw': raw, 'kind': 'unknown', 'confidence': 'low'}

    if not raw:
        intent.update(kind='unknown', reply='我没听清，你再说一遍？')
        return intent

    if any(w in raw for w in SECURITY_WORDS):
        cands, room, _ = resolve(raw, devices)
        sec = [d for d in cands if d['security_domain']] or [d for d in devices if d['security_domain'] and d['room'] == room]
        names = [d['name'] for d in sec][:3]
        intent.update(kind='security', devices=[d['name'] for d in names and sec or []],
                      reply='安全类动作我不代为执行（08 规范第 3 节）：声纹可伪造、聊天可被冒充。'
                            + (f'涉及：{"、".join(names)}。' if names else '')
                            + '请在米家 App 里手动操作。')
        return intent

    if any(w in raw for w in QUERY_WORDS) and not any(w in raw for w in ('开', '关', '打开', '关闭', '调')):
        intent.update(kind='query', confidence='high')
        return intent

    for sid, words in SCENE_WORDS:
        if any(w in raw for w in words):
            intent.update(kind='scene', scene=sid, confidence='high')
            return intent

    if any(w in raw for w in VAGUE_WORDS):
        # 03 §3「模糊意图」：按**最保守的可逆解释**先做最小一步，回执里说明；找不到就只问不动手
        v = resolve_vague(raw, devices)
        if v:
            intent.update(kind='single', action=v['action'], target=v['target'], confidence='medium',
                          vague_note=v['note'] + '，要更彻底你再说一声')
            return intent
        intent.update(kind='vague', confidence='low',
                      reply='这句话我能理解成好几件事，且我这儿没有"最轻的那一步"可做。'
                            '你是想开空调、开灯，还是先看看数据？')
        return intent

    act = None
    if re.search(r'(打开|开|开启)', raw):
        act = 'turn_on'
    if re.search(r'(关闭|关掉|关上|关)', raw):
        act = 'turn_off'
    if act:
        cands, room, mtype = resolve(raw, devices)
        for d in cands:
            if d['type'] == 'cover':
                act = 'open' if act == 'turn_on' else 'close'
                break
        if not cands:
            intent.update(kind='unknown', reply='这台设备我这儿没有，或者名字对不上（我没有改过任何设备名）。')
            return intent
        if len(cands) > 1:
            # 03 §3：**指名了房间或类型就不是歧义** —— "把客厅的灯关掉"＝客厅所有灯；
            # 只有"那盏灯"这种没有限定、跨房间多候选时，才问一句（一次只问一个）。
            if room:
                intent.update(kind='single', action=act, targets=[d['name'] for d in cands],
                              target=cands[0]['name'], confidence='high')
                return intent
            intent.update(kind='ambiguous', action=act, options=[d['name'] for d in cands[:4]],
                          reply=f"你说的是哪一台？{ '、'.join(d['name'] for d in cands[:3]) }")
            return intent
        intent.update(kind='single', action=act, target=cands[0]['name'], confidence='high')
        return intent

    intent.update(kind='unknown', reply='这句话我还理解不了，换个说法？')
    return intent


# ═══════════ 计划（把意图展开成步骤） ═══════════
def pick_entity(device, domain):
    for e in device.get('entities') or []:
        if e.startswith(domain + '.'):
            return e
    return device.get('entity_id')


def plan_steps(intent_, state=None, scenes=None):
    """展开成步骤清单：[{device, entity_id, domain, service, expect, security, readonly, remind_only}]"""
    state = state or load_state()
    devices = {d['name']: d for d in state.get('devices') or []}
    steps = []

    def add(dev, action, remind_only=False):
        act = action or 'turn_off'
        # 窗帘没有"开/关"服务：按设备类型归一化（03 §8 只读语义之外的正常可控设备）
        if dev.get('type') == 'cover':
            act = 'open' if act == 'turn_on' else 'close'
        dom, svc, expect, _inv = ACTION_MAP.get(act, ('light', 'turn_on', 'on', 'turn_off'))
        # 以设备**真实实体**为准解析域与服务（panel_action 是唯一解析器）：
        # 否则会出现"给 button.*_toggle 发 light.turn_on"这类错（2026-10-17 实测）
        try:
            import panel_action as _P
            real = _P.actions_for(dev).get(act)
            if real:
                dom, svc, expect = real['domain'], real['service'], real['expect']
        except Exception:  # noqa
            pass
        ent = None
        try:
            import panel_action as _P2
            _r = _P2.actions_for(dev).get(act)
            ent = _r and _r['entity_id']
        except Exception:  # noqa
            ent = None
        steps.append({'device': dev['name'], 'room': dev['room'], 'entity_id': ent or pick_entity(dev, dom),
                      'domain': dom, 'service': svc, 'expect': expect,
                      'security': bool(dev.get('security_domain')),
                      'readonly': dev.get('type') in READONLY_TYPES,
                      'remind_only': bool(remind_only or dev.get('security_domain'))})

    kind = intent_['kind']
    if kind == 'single':
        # 指名房间的"把客厅的灯关掉"会带 targets（多台）：逐一展开成步骤
        names = intent_.get('targets') or ([intent_['target']] if intent_.get('target') else [])
        for nm in names:
            d = devices.get(nm)
            if d:
                add(d, intent_.get('action') or 'turn_on')
    elif kind == 'scene':
        doc = scenes or load_scenes()
        sc = next((s for s in doc.get('scenes', []) if s['id'] == intent_.get('scene') and s.get('enabled')), None)
        if sc:
            for st in sc['steps']:
                sel = st.get('selector') or {}
                if st.get('action') is None:
                    continue
                for d in (state.get('devices') or []):
                    if sel.get('type') and d['type'] != sel['type']:
                        continue
                    if sel.get('room') and d['room'] != sel['room']:
                        continue
                    add(d, st['action'], st.get('remind_only', False))
    elif kind == 'vague':
        # 最保守的一步：房间里有除湿/新风类设备就动它，否则只回话不动手
        for d in (state.get('devices') or []):
            if d.get('type') == 'plug' and '新风' in d['name']:
                add(d, 'turn_on')
                break
    return steps


def guard(steps):
    """守门：安全域与只读设备一律不自动执行。返回 (可执行步骤, 被拦截步骤)。"""
    doable, blocked = [], []
    for s in steps:
        if s['security'] or s['remind_only']:
            blocked.append({**s, 'reason': '安全域：只提醒，不自动执行（08 §2）'})
        elif s['readonly']:
            blocked.append({**s, 'reason': '只读设备：不执行开/关（03 §1C）'})
        else:
            doable.append(s)
    return doable, blocked


# ═══════════ 执行 + 回读（执行器可注入） ═══════════
class FakeExecutor:
    """测试用：不改真设备，只按脚本返回回读结果。"""

    def __init__(self, fail_on=None, readback_mismatch=None):
        self.calls = []
        self.fail_on = set(fail_on or [])
        self.mismatch = set(readback_mismatch or [])

    def call(self, step):
        self.calls.append(step)
        if step['device'] in self.fail_on:
            raise RuntimeError('设备离线')
        return {'ok': True}

    def read_back(self, step, timeout=2.0):
        if step['device'] in self.mismatch:
            return False, 'on' if step['expect'] == 'off' else 'off', 0.1
        return True, step['expect'], 0.1


def execute(steps, executor):
    """逐步执行 + 每步回读。返回结果清单（含回读值）。"""
    results = []
    for s in steps:
        rec = {'device': s['device'], 'room': s['room'], 'service': s['service'],
               'entity_id': s['entity_id'], 'expect': s['expect'], 'ok': False, 'readback': None,
               'error': None}
        try:
            executor.call(s)
        except Exception as e:  # noqa  —— 失败必须显式记录，不许吞（11 §5）
            rec['error'] = f'{type(e).__name__}: {e}'
            results.append(rec)
            continue
        ok, actual, cost = executor.read_back(s)
        rec.update(ok=bool(ok), readback=actual, readback_seconds=cost)
        if not ok:
            rec['error'] = f'回读与预期不符（期望 {s["expect"]}，实际 {actual}）'
        results.append(rec)
    return results


# ═══════════ 三段式回执 ═══════════
SERVICE_WORD = {'light.turn_on': '打开', 'light.turn_off': '关掉', 'cover.open_cover': '拉开',
                'cover.close_cover': '合上', 'climate.turn_on': '打开', 'climate.turn_off': '关掉',
                'switch.turn_on': '打开', 'switch.turn_off': '关掉'}


def dry_receipt(steps, blocked, note):
    """演练（或未确认）时的回执：**先说要做什么，再说为什么没执行**。

    之前这里直接调 receipt([], ...) 会输出"没有需要执行的动作"—— 明明有计划却说没动作，
    与事实不符（实测抓到）。
    """
    lines = []
    if steps:
        shown = '、'.join(f"{s['device']}（{SERVICE_WORD.get(s['domain'] + '.' + s['service'], s['service'])}）"
                          for s in steps[:3])
        lines.append(f"将执行 {len(steps)} 步：{shown}" + ('…' if len(steps) > 3 else ''))
    else:
        lines.append('没有需要执行的动作')
    lines.append(note)
    if blocked:
        lines.append('未执行（按规范拦截）：' + '、'.join(f"{b['device']}（{b['reason']}）" for b in blocked[:3]))
    return '\n'.join([x for x in lines if x])


def query_reply(state=None):
    """闲聊/查看类：只读，回答状态真相（03 §3）。安全域只说"有几件"，不在对话里报门锁明细。"""
    state = state or load_state()
    s = state.get('summary') or {}
    if not s:
        return '状态还没生成，稍后再问我一次。'
    lines = [f"家里 {s.get('total', 0)} 台设备：在线 {s.get('online', 0)}、"
             f"离线 {s.get('offline', 0)}"
             + (f"、未上报 {s.get('unknown', 0)}" if s.get('unknown') else '')]
    att = s.get('attention_count', 0)
    if att:
        sec = s.get('attention_sec', 0)
        lines.append(f"需要你注意 {att} 项" + (f"（其中安全 {sec} 项，明细在工作台里看）" if sec else ''))
    else:
        lines.append('没有需要你注意的事')
    heads = [a for a in (state.get('attention') or []) if a.get('level') != 'sec'][:3]
    for a in heads:
        lines.append(f"· {a.get('room', '')}·{a.get('device', '')}：{a.get('issue', '')}")
    lines.append('要做什么跟我说一声；安全的那些我只提醒，不代为执行。')
    return '\n'.join(lines)


def receipt(results, blocked, expect_note=None):
    done = [r for r in results if r['ok']]
    failed = [r for r in results if not r['ok']]
    parts = []
    if done:
        parts.append(f"{len(done)} 项已完成（{'、'.join(r['device'] for r in done[:3])}）")
    if failed:
        parts.append(f"{len(failed)} 项没做成（{'、'.join(r['device'] + '：' + (r['error'] or '') for r in failed[:2])}）")
    if not results and not blocked:
        parts.append('没有需要执行的动作')
    head = '、'.join(parts) if parts else '未执行'
    now = expect_note or (f"当前：{done[0]['readback'] if done else '—'}（回读确认）")
    tail = '要撤销吗？' if done else ('需要我记一条待办吗？' if blocked else '')
    lines = [head, now]
    if blocked:
        lines.append('未执行（按规范拦截）：' + '、'.join(f"{b['device']}（{b['reason']}）" for b in blocked[:3]))
    lines.append(tail)
    return '\n'.join([x for x in lines if x])


# ═══════════ 动作记录与撤销 ═══════════
def record(intent_, results, blocked):
    doc = {'version': 1, 'actions': []}
    if os.path.exists(ACTIONS):
        try:
            doc = json.load(open(ACTIONS, encoding='utf-8'))
        except Exception:  # noqa
            doc = {'version': 1, 'actions': []}
    entry = {'id': uuid.uuid4().hex[:12], 'at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
             'raw': intent_.get('raw'), 'kind': intent_.get('kind'),
             'results': results, 'blocked': [{'device': b['device'], 'reason': b['reason']} for b in blocked],
             'undone': False}
    doc['actions'].append(entry)
    json.dump(doc, open(ACTIONS, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return entry


def undo(action_id, executor=None):
    """撤销：对可逆且已成功的步骤反向执行，并再次回读。安全域从不执行，也就无从撤销。"""
    doc = json.load(open(ACTIONS, encoding='utf-8')) if os.path.exists(ACTIONS) else {'actions': []}
    entry = next((a for a in doc['actions'] if a['id'] == action_id), None)
    if not entry:
        return {'ok': False, 'error': '找不到这条动作记录'}
    if entry.get('undone'):
        return {'ok': False, 'error': '这条已经撤销过了'}
    undo_steps, results = [], []
    for r in entry['results']:
        if not r['ok']:
            continue
        inv = ACTION_MAP.get(r['service'], (None, None, None, None))[3]
        if not inv or r['service'] in ('lock', 'unlock'):
            continue          # 安全域动作不执行、也不撤销
        domain = r['entity_id'].split('.')[0] if r['entity_id'] else 'light'
        undo_steps.append({'device': r['device'], 'room': r['room'], 'entity_id': r['entity_id'],
                           'domain': domain, 'service': inv,
                           'expect': INVERSE_EXPECT.get(inv)})   # 撤销也要有期望值，否则回读等于没验证
    if executor is None:
        return {'ok': False, 'error': '未提供执行器：撤销需要真实执行能力', 'steps': undo_steps}
    for s in undo_steps:
        rec = {'device': s['device'], 'service': s['service'], 'ok': False, 'readback': None, 'error': None}
        try:
            executor.call(s)
            ok, actual, _ = executor.read_back(s)
            rec.update(ok=bool(ok), readback=actual)
        except Exception as e:  # noqa
            rec['error'] = f'{type(e).__name__}: {e}'
        results.append(rec)
    entry['undone'] = True
    entry['undo_results'] = results
    json.dump(doc, open(ACTIONS, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return {'ok': all(r['ok'] for r in results) if results else False,
            'results': results, 'note': '撤销要真的撤销（读回确认），不是标记'}


# ═══════════ 端到端（供界面/对话调用） ═══════════
def handle(text, executor=None, state=None, dry_run=True, dry_note=None):
    """一句话 → 完整链路。dry_run=True 时只到守门为止（不执行）——当前默认如此，
    因为真实执行需要 HA 令牌（见 app/ha.py）。"""
    state = state or load_state()
    intent_ = parse(text, state)
    out = {'intent': intent_, 'steps': [], 'results': [], 'blocked': [], 'receipt': ''}
    if intent_['kind'] in ('unknown', 'security', 'ambiguous', 'query'):
        out['receipt'] = intent_.get('reply', '') or query_reply(state)
        return out
    steps = plan_steps(intent_, state)
    doable, blocked = guard(steps)
    out['steps'], out['blocked'] = steps, blocked
    if dry_run or executor is None:
        # 未执行的原因必须**说真的**：可能是"没配令牌"，也可能只是"这个入口默认只演练"
        if dry_note is None:
            dry_note = '（未执行：未配置 HA 访问令牌）'
            try:
                import ha
                if ha.configured():
                    dry_note = '（未执行：默认只演练；要真执行加 execute=1）'
            except Exception:  # noqa
                pass
        out['receipt'] = dry_receipt(doable, blocked, intent_.get('vague_note') or dry_note)
        return out
    results = execute(doable, executor)
    out['results'] = results
    # 审计留痕：成功/失败逐条记，被拒也记（08 §4）
    import sys as _sys
    _sys.path.insert(0, os.path.join(ROOT, 'app'))
    import audit as _audit
    for r in results:
        _audit.log(action=r['service'], target=r['entity_id'] or r['device'], channel='对话',
                   authorization='对话授权', result='ok' if r['ok'] else 'failed',
                   readback=r.get('readback'), detail=r.get('error'))
    for b in blocked:
        _audit.log(action='refused', target=b.get('entity_id') or b['device'], channel='对话',
                   authorization='不适用', result='blocked', readback=None, detail=b['reason'])
    out['receipt'] = receipt(results, blocked)
    out['action_id'] = record(intent_, results, blocked)['id']
    return out


if __name__ == '__main__':
    import sys
    txt = ' '.join(sys.argv[1:]) or '我要睡了'
    res = handle(txt)
    print(json.dumps(res, ensure_ascii=False, indent=1))
