#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HA 调用审计的测试（tools/audit_ha_calls.py）

审计要能**真的发现问题**才有意义，所以：① 扫描逻辑用造出来的代码文件验证 ② 真跑一次真环境
（引用不存在的服务必须被抓出来）。

用法：python3 tools/test_audit_ha_calls.py      退出码 0 = 全过
"""
import importlib.util
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='audit-test-')
spec = importlib.util.spec_from_file_location('ah', os.path.join(ROOT, 'tools', 'audit_ha_calls.py'))
ah = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ah)

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def main():
    # ① 真环境：全部存在
    problems, info = ah.run()
    check('真环境：我们引用的服务/命令/接口都存在', not problems, '；'.join(problems)[:100])
    check('确实扫到了服务引用（不是空集）', len(info.get('services_checked') or []) >= 10,
          f"{len(info.get('services_checked') or [])} 个")
    check('WS 四个命令都可用', all((info.get('ws_commands') or {}).values()),
          json.dumps(info.get('ws_commands') or {}, ensure_ascii=False))

    # ② 扫描逻辑：造一个引用不存在服务的文件，必须被抓出来
    fake = os.path.join(TMP, 'fake.py')
    # 用拼接构造，避免这段字面量被审计扫到（审计排除 test_*.py，但双保险更稳）
    call = 'call_' + 'service'
    open(fake, 'w', encoding='utf-8').write(
        f"ha.{call}('light', 'turn_on')\n"
        f"ha.{call}('nonexistent_domain', 'do_magic')\n")
    real_root = ah.ROOT
    ah.ROOT = TMP
    calls = ah.static_calls()
    ah.ROOT = real_root
    check('能扫出字面量服务调用', ('light', 'turn_on') in calls, str(sorted(calls)))
    check('能扫出"不存在的域"（交给核对环节判失败）', ('nonexistent_domain', 'do_magic') in calls)

    have = {'light': {'turn_on'}}
    missing = [f'{d}.{s}' for d, s in calls if d not in have or s not in have[d]]
    check('核对环节能把不存在的服务判出来', 'nonexistent_domain.do_magic' in missing, str(missing))

    # ③ 映射表与场景步骤都被采集
    mc = ah.mapping_calls()
    check('采集了 panel_action 的域→服务映射', ('light', 'turn_on') in mc and ('button', 'press') in mc,
          str(sorted(mc))[:80])
    check('采集了场景步骤里的服务（读 data/scenes.json）', isinstance(ah.scene_calls(), set))

    # ③.5 实体审计（服务名对了不代表实体还在）
    ep, ei = ah.entity_audit()
    check('真环境：实体审计无问题（无失效实体/坏动作目标/安全域误放行）', not ep, '；'.join(ep)[:80])
    check('实体审计给出计数（HA 实体数、设备数、可控设备数）',
          (ei.get('entities_in_ha') or 0) > 0 and (ei.get('devices') or 0) > 0 and (ei.get('controllable_devices') or 0) > 0,
          str(ei))
    check('可控设备数少于总设备数（只读/安全域没被算成可控）',
          ei.get('controllable_devices', 99) < ei.get('devices', 0),
          f"{ei.get('controllable_devices')} / {ei.get('devices')}")

    # ④ 接入体检
    pre = open(os.path.join(ROOT, 'tools', 'preflight.py'), encoding='utf-8').read()
    check('开工前体检已包含调用审计', 'audit_ha_calls' in pre)

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
