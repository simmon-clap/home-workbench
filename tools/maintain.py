#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
长期维护：日志轮转 + 磁盘余量守护（P5 加固 · 十年测试）

为什么要有：这两件事**失效时都是静默的**——
  · 日志无限增长 → 占满磁盘（谁都不会注意到，直到写不进去）
  · 磁盘将满 → HA 的 recorder 会停、备份会失败，但界面照样显示"正常"
宪章第三条：不允许拿旧读数冒充现在；同理，也不允许"磁盘快满了却装作没事"。

做什么：
  1. **日志轮转**：`logs/*.log` 超过阈值就只保留最后 N 行（原文件先备份一份到 logs/archive 带时间戳）
  2. **磁盘余量**：低于警戒线就在结果里明说（供简报/工作台提示），并写出当前余量
  3. 清理 `logs/archive/` 里超过保留期的临时文件

不做：不删证据（logs/evidence 一律不动）、不删备份（备份保留由 backup.sh 管）。

用法：
  python3 tools/maintain.py            # 执行维护并打印结果
  python3 tools/maintain.py --dry      # 只看会做什么
"""
import argparse
import datetime
import glob
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(ROOT, 'logs')
ARCHIVE = os.path.join(LOGS, 'archive')
DATA = os.path.join(ROOT, 'data')
STATE = os.path.join(DATA, 'maintenance.json')
TZ = datetime.timezone(datetime.timedelta(hours=8))

LOG_MAX_BYTES = 5 * 1024 * 1024      # 单个日志超过 5MB 就轮转
LOG_KEEP_LINES = 2000                # 轮转后保留最后 2000 行
ARCHIVE_KEEP_DAYS = 30               # logs/archive 里的 .tmp/.log 保留 30 天
DISK_WARN_GB = 5.0                   # 磁盘余量警戒线
DISK_CRIT_GB = 2.0                   # 严重


def disk_free_gb(path='/'):
    st = os.statvfs(path)
    return round(st.f_bavail * st.f_frsize / 1e9, 2)


def rotate_logs(dry=False):
    """把过大的日志截断成最后 N 行（原文归档一份）。返回处理明细。"""
    os.makedirs(ARCHIVE, exist_ok=True)
    done = []
    for path in sorted(glob.glob(os.path.join(LOGS, '*.log'))):
        size = os.path.getsize(path)
        if size <= LOG_MAX_BYTES:
            continue
        name = os.path.basename(path)
        stamp = datetime.datetime.now(TZ).strftime('%Y%m%d-%H%M%S')
        if dry:
            done.append({'file': name, 'size_mb': round(size / 1048576, 1), 'action': 'would rotate'})
            continue
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
        except OSError as err:
            done.append({'file': name, 'error': str(err)[:80]})
            continue
        keep = lines[-LOG_KEEP_LINES:]
        shutil.copy2(path, os.path.join(ARCHIVE, f'{name}.{stamp}.gz.bak'))
        with open(path, 'w', encoding='utf-8') as f:
            f.write(''.join(keep))
        done.append({'file': name, 'from_mb': round(size / 1048576, 1),
                     'to_lines': len(keep), 'archived': f'{name}.{stamp}.gz.bak'})
    return done


def prune_archive(dry=False, keep_days=ARCHIVE_KEEP_DAYS):
    """清理 archive 里过期的临时/日志副本（**证据目录一律不动**）。"""
    cut = datetime.datetime.now().timestamp() - keep_days * 86400
    removed = []
    for path in glob.glob(os.path.join(ARCHIVE, '*')):
        base = os.path.basename(path)
        if os.path.isdir(path):
            continue
        if not (base.endswith('.tmp') or '.log.' in base or base.endswith('.bak')):
            continue
        if os.path.getmtime(path) >= cut:
            continue
        if dry:
            removed.append(base)
            continue
        try:
            os.remove(path)
            removed.append(base)
        except OSError:
            pass
    return removed


def check_disk(free=None):
    free = disk_free_gb() if free is None else free
    if free < DISK_CRIT_GB:
        level, msg = 'crit', f'磁盘余量只剩 {free} GB —— **随时可能写不进去**（HA 历史、备份都会受影响）'
    elif free < DISK_WARN_GB:
        level, msg = 'warn', f'磁盘余量 {free} GB，低于警戒线 {DISK_WARN_GB} GB，该清理了'
    else:
        level, msg = 'ok', f'磁盘余量 {free} GB，正常'
    return {'free_gb': free, 'level': level, 'message': msg,
            'warn_gb': DISK_WARN_GB, 'crit_gb': DISK_CRIT_GB}


def run(dry=False):
    now = datetime.datetime.now(TZ)
    rot = rotate_logs(dry=dry)
    pruned = prune_archive(dry=dry)
    disk = check_disk()
    logs_mb = round(sum(os.path.getsize(p) for p in glob.glob(os.path.join(LOGS, '*.log'))) / 1048576, 1)
    doc = {'at': now.isoformat(timespec='seconds'), 'rotated': rot, 'pruned': pruned,
           'disk': disk, 'logs_mb': logs_mb,
           'policy': {'log_max_mb': LOG_MAX_BYTES // 1048576, 'keep_lines': LOG_KEEP_LINES,
                      'archive_keep_days': ARCHIVE_KEEP_DAYS, 'disk_warn_gb': DISK_WARN_GB}}
    if not dry:
        os.makedirs(DATA, exist_ok=True)
        json.dump(doc, open(STATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return doc


def summary():
    try:
        return json.load(open(STATE, encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()
    doc = run(dry=a.dry)
    if a.dry:
        print('[dry] 会轮转：', [r['file'] for r in doc['rotated']] or '无')
        print('[dry] 会清理：', doc['pruned'] or '无')
    else:
        print(f"日志轮转：{len(doc['rotated'])} 个文件" + (f"（{[r['file'] for r in doc['rotated']]}）" if doc['rotated'] else ''))
        print(f"清理归档：{len(doc['pruned'])} 项" if doc['pruned'] else '清理归档：无')
    print(f"日志总量：{doc['logs_mb']} MB")
    print(doc['disk']['message'])
    return 0 if doc['disk']['level'] != 'crit' else 1


if __name__ == '__main__':
    sys.exit(main())
