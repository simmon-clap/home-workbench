#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
面板动作解析测试（P4/P6 交叉）

依据：docs/spec/02 §8（兜底可用）· 03 §1C（安全域/只读不给动作）· 05 §4（执行后回读）
      11 §11（新增功能必须带测试）

为什么专门测这个：2026-10-17 实测抓到两个会**真的发错指令**的 bug——
  ① 扫地机/音箱/电视在 HA 里没有 vacuum.*/media_player.*，旧实现按"设备类型"猜服务，
     会给 button.* 实体发 light.turn_off；
  ② 窗帘的 switch.*_motor_reverse（电机方向）被当成"关掉"，一点就翻转电机方向。
本测试就是"再也不许发生"的机械保证。

用法：python3 tools/test_panel.py      退出码 0 = 全过
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
import panel_action as P  # noqa: E402
import audit as A  # noqa: E402

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


# 每个域允许的服务（动作的域与服务必须自洽）
DOMAIN_SERVICES = {
    'light': {'turn_on', 'turn_off'},
    'fan': {'turn_on', 'turn_off'},
    'switch': {'turn_on', 'turn_off'},
    'climate': {'turn_on', 'turn_off'},
    'media_player': {'turn_on', 'turn_off'},
    'cover': {'open_cover', 'close_cover'},
    'button': {'press'},
}


def main():
    A.AUDIT = os.path.join(tempfile.mkdtemp(prefix='panel-test-'), 'audit.jsonl')
    devices = json.load(open(os.path.join(ROOT, 'data', 'state.json'), encoding='utf-8'))['devices']
    check('状态数据可用', len(devices) > 0, f'{len(devices)} 台')

    # ① 解析出的实体域与服务必须自洽（这是防"发错服务"的核心断言）
    bad = []
    for d in devices:
        for act, spec in P.actions_for(d).items():
            dom = spec['entity_id'].split('.')[0]
            if dom != spec['domain']:
                bad.append(f"{d['name']}:{act} 实体域 {dom} ≠ 服务域 {spec['domain']}")
            if spec['service'] not in DOMAIN_SERVICES.get(spec['domain'], set()):
                bad.append(f"{d['name']}:{act} 服务 {spec['service']} 不属于 {spec['domain']}")
    check('所有动作的实体域与服务域自洽（防发错服务）', not bad, '; '.join(bad[:3]))

    # 回归：空气净化器有 fan.* 也有 switch.*_alarm —— 绝不能把"打开净化器"发成开关告警
    pur = next((d for d in devices if '空气净化器' in d['name']), None)
    if pur:
        spec = (P.actions_for(pur) or {}).get('turn_on') or {}
        check('净化器走 fan.*（不再误发到 switch.*_alarm）',
              spec.get('domain') == 'fan' and spec.get('entity_id', '').startswith('fan.'),
              f"{spec.get('entity_id')} / {spec.get('service')}")

    # ② 设置项绝不能被当成电源开关
    settings = ('motor_reverse', 'mute', 'sleep_mode', 'no_disturb', 'indicator', 'child_lock')
    polluted = [f"{d['name']}:{a}→{s['entity_id']}" for d in devices
                for a, s in P.actions_for(d).items() if any(w in s['entity_id'] for w in settings)]
    check('设置项（电机方向/静音/免打扰…）不出现在动作里', not polluted, '; '.join(polluted[:2]))

    # ③ 窗帘只给开/合，不给开/关
    curtain = next((d for d in devices if d['type'] == 'cover'), None)
    if curtain:
        acts = set(P.actions_for(curtain).keys())
        check('窗帘只给「打开/合上」', acts == {'open', 'close'}, str(acts))

    # ④ 按钮类动作必须标注"不回传状态"
    ir = next((d for d in devices if d['type'] == 'tv'), None)
    if ir:
        acts = P.actions_for(ir)
        if acts:
            check('红外遥控类动作标注不可回读', all(not v['verifiable'] for v in acts.values()),
                  json.dumps(list(acts.keys()), ensure_ascii=False))
        else:
            check('红外遥控类动作标注不可回读', True, '该设备无动作')

    # ⑤ 安全域 / 只读设备一律没有动作
    sec = [d for d in devices if d['security_domain']]
    check('安全域设备没有任何动作', all(not P.actions_for(d) for d in sec), f'{len(sec)} 台')
    ro = [d for d in devices if d['type'] in ('sensor', 'camera')]
    check('只读设备没有任何动作', all(not P.actions_for(d) for d in ro), f'{len(ro)} 台')

    # ⑥ 演练：可控设备能计划出正确步骤
    ctrl = next((d for d in devices if P.actions_for(d).get('turn_off')), None)
    if ctrl:
        out = P.run(ctrl['name'], 'turn_off', dry=True)
        step = out.get('step') or {}
        check('演练给出与实体匹配的步骤', out.get('ok') and step.get('domain') == step['entity_id'].split('.')[0],
              f"{step.get('domain')}.{step.get('service')}")

    # ⑦ 守门：安全域被拒、未知动作被拒、没有可用动作的设备被拒
    if sec:
        out = P.run(sec[0]['name'], 'turn_off', dry=True)
        check('面板拒绝安全域设备', out.get('blocked') is True and '安全域' in out.get('reason', ''))
    out = P.run('不存在的设备', 'turn_off', dry=True)
    check('面板拒绝不存在的设备', out.get('blocked') is True and '找不到' in out.get('reason', ''))
    out = P.run(ctrl['name'] if ctrl else 'x', 'explode', dry=True)
    check('面板拒绝未知动作', out.get('blocked') is True)
    noact = next((d for d in devices if not P.actions_for(d) and not d['security_domain']
                  and d['type'] not in ('sensor', 'camera')), None)
    if noact:
        out = P.run(noact['name'], 'turn_off', dry=True)
        check('没有可用动作的设备被明确拒绝（不猜）', out.get('blocked') is True and '没有可用' in out.get('reason', ''),
              noact['name'])

    # ⑧ 被拒也要留痕（**真请求**才留痕；演练不写审计，见 tools/test_exec.py）
    if sec:
        P.run(sec[0]['name'], 'turn_off')
    check('真请求被拒也写审计', any(x['result'] == 'blocked' for x in A.load()))

    # ⑨ 米家依赖清单（判据 1 的检查表）：分类必须与实体解析一致，不许虚高
    gp = os.path.join(ROOT, 'data', 'mijia-dependency.json')
    if os.path.exists(gp):
        d = json.load(open(gp, encoding='utf-8'))
        c = d.get('counts') or {}
        check('依赖清单的分类总数等于设备数', sum(c.values()) == len(devices),
              f"{sum(c.values())} vs {len(devices)}")
        sec_names = {x['name'] for x in devices if x['security_domain']}
        need = {x['name'] for x in (d.get('devices') or {}).get('need_mijia', [])}
        check('"仍需米家"只能包含安全域设备', need <= sec_names, str(sorted(need - sec_names)[:3]))
        bad_input = [x['name'] for x in (d.get('devices') or {}).get('input', []) if P.actions_for(
            next(y for y in devices if y['name'] == x['name']))]
        check('输入类设备确实没有可控动作', not bad_input, str(bad_input[:2]))
        bad_ok = [x['name'] for x in (d.get('devices') or {}).get('ok', []) if not any(
            v['verifiable'] for v in P.actions_for(
                next(y for y in devices if y['name'] == x['name'])).values())]
        check('"不用米家"的设备必须有可回读动作', not bad_ok, str(bad_ok[:2]))
        check('清单写明来源与生成时间', bool(d.get('source')) and bool(d.get('generated_at')))

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
