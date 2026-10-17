#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HA OS 虚拟机开机自启测试（tools/vm_autostart.py）

要点：
  ① 迁移前（没有 UTM / 没有虚拟机）**不算失败**，但要说清"尚未迁移"
  ② 一旦有虚拟机，**没有自启就必须判失败**（否则 Mac 重启后 HA 不会回来，且不报错）
  ③ 装了自启后要能读出来、并且**登记进清单**（让门禁 Q36 一起守）
  ④ utmctl 输出里的分隔线不能被当成一台虚拟机

全程用假 utmctl 与临时目录，不碰真实 LaunchAgents。

用法：python3 tools/test_vm_autostart.py      退出码 0 = 全过
"""
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='vm-auto-test-')
OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def make_utm(list_out, name='utmctl'):
    p = os.path.join(TMP, name)
    with open(p, 'w') as f:
        f.write('#!/bin/bash\nif [ "$1" = "list" ]; then\ncat <<\'OUT\'\n' + list_out + '\nOUT\nfi\n')
    os.chmod(p, 0o700)          # 注意：别用 0o500 —— 再写同名文件会 PermissionError（实测踩过）
    return p


def load(utm=None):
    env = dict(os.environ, SMART_HOME_LAUNCH_AGENTS=os.path.join(TMP, 'agents'),
               SMART_HOME_MANIFEST=os.path.join(TMP, 'manifest.json'))
    if utm:
        env['UTM_CLI'] = utm
    spec = importlib.util.spec_from_file_location('vm', os.path.join(ROOT, 'tools', 'vm_autostart.py'))
    mod = importlib.util.module_from_spec(spec)
    old = dict(os.environ)
    os.environ.update(env)
    try:
        spec.loader.exec_module(mod)
    finally:
        os.environ.clear(); os.environ.update(old)
    return mod


HEADER = 'UUID                                 Name        Status\n' \
         '-----------------------------------  ----------  ----------'


def main():
    empty = make_utm(HEADER, 'utmctl-empty')
    one = make_utm(HEADER + '\nA1B2C3D4-1111-2222-3333-444455556666  HA OS       stopped', 'utmctl-one')

    m0 = load(empty)
    ok0, i0 = m0.check()
    check('没有虚拟机 → 不算失败（迁移前正常）', ok0, i0['verdict'])

    m1 = load(one)
    vms = m1.list_vms()
    check('能列出虚拟机', len(vms) == 1, f'{len(vms)} 台')
    check('utmctl 的分隔线没被当成虚拟机', all(set(v['id']) != {'-'} for v in vms), str(vms))
    ok1, i1 = m1.check()
    check('有虚拟机但没自启 → 判失败', ok1 is False, i1['verdict'][:40])
    check('失败时明确指出后果', '不会自己回来' in i1['verdict'], i1['verdict'][:50])

    path = m1.install('A1B2C3D4-1111-2222-3333-444455556666')
    check('装上了自启 plist', os.path.exists(path), path)
    import plistlib
    d = plistlib.load(open(path, 'rb'))
    check('自启是 RunAtLoad（开机就跑）', d.get('RunAtLoad') is True)
    check('自启命令是 utmctl start <vm-id>',
          d['ProgramArguments'][-2:] == ['start', 'A1B2C3D4-1111-2222-3333-444455556666'],
          str(d['ProgramArguments']))
    ok2, i2 = m2 = load(one).check()
    check('装完后检查通过', ok2, i2['verdict'])

    man = json.load(open(os.path.join(TMP, 'manifest.json'), encoding='utf-8'))
    ids = [s['id'] for s in man.get('services') or []]
    check('已登记进清单（门禁 Q36 会一起守）', 'haos-vm' in ids, str(ids))

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
