#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
场景的结构化模型（可见 / 可编辑 / 可停用 / 可回滚 / 能自然语言复述）

依据：docs/spec/03-功能与交互规范 v1.2 §7
  「结构化场景必须**可见、可编辑、可停用、可回滚**，同时用自然语言复述一遍」
  验收第 8 条：「场景可查看、可编辑、可停用，且能自然语言复述」

数据：`data/scenes.json`（与 intent.plan_steps 共用同一份结构）
  {'version':1, 'scenes':[{id,name,enabled,steps:[{selector:{type,room},action,remind_only}],history:[...]}]}

只做场景这一件事；执行仍由 intent + panel_action 负责（L3 分层不变）。
"""
import datetime
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
SCENES = os.environ.get('SMART_HOME_SCENES') or os.path.join(DATA, 'scenes.json')
TZ = datetime.timezone(datetime.timedelta(hours=8))

# 动作 → 人话（复述用）；type → 人话
ACT_WORDS = {'turn_on': '打开', 'turn_off': '关掉', 'open': '拉开', 'close': '合上', 'lock': '上锁'}
TYPE_WORDS = {'light': '灯', 'cover': '窗帘', 'ac': '空调', 'plug': '插座', 'tv': '电视',
              'speaker': '音箱', 'vacuum': '扫地机', 'lock': '门锁'}
ALLOWED_STEPS = ('turn_on', 'turn_off', 'open', 'close', 'lock')


def _load():
    try:
        return json.load(open(SCENES, encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        import intent as _i
        return {'version': 1, 'scenes': _i.default_scenes()}


def _save(doc):
    json.dump(doc, open(SCENES, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def _hist(doc, scene, field, before, after, note=''):
    scene.setdefault('history', []).append({
        'at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
        'field': field, 'from': before, 'to': after, 'note': note})


def list_scenes():
    return _load().get('scenes') or []


def get(sid):
    return next((s for s in list_scenes() if s.get('id') == sid), None)


def describe(scene):
    """把结构化场景复述成一句人话（规范 §7 要求"同时用自然语言复述一遍"）。"""
    if not scene:
        return ''
    parts = []
    for st in scene.get('steps') or []:
        sel = st.get('selector') or {}
        what = TYPE_WORDS.get(sel.get('type'), sel.get('type') or '设备')
        where = f"{sel['room']}的" if sel.get('room') else ''
        if st.get('action') is None:
            continue
        act = ACT_WORDS.get(st['action'], st['action'])
        tail = '（只提醒，需你在米家手动）' if st.get('remind_only') else ''
        parts.append(f"{where}{what}{act}{tail}")
    head = scene.get('name', scene.get('id', '?'))
    if not parts:
        return f"{head}：还没有步骤"
    return f"{head} = " + '、'.join(parts) + f"（共 {len(parts)} 步）"


def view():
    """给界面/接口用的视图：含复述、步骤数、停用状态。"""
    out = []
    for s in list_scenes():
        out.append({'id': s.get('id'), 'name': s.get('name'), 'enabled': bool(s.get('enabled')),
                    'steps': len([x for x in (s.get('steps') or []) if x.get('action')]),
                    'describe': describe(s),
                    # 带上**真实索引**：界面只显示有动作的步骤，但删除要按真实索引来（否则删错步）
                    'step_list': [{'index': i, 'selector': x.get('selector'), 'action': x.get('action'),
                                   'remind_only': bool(x.get('remind_only')),
                                   'describe': describe({'name': '', 'steps': [x]})[3:]}
                                  for i, x in enumerate(s.get('steps') or [])]})
    return out


def set_enabled(sid, enabled):
    """可停用 / 可启用。"""
    doc = _load()
    s = next((x for x in doc['scenes'] if x.get('id') == sid), None)
    if not s:
        return False, f'没有这个场景：{sid}'
    before = bool(s.get('enabled'))
    s['enabled'] = bool(enabled)
    _hist(doc, s, 'enabled', before, bool(enabled), '停用' if not enabled else '启用')
    _save(doc)
    return True, f"{s['name']} 已{'启用' if enabled else '停用'}"


def add_step(sid, action, type_, room=None, remind_only=False):
    """加一步。安全域动作一律标成"只提醒"（08 §2 不自动执行）。"""
    if action not in ALLOWED_STEPS:
        return False, f'不支持的动作：{action}'
    if type_ not in TYPE_WORDS:
        return False, f'不认识的设备类型：{type_}'
    doc = _load()
    s = next((x for x in doc['scenes'] if x.get('id') == sid), None)
    if not s:
        return False, f'没有这个场景：{sid}'
    sel = {'type': type_}
    if room:
        sel['room'] = room
    step = {'selector': sel, 'action': action}
    if remind_only or type_ == 'lock':
        step['remind_only'] = True
    s.setdefault('steps', []).append(step)
    _hist(doc, s, 'steps', len(s['steps']) - 1, len(s['steps']), f'加一步：{describe({"name": "", "steps": [step]})[3:]}')
    _save(doc)
    return True, f"{s['name']} 加了一步：{describe({'name': '', 'steps': [step]})[3:]}"


def remove_step(sid, index):
    doc = _load()
    s = next((x for x in doc['scenes'] if x.get('id') == sid), None)
    if not s:
        return False, f'没有这个场景：{sid}'
    steps = s.get('steps') or []
    if not (0 <= index < len(steps)):
        return False, f'步骤序号超出范围：{index}'
    gone = steps.pop(index)
    _hist(doc, s, 'steps', gone, None, '删一步')
    _save(doc)
    return True, f"{s['name']} 删掉了一步"


def undo(sid):
    """可回滚：撤销这个场景最近一次改动。"""
    doc = _load()
    s = next((x for x in doc['scenes'] if x.get('id') == sid), None)
    if not s:
        return False, f'没有这个场景：{sid}'
    hist = s.get('history') or []
    if not hist:
        return False, '这个场景还没有可回滚的改动'
    h = hist.pop()
    if h['field'] == 'enabled':
        s['enabled'] = h['from']
    elif h['field'] == 'steps' and h.get('to') is not None and h.get('from') is not None:
        # 加了一步 → 删掉它
        if len(s.get('steps') or []) > h['to'] - 1:
            s['steps'].pop(h['to'] - 1)
    elif h['field'] == 'steps' and h.get('to') is None:
        s.setdefault('steps', []).insert(min(h.get('from') if isinstance(h.get('from'), int) else 0,
                                             len(s.get('steps') or [])), h['from'])
    s['history'] = hist
    _save(doc)
    return True, f"{s['name']} 已回滚上一次改动"


def summary():
    sc = list_scenes()
    return {'scenes': len(sc), 'enabled': sum(1 for s in sc if s.get('enabled')),
            'steps': sum(len([x for x in (s.get('steps') or []) if x.get('action')]) for s in sc)}


if __name__ == '__main__':
    print(json.dumps(summary(), ensure_ascii=False))
    for s in view():
        print(f"  [{'启用' if s['enabled'] else '停用'}] {s['describe']}")
