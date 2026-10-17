#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布前审计：检查将要公开的文件里是否混入个人标识、凭证、隐私数据。

用法：
  python3 tools/release_audit.py [--public-set] [目录]

  --public-set  只检查计划公开的白名单（app/ tools/ dsh-plugin/ docs/oss/ 等），
                忽略私有 README/docs/spec 等；CI/发布流程用这个。
  默认          检查 git 已跟踪的全部文件（开发仓自检）。

规则：
  1) 禁止目录被跟踪：data/ config/ backups/ logs/ installers/ vm/ vendor/
  2) 个人标识：内网/tailnet IP、tailnet 主机名、本机用户名路径、家庭名前缀、手机名
  3) 凭证：JWT、私钥、密码赋值
  4) 大文件（>2MB）提醒（可能误入二进制素材）
退出码：0 = 通过；1 = 发现问题。
"""
import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORBIDDEN_DIRS = ('data/', 'config/', 'backups/', 'logs/', 'installers/', 'vm/', 'vendor/')
PUBLIC_DIRS = ('app/', 'tools/', 'dsh-plugin/', 'docs/oss/')
PUBLIC_FILES = ('LICENSE', 'SECURITY.md', 'PRIVACY.md', 'docs/oss/README-public-draft.md',
                'docker-compose.yml', '.gitignore', 'CONTRIBUTING.md', '.github/')
PATTERNS = [
    ('内网 IP', re.compile(r'\b192\.168\.\d{1,3}\.\d{1,3}\b')),
    ('tailnet IP', re.compile(r'\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b')),
    ('tailnet 主机名', re.compile(r'tail[0-9a-f]{6,}\.ts\.net', re.I)),
    ('本机用户路径', re.compile(r'/Users/[A-Za-z][A-Za-z0-9._-]+')),
    ('用户名', re.compile(r'\bsimmon\b', re.I)),
    ('家庭名前缀', re.compile(r'小盆友|西蒙')),
    ('个人手机名', re.compile(r'Ming的iPhone|iPhone\d{2},\d')),
    ('DSH 私有目录', re.compile(r'飞书工作区|default-workspace')),
    ('JWT', re.compile(r'eyJ[A-Za-z0-9_-]{20,}')),
    ('私钥', re.compile(r'PRIVATE KEY')),
    ('密码赋值', re.compile(r'password\s*[:=]\s*["\'][^"\']{4,}', re.I)),
]
SKIP_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.ico', '.pdf', '.tgz', '.zip', '.pyc'}
TEXT_EXT = {'.py', '.md', '.yml', '.yaml', '.js', '.mjs', '.html', '.css', '.sh', '.json', '.txt', '.toml'}


def tracked():
    try:
        out = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True)
        return [l for l in out.stdout.splitlines() if l.strip()]
    except Exception:
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--public-set', action='store_true')
    ap.add_argument('dir', nargs='?', default=ROOT)
    a = ap.parse_args()
    files = tracked()
    if a.dir != ROOT:
        files = []
        for base, _, names in os.walk(a.dir):
            for n in names:
                rel = os.path.relpath(os.path.join(base, n), a.dir)
                files.append(rel)
    if a.public_set:
        files = [f for f in files if f.startswith(PUBLIC_DIRS) or f in PUBLIC_FILES]
    problems, warns = [], []
    for rel in files:
        if rel.replace(os.sep, '/') == 'tools/release_audit.py':
            continue  # 本文件是扫描器，规则本身就是这些字样
        if any(rel.startswith(d) for d in FORBIDDEN_DIRS):
            problems.append(f'{rel}: 禁止发布的数据目录')
            continue
        p = os.path.join(a.dir, rel)
        try:
            size = os.path.getsize(p)
        except OSError:
            continue
        if size > 2 * 1024 * 1024:
            warns.append(f'{rel}: 大文件 {size//1024} KB（确认是否素材）')
        ext = os.path.splitext(rel)[1].lower()
        if ext in SKIP_EXT or ext not in TEXT_EXT:
            continue
        try:
            text = open(p, encoding='utf-8', errors='ignore').read()
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for name, pat in PATTERNS:
                if pat.search(line):
                    problems.append(f'{rel}:{i}: {name} → {line.strip()[:90]}')
    for w in warns:
        print('⚠️ ', w)
    if problems:
        print(f'\n❌ 发现 {len(problems)} 处需要处理：')
        for x in problems[:60]:
            print('  -', x)
        if len(problems) > 60:
            print(f'  … 还有 {len(problems)-60} 处')
        return 1
    print(f'\n✅ 发布审计通过：{len(files)} 个文件无个人标识/凭证/禁止目录')
    return 0


if __name__ == '__main__':
    sys.exit(main())
