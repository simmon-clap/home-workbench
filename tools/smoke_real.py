#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真实执行冒烟测试（需要 HA 令牌；没有令牌会明确 SKIP，不算通过）

依据：docs/spec/05 §4（执行必须回读）· 09 §2（复验要真实：真机、真调用、真回读）

做什么：
  1) 只读验证：经 HA API 读一台设备的真实状态
  2) **写路径验证（幂等无副作用）**：挑一盏当前就是「关」的灯，再发一次关灯指令，
     回读仍为「关」——这样验证了"能真写、能真回读"，但对家里**没有任何可见影响**

用法：python3 tools/smoke_real.py        退出码 0 = 通过或明确跳过
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
import ha  # noqa: E402
import audit as A  # noqa: E402

OK, FAIL, SKIP = [], [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def main():
    if not ha.configured():
        print('⏭️  未配置 HA 令牌 —— 真实执行冒烟跳过（不算通过）')
        return 0
    check('HA 令牌形状正常', ha.token_problem() is None)
    check('HA API 可达', ha.ping())

    # 1) 只读：挑一台有实体且在线可控的设备
    st = json.load(open(os.path.join(ROOT, 'data', 'state.json'), encoding='utf-8'))
    lights = [d for d in st['devices'] if d['type'] == 'light' and not d['security_domain']]
    if not lights:
        FAIL.append('找不到可测灯具')
        print('❌ 找不到可测灯具'); return 1
    light = lights[0]
    api_state = ha.get_state(light['entity_id'])
    check('只读：能读到真实状态', 'state' in api_state, f"{light['name']} = {api_state.get('state')}")

    # 2) 写路径：只在"已经是关"的灯上做幂等关灯
    off_lights = []
    for d in lights[:8]:
        try:
            if ha.get_state(d['entity_id']).get('state') == 'off':
                off_lights.append(d)
        except Exception:  # noqa
            continue
    if not off_lights:
        print('⏭️  当前没有处于「关」状态的灯，跳过写路径测试（不冒险影响家里）')
        SKIP.append('写路径（无合适的幂等目标）')
        return summary()

    target = off_lights[0]
    step = {'device': target['name'], 'room': target['room'], 'entity_id': target['entity_id'],
            'domain': 'light', 'service': 'turn_off', 'expect': 'off'}
    A.log(action='turn_off', target=target['entity_id'], channel='冒烟测试', authorization='幂等无副作用测试',
          result='pending', detail='真实写路径验证（目标本来已是关）')
    ex = ha.HaExecutor()
    ex.call(step)
    ok, actual, cost = ex.read_back(step)
    check('写路径：真调用 + 真回读通过', ok and actual == 'off',
          f"{target['name']} → {actual}（{cost}s）")
    A.log(action='turn_off', target=target['entity_id'], channel='冒烟测试',
          authorization='幂等无副作用测试', result='ok' if ok else 'failed', readback=actual,
          detail='写路径冒烟（目标本来已是关，无可见影响）')

    # 3) 安全域：真实执行器必须拒绝
    sec = next((d for d in st['devices'] if d['security_domain'] and d['entity_id']), None)
    if sec:
        refused = False
        try:
            ex.call({'device': sec['name'], 'entity_id': sec['entity_id'],
                     'domain': 'lock', 'service': 'unlock', 'security': True})
        except RuntimeError as e:
            refused = '安全域' in str(e)
        check('真实执行器拒绝安全域动作', refused, sec['name'])

    return summary()


def summary():
    print(f'\n冒烟结果：通过 {len(OK)} · 失败 {len(FAIL)} · 跳过 {len(SKIP)}'
          + (f'　失败项 {FAIL}' if FAIL else '　通过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
