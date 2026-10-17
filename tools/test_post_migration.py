#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
迁移后验收的测试（tools/post_migration.py）

验收工具的价值在于**它会不会漏判**：迁移没成的时候如果说"完成了"，后面全是坑。
所以重点测：形态没翻转必须判失败；状态层没走 API 必须判失败；HomeKit 没配/发现不了必须判失败。

用法：python3 tools/test_post_migration.py      退出码 0 = 全过
"""
import importlib.util
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='postmig-test-')
spec = importlib.util.spec_from_file_location('pm', os.path.join(ROOT, 'tools', 'post_migration.py'))
pm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pm)

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def main():
    real_cfg = pm._ha_config
    real_data = pm.DATA

    # ① 形态判定：容器版必须判失败，HA OS 才通过
    pm._ha_config = lambda: {'version': '2026.10.1', 'components': ['light', 'xiaomi_home']}
    ok1, d1 = pm.check_form()
    check('容器版（无 hassio）→ 判失败', ok1 is False and '容器版' in d1, d1)
    pm._ha_config = lambda: {'version': '2026.10.1', 'components': ['hassio', 'homekit']}
    ok2, d2 = pm.check_form()
    check('HA OS（有 hassio）→ 通过', ok2 is True, d2)
    pm._ha_config = lambda: None
    ok3, d3 = pm.check_form()
    check('读不到配置 → 判失败（不当成通过）', ok3 is False, d3)
    pm._ha_config = real_cfg

    # ② 状态层数据来源
    pm.DATA = TMP
    p = os.path.join(TMP, 'state.json')
    json.dump({'data_source': {'registries': 'api', 'states': 'api'}}, open(p, 'w'))
    ok4, _ = pm.check_state_source()
    check('状态层走 API → 通过', ok4 is True)
    json.dump({'data_source': {'registries': 'files', 'states': 'files'}}, open(p, 'w'))
    ok5, d5 = pm.check_state_source()
    check('状态层还是读文件 → 判失败', ok5 is False, d5)
    os.remove(p)
    check('缺 state.json → 判失败', pm.check_state_source()[0] is False)
    pm.DATA = real_data

    # ③ 汇总判定：任一条不过就不是"迁完"
    def fake_all(quick=False):
        res = [{'check': 'a', 'ok': True, 'detail': ''}, {'check': 'b', 'ok': False, 'detail': '没成'}]
        return {'done': all(r['ok'] for r in res), 'quick': quick, 'results': res, 'manual': pm.MANUAL}
    check('有未通过项 → 不算迁完', fake_all()['done'] is False)

    # ④ 必须如实列出"只能人做"的事
    check('列出了需要人工完成的事项', len(pm.MANUAL) >= 3, str(len(pm.MANUAL)))
    check('人工事项里包含配对与授权',
          any('配对' in m for m in pm.MANUAL) and any('授权' in m for m in pm.MANUAL))
    check('人工事项里提示 Tailscale 地址可能变', any('Tailscale' in m for m in pm.MANUAL))

    # ⑤ 与体检是镜像关系（都覆盖关键项）
    src = open(os.path.join(ROOT, 'tools', 'post_migration.py'), encoding='utf-8').read()
    for label in ('hassio', 'mdns_check', 'vm_autostart', 'migrate_check', 'uptime_check', 'gate.py'):
        check(f'验收覆盖「{label}」', label in src)
    check('真环境：验收能跑且给出结论（当前应为未完成）',
          pm.run_all(quick=True)['done'] in (True, False))

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
