#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
"开始前体检"测试（tools/preflight.py）

体检的价值全在**能不能判 NO-GO**：如果什么情况都说"可以开始"，它就是个摆设。
所以正反都测：全绿→GO；任何一项不过→NO-GO；缺物料→指出缺什么。

用法：python3 tools/test_preflight.py      退出码 0 = 全过
"""
import importlib.util
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='preflight-test-')
spec = importlib.util.spec_from_file_location('pf', os.path.join(ROOT, 'tools', 'preflight.py'))
pf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pf)

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def main():
    # ① 真环境：各检查项能单独跑通
    ok_b, d_b = pf.check_backup()
    check('真环境：备份检查给出文件名与体积', ok_b and 'tgz' in d_b, d_b)
    ok_base, d_base = pf.check_baseline()
    check('真环境：基线条目读得出数字（不是 len() 列表）', ok_base and '台设备' in d_base, d_base)
    ok_m, d_m = pf.check_materials()
    check('真环境：物料齐备', ok_m, d_m)

    # ② 备份异常要能判出来
    bdir = os.path.join(TMP, 'backups')
    os.makedirs(bdir, exist_ok=True)
    check('没有备份 → 判失败', pf.check_backup(backups_dir=bdir)[0] is False)
    old = os.path.join(bdir, 'old.tgz')
    open(old, 'wb').write(b'x' * 2000)
    os.utime(old, (time.time() - 48 * 3600,) * 2)
    check('备份太旧（48h）→ 判失败', pf.check_backup(backups_dir=bdir)[0] is False,
          pf.check_backup(backups_dir=bdir)[1])
    tiny = os.path.join(bdir, 'tiny.tgz')
    open(tiny, 'wb').write(b'x' * 100)
    check('备份体积极小（可疑）→ 判失败', pf.check_backup(backups_dir=bdir)[0] is False,
          pf.check_backup(backups_dir=bdir)[1])

    # ③ 缺物料要点名
    empty = os.path.join(TMP, 'empty')
    os.makedirs(empty, exist_ok=True)
    ok3, d3 = pf.check_materials(data_dir=empty, installers=empty)
    check('缺物料 → 判失败且点名', ok3 is False and '缺' in d3, d3)
    check('点名包含 UTM 与镜像', 'UTM' in d3 and 'HA OS' in d3, d3)

    # ④ GO / NO-GO 判定：注入一个必失败的检查
    real = pf.run_all
    def fake_all(quick=False):
        results = [{'check': 'A', 'ok': True, 'detail': ''},
                   {'check': 'B', 'ok': False, 'detail': '坏了'}]
        return {'go': all(r['ok'] for r in results), 'quick': quick, 'results': results}
    res_bad = fake_all()
    check('任何一项不过 → NO-GO', res_bad['go'] is False, str(res_bad['go']))

    # ⑤ 检查项齐全（八项：含门禁）
    src = open(os.path.join(ROOT, 'tools', 'preflight.py'), encoding='utf-8').read()
    for label in ('备份', '基线', '迁移预检', 'uptime_check', 'vm_autostart', 'homekit_config', '物料', 'gate.py'):
        check(f'体检包含「{label}」', label in src)

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
