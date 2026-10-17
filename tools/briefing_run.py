#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定时简报运行器（早 / 晚各一次，落盘留档）

依据：docs/spec/04-主动性与出声规范 v1.0 §3（定时简报：每天最多 2 次、固定时段、没新料说没有）
      09 §2（运维要留痕）· 11-代码规范 v1.1

做什么：生成当前时段的简报 → 写入 `data/briefings/YYYY-MM-DD-<slot>.md` → 追加一行运行日志
        → 更新 `data/briefings/status.json`（供门禁/界面查询"最近一次有没有真的跑"）。
        同一天同一时段**只生成一次**（重复触发不覆盖、不重复投递）——将来接通微信小号后，
        这层幂等就是"不重复打扰"的保证。
不做什么：不发送到任何通道（微信小号通道属最后一项，接通后在这里加一行投递即可）。

用法：
  python3 tools/briefing_run.py                 # 按时段自动判断（04:00–14:00 早间，其余晚间）
  python3 tools/briefing_run.py --slot morning  # 指定时段
  python3 tools/briefing_run.py --force         # 忽略"今天已生成"
"""
import argparse
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
import briefing  # noqa: E402

OUT = os.path.join(ROOT, 'data', 'briefings')
LOG = os.path.join(ROOT, 'logs', 'briefing.log')
TZ = datetime.timezone(datetime.timedelta(hours=8))


def slot_of(now):
    return 'morning' if 4 <= now.hour < 14 else 'evening'


def run(slot=None, force=False, outdir=None, now=None):
    now = now or datetime.datetime.now(TZ)
    slot = slot or slot_of(now)
    outdir = outdir or OUT
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f'{now.strftime("%Y-%m-%d")}-{slot}.md')

    if os.path.exists(path) and not force:
        return {'ok': True, 'skipped': True, 'path': path, 'reason': f'{slot} 简报今天已生成（幂等，不重复）'}

    text = briefing.compose(slot, now=now)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text.rstrip() + '\n')

    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f'{now.isoformat(timespec="seconds")}\t{slot}\t{path}\t{len(text)} 字\n')

    status_path = os.path.join(outdir, 'status.json')
    status = {}
    if os.path.exists(status_path):
        try:
            status = json.load(open(status_path, encoding='utf-8'))
        except ValueError:
            status = {}
    status[slot] = {'at': now.isoformat(timespec='seconds'), 'path': os.path.relpath(path, ROOT),
                    'chars': len(text), 'head': text.splitlines()[1] if len(text.splitlines()) > 1 else ''}
    json.dump(status, open(status_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return {'ok': True, 'skipped': False, 'path': path, 'chars': len(text)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--slot', choices=['morning', 'evening'])
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    out = run(a.slot, a.force)
    if out.get('skipped'):
        print(f'⏭️  {out["reason"]}')
    else:
        print(f'✅ 已生成 {os.path.relpath(out["path"], ROOT)}（{out["chars"]} 字）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
