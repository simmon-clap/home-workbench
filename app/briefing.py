#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
定时简报（早 / 晚各一份）

依据：docs/spec/04-主动性与出声规范 v1.0 §3（定时简报：每天最多 2 次、固定时段）
      宪章第九条边界（没新料就说没有，不许编）· 11-代码规范 v1.0

内容口径（只讲真实数据）：
  1) 一句话状态（来自 L2 状态模型）
  2) 需要你注意的（安全优先，最多 3 条）
  3) 它昨天/今天做了什么（来自动作记录与审计，只报事实）
  4) 出声额度与静默状态（透明）
没有的部分**如实写"没有"**，不补空话。

用法：
  python3 app/briefing.py            # 打印当前时段的简报
  python3 app/briefing.py morning    # 指定时段
"""
import argparse
import datetime
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
TZ = datetime.timezone(datetime.timedelta(hours=8))


def _load(path, default):
    try:
        return json.load(open(path, encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return default


def today_actions(date=None):
    """统计今天的动作（来自 actions.json，只报事实）。"""
    doc = _load(os.path.join(DATA, 'actions.json'), {'actions': []})
    date = date or datetime.datetime.now(TZ).strftime('%Y-%m-%d')
    acts = [a for a in doc.get('actions', []) if (a.get('at') or '').startswith(date)]
    ok_steps = sum(1 for a in acts for r in a.get('results', []) if r.get('ok'))
    failed = sum(1 for a in acts for r in a.get('results', []) if not r.get('ok'))
    blocked = sum(len(a.get('blocked') or []) for a in acts)
    return {'count': len(acts), 'ok_steps': ok_steps, 'failed': failed, 'blocked': blocked}


def compose(kind=None, now=None):
    now = now or datetime.datetime.now(TZ)
    # 时段：04:00–14:00 算早间，其余算晚间（覆盖 04 §3 的"固定时段"语义）
    kind = kind or ('morning' if 4 <= now.hour < 14 else 'evening')
    st = _load(os.path.join(DATA, 'state.json'), {})
    s = st.get('summary') or {}
    att = st.get('attention') or []
    acts = today_actions(now.strftime('%Y-%m-%d'))
    quiet = _load(os.path.join(DATA, 'quiet-hours.json'), {})
    quota = _load(os.path.join(DATA, 'quota.json'), {'score': 4})

    h = now.hour
    head = '夜里好' if h < 5 else ('早上好' if h < 12 else ('下午好' if h < 18 else '晚上好'))
    lines = [f'{head} · {now.strftime("%m-%d %H:%M")}',
             f"家里：{s.get('headline', '状态数据尚未生成')}"
             f"（{s.get('total', 0)} 台设备 · 在线 {s.get('online', 0)} · 离线 {s.get('offline', 0)}）"]

    # **数据新鲜度**：偏旧就必须说（宪章第三条：不许拿旧读数冒充现在）。
    # 现实场景：迁移/HA 故障期间状态刷新会失败，简报仍会照常发 —— 不说就是误导
    try:
        _ga = st.get('generated_at')
        if _ga:
            _age = (now - datetime.datetime.fromisoformat(_ga)).total_seconds() / 60
            if _age >= 10:
                lines.append(f"⚠️ **这份状态是 {int(_age)} 分钟前的**（中枢可能连不上）："
                             f"下面说的是最后一次可用读数，不是现在。")
    except (TypeError, ValueError):
        pass

    if att:
        lines.append('需要你注意：')
        for a in att[:3]:
            lines.append(f"  · [{a['level']}] {a['room']} · {a['device']} —— {a['issue']}（{a['detail']}）")
        if len(att) > 3:
            lines.append(f"  · 另有 {len(att) - 3} 项，可在家庭工作台查看")
    else:
        lines.append('需要你注意的：没有')

    if acts['count']:
        lines.append(f"它今天做了：{acts['count']} 次操作 · 成功 {acts['ok_steps']} 步"
                     + (f" · 失败 {acts['failed']} 步" if acts['failed'] else '')
                     + (f" · 按规范拦截 {acts['blocked']} 步" if acts['blocked'] else ''))
    else:
        lines.append('它今天做了：没有')

    score = quota.get('score', 4)
    lvl = '低' if score < 4 else ('中' if score < 8 else '高')
    spans = quiet.get('silent_hours') or []
    span_txt = '、'.join(f'{a}–{b}' for a, b in spans) if spans else '未设置'
    lines.append(f'出声额度：{lvl}（{score}/10）· 静默时段：{span_txt}（安全事件例外）')

    # 磁盘余量：**只在偏低时出现**（正常时不打扰）
    try:
        import importlib.util as _iu
        _sp = _iu.spec_from_file_location('mt', os.path.join(ROOT, 'tools', 'maintain.py'))
        _mt = _iu.module_from_spec(_sp); _sp.loader.exec_module(_mt)
        _d = _mt.check_disk()
        if _d['level'] != 'ok':
            lines.append(_d['message'])
    except Exception:  # noqa
        pass

    # 判据 1（头号验收）：今天开没开米家 —— 只有用户知道，所以每天提示一次
    try:
        import sys as _sys2
        _sys2.path.insert(0, os.path.join(ROOT, 'tools'))
        import criterion1 as _c1
        _e = _c1.get_day()
        _st = {'pass': '达标（没开米家）', 'fail': '未达标', None: '还没记录'}.get(_e and _e['status'])
        _line1 = (f"判据 1：{_st}"
                  + (f"（{_e['reason']}）" if _e and _e.get('reason') else '')
                  + f" · 连续达标 {_c1.streak()} 天")
        # 还没记录时，**给一句能直接照做的话**（否则"每天都提示"就只是噪音）
        if not (_e and _e.get('status')):
            _line1 += '　→ 今天没开米家的话，回我一句「没开米家」我就记上；开了就说一声原因'
        lines.append(_line1)
    except Exception:  # noqa
        pass

    # 需要用户决定的事：有未决项就必须出现在简报里（用户 2026-10-17 要求"要决定就发消息"）
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
        import decisions as _dec
        _line = _dec.line()
        if _line:
            lines.append(_line)
    except Exception:  # noqa
        pass

    # 判据 1 的日常检查：还需米家的设备有几台、有没有清单外的新依赖
    gap = _load(os.path.join(DATA, 'mijia-dependency.json'), {})
    gc = gap.get('counts') or {}
    if gc:
        # 这里必须是**真实计数**：之前写成"清单外新增 0 项"是写死的（2026-10-17 自查发现）
        extra = gap.get('recorded_count')
        if extra is None:
            extra = len(gap.get('recorded_gaps') or [])
        lines.append(f"米家依赖：仍需米家 {gc.get('need_mijia', 0)} 台（安全域，设计如此）· "
                     f"不用米家 {gc.get('ok', 0)} 台 · 你补录的清单外依赖 {extra} 条")
        for x in (gap.get('recorded_gaps') or [])[-2:]:
            lines.append(f"  · 你记的：{x.get('reason')}")
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('kind', nargs='?', choices=['morning', 'evening'])
    a = ap.parse_args()
    print(compose(a.kind))


if __name__ == '__main__':
    main()
