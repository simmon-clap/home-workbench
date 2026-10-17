#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P3 意图与执行层测试（不依赖 HA 令牌：全部用假执行器）

依据：docs/spec/03 §2–§6 · 04 §2 · 08 §2–§3 · 11 §11（新增功能必须带测试）

用法：python3 tools/test_intent.py      退出码 0 = 全过
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
import intent as I  # noqa: E402

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def main():
    # 测试隔离：动作记录写临时文件，不污染真实 data/
    _tmp = tempfile.mkdtemp(prefix='intent-test-')
    I.ACTIONS = os.path.join(_tmp, 'actions.json')
    # 测试绝不写生产数据：审计也指向临时目录（2026-10-17 实测过污染：审计被测试写了 900+ 条）
    sys.path.insert(0, os.path.join(ROOT, 'app'))
    import audit as _audit
    _audit.AUDIT = os.path.join(_tmp, 'audit.jsonl')
    state = I.load_state()
    devices = state.get('devices') or []
    check('状态数据可用', len(devices) > 0, f'{len(devices)} 台')

    # —— 场景解析与展开 ——
    it = I.parse('我要睡了', state)
    check('「我要睡了」识别为场景 goodnight', it['kind'] == 'scene' and it.get('scene') == 'goodnight', it.get('kind'))
    steps = I.plan_steps(it, state)
    check('场景展开出多个步骤', len(steps) >= 3, f'{len(steps)} 步')
    doable, blocked = I.guard(steps)
    check('场景里的安全域步骤被拦截', any(b['security'] for b in blocked) or not any(s['security'] for s in steps),
          f"拦截 {len(blocked)} 步")
    check('可执行步骤里没有安全域设备', all(not s['security'] for s in doable))

    # —— 单动作（用真实设备名，验证不改名也能听懂）——
    light = next((d for d in devices if d['type'] == 'light' and not d['security_domain']), None)
    if light:
        it2 = I.parse(f"把{light['name']}关掉", state)
        check('按设备原名可解析为单动作', it2['kind'] == 'single' and it2.get('target') == light['name'],
              f"{it2['kind']} / {it2.get('target')}")

    # —— 歧义：一次只问一个问题 ——
    from collections import Counter
    # 03 §3：指名房间**不是**歧义（那是"这个房间的所有灯"）；只有无限定的指代才问
    room_multi = next((r for r, c in Counter(d['room'] for d in devices if d['type'] == 'light').items() if c >= 2), None)
    if room_multi:
        it3 = I.parse(f"把{room_multi}的灯关掉", state)
        check('指名房间的多候选→整体执行（不是歧义）',
              it3['kind'] == 'single' and len(it3.get('targets') or []) >= 2,
              f"{it3['kind']} / {len(it3.get('targets') or [])} 台")
        it3b = I.parse('把那盏灯关掉', state)
        check('无限定指代→歧义并给候选（一次只问一个）',
              it3b['kind'] == 'ambiguous' and it3b.get('options'),
              f"{it3b['kind']} / {len(it3b.get('options') or [])} 个候选")

    # —— 安全域：拒执 + 指向米家 ——
    it4 = I.parse('把主卧门锁打开', state)
    check('安全域意图被识别并拒绝执行', it4['kind'] == 'security' and '米家' in it4.get('reply', ''), it4['kind'])
    out4 = I.handle('把主卧门锁打开', state=state)
    check('安全域请求不产生任何执行步骤', not out4['steps'] and not out4['results'])

    # —— 只读设备：不执行开关 ——
    sensor = next((d for d in devices if d['type'] == 'sensor' and not d['security_domain']), None)
    if sensor:
        step = [{'device': sensor['name'], 'room': sensor['room'], 'entity_id': sensor['entity_id'],
                 'domain': 'light', 'service': 'turn_on', 'expect': 'on',
                 'security': False, 'readonly': True, 'remind_only': False}]
        d2, b2 = I.guard(step)
        check('只读设备被守门拦下', not d2 and b2 and '只读' in b2[0]['reason'])

    # —— 执行 + 回读（假执行器）——
    ex = I.FakeExecutor()
    out = I.handle('我要睡了', executor=ex, state=state, dry_run=False)
    check('执行后每步都有回读值', out['results'] and all(r['readback'] == 'off' or r['ok'] for r in out['results']),
          f"{len(out['results'])} 步")
    check('回执含三段式要素（做了什么 / 现在什么样 / 撤销）',
          ('已完成' in out['receipt']) and ('回读' in out['receipt']) and ('撤销' in out['receipt']))

    # —— 部分成功 ——
    first = out['results'][0]['device']
    ex2 = I.FakeExecutor(fail_on=[first])
    out2 = I.handle('我要睡了', executor=ex2, state=state, dry_run=False)
    check('部分成功时如实报告失败项与原因', ('没做成' in out2['receipt']) and (first in out2['receipt']))

    # —— 回读不符必须失败 ——
    ex3 = I.FakeExecutor(readback_mismatch=[first])
    out3 = I.handle('我要睡了', executor=ex3, state=state, dry_run=False)
    bad = [r for r in out3['results'] if r['device'] == first][0]
    check('回读与预期不符时判为失败', bad['ok'] is False and '回读' in (bad['error'] or ''))

    # —— 撤销 ——
    aid = out['action_id']
    und = I.undo(aid, executor=I.FakeExecutor())
    check('撤销可执行且要求读回确认', und['ok'] and all(r['readback'] is not None for r in und['results']),
          f"{len(und.get('results', []))} 步")
    und2 = I.undo(aid, executor=I.FakeExecutor())
    check('重复撤销被拒绝', und2['ok'] is False and '撤销过' in und2.get('error', ''))
    acts = json.load(open(I.ACTIONS, encoding='utf-8'))['actions']
    check('安全域从不进入可撤销步骤',
          all(r['service'] not in ('lock', 'unlock') for a in acts for r in a['results']))

    # —— 查询 ——
    it5 = I.parse('家里怎么样', state)
    check('查询类意图不乱执行', it5['kind'] == 'query')

    # —— dry-run 默认不执行 ——
    out6 = I.handle('我要睡了', state=state)
    check('默认 dry-run 不执行（等令牌）', not out6['results'] and '未执行' in out6['receipt'])

    # ── 03 §3 意图分级：模糊意图 / 房间级 / 演练回执 / 只读回话 ──
    st2 = I.load_state()
    o = I.handle('有点闷', dry_run=True, state=st2)
    check('模糊意图走"最轻的一步"（不是什么都不做）',
          o['intent']['kind'] == 'single' and len(o['steps']) == 1,
          f"kind={o['intent']['kind']} steps={len(o['steps'])}")
    check('模糊意图回执说明"按最轻的方式做了"', '最轻' in (o.get('receipt') or ''),
          (o.get('receipt') or '').replace(chr(10), ' ')[:60])
    check('模糊意图不选"网关"这类中枢设备',
          bool(o['steps']) and '网关' not in o['steps'][0]['device'], str(o['steps'][:1]))
    o_room = I.handle('把客厅的灯关掉', dry_run=True, state=st2)
    check('"把客厅的灯关掉"＝客厅所有灯（**不是**歧义）',
          o_room['intent']['kind'] == 'single' and len(o_room['steps']) >= 3, f"{len(o_room['steps'])} 步")
    rec = I.handle('把主卧的窗帘关上', dry_run=True, state=st2)
    check('演练回执说清"将要做什么"',
          '将执行 1 步' in (rec.get('receipt') or '') and '没有需要执行的动作' not in (rec.get('receipt') or ''),
          (rec.get('receipt') or '').splitlines()[0][:50])
    q = I.handle('家里最近怎么样', dry_run=True, state=st2)
    check('查看类回答状态真相（不是空回执）',
          q['intent']['kind'] == 'query' and '台设备' in (q.get('receipt') or ''),
          (q.get('receipt') or '')[:40])
    check('查看类不在对话里报安全域明细',
          '门锁' not in (q.get('receipt') or '') and '安全' in (q.get('receipt') or ''),
          (q.get('receipt') or '').replace(chr(10), ' ')[:60])

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
