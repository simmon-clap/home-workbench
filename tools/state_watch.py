#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
外部改动入账：状态变了，要说得清"是我们做的，还是别的地方动的"

依据（宪章直接推导，不需要新规范）：
  · 第三条：状态可以被新事实推翻，但**推翻要留痕** —— 保留"当时为什么这么判断"
  · 第四条：发出指令不是终点，回读之后才算完成 —— 所以我们**绝不把外部改动冒充成自己的回执**
  · 判据 3：任何一次"已完成"都能点回状态证据

为什么现在就要做：家里的灯可能被**墙面开关、米家 App、家庭 App** 动过。
不记来源的话，工作台只会显示"变了"，用户无法判断这是系统做的还是别人做的 —— 状态真相不完整。

做法：
  比对两次状态快照 → 找出变化的设备 → 看最近有没有**我方动作**记录（审计/动作台账）：
    · 有 → source=self（我方）
    · 没有 → source=external（外部：墙面开关 / 米家 / 家庭 App / 别人）
  写入 data/state-changes.jsonl（只追加），并保留快照供下次比对。

诚实规则：**首次运行只建立基线**，不把早已存在的差异说成"外部改动"。

用法：
  python3 tools/state_watch.py --once        # 查一次（定时任务用）
  python3 tools/state_watch.py --recent 20   # 最近的变化（含来源）
"""
import argparse
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CHANGES = os.environ.get('SMART_HOME_CHANGES') or os.path.join(DATA, 'state-changes.jsonl')
SNAPDIR = os.environ.get('SMART_HOME_SNAPDIR') or os.path.join(DATA, 'state-history')
SELF_WINDOW_MIN = 10          # 我方动作在这个窗口内，算"我们做的"
TZ = datetime.timezone(datetime.timedelta(hours=8))


def _load(path, default):
    try:
        return json.load(open(path, encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return default


def _now(now=None):
    return now or datetime.datetime.now(TZ)


def snapshot(state=None):
    st = state or _load(os.path.join(DATA, 'state.json'), {'devices': []})
    out = {}
    for d in st.get('devices') or []:
        out[d['name']] = {'state': d.get('state'), 'room': d.get('room'),
                          'confidence': d.get('confidence')}
    return out


def self_actions(window_min=SELF_WINDOW_MIN, now=None):
    """最近 N 分钟内我方真的执行过动作的设备集合（含来源证据）。"""
    now = now or _now()
    since = now - datetime.timedelta(minutes=window_min)
    hits = {}

    def _ts(s):
        try:
            t = datetime.datetime.fromisoformat(s)
            return t if t.tzinfo else t.replace(tzinfo=TZ)
        except (TypeError, ValueError):
            return None

    for row in _load(os.path.join(DATA, 'actions.json'), {}).get('actions') or []:
        t = _ts(row.get('at'))
        if t and t >= since:
            for r in row.get('results') or []:
                if r.get('ok'):
                    hits[r.get('device')] = f"我方动作（动作记录 {row.get('at')}）"
    try:
        for line in open(os.path.join(DATA, 'audit.jsonl'), encoding='utf-8'):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            t = _ts(row.get('at'))
            if t and t >= since and row.get('result') == 'ok':
                tg = row.get('target')
                if tg:
                    hits.setdefault(tg, f"我方动作（审计 {row.get('at')}）")
    except FileNotFoundError:
        pass
    return hits


def check_once(now=None, verbose=True):
    now = _now(now)
    os.makedirs(SNAPDIR, exist_ok=True)
    cur = snapshot()
    path = os.path.join(SNAPDIR, 'last.json')
    first_run = not os.path.exists(path)
    # 注意：快照文件是 {'at':..., 'devices': {...}}，比对要取里面的 devices（曾漏掉这层导致永远比不到变化）
    prev = {} if first_run else ((_load(path, {}) or {}).get('devices') or {})

    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'at': now.isoformat(timespec='seconds'), 'devices': cur}, f, ensure_ascii=False, indent=1)

    if first_run:
        if verbose:
            print(f'首次运行：只建立基线（{len(cur)} 台设备），不把已有差异说成外部改动')
        return [], 0

    ours = self_actions(now=now)
    changes = []
    for name, c in cur.items():
        p = prev.get(name)
        if p is None:
            continue
        if p.get('state') == c.get('state'):
            continue
        src = 'self' if name in ours else 'external'
        rec = {'at': now.isoformat(timespec='seconds'), 'device': name, 'room': c.get('room'),
               'from': p.get('state'), 'to': c.get('state'), 'source': src,
               'evidence': ours.get(name) or '没有我方动作记录 → 判定为外部改动'}
        changes.append(rec)

    if changes:
        os.makedirs(os.path.dirname(CHANGES), exist_ok=True)
        with open(CHANGES, 'a', encoding='utf-8') as f:
            for r in changes:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
    if verbose:
        if changes:
            ext = [c for c in changes if c['source'] == 'external']
            print(f'记录了 {len(changes)} 处变化（其中外部 {len(ext)} 处）')
            for c in changes[:8]:
                tag = '外部' if c['source'] == 'external' else '我方'
                print(f"  [{tag}] {c['device']}：{c['from']} → {c['to']}")
        else:
            print('没有状态变化')
    return changes, len(changes)


def recent(limit=20):
    rows = []
    try:
        for line in open(CHANGES, encoding='utf-8'):
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    except FileNotFoundError:
        return []
    return rows[-limit:][::-1]


def for_device(name, limit=5):
    return [r for r in recent(500) if r.get('device') == name][:limit]


def summary():
    rows = recent(500)
    return {'total': len(rows), 'external': sum(1 for r in rows if r.get('source') == 'external'),
            'self': sum(1 for r in rows if r.get('source') == 'self'),
            'last_at': rows[0]['at'] if rows else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--recent', type=int)
    ap.add_argument('--device')
    a = ap.parse_args()
    if a.recent:
        rows = recent(a.recent)
        if not rows:
            print('还没有记录（首次运行只建立基线，之后才有变化可记）')
        for r in rows:
            tag = '外部' if r['source'] == 'external' else '我方'
            print(f"  {r['at'][5:16]} [{tag}] {r['device']}：{r['from']} → {r['to']}")
        return 0
    if a.device:
        for r in for_device(a.device):
            tag = '外部' if r['source'] == 'external' else '我方'
            print(f"  {r['at'][5:16]} [{tag}] {r['from']} → {r['to']}（{r['evidence']}）")
        return 0
    check_once()
    return 0


if __name__ == '__main__':
    sys.exit(main())
