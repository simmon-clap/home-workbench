#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
待决事项台账（"需要我决定的事"只有一个地方）

为什么要有：用户 2026-10-17 明确要求「后续需要我做决定的就发给我消息」。
散落在长回复里的决策会丢；所以集中成台账，并：
  · 每日简报带一行「等你决定 N 项」
  · 门禁检查：台账里有未决项时，简报必须出现这一行（防"问了但没提醒"）
  · 每天定时检查，挂起超过 24 小时的会主动提醒一次（不重复轰炸）

用法：
  python3 tools/decisions.py            # 打印未决项（一行概括 + 明细）
  python3 tools/decisions.py --render   # 同时刷新 data/pending-decisions.md
"""
import argparse
import datetime
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
FILE = os.path.join(DATA, 'decisions.json')
MD = os.path.join(DATA, 'pending-decisions.md')
TZ = datetime.timezone(datetime.timedelta(hours=8))
REMIND_AFTER_H = 24


def load():
    try:
        return json.load(open(FILE, encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return []


def save(items):
    json.dump(items, open(FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def parse_at(s):
    try:
        return datetime.datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def age_hours(item, now=None):
    now = now or datetime.datetime.now(TZ)
    t = parse_at(item.get('opened_at'))
    return round((now - t).total_seconds() / 3600, 1) if t else None


def open_items():
    return [x for x in load() if x.get('status') == 'open']


def resolve(did, answer):
    items = load()
    for x in items:
        if x.get('id') == did:
            x['status'] = 'decided'
            x['answer'] = answer
            x['decided_at'] = datetime.datetime.now(TZ).isoformat(timespec='seconds')
            save(items)
            return True, f'{did} 已记录你的决定：{answer}'
    return False, f'没有这个待决项：{did}'


def line(limit=1):
    """给简报用的一行概括。"""
    items = open_items()
    if not items:
        return None
    first = items[0]
    extra = f"（另有 {len(items) - 1} 项）" if len(items) > 1 else ''
    return f"等你决定：{len(items)} 项 —— {first['question']}{extra}"


def render():
    items = load()
    opens = [x for x in items if x.get('status') == 'open']
    out = ['# 待决事项（需要你决定的事）', '',
           '> 这是唯一事实源：我每次汇报都会带一行，每天也会定时检查；挂起超 24 小时会主动提醒一次。', '',
           f'未决：**{len(opens)} 项** · 已决：{len([x for x in items if x.get("status") == "decided"])} 项', '']
    for x in opens:
        out += [f"## {x['id']} · {x['question']}", '',
                f"- **为什么需要你定**：{x.get('why', '—')}",
                f"- **我需要的**：{x.get('need', '—')}",
                f"- **选项**：" + ' ；'.join(x.get('options') or []),
                f"- **你不决定我会怎么做**：{x.get('if_not', '—')}",
                f"- **挂起**：{age_hours(x)} 小时", '']
    done = [x for x in items if x.get('status') == 'decided']
    if done:
        out += ['## 已决定', '', '| 编号 | 事项 | 你的决定 | 时间 |', '|---|---|---|---|']
        out += [f"| {x['id']} | {x['question']} | {x.get('answer', '')} | {x.get('decided_at', '')[:16]} |" for x in done]
        out += ['']
    open(MD, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    return MD


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--render', action='store_true')
    ap.add_argument('--resolve', nargs=2, metavar=('ID', 'ANSWER'))
    ap.add_argument('--stale', type=float, default=REMIND_AFTER_H, help='挂起多少小时算该提醒')
    a = ap.parse_args()
    if a.resolve:
        ok, msg = resolve(a.resolve[0], a.resolve[1])
        print(msg)
        render()
        return 0 if ok else 1
    items = open_items()
    if not items:
        print('没有待决事项')
    else:
        stale = [x for x in items if (age_hours(x) or 0) >= a.stale]
        print(f'待决 {len(items)} 项' + (f'（其中挂起 ≥{a.stale}h：{len(stale)} 项）' if stale else ''))
        for x in items:
            print(f"  {x['id']} [{age_hours(x)}h] {x['question']} —— 需要：{x.get('need', '')}")
    if a.render:
        print('已刷新', os.path.relpath(render(), ROOT))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
