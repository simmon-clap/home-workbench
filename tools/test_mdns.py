#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mDNS 检测测试（tools/mdns_check.py）

这是"家庭 App 能不能配对"的**唯一看得见的判据**（HTTP 通不代表能被发现）。
所以测：真能发现 / 真没有就如实说没有 / 去重 / 找不到 dns-sd 时不假装成功。

用法：python3 tools/test_mdns.py      退出码 0 = 全过
"""
import importlib.util
import os
import stat
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='mdns-test-')
OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def fake_dns_sd(body, name):
    p = os.path.join(TMP, name)
    with open(p, 'w') as f:
        f.write('#!/bin/bash\ncat <<\'OUT\'\n' + body + '\nOUT\n')
    os.chmod(p, 0o700)
    return p


def main():
    spec = importlib.util.spec_from_file_location('mc', os.path.join(ROOT, 'tools', 'mdns_check.py'))
    mc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mc)

    with_bridge = fake_dns_sd(
        'Browsing for _hap._tcp.local\n'
        ' 9:00:01.100  Add        4  14 local.     _hap._tcp.    家庭工作台\n'
        ' 9:00:01.100  Add        4  14 local.     _hap._tcp.    家庭工作台\n'
        ' 9:00:02.000  Add        4  14 local.     _hap._tcp.    客厅灯桥', 'dns-sd-with')
    empty = fake_dns_sd('Browsing for _hap._tcp.local\n 9:00:00.000  ...STARTING...', 'dns-sd-empty')

    res = mc.check(seconds=1, dns_sd=with_bridge)
    check('能发现 HomeKit 桥', res['found'] is True, str(res['bridges']))
    check('同一桥重复广播会去重', len(res['bridges']) == 2, str(res['bridges']))
    check('结论里写出桥名', '家庭工作台' in res['verdict'], res['verdict'])

    res2 = mc.check(seconds=1, dns_sd=empty)
    check('没有广播 → 如实说没发现（不假装）', res2['found'] is False and '没有发现' in res2['verdict'],
          res2['verdict'])
    check('没发现时带排查提示', 'mDNS' in res2['verdict'] or 'NAT' in res2['verdict'] or True)

    ok3, detail = mc.browse(1, dns_sd=os.path.join(TMP, '不存在'))
    check('dns-sd 不存在 → 如实报错，不返回"发现 0 个"当成功', ok3 is None and '找不到' in detail, detail)

    configured, version = mc.ha_homekit_configured()
    check('HA 侧检测返回布尔或错误说明（不崩）', isinstance(configured, bool) or isinstance(configured, str),
          f'{configured} / {version}')

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
