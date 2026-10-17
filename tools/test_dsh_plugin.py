#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH 插件入口测试（P6 多端 · "在 DSH 上有个单独的插件入口"）

目标里明确要求：**桌面端 DSH 要有家庭工作台的独立入口，而且不发到笔记本那端**。
这个交付物容易"装了但没激活"（依赖装了、bundle 名单里没有 → 侧边栏不出现，也不报错）。
所以逐层验：目录结构 → manifest → 补丁 → 客户端 bundle → **profile 里是否已激活** → iframe 目标可达。

用法：python3 tools/test_dsh_plugin.py      退出码 0 = 全过
"""
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, 'app', 'dsh-plugin')
PROFILE = os.path.expanduser('~/.dsh/profiles/desktop')
OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def sha(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()[:16] if os.path.exists(p) else None


def main():
    check('插件目录在', os.path.isdir(PLUGIN))
    pkg = json.load(open(os.path.join(PLUGIN, 'package.json'), encoding='utf-8'))
    check('manifest 名字正确', pkg.get('name') == 'dsh-family-workbench', pkg.get('name'))
    check('声明了 bundle 补丁', (pkg.get('dsh', {}).get('bundle', {}) or {}).get('patch'),
          str(pkg.get('dsh', {}).get('bundle')))
    check('只装 web 客户端（桌面端）', (pkg.get('dsh', {}).get('client', {}) or {}).get('platform') == 'web')

    patch = open(os.path.join(PLUGIN, 'cordis.patch.yml'), encoding='utf-8').read()
    check('补丁里有侧边栏入口 insert', 'insert:' in patch and 'family-workbench' in patch)

    client = open(os.path.join(PLUGIN, 'client', 'client.js'), encoding='utf-8').read()
    check('客户端指向本机工作台（127.0.0.1:8300）', '127.0.0.1:8300' in client)
    check('用 iframe 嵌入（不耦合两边构建链）', 'iframe' in client)
    check('只绑本机（不用局域网/tailnet 地址）',
          '192.168.' not in client and 'ts.net' not in client)

    # profile 是否真的激活（装了≠激活）
    if os.path.isdir(PROFILE):
        prof = json.load(open(os.path.join(PROFILE, 'package.json'), encoding='utf-8'))
        deps = prof.get('dependencies') or {}
        bundles = ((prof.get('dsh') or {}).get('profile') or {}).get('bundles') or []
        check('profile 里装了它', 'dsh-family-workbench' in deps, str(deps.get('dsh-family-workbench')))
        check('profile 的 bundle 名单**已激活**它（装了没激活=侧边栏不出现且不报错）',
              'dsh-family-workbench' in bundles)
        inst = os.path.join(PROFILE, 'node_modules', 'dsh-family-workbench')
        check('已装客户端与源码一致', sha(os.path.join(inst, 'client', 'client.js')) == sha(os.path.join(PLUGIN, 'client', 'client.js')),
              str(sha(os.path.join(inst, 'client', 'client.js'))))
        check('已装补丁与源码一致',
              sha(os.path.join(inst, 'cordis.patch.yml')) == sha(os.path.join(PLUGIN, 'cordis.patch.yml')))
    else:
        check('（未在本机找到 desktop profile，跳过激活检查）', True)

    # iframe 目标可达
    try:
        out = subprocess.run(['/usr/bin/curl', '-s', '-o', '/dev/null', '-w', '%{http_code}',
                              'http://127.0.0.1:8300/'], capture_output=True, text=True, timeout=10)
        check('iframe 目标（工作台 8300）此刻可达', out.stdout.strip() == '200', out.stdout.strip())
    except Exception as err:  # noqa
        check('iframe 目标可达', False, str(err)[:60])

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
