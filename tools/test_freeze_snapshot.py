#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
冻结快照测试（tools/freeze_snapshot.py）

它的价值在于**能查出漂移**：改动、删除、新增都要分别报出来。
所以用临时目录造三种情况各验一遍。

用法：python3 tools/test_freeze_snapshot.py      退出码 0 = 全过
"""
import importlib.util
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='freeze-test-')
spec = importlib.util.spec_from_file_location('fs', os.path.join(ROOT, 'tools', 'freeze_snapshot.py'))
fs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fs)

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def main():
    # 真环境：能建快照且零漂移
    snap = fs.build()
    check('真环境能建快照（有文件指纹与规范版本）',
          snap['file_count'] > 50 and bool(snap['spec_versions']), f"{snap['file_count']} 个文件")
    check('规范版本都认出来了（01–11）', len(snap['spec_versions']) >= 10, str(snap['spec_versions']))
    res0 = fs.verify(json.dumps(snap) and _write(snap), current=snap)
    check('同一份内容自比零漂移', res0['drift'] is False, str(res0))

    # 造：改动 / 删除 / 新增
    base = {'at': 'x', 'spec_versions': {}, 'file_count': 2, 'files': {'a.py': 'h1', 'b.py': 'h2'},
            'key_data': {'data/x.json': 'k1'}}
    cur = {'at': 'y', 'spec_versions': {}, 'file_count': 2, 'files': {'a.py': 'CHANGED', 'c.py': 'h3'},
           'key_data': {'data/x.json': 'k2'}}
    res = fs.verify(_write(base), current=cur)
    check('能查出"改动"', res['changed'] == ['a.py'], str(res['changed']))
    check('能查出"删除"', res['removed'] == ['b.py'], str(res['removed']))
    check('能查出"新增"', res['added'] == ['c.py'], str(res['added']))
    check('能查出关键数据变化（仅提示，不算漂移）',
          res['data_changed'] == ['data/x.json'] and res['drift'] is True, str(res['data_changed']))

    # 接进迁移后验收
    post = open(os.path.join(ROOT, 'tools', 'post_migration.py'), encoding='utf-8').read()
    check('迁移后验收已包含"与冻结快照比对"', 'freeze_snapshot' in post or '冻结' in post)

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


def _write(obj):
    p = os.path.join(TMP, 'snap.json')
    json.dump(obj, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    return p


if __name__ == '__main__':
    sys.exit(main())
