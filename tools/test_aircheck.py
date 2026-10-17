#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Air 演练就绪检查测试（tools/air_check.py）

这个工具的价值在于"不装、不改，只如实报告能不能开始"。所以重点测：
  ① Air 不可达时**如实说不通**，并给出用户要做的两件事
  ② 不探测到时**绝不假装可达**
  ③ 本地物料（HA OS 镜像 / 最新备份 / 手册）能列出来
  ④ 演练步骤与关键验收点（mDNS）在输出里写清楚

用法：python3 tools/test_aircheck.py      退出码 0 = 全过
"""
import importlib.util
import io
import os
import sys
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('ac', os.path.join(ROOT, 'tools', 'air_check.py'))
ac = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ac)

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def run_main():
    buf = io.StringIO()
    with redirect_stdout(buf):
        ac.main()
    return buf.getvalue()


def main():
    # ① 不可达时如实报告（当前 Air 休眠，正好是这个分支）
    ac.check_air = lambda: {'reachable': False, 'ip': None, 'info': {}}
    out = run_main()
    check('Air 不可达时如实说"连不上"', '连不上' in out, out.splitlines()[1][:50])
    check('给出用户要做的两件事（唤醒 + 远程登录）',
          '唤醒' in out and '远程登录' in out)
    check('没有假装可达（不出现"✅ Air 可达"）', '✅ Air 可达' not in out)

    # ② 可达时报告硬件与环境，并提示需装什么
    ac.check_air = lambda: {'reachable': True, 'ip': '203.0.113.9',
                            'info': {'macos': '15.0', 'mem_gb': 16, 'cpu': 8, 'disk_free_gb': 100.0,
                                     'utm': False, 'qemu': False, 'brew': True, 'virtualization': True}}
    out = run_main()
    check('可达时报告系统与硬件', 'macOS 15.0' in out and '16 GB' in out)
    check('未装虚拟化时提示"等你点头才装"', '等你点头才装' in out)

    # ③ 内存不足要提醒
    ac.check_air = lambda: {'reachable': True, 'ip': 'x',
                            'info': {'macos': '15.0', 'mem_gb': 4, 'cpu': 4, 'disk_free_gb': 20.0,
                                     'utm': False, 'qemu': False, 'brew': False, 'virtualization': True}}
    out = run_main()
    check('内存偏小时给出提醒', '内存 < 8GB' in out or '吃紧' in out)

    # ④ 本地物料与演练步骤
    mat = ac.local_materials()
    check('能列出本地物料（镜像/备份/手册）',
          'haos_image' in mat and 'latest_backup' in mat and 'runbooks' in mat,
          f"{mat.get('latest_backup')} / {mat.get('haos_image')}")

    ac.check_air = lambda: {'reachable': False, 'ip': None, 'info': {}}
    out = run_main()
    check('写清演练会做什么（含"不碰家里"）', '不碰家里' in out and 'check_config' in out)
    check('写明停机可压到 10 分钟内', '10 分钟' in out)

    rb = os.path.join(ROOT, 'data', 'runbook-air-rehearsal.md')
    check('演练手册存在', os.path.exists(rb))
    txt = open(rb, encoding='utf-8').read() if os.path.exists(rb) else ''
    check('手册含关键验收点 mDNS', 'mDNS' in txt)
    check('手册写明"桥接不可用不许假装通过"', '不假装' in txt or '未验证' in txt)
    check('手册含 HomeKit 试点与安全域红线', 'homekit-exposure' in txt and '安全域' in txt)

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
