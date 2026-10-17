#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
面板操作（墙面屏/手机上的手动兜底）

依据：docs/spec/02-视觉规范 v1.0 §8「兜底可用：任何一句话能做的事，墙面屏上都能手动做到」
      03 §1C 第 4 条（安全域只给「需本机确认」、只读设备不给动作）
      05 §4（执行后必须回读）· 08 §2（安全域不得自动执行）· 11-代码规范 v1.0

做什么：把面板上的一次点击变成「步骤 → 守门 → 执行 → 回读 → 审计 → 可撤销」。
不做什么：不绕过守门（安全域/只读一律拒绝）；不猜设备（找不到就直说）。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit  # noqa: E402
import intent as I  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, 'data', 'state.json')

# 面板上允许的动作（比对话窄：只给最常用的开/关/启停）
ALLOWED = {'turn_on', 'turn_off', 'open', 'close'}

# 实体域 → 该域上的开/关语义（**按实体域决定服务，绝不按设备类型猜**）
# 2026-10-17 修掉的真实 bug：扫地机/音箱/电视在 HA 里没有 vacuum.*/media_player.*，
# 只有 button.*；旧实现按"类型→light.turn_off"会往 button 实体发错服务。
DOMAIN_ACTIONS = {
    'light': {'turn_on': ('turn_on', 'on', True), 'turn_off': ('turn_off', 'off', True)},
    'switch': {'turn_on': ('turn_on', 'on', True), 'turn_off': ('turn_off', 'off', True)},
    'climate': {'turn_on': ('turn_on', 'on', True), 'turn_off': ('turn_off', 'off', True)},
    'media_player': {'turn_on': ('turn_on', 'on', True), 'turn_off': ('turn_off', 'off', True)},
    'cover': {'open': ('open_cover', 'open', True), 'close': ('close_cover', 'closed', True)},
    # 风机类（空气净化器/风扇）：本体电源就在 fan.* 上（2026-10-17 实测：净化器若走
    # switch.*_alarm 就是开关告警，完全不是"打开净化器"）
    'fan': {'turn_on': ('turn_on', 'on', True), 'turn_off': ('turn_off', 'off', True)},
}
# 按钮类（红外遥控等）：能发指令，但设备不回传状态 —— 必须如实标注"无法回读确认"
BUTTON_WORDS = {'turn_on': ('turn_on',), 'turn_off': ('turn_off', 'stop_clean')}

# 这些实体**不是设备电源**，而是设置项：绝不能当成"开/关"发出去。
# 2026-10-17 实测抓到的坑：窗帘的 `switch.*_motor_reverse`（电机方向）会被当成"关掉"，
# 一点就把电机方向翻转；音箱的 `*_mute_p`、`*_sleep_mode_p` 同理。
EXCLUDE_ENTITY = re.compile(
    r'motor_reverse|reverse|child_lock|indicator|do_not_disturb|no_disturb|mute|sleep_mode|'
    r'scene|countdown|delay|memory|_tip|tip_|level|bright|color|ct_|mode|speed|volume|'
    # 2026-10-17 实测：空气净化器的"打开"被解析成 switch.*_alarm（告警开关），点一下是开关告警
    r'alarm|reset|physical_controls|particle_abnormal|heartbeat|debug|favorite|'
    r'night|timer|screen|led|_e_|door_opening|filter')

# 电源类域的优先级：**越靠前越贴近设备本体**
# （净化器有 fan.* 也有 switch.*_alarm —— 必须选 fan，不能选那个告警开关）
POWER_PRIORITY = ['fan', 'climate', 'vacuum', 'media_player', 'light', 'switch']
OPEN_CLOSE_DOMAIN = 'cover'
LABELS = {'turn_on': '打开', 'turn_off': '关掉', 'open': '打开', 'close': '合上'}


def actions_for(device):
    """按设备**真实实体**解析可用动作。

    返回 {action: {'entity_id','domain','service','expect','verifiable'}}。
    """
    acts = {}
    if not device or device.get('security_domain') or device.get('type') in I.READONLY_TYPES:
        return acts                      # 安全域/只读：没有可执行动作（03 §1C · 08 §2）

    # 先按域归集候选实体（排除设置项），再**按优先级**决定用哪个域
    by_dom = {}
    for e in device.get('entities') or []:
        dom, _, obj = e.partition('.')
        if EXCLUDE_ENTITY.search(obj):
            continue                     # 设置项不是电源开关
        if dom in DOMAIN_ACTIONS or dom == 'button':
            by_dom.setdefault(dom, []).append(e)

    for dom in POWER_PRIORITY:
        for e in by_dom.get(dom, []):
            for act, (svc, expect, verifiable) in (DOMAIN_ACTIONS.get(dom) or {}).items():
                if act not in acts:
                    acts[act] = {'entity_id': e, 'domain': dom, 'service': svc,
                                 'expect': expect, 'verifiable': verifiable}
    for e in by_dom.get(OPEN_CLOSE_DOMAIN, []):
        for act, (svc, expect, verifiable) in DOMAIN_ACTIONS[OPEN_CLOSE_DOMAIN].items():
            if act not in acts:
                acts[act] = {'entity_id': e, 'domain': OPEN_CLOSE_DOMAIN, 'service': svc,
                             'expect': expect, 'verifiable': verifiable}
    # 按钮类兜底（红外遥控等）：能发指令但不回读，必须如实标注
    for e in by_dom.get('button', []):
        _, _, obj = e.partition('.')
        for act, words in BUTTON_WORDS.items():
            if act in acts:
                continue
            if any(w in obj for w in words):
                acts[act] = {'entity_id': e, 'domain': 'button', 'service': 'press',
                             'expect': None, 'verifiable': False}
    return acts


def available_actions(device):
    """面板上这台设备能做什么（安全域与只读设备一律为空）。"""
    return list(actions_for(device).keys())


def _state():
    try:
        return json.load(open(STATE, encoding='utf-8'))
    except FileNotFoundError:
        return {'devices': []}


def available_actions(device):
    """这台设备在面板上能做什么（安全域与只读设备一律为空）。"""
    if device.get('security_domain'):
        return []
    if device.get('type') in I.READONLY_TYPES:
        return []
    return list(TYPE_ACTIONS.get(device.get('type'), ()))


def plan(name, action):
    """把（设备名, 动作）变成一步计划；失败时给出人能看懂的原因。"""
    if action not in ALLOWED:
        return None, f'不支持的动作：{action}'
    dev = next((d for d in _state().get('devices', []) if d['name'] == name), None)
    if not dev:
        return None, f'找不到设备「{name}」（我没有改过任何设备名）'
    if dev.get('security_domain'):
        return None, '安全域设备：只提醒，不自动执行；请在米家 App 手动操作（08 §2）'
    if dev.get('type') in I.READONLY_TYPES:
        return None, '只读设备（传感器/摄像头）：不提供开/关（03 §1C）'
    if action not in TYPE_ACTIONS.get(dev.get('type'), ()):
        return None, f'「{dev["name"]}」不支持 {action}'
    dom, svc, expect, _inv = I.ACTION_MAP[action]
    return {'device': dev['name'], 'room': dev['room'], 'entity_id': I.pick_entity(dev, dom),
            'domain': dom, 'service': svc, 'expect': expect,
            'security': False, 'readonly': False, 'remind_only': False}, None


def run(name, action, dry=False):
    """执行一次面板操作。dry=True 只做计划与守门（供测试与非本机预览）。"""
    if action not in ALLOWED:
        return _blocked(action, name, f'不支持的动作：{action}', dry=dry)
    dev = next((d for d in _state().get('devices', []) if d['name'] == name), None)
    if not dev:
        return _blocked(action, name, f'找不到设备「{name}」（我没有改过任何设备名）', dry=dry)
    if dev.get('security_domain'):
        return _blocked(action, name, '安全域设备：只提醒，不自动执行；请在米家 App 手动操作（08 §2）', dry=dry)
    if dev.get('type') in I.READONLY_TYPES:
        return _blocked(action, name, '只读设备（传感器/摄像头）：不提供开/关（03 §1C）', dry=dry)
    spec = actions_for(dev).get(action)
    if not spec:
        return _blocked(action, name, f'「{dev["name"]}」没有可用的 {ALLOWED and action} 路径'
                                      f'（它的实体里没有对应可控实体）', dry=dry)
    step = {'device': dev['name'], 'room': dev['room'], 'entity_id': spec['entity_id'],
            'domain': spec['domain'], 'service': spec['service'], 'expect': spec['expect'],
            'security': False, 'readonly': False, 'remind_only': False}
    if dry:
        return {'ok': True, 'dry': True, 'step': step, 'verifiable': spec['verifiable'],
                'receipt': f'（演练）将执行：{spec["domain"]}.{spec["service"]} → {dev["name"]}'
                           + ('' if spec['verifiable'] else '（这台设备不回传状态）')}

    import ha
    executor = ha.real_executor()
    if executor is None:
        return {'ok': False, 'reason': '未配置 HA 令牌，无法执行（不会假装完成）',
                'receipt': '未执行：缺少 HA 访问令牌'}

    results = I.execute([step], executor)
    r = results[0]
    entry = I.record({'raw': f'面板：{name} {action}', 'kind': 'panel'}, results, [])
    word = LABELS.get(action, action)
    if not spec['verifiable'] and r['error'] is None:
        # 不回传状态的设备：如实说"无法确认"，不冒充"已完成"
        receipt = f'{r["device"]} 指令已发出（这台设备不回传状态，**无法确认**是否生效）'
        result_word = 'sent_unverified'
    elif r['ok']:
        receipt = f'{r["device"]} {word} · 现在：{r["readback"]}（回读确认） · 可撤销'
        result_word = 'ok'
    else:
        receipt = f'{r["device"]} 没做成 · {r.get("error") or "原因未知"}'
        result_word = 'failed'
    audit.log(action=f'{spec["domain"]}.{spec["service"]}', target=spec['entity_id'], channel='面板',
              authorization='面板点击', result=result_word,
              readback=r.get('readback'), detail=r.get('error'))
    return {'ok': bool(r['ok']) or result_word == 'sent_unverified', 'readback': r.get('readback'),
            'verifiable': spec['verifiable'], 'receipt': receipt, 'action_id': entry['id']}


def _blocked(action, name, reason, dry=False):
    # 演练（dry）不写审计：它什么都没做，写进去就是污染（实测被测试刷出 157 条"被拒"）
    if not dry:
        audit.log(action=action, target=name, channel='面板', authorization='不适用',
                  result='blocked', detail=reason)
    return {'ok': False, 'blocked': True, 'reason': reason, 'receipt': reason}


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('name')
    ap.add_argument('action', choices=sorted(ALLOWED))
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()
    print(json.dumps(run(a.name, a.action, dry=a.dry), ensure_ascii=False, indent=1))

# ═══════════ 场景（一键，带预告）═══════════
def scenes():
    """列出可用场景及其影响面（受影响台数 / 可执行步数 / 按规范拦截步数）。"""
    doc = I.load_scenes()
    out = []
    for sc in doc.get('scenes', []):
        if not sc.get('enabled'):
            continue
        steps = I.plan_steps({'kind': 'scene', 'scene': sc['id']}, _state())
        doable, blocked = I.guard(steps)
        out.append({'id': sc['id'], 'name': sc['name'],
                    'devices': len({x['device'] for x in steps}),
                    'executable': len(doable), 'blocked': len(blocked)})
    return out


def _scene_preview(sc, doable, blocked):
    n_dev = len({x['device'] for x in doable})
    txt = f'{sc["name"]}：将执行 {len(doable)} 步、涉及 {n_dev} 台设备'
    if blocked:
        txt += f'；按规范拦截 {len(blocked)} 步（安全域只提醒）'
    return txt


def run_scene(scene_id, dry=False):
    """执行一个场景。dry=True 只给预告（面板上第一次点击用）。"""
    doc = I.load_scenes()
    sc = next((x for x in doc.get('scenes', []) if x['id'] == scene_id and x.get('enabled')), None)
    if not sc:
        return {'ok': False, 'reason': f'没有这个场景：{scene_id}'}
    steps = I.plan_steps({'kind': 'scene', 'scene': scene_id}, _state())
    doable, blocked = I.guard(steps)
    preview = _scene_preview(sc, doable, blocked)
    if not doable:
        return {'ok': False, 'reason': f'{preview}（没有可执行步骤）', 'preview': preview}
    if dry:
        return {'ok': True, 'dry': True, 'preview': preview, 'executable': len(doable),
                'blocked': len(blocked), 'devices': len({x['device'] for x in doable})}

    import ha
    executor = ha.real_executor()
    if executor is None:
        return {'ok': False, 'reason': '未配置 HA 令牌，无法执行（不会假装完成）'}

    results = I.execute(doable, executor)
    entry = I.record({'raw': f'场景：{sc["name"]}', 'kind': 'scene'}, results, blocked)
    for r in results:
        audit.log(action=r['service'], target=r['entity_id'] or r['device'], channel='面板',
                  authorization='场景点击', result='ok' if r['ok'] else 'failed',
                  readback=r.get('readback'), detail=r.get('error'))
    for b in blocked:
        audit.log(action='refused', target=b.get('entity_id') or b['device'], channel='面板',
                  authorization='不适用', result='blocked', detail=b['reason'])
    good = [r for r in results if r['ok']]
    bad = [r for r in results if not r['ok']]
    receipt = f'{sc["name"]}：{len(good)} 项完成'
    if bad:
        receipt += f'，{len(bad)} 项没做成（{bad[0]["device"]}：{bad[0].get("error") or "原因未知"}）'
    if blocked:
        receipt += f'；拦截 {len(blocked)} 步（安全域只提醒）'
    receipt += ' · 可撤销'
    return {'ok': not bad, 'action_id': entry['id'], 'receipt': receipt,
            'done': len(good), 'failed': len(bad), 'blocked_count': len(blocked)}
