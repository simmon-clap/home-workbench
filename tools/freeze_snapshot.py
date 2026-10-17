#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
迁移前冻结快照（指纹 + 版本 + 计数），并支持事后校验漂移

为什么要有：迁移是个大动作，最怕的是"某个文件在窗口前后被悄悄改了而没人知道"。
冻结快照做两件事：
  ① 把 `app/` `tools/` `docs/spec/` 与关键数据的**内容指纹**记下来（含每个文件的 sha256）
  ② 迁移前后可 `--verify` 比对：谁改了、谁没了、谁多出来了 —— 一目了然

用法：
  python3 tools/freeze_snapshot.py                 # 冻结（写 logs/evidence/<日期>-freeze/）
  python3 tools/freeze_snapshot.py --verify <快照.json>
  python3 tools/freeze_snapshot.py --json
退出码：冻结成功 0；校验发现有漂移 1
"""
import argparse
import hashlib
import json
import os
import re
import sys
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = datetime.timezone(datetime.timedelta(hours=8))
GROUPS = {
    'app': os.path.join(ROOT, 'app'),
    'tools': os.path.join(ROOT, 'tools'),
    'spec': os.path.join(ROOT, 'docs', 'spec'),
}
KEY_DATA = ['data/state.json', 'data/settings.json', 'data/scenes.json', 'data/rules.json',
            'data/security-domain.json', 'data/homekit-exposure.json', 'data/homekit-config.yaml',
            'data/automation-manifest.json', 'data/decisions.json', 'data/migration-baseline.json',
            'data/criterion1.json', 'config/homeassistant/automations.yaml']
SKIP_DIRS = {'__pycache__', 'node_modules', '.git', '_archive'}
SKIP_SUFFIX = ('.pyc', '.png', '.dmg', '.xz', '.qcow2', '.tgz')


def sha256(path, limit=None):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def walk(base):
    out = {}
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if fn.endswith(SKIP_SUFFIX):
                continue
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, ROOT)
            try:
                out[rel] = sha256(p)
            except OSError:
                continue
    return out


def spec_versions():
    vers = {}
    d = os.path.join(ROOT, 'docs', 'spec')
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            m = re.match(r'(\d+)-.*-(v[\d.]+)\.md$', fn)
            if m:
                vers[m.group(1)] = m.group(2)
    return vers


def build():
    files = {}
    for name, base in GROUPS.items():
        got = walk(base)
        files.update(got)
    data = {}
    for rel in KEY_DATA:
        p = os.path.join(ROOT, rel)
        if os.path.exists(p):
            try:
                data[rel] = sha256(p)
            except OSError:
                pass
    return {
        'at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
        'spec_versions': spec_versions(),
        'file_count': len(files),
        'files': files,
        'key_data': data,
    }


def verify(snap_path, current=None):
    snap = json.load(open(snap_path, encoding='utf-8'))
    cur = current or build()
    changed, removed, added = [], [], []
    for rel, h in snap['files'].items():
        if rel not in cur['files']:
            removed.append(rel)
        elif cur['files'][rel] != h:
            changed.append(rel)
    for rel in cur['files']:
        if rel not in snap['files']:
            added.append(rel)
    data_changed = [rel for rel, h in snap.get('key_data', {}).items()
                    if cur['key_data'].get(rel) != h]
    return {'changed': sorted(changed), 'removed': sorted(removed), 'added': sorted(added),
            'data_changed': sorted(data_changed), 'drift': bool(changed or removed or added)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--verify', metavar='SNAPSHOT')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    if a.verify:
        res = verify(a.verify)
        if a.json:
            print(json.dumps(res, ensure_ascii=False, indent=1))
        else:
            print('=== 与冻结快照比对 ===')
            print(f"  改动 {len(res['changed'])} · 删除 {len(res['removed'])} · 新增 {len(res['added'])}")
            for k in ('changed', 'removed', 'added'):
                if res[k]:
                    print(f"  {k}: " + '、'.join(res[k][:8]) + ('…' if len(res[k]) > 8 else ''))
            if res['data_changed']:
                print('  关键数据变化（迁移前后本来就会变，仅提示）: ' + '、'.join(res['data_changed'][:5]))
            print('结论：' + ('**有代码/规范漂移**（上面列出的文件被改动）' if res['drift']
                            else '**代码与规范零漂移** ✅'))
        return 1 if res['drift'] else 0

    snap = build()
    E = os.path.join(ROOT, 'logs', 'evidence',
                     datetime.datetime.now(TZ).strftime('%Y%m%d') + '-freeze')
    os.makedirs(E, exist_ok=True)
    out = os.path.join(E, 'freeze-snapshot.json')
    json.dump(snap, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if a.json:
        print(json.dumps({k: v for k, v in snap.items() if k != 'files'}, ensure_ascii=False, indent=1))
    else:
        print('=== 冻结快照 ===')
        print(f"  时间：{snap['at']}")
        print(f"  文件指纹：{snap['file_count']} 个（app / tools / docs/spec）")
        print(f"  关键数据：{len(snap['key_data'])} 个")
        print('  规范版本：' + ' · '.join(f"{k}={v}" for k, v in sorted(snap['spec_versions'].items())))
        print(f"  快照写入：{os.path.relpath(out, ROOT)}")
        print(f"  事后校验：python3 tools/freeze_snapshot.py --verify {os.path.relpath(out, ROOT)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
