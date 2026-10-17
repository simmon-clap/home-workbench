#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
出声决策与额度（什么时候该开口）

依据：docs/spec/04-主动性与出声规范 v1.0 §3–§6
  三问：为什么现在说 / 依据是什么 / 不说会怎样（缺一不出声）
  四类出声：安全事件（不占额度·必达）· 错过就没了 · 需要你决策 · 定时简报
  额度：照做↑ 知道了小幅↑ 忽略↓ 说“别提醒”↓且生效 **不出声不涨额度**
  免打扰：静默时段（安全事件例外）· 同因合并（默认 60 分钟）
  反向刹车：该说没说 → 一键标记 → 放宽该类条件

做什么：给定一条"待注意项"，判定**该不该出声**，并记录出声/反馈以调整额度。
不做什么：不执行业务动作（那是 L3）；安全事件永远出声，额度管不着。
"""
import datetime
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
QUOTA = os.path.join(DATA, 'quota.json')
SPOKEN = os.path.join(DATA, 'spoken.jsonl')
QUIET = os.path.join(DATA, 'quiet-hours.json')
# 安全事件重复提醒的策略（规范冲突的处置）：
#   · 'merge'（默认）：安全事件**必达**（不占额度、不受静默约束），但**同一设备同一原因
#     1 小时内只出一次声**（04 §4「合并」）—— 持续存在的问题每小时会再提醒一次，不会静默消失。
#   · 'every_run'：每次判定都出声（安全优先于合并）。
# 冲突说明：04 §3 说安全事件"必达"，§4 说"同设备同原因 1 小时内只出一次声"。
# 默认取 merge（既必达又克制）；用户可一句话切到 every_run。
SAFETY_REPEAT = os.environ.get('SMART_HOME_SAFETY_REPEAT', 'merge')
TZ = datetime.timezone(datetime.timedelta(hours=8))

LEVELS = [('低', 0), ('中', 4), ('高', 8)]
FEEDBACK_DELTA = {'acted': +2, 'ack': +1, 'ignored': -1, 'muted': -3, 'silent': 0}


def _load(path, default):
    try:
        return json.load(open(path, encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return default


def load_quota():
    q = _load(QUOTA, None)
    if not q:
        q = {'score': 4, 'history': [], 'muted_kinds': [], 'relaxed_kinds': []}
    return q


def save_quota(q):
    os.makedirs(DATA, exist_ok=True)
    json.dump(q, open(QUOTA, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def level_of(score):
    name = LEVELS[0][0]
    for n, lo in LEVELS:
        if score >= lo:
            name = n
    return name


def quiet_hours():
    return _load(QUIET, {'silent_hours': [['23:00', '07:00']], 'security_exempt': True,
                         'merge_window_minutes': 60})


def in_quiet(now=None, cfg=None):
    """静默时段判定（支持跨夜，如 23:00–07:00）。"""
    cfg = cfg or quiet_hours()
    now = now or datetime.datetime.now(TZ)
    cur = now.strftime('%H:%M')
    for span in cfg.get('silent_hours') or []:
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            continue
        s, e = span
        if s <= e:
            if s <= cur < e:
                return True
        elif cur >= s or cur < e:      # 跨夜
            return True
    return False


def _spoken_recent(device, issue, window_min):
    if not os.path.exists(SPOKEN):
        return False
    cutoff = datetime.datetime.now(TZ) - datetime.timedelta(minutes=window_min)
    with open(SPOKEN, encoding='utf-8') as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get('device') != device or e.get('issue') != issue:
                continue
            try:
                if datetime.datetime.fromisoformat(e['at']) >= cutoff:
                    return True
            except (KeyError, ValueError):
                continue
    return False


def speak(item, now=None):
    """判定该不该出声。返回 (是否出声, 原因)。原因必须能回答"为什么现在说/不说"。"""
    cfg = quiet_hours()
    q = load_quota()
    lvl = item.get('level')
    kind = item.get('kind')

    # 1) 三问缺一不出声（04 §3）
    missing = [k for k in ('issue', 'detail', 'suggestion') if not item.get(k)]
    if missing:
        return False, f'缺三问要素（{",".join(missing)}），无理由不出声'

    # 2) 安全事件：不占额度、不受静默约束（宪章第七条唯一例外）
    if lvl == 'sec':
        if SAFETY_REPEAT == 'merge':
            w = cfg.get('merge_window_minutes', 60)
            if _spoken_recent(item.get('device'), item.get('issue'), w):
                # 仍然"必达"：第一次一定出声；同一件事在窗口内不重复打扰（工作台与台账里都看得到）
                return False, f'安全事件：必达，但同设备同原因 {w} 分钟内已出过声 → 本次只记账不重复打扰'
        return True, '安全事件：必达（不占额度、不受静默约束）'

    # 2.5) 用户明确说过"这类别提醒"：优先级高于额度与时段，原因也要如实说是这条
    if kind in (q.get('muted_kinds') or []):
        return False, '你让这类别提醒（已生效）'

    # 3) 静默时段
    if in_quiet(now, cfg):
        return False, '静默时段内，非安全类不出声'

    # 4) 同因合并
    if _spoken_recent(item.get('device'), item.get('issue'), cfg.get('merge_window_minutes', 60)):
        return False, f"同设备同原因 {cfg.get('merge_window_minutes', 60)} 分钟内已出过声"

    # 5) 额度：低额度时只允许"错过就没了"
    if level_of(q['score']) == '低' and kind not in ('missed', 'security_offline'):
        return False, '额度低：只允许「错过就没了」类出声'

    return True, '需要你知道，且额度与时段允许'


def mark_spoken(item, note=''):
    os.makedirs(DATA, exist_ok=True)
    rec = {'at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
           'device': item.get('device'), 'issue': item.get('issue'),
           'level': item.get('level'), 'kind': item.get('kind'), 'note': note}
    with open(SPOKEN, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    return rec


def feedback(event, kind=None, reason=None):
    """记录用户反馈并调整额度。**不出声不涨额度**（04 §4）。"""
    if event not in FEEDBACK_DELTA:
        raise ValueError(f'未知反馈：{event}')
    q = load_quota()
    delta = FEEDBACK_DELTA[event]
    q['score'] = max(0, min(10, q['score'] + delta))
    if event == 'muted' and kind and kind not in q['muted_kinds']:
        q['muted_kinds'].append(kind)
    q['history'].append({'at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
                        'event': event, 'delta': delta, 'kind': kind, 'reason': reason})
    save_quota(q)
    return {'score': q['score'], 'level': level_of(q['score']), 'delta': delta}


def mark_missed(item, note=None):
    """漏报刹车：该说没说 → 放宽该类条件（04 §4 反向刹车）。"""
    q = load_quota()
    kind = item.get('kind')
    if kind and kind not in q['relaxed_kinds']:
        q['relaxed_kinds'].append(kind)
    if kind in q.get('muted_kinds', []):
        q['muted_kinds'].remove(kind)       # 放宽：取消这类静音
    q['history'].append({'at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
                        'event': 'missed', 'delta': 0, 'kind': kind, 'reason': note or '该说没说，放宽'})
    save_quota(q)
    return {'relaxed_kinds': q['relaxed_kinds'], 'muted_kinds': q['muted_kinds']}


def budget():
    q = load_quota()
    return {'score': q['score'], 'level': level_of(q['score']),
            'muted_kinds': q.get('muted_kinds') or [],
            'relaxed_kinds': q.get('relaxed_kinds') or [],
            'history_tail': (q.get('history') or [])[-5:]}


def run(items, now=None):
    """批量判定：返回 [(item, 是否出声, 原因)]。已出声的自动记账（供合并窗口）。"""
    out = []
    for it in items:
        ok, why = speak(it, now)
        out.append((it, ok, why))
        if ok:
            mark_spoken(it, why)
    return out


if __name__ == '__main__':
    st = _load(os.path.join(DATA, 'state.json'), {})
    print('当前额度：', json.dumps(budget(), ensure_ascii=False))
    for it, ok, why in run(st.get('attention') or []):
        print(f"  {'🔔' if ok else '—'} {it['room']} · {it['device']} —— {why}")
