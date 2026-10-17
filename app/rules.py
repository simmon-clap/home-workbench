#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
规则（自然语言创建的场景/自动化）

依据：docs/spec/03-功能与交互规范 v1.3 §7
  「自然语言创建：'每天 22:30 之后如果客厅没人就把灯关了' → 生成**结构化场景**；
    必须可见、可编辑、可停用、可回滚，同时用自然语言复述一遍（"我理解成……对吗？"）」

落点：**HA 是底座**（05 §2）——规则最终写成 `config/homeassistant/automations.yaml` 里的
一条 automation，再 `automation.reload`，并**回读**确认实体真的出现了（05 §4 执行必回读）。

诚实边界：条件里的"有没有人"必须有**可用的人体/存在传感器**才做得了；
没有就明说做不了，并给出可替代的更简单规则 —— 不生成一条永远不成立的自动化。
"""
import datetime
import json
import os
import sys
import re
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
RULES = os.environ.get('SMART_HOME_RULES') or os.path.join(DATA, 'rules.json')
import ha_paths
HA_CONFIG = ha_paths.ha_config_dir()                     # 统一来源（env: SMART_HOME_HA_CONFIG）
AUTOMATIONS = os.path.join(HA_CONFIG, 'automations.yaml')
TZ = datetime.timezone(datetime.timedelta(hours=8))

# 动作识别：中文语序两种都有 ——「关掉客厅的灯」（动词在前）与「客厅的灯关了」（名词在前）
NOUNS = {'light': ('灯', '照明'), 'cover': ('窗帘', '帘'), 'ac': ('空调',)}
OFF_WORDS = ('关掉', '关闭', '关上', '关了', '关', '熄灭', '灭', '合上', '拉上', '停')
ON_WORDS = ('打开', '拉开', '开了', '开', '亮')
ACTION_WORD = {('light', 'turn_off'): '关掉{room}的灯', ('light', 'turn_on'): '打开{room}的灯',
               ('cover', 'close'): '合上{room}的窗帘', ('cover', 'open'): '拉开{room}的窗帘',
               ('ac', 'turn_off'): '关掉{room}的空调', ('ac', 'turn_on'): '打开{room}的空调'}


def detect_action(text):
    """在名词附近（前后 6 个字内）找动词，判断开/关。返回 (类型, 动作) 或 None。"""
    best = None
    for typ, words in NOUNS.items():
        for w in words:
            i = text.find(w)
            if i < 0:
                continue
            near = text[max(0, i - 6): i + len(w) + 6]
            for v in OFF_WORDS:
                if v in near:
                    cand = (typ, 'turn_off' if typ != 'cover' else 'close', abs(near.find(v) - 6))
                    best = min(best, cand, key=lambda x: x[2]) if best else cand
                    break
            for v in ON_WORDS:
                if v in near:
                    cand = (typ, 'turn_on' if typ != 'cover' else 'open', abs(near.find(v) - 6))
                    best = min(best, cand, key=lambda x: x[2]) if best else cand
                    break
    return (best[0], best[1]) if best else None


def _load(path, default):
    try:
        return json.load(open(path, encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return default


def rooms():
    st = _load(os.path.join(DATA, 'state.json'), {'devices': []})
    return sorted({d['room'] for d in st.get('devices') or [] if d.get('room')})


def presence_entities():
    """按房间列出可用的人体/存在传感器（含 event 实体；stateful 才适合做 for 条件）。"""
    try:
        sys_path = os.path.join(ROOT, 'app')
        import sys
        sys.path.insert(0, sys_path)
        import ha
        states = json.loads(json.dumps(ha._req('/api/states'))) if ha.configured() else []
    except Exception:  # noqa
        states = []
    st = _load(os.path.join(DATA, 'state.json'), {'devices': []})
    ent2room = {e: (d['room'], d['name']) for d in st.get('devices') or [] for e in (d.get('entities') or [])}
    out = {}
    for s in states:
        if (s.get('attributes') or {}).get('device_class') in ('motion', 'occupancy', 'presence'):
            room, name = ent2room.get(s['entity_id'], (None, None))
            if room:
                out.setdefault(room, []).append({'entity_id': s['entity_id'], 'name': name,
                                                 'kind': s['entity_id'].split('.')[0]})
    return out


def parse(text, state=None):
    """把一句话解析成结构化规则提案（**不写入任何东西**）。"""
    raw = (text or '').strip()
    out = {'raw': raw, 'kind': 'rule', 'confidence': 'low'}
    if not raw:
        return {**out, 'ok': False, 'recap': '没听清，再说一遍？'}

    # 触发：每天 HH:MM（之后 / 时 / 无"之后"也算）
    m = re.search(r'(?:每天|每日)?\s*(\d{1,2})[:：点](\d{1,2})?\s*(?:之后|后|时|的时候)?', raw)
    trigger = None
    if m and ('每天' in raw or '每日' in raw or re.search(r'\d{1,2}[:：点]\d{1,2}', raw)):
        hh = int(m.group(1)); mm = int(m.group(2) or 0)
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            trigger = {'type': 'time', 'at': f'{hh:02d}:{mm:02d}'}
    # 条件：<房间> 没人 / 没有人 / 无人
    cond = None
    room_in_cond = next((r for r in rooms() if r in raw and re.search(rf'{re.escape(r)}.{{0,6}}(没人|没有人|无人)', raw)), None)
    if room_in_cond:
        cond = {'type': 'no_presence', 'room': room_in_cond}
    # 动作
    action = None
    det = detect_action(raw)
    if det:
        action = {'type': det[0], 'action': det[1]}
    # 动作的房间：优先动作附近的房间名，否则用条件里的房间，否则全屋
    act_room = None
    for r in rooms():
        if re.search(rf'{re.escape(r)}.{{0,4}}(的)?(灯|照明|窗帘|帘|空调)', raw):
            act_room = r
            break
    act_room = act_room or (cond or {}).get('room')
    if action:
        action['room'] = act_room

    out.update({'trigger': trigger, 'condition': cond, 'action': action})
    out['recap'] = describe(out)
    out['ok'] = bool(action)
    # 可行性：条件需要该房间有人体传感器
    if cond:
        pres = presence_entities().get(cond['room']) or []
        out['condition_feasible'] = bool(pres)
        out['presence'] = pres
    else:
        out['condition_feasible'] = True
    return out


def describe(rule):
    """自然语言复述（规范 §7 明确要求"我理解成……对吗？"）。"""
    t = rule.get('trigger')
    c = rule.get('condition')
    a = rule.get('action')
    if not a:
        return '我没听懂要做什么动作（比如"关灯"）'
    when = f"每天 {t['at']} 之后" if t else '你说一声的时候'
    cond = f"，如果{c['room']}连续一段时间没人" if c else ''
    room = a.get('room') or '全屋'
    act = ACTION_WORD.get((a['type'], a['action']), '执行动作').format(room=room)
    return f"我理解成：{when}{cond}，就{act}。对吗？"


def needs(rule):
    """还缺什么（用于追问一句，别连环问）。"""
    if not rule.get('action'):
        return '要做的是哪件事？（例如"关掉客厅的灯"）'
    if rule.get('condition') and not rule.get('condition_feasible'):
        room = rule['condition']['room']
        return (f"{room}里我没有人体/存在传感器，判断不了「有没有人」。"
                f"可以改成不带条件的：每天 {rule['trigger']['at'] if rule.get('trigger') else '——'} 就"
                + (ACTION_WORD.get((rule['action']['type'], rule['action']['action']), '执行').format(room=rule['action'].get('room') or '全屋'))
                + '。要这样吗？')
    return None


# ═══════════ 存储与执行 ═══════════
def _rules_doc():
    d = _load(RULES, None) or {'version': 1, 'rules': []}
    d.setdefault('rules', [])
    return d


def save(doc):
    json.dump(doc, open(RULES, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def list_rules():
    return _rules_doc()['rules']


def add_proposal(rule):
    doc = _rules_doc()
    rid = uuid.uuid4().hex[:8]
    entry = {'id': rid, 'status': 'proposed', 'created_at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
             'recap': rule.get('recap'), 'trigger': rule.get('trigger'), 'condition': rule.get('condition'),
             'action': rule.get('action'), 'source_text': rule.get('raw'), 'history': []}
    doc['rules'].append(entry)
    save(doc)
    return entry


def _yaml_rule(entry, entities):
    """把规则渲染成 HA automation（YAML 片段）。只支持我们自己的已知结构，安全。"""
    alias = entry.get('recap', '').replace('\n', ' ')[:40] or entry['id']
    lines = [f"- id: 'smarthome_{entry['id']}'", f"  alias: '{alias}'"]
    t = entry.get('trigger')
    if t and t.get('type') == 'time':
        lines += ['  trigger:', '    - platform: time', f"      at: '{t['at']}:00'"]
    else:
        lines += ['  trigger:', '    - platform: event', '      event_type: smarthome_manual']
    c = entry.get('condition')
    if c:
        for eid in entities:
            lines += ['  condition:', '    - condition: state', f'      entity_id: {eid}',
                      "      state: 'off'", '      for:', "        minutes: 10"]
            break
    a = entry['action']
    svc_dom = {'light': 'light', 'cover': 'cover', 'ac': 'climate'}[a['type']]
    svc = {'turn_off': 'turn_off', 'turn_on': 'turn_on', 'open': 'open_cover', 'close': 'close_cover'}[a['action']]
    rule = {'light': 'light', 'cover': 'cover', 'ac': 'climate'}[a['type']]
    lines += ['  action:', f'    - service: {svc_dom}.{svc}', '      target:', '        entity_id:']
    for eid in entities:
        lines.append(f'          - {eid}')
    return '\n'.join(lines) + '\n'


WRITE_MODE = os.environ.get('SMART_HOME_RULE_WRITE', 'auto')   # auto | api | yaml


def _rule_dict(entry, entities):
    """规则的**字典形态**（官方配置接口要的就是这个）。

    与 `_yaml_rule()` 必须描述同一件事 —— 测试里逐字段比对，防止两条路各自漂移。
    """
    alias = entry.get('recap', '').replace('\n', ' ')[:40] or entry['id']
    t = entry.get('trigger')
    if t and t.get('type') == 'time':
        trigger = [{'platform': 'time', 'at': f"{t['at']}:00"}]
    else:
        trigger = [{'platform': 'event', 'event_type': 'smarthome_manual'}]
    rule = {'id': f"smarthome_{entry['id']}", 'alias': alias, 'trigger': trigger}
    if entry.get('condition'):
        for eid in entities:
            rule['condition'] = [{'condition': 'state', 'entity_id': eid,
                                  'state': 'off', 'for': {'minutes': 10}}]
            break
    a = entry['action']
    svc_dom = {'light': 'light', 'cover': 'cover', 'ac': 'climate'}[a['type']]
    svc = {'turn_off': 'turn_off', 'turn_on': 'turn_on',
           'open': 'open_cover', 'close': 'close_cover'}[a['action']]
    rule['action'] = [{'service': f'{svc_dom}.{svc}', 'target': {'entity_id': list(entities)}}]
    return rule


def _write_mode():
    """实际用哪条路写：api（官方接口，迁移后唯一可行）或 yaml（写本地文件）。"""
    if WRITE_MODE == 'yaml':
        return 'yaml'
    try:
        import sys as _s
        _s.path.insert(0, os.path.join(ROOT, 'app'))
        import ha
        if ha.config_available('automation'):
            return 'api'
    except Exception:  # noqa
        pass
    return 'yaml' if WRITE_MODE == 'auto' else 'api'


def action_entities(action, state=None):
    """动作作用到哪些实体（按类型 + 房间筛）。"""
    st = state or _load(os.path.join(DATA, 'state.json'), {'devices': []})
    dom = {'light': 'light', 'cover': 'cover', 'ac': 'climate'}[action['type']]
    out = []
    for d in st.get('devices') or []:
        if action.get('room') and d.get('room') != action['room']:
            continue
        if action['type'] == 'light' and d.get('type') != 'light':
            continue
        if action['type'] == 'cover' and d.get('type') != 'cover':
            continue
        if action['type'] == 'ac' and d.get('type') != 'ac':
            continue
        if d.get('security_domain'):
            continue                       # 安全域永不自动执行（08 §2）
        for e in d.get('entities') or []:
            if e.startswith(dom + '.'):
                out.append(e)
                break
    return sorted(set(out))


def commit(rule_id, confirm=False, dry=False):
    """确认后落到底座：写 automations.yaml → check_config → reload → 回读实体。

    confirm=False 时**只返回将要写入的内容**（规范 §7 的"我理解成……对吗？"）。
    """
    doc = _rules_doc()
    entry = next((r for r in doc['rules'] if r['id'] == rule_id), None)
    if not entry:
        return {'ok': False, 'error': f'没有这条规则：{rule_id}'}
    ents = action_entities(entry['action'])
    if not ents:
        return {'ok': False, 'error': '这条规则没有作用对象（该房间没有这类设备）'}
    pres = []
    if entry.get('condition'):
        pres = [p['entity_id'] for p in (presence_entities().get(entry['condition']['room']) or [])]
        if not pres:
            return {'ok': False, 'error': f"{entry['condition']['room']}没有人体/存在传感器，做不了这个条件"}
    yaml_text = _yaml_rule(entry, ents)
    if not confirm or dry:
        return {'ok': True, 'dry': True, 'yaml': yaml_text,
                'entities': ents, 'presence': pres, 'recap': entry.get('recap')}

    mode = _write_mode()
    if mode == 'api':
        # 走 HA 官方配置接口：由 HA 自己写文件并**自动 reload**（迁移到 HA OS 后只有这条路可行）
        import sys as _s
        _s.path.insert(0, os.path.join(ROOT, 'app'))
        import ha
        aid = f'smarthome_{rule_id}'
        prev, _prev_how = None, ''
        try:
            prev = ha.config_get('automation', aid)        # 存一份旧的，失败好回退
        except Exception:  # noqa
            prev = None
        ok_save, detail = ha.config_save('automation', aid, _rule_dict(entry, ents))
        if not ok_save:
            return {'ok': False, 'error': f'保存到 HA 失败（{detail}）—— 规则没生效', 'write_mode': mode}
        # **实体 id 不是我们写的那个**：YAML 自动化的 entity_id 从 alias 派生，必须按 id 属性找
        real_eid = ha.find_automation_entity(aid)
        if not real_eid:
            ha.call_service('automation', 'reload', blocking=False)
            import time as _t
            for _ in range(6):
                _t.sleep(1)
                real_eid = ha.find_automation_entity(aid)
                if real_eid:
                    break
        ok, state, cost = (ha.read_back(real_eid, expect='on', timeout=12) if real_eid
                           else (False, None, 0.0))
        if not ok:
            # 回退：有旧的就写回旧的，没有就删掉我们刚建的
            if prev:
                ha.config_save('automation', aid, prev.get('config') or prev)
            else:
                ha.config_delete('automation', aid)
            return {'ok': False, 'write_mode': mode,
                    'error': '写入后没有回读到 automation 实体，已回退（规则没生效）'}
        entry.update({'status': 'active', 'yaml': yaml_text, 'entities': ents, 'presence': pres,
                      'ha_entity': real_eid, 'write_mode': mode,
                      'committed_at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
                      'readback': state, 'readback_ok': True})
        save(doc)
        return {'ok': True, 'recap': entry.get('recap'), 'readback': state, 'seconds': cost,
                'write_mode': mode, 'error': None}

    # 真写（兜底路径）：追加到 automations.yaml（先备份原文），再让 HA 校验与重载
    backup = AUTOMATIONS + '.bak-' + datetime.datetime.now(TZ).strftime('%H%M%S')
    old = open(AUTOMATIONS, encoding='utf-8').read() if os.path.exists(AUTOMATIONS) else ''
    with open(backup, 'w', encoding='utf-8') as f:
        f.write(old)
    with open(AUTOMATIONS, 'w', encoding='utf-8') as f:
        f.write(old.rstrip() + '\n' + yaml_text)

    import sys
    sys.path.insert(0, os.path.join(ROOT, 'app'))
    import ha
    errs = ha.call_service('homeassistant', 'check_config', blocking=False)
    bad = []
    if isinstance(errs, dict):
        bad = (errs.get('result') or errs.get('errors') or []) if isinstance(errs, dict) else []
    if bad:
        with open(AUTOMATIONS, 'w', encoding='utf-8') as f:      # 校验不过 → 原样退回
            f.write(old)
        return {'ok': False, 'error': f'HA 校验不通过，已回退：{bad}', 'backup': backup}
    ha.call_service('automation', 'reload', blocking=False)
    import time as _t2
    real_eid2 = None
    for _ in range(6):
        real_eid2 = ha.find_automation_entity(f'smarthome_{rule_id}')
        if real_eid2:
            break
        _t2.sleep(1)
    ok, state, cost = (ha.read_back(real_eid2, expect='on', timeout=10) if real_eid2
                       else (False, None, 0.0))
    entry.update({'status': 'active', 'yaml': yaml_text, 'entities': ents, 'presence': pres,
                  'ha_entity': real_eid2, 'committed_at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
                  'readback': state, 'readback_ok': bool(ok), 'backup': backup})
    save(doc)
    return {'ok': bool(ok), 'recap': entry.get('recap'), 'readback': state, 'seconds': cost,
            'write_mode': 'yaml',
            'error': None if ok else '写入后没有回读到 automation 实体（可能没生效）'}


def set_enabled(rule_id, enabled):
    """真停用/真启用：调 HA 的 automation.turn_off/turn_on，并**回读**确认。"""
    doc = _rules_doc()
    entry = next((r for r in doc['rules'] if r['id'] == rule_id), None)
    if not entry:
        return {'ok': False, 'error': f'没有这条规则：{rule_id}'}
    entity = entry.get('ha_entity')
    if not entity:
        return {'ok': False, 'error': '这条规则还没创建到 HA（没有实体可停用）'}
    import sys
    sys.path.insert(0, os.path.join(ROOT, 'app'))
    import ha
    ha.call_service('automation', 'turn_on' if enabled else 'turn_off',
                    {'entity_id': entity}, blocking=True)
    ok, state, cost = ha.read_back(entity, expect='on' if enabled else 'off', timeout=10)
    entry['status'] = 'active' if (enabled and ok) else ('disabled' if not enabled else 'active')
    entry.setdefault('history', []).append({'at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
                                            'to': entry['status'], 'readback': state})
    save(doc)
    return {'ok': bool(ok), 'state': state, 'seconds': cost,
            'error': None if ok else f'回读没确认（现在读到 {state}）'}


def set_status(rule_id, status):
    """停用 / 启用（停用即从 automations.yaml 移除并 reload）。"""
    doc = _rules_doc()
    entry = next((r for r in doc['rules'] if r['id'] == rule_id), None)
    if not entry:
        return False, f'没有这条规则：{rule_id}'
    entry['status'] = status
    entry.setdefault('history', []).append({'at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
                                            'to': status})
    save(doc)
    return True, f"规则已{'启用' if status == 'active' else '停用'}（HA 里的自动化需同步 reload）"


def view():
    return [{'id': r['id'], 'status': r.get('status'), 'recap': r.get('recap'),
             'trigger': r.get('trigger'), 'condition': r.get('condition'), 'action': r.get('action'),
             'created_at': r.get('created_at'), 'ha_entity': r.get('ha_entity'),
             'readback_ok': r.get('readback_ok')} for r in list_rules()]


def summary():
    rs = list_rules()
    return {'rules': len(rs), 'active': sum(1 for r in rs if r.get('status') == 'active'),
            'proposed': sum(1 for r in rs if r.get('status') == 'proposed')}


if __name__ == '__main__':
    import sys
    txt = ' '.join(sys.argv[1:]) or '每天22:30如果客厅没人就把客厅的灯关了'
    p = parse(txt)
    print('复述:', p['recap'])
    print('触发:', p.get('trigger'), '| 条件:', p.get('condition'), '| 动作:', p.get('action'))
    print('条件可行:', p.get('condition_feasible'), '| 还需:', needs(p))
    print('作用对象:', action_entities(p['action']) if p.get('action') else [])
