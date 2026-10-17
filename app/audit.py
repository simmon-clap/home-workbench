#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
审计留痕（只追加）

依据：docs/spec/08-安全与隐私规范 v1.1 §4（必须记录的字段）· 07 §4（审计只追加）
      11-代码规范 v1.0（标准库、无裸 except、路径可迁移）

做什么：
  把每一次"谁、通过哪条通道、对哪台设备、做了什么、用什么授权、结果与回读值"追加到
  data/audit.jsonl（一行一条 JSON，文本可读、可导出、可追溯）。

不做什么：
  不提供删除/修改接口（审计只能追加，见 M04 门禁）；不记录凭证与影像（08 §6·§7）。
"""
import datetime
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT = os.path.join(ROOT, 'data', 'audit.jsonl')
TZ = datetime.timezone(datetime.timedelta(hours=8))

FIELDS = ['at', 'actor', 'channel', 'action', 'target', 'authorization',
          'result', 'readback', 'detail']


def now_iso():
    return datetime.datetime.now(TZ).isoformat(timespec='seconds')


def log(action, target=None, actor='agent', channel='workbench', authorization='无需',
        result='ok', readback=None, detail=None):
    """追加一条审计记录。返回这条记录（便于调用方回执）。"""
    entry = {'at': now_iso(), 'actor': actor, 'channel': channel, 'action': action,
             'target': target, 'authorization': authorization, 'result': result,
             'readback': readback, 'detail': detail}
    # 来源标记：门禁跑测试时会注入一个随机 tag。这样"测试是否污染生产审计"可以**按标记确定性判定**，
    # 而不是比行数（后台服务本身会正常写审计，比行数会误报 —— 2026-10-17 实测踩到）。
    tag = os.environ.get('SMART_HOME_AUDIT_TAG')
    if tag:
        entry['tag'] = tag
    os.makedirs(os.path.dirname(AUDIT), exist_ok=True)
    with open(AUDIT, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    return entry


def load(limit=None, target=None, result=None):
    """读取审计（最近在后）。只读，无删除。"""
    if not os.path.exists(AUDIT):
        return []
    out = []
    with open(AUDIT, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue      # 坏行跳过，但不改写文件（审计不可篡改）
            if target and e.get('target') != target:
                continue
            if result and e.get('result') != result:
                continue
            out.append(e)
    return out[-limit:] if limit else out


def summary():
    """给界面/验收用的小结：总数、按结果分布、安全域被拒次数。"""
    rows = load()
    dist = {}
    for e in rows:
        dist[e.get('result', '?')] = dist.get(e.get('result', '?'), 0) + 1
    return {'total': len(rows),
            'blocked': dist.get('blocked', 0),
            'failed': dist.get('failed', 0),
            'ok': dist.get('ok', 0),
            'last_at': rows[-1]['at'] if rows else None}


if __name__ == '__main__':
    s = summary()
    print(f"审计记录 {s['total']} 条 · 成功 {s['ok']} · 被拒 {s['blocked']} · 失败 {s['failed']}")
    print(f"最近一条：{s['last_at']}")
    for e in load(limit=5)[::-1]:
        print(f"  {e['at'][11:19]} [{e['result']}] {e['action']} → {e['target']}（{e['authorization']}）")
