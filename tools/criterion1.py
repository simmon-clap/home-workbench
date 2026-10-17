#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
判据 1 追踪器：「一整天没打开米家 App」

为什么要有：这是整个项目的**头号验收判据**，但"今天没开米家"只有你知道。
所以本工具做三件事：
  ① 每天自动汇集"今天出现过、且**只有米家能解决**"的场景（安全域待办、需手动处置的设备、你补录的依赖）
  ② 让你**一句话记录**今天的结果（`--record pass` / `--record fail --reason "..."`），或什么都不说 → 今天记为"未记录"
  ③ 算连续达标天数

诚实规则（写在代码里，也由门禁守着）：
  · **没有你的记录，绝不自动宣布达标**（`unknown` 就是 unknown）
  · "今天必须开米家"的证据只认：安全域待办、离线需手动处置、你的补录 —— 不靠猜
  · 记录里保留原因与时间，便于回溯（宪章判据 3：任何结论都能点回证据）

用法：
  python3 tools/criterion1.py --today            # 今天怎么样（含自动汇集的可疑场景）
  python3 tools/criterion1.py --record pass      # 记：今天没开米家
  python3 tools/criterion1.py --record fail --reason "扫地机卡住，米家里点了继续"
  python3 tools/criterion1.py --streak           # 连续达标天数
"""
import argparse
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
FILE = os.environ.get('SMART_HOME_CRITERION1') or os.path.join(DATA, 'criterion1.json')
TZ = datetime.timezone(datetime.timedelta(hours=8))


def _load(path, default):
    try:
        return json.load(open(path, encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return default


def doc():
    d = _load(FILE, None)
    if not d:
        d = {'version': 1, 'started_at': datetime.datetime.now(TZ).isoformat(timespec='seconds'), 'days': []}
    d.setdefault('days', [])
    return d


def save(d):
    json.dump(d, open(FILE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def today_str(now=None):
    return (now or datetime.datetime.now(TZ)).strftime('%Y-%m-%d')


def record(status, reason='', by='user', now=None):
    if status not in ('pass', 'fail'):
        return False, '只能记 pass 或 fail'
    if status == 'fail' and not (reason or '').strip():
        return False, '记"没达标"必须写一句为什么（否则回溯不了）'
    d = doc()
    day = today_str(now)
    entry = {'date': day, 'status': status, 'reason': (reason or '').strip(),
             'by': by, 'at': (now or datetime.datetime.now(TZ)).isoformat(timespec='seconds')}
    d['days'] = [x for x in d['days'] if x.get('date') != day] + [entry]
    d['days'].sort(key=lambda x: x['date'])
    save(d)
    return True, f"{day} 记为 {'达标（没开米家）' if status == 'pass' else '未达标：' + entry['reason']}"


def get_day(day=None):
    day = day or today_str()
    return next((x for x in doc()['days'] if x.get('date') == day), None)


def streak(now=None):
    """连续达标天数（从今天往回数；今天未记录则从昨天开始数）。"""
    days = {x['date']: x for x in doc()['days']}
    today = now or datetime.datetime.now(TZ)
    n = 0
    cur = today
    if days.get(today.strftime('%Y-%m-%d'), {}).get('status') != 'pass':
        cur = today - datetime.timedelta(days=1)          # 今天还没记，就从昨天往回数
    while days.get(cur.strftime('%Y-%m-%d'), {}).get('status') == 'pass':
        n += 1
        cur -= datetime.timedelta(days=1)
    return n


def suspicious_events(now=None):
    """今天出现过、且**只有米家能解决**的场景（不猜，逐条给证据来源）。"""
    now = now or datetime.datetime.now(TZ)
    day = today_str(now)
    out = []

    # ① 安全域待办（我们必须只提醒、他得在米家里手动做）
    st = _load(os.path.join(DATA, 'state.json'), {'attention': []})
    for a in st.get('attention') or []:
        if a.get('level') == 'sec' or a.get('kind') == 'security':
            out.append({'what': f"{a.get('room', '')}·{a.get('device', '')}：{a.get('issue', '')}",
                        'evidence': 'state.json 的待注意（安全域）',
                        'note': '安全域只提醒：这条**必须你手动处置**，但不是必须开米家（工作台里能看到）'})

    # ② 依赖清单里"仍需米家"的设备数
    gap = _load(os.path.join(DATA, 'mijia-dependency.json'), {})
    need = (gap.get('counts') or {}).get('need_mijia')
    if need:
        out.append({'what': f'仍有 {need} 台设备只能通过米家控制（安全域，设计如此）',
                    'evidence': 'data/mijia-dependency.json',
                    'note': '设计使然：安全域不代执行；需要你手动时才算一次"开米家"'})

    # ③ 你自己补录的清单外依赖
    s = _load(os.path.join(DATA, 'settings.json'), {})
    for x in s.get('extra_deps') or []:
        if (x.get('at') or '').startswith(day):
            out.append({'what': x.get('reason'), 'evidence': '功能设置·米家依赖补录', 'note': '你亲自记的，算硬证据'})

    # ④ 扫地机这类"地图/耗材"要翻米家的场景（能力表里的未接通项）
    cap = _load(os.path.join(DATA, 'capabilities.json'), {})
    for item in cap.get('not_connected') or []:
        out.append({'what': item, 'evidence': '能力表（未接通）',
                    'note': '未接通的能力若要办，得回米家'})
    return out


def report(now=None):
    now = now or datetime.datetime.now(TZ)
    day = today_str(now)
    e = get_day(day)
    st = e['status'] if e else 'unknown'
    label = {'pass': '达标（今天没开米家）', 'fail': '未达标', 'unknown': '今天还没记录'}[st]
    lines = [f"判据 1 · {day}：{label}"]
    if e and e.get('reason'):
        lines.append(f"  原因：{e['reason']}")
    n = streak(now)
    lines.append(f"  连续达标：{n} 天" + (f"（从 {doc().get('started_at', '')[:10]} 起记）" if n else ''))
    ev = suspicious_events(now)
    if ev:
        lines.append(f"  今天值得留意的 {len(ev)} 条：")
        for x in ev[:5]:
            lines.append(f"    · {x['what']}")
            lines.append(f"      （来源：{x['evidence']}；{x['note']}）")
    else:
        lines.append('  今天没有出现"只有米家能解决"的场景')
    if st == 'unknown':
        lines.append('  要记的话：python3 tools/criterion1.py --record pass|fail [--reason "..."]')
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--today', action='store_true')
    ap.add_argument('--record', choices=['pass', 'fail'])
    ap.add_argument('--reason', default='')
    ap.add_argument('--streak', action='store_true')
    a = ap.parse_args()
    if a.record:
        ok, msg = record(a.record, a.reason)
        print(('✅ ' if ok else '❌ ') + msg)
        return 0 if ok else 1
    if a.streak:
        print(f"连续达标 {streak()} 天")
        return 0
    print(report())
    return 0


if __name__ == '__main__':
    sys.exit(main())
