#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成干净的公开仓库目录（白名单复制 + 说明文件替换），不推远端。

用法：python3 tools/build_public_repo.py [输出目录]   （默认 ~/smart-home-public）
之后：cd 输出目录 && git init && git add . && git commit；由用户推到 GitHub。
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.abspath(os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else '~/smart-home-public'))
INCLUDE_DIRS = ('app', 'tools', 'dsh-plugin', '.github')
INCLUDE_FILES = ('LICENSE', 'docker-compose.yml', '.gitignore')
MAP = [('docs/oss/README-public-draft.md', 'README.md'),
       ('docs/oss/SECURITY.md', 'SECURITY.md'),
       ('docs/oss/PRIVACY.md', 'PRIVACY.md'),
       ('docs/oss/CONFIGURATION.md', 'docs/CONFIGURATION.md'),
       ('docs/oss/RELEASE-PLAN.md', 'docs/RELEASE-PLAN.md'),
       ('docs/oss/CONTRIBUTING.md', 'CONTRIBUTING.md')]
SKIP_NAMES = ('__pycache__', '.DS_Store')


def copy_tree(src, dst):
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        if name in SKIP_NAMES:
            continue
        s, d = os.path.join(src, name), os.path.join(dst, name)
        if os.path.isdir(s):
            copy_tree(s, d)
        else:
            shutil.copy2(s, d)


def main():
    force = '--force' in sys.argv
    if os.path.exists(OUT) and os.listdir(OUT):
        if not force:
            sys.exit(f'输出目录非空：{OUT}（加 --force 覆盖，或换个目录）')
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)
    for d in INCLUDE_DIRS:
        s = os.path.join(ROOT, d)
        if os.path.isdir(s):
            copy_tree(s, os.path.join(OUT, d))
    for f in INCLUDE_FILES:
        s = os.path.join(ROOT, f)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(OUT, f))
    for src, dst in MAP:
        s = os.path.join(ROOT, src)
        if os.path.isfile(s):
            os.makedirs(os.path.dirname(os.path.join(OUT, dst)) or OUT, exist_ok=True)
            shutil.copy2(s, os.path.join(OUT, dst))
    print(f'已生成公开仓库目录：{OUT}')
    print('（data/config/backups/logs/installers/vm/vendor 未复制；README 用对外草稿）')


if __name__ == '__main__':
    main()
