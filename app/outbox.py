#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投递链（"决定要说" → "真的送到你眼前"）

为什么要有：`notify.py` 只负责判定该不该出声，**但没有任何东西把消息送出去** ——
决策逻辑写了、测了，投递却没接（2026-10-17 自查发现的同类缺口：接口/逻辑在、链路不通）。
本模块补上这一段，并让通道可插拔（微信小号通道未接通，先用本地通道跑通）。

通道（按顺序尝试，任何一个成功即可）：
  1. `outbox`  写进 data/outbox/<日期>.jsonl（**始终可用**；工作台"最近说过什么"读它）
  2. `desktop` macOS 通知中心（osascript；屏幕上会出现，所以**必须脱敏**）
  3. `wechat`  微信小号通道 —— 未接通，如实返回 not_connected（不做假通道）

隐私硬规则（08 §3 / 宪章第七条）：
  **旁观者能看到的通道（桌面通知、微信）不得出现安全域细节**（门锁、摄像头、在家/离家）。
  安全类消息在这些通道上一律说成"有 N 件安全的事想让你看一眼，详情在工作台"，
  完整内容只留在工作台（局域网/tailnet 内可达）。
"""
import datetime
import json
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
OUTBOX = os.environ.get('SMART_HOME_OUTBOX') or os.path.join(DATA, 'outbox')
TZ = datetime.timezone(datetime.timedelta(hours=8))

# 旁观者可见的通道：必须脱敏
PUBLIC_CHANNELS = ('desktop', 'wechat')
# 安全域相关词汇（出现即视为敏感）
SECRET_KINDS = ('security', 'offline_sec', 'sec', 'lock', 'camera', 'presence', 'away', 'home')


def _masked(text, item):
    """对旁观者可见通道脱敏：安全的只说"有安全的事"，不点设备名。"""
    if item.get('level') == 'sec' or item.get('kind') in SECRET_KINDS:
        # 不报数字：之前写死"1 件"，实测有 3 件时就是错的（宁可少说，不许说错）
        return '有安全的事想让你看一眼（详情在工作台里看，这里不显示）'
    return text


def compose(items):
    """把"该说的项"合成一条消息（多条合并成一条，规范 03 §4：不刷屏）。"""
    items = list(items)
    if not items:
        return ''
    sec = [i for i in items if i.get('level') == 'sec']
    normal = [i for i in items if i.get('level') != 'sec']
    shown = normal[:4]
    parts = [f"{i.get('room', '')}·{i.get('device', '')}：{i.get('issue', '')}" for i in shown]
    if sec:
        parts.append(f"另有 {len(sec)} 件安全的事" if normal else f"有 {len(sec)} 件安全的事想让你看一眼")
    # 只统计**没写进这条消息**的普通项（之前把安全项也重复计入了，实测出现"有3件…还有2项"）
    more = len(normal) - len(shown)
    if more > 0:
        parts.append(f"还有 {more} 项，工作台里看")
    return '；'.join(parts)


DEDUPE_WINDOW_S = int(os.environ.get('SMART_HOME_DELIVER_DEDUPE_S', '3600'))


def _same_text_recent(text, window_s=None):
    """同一段文字最近是否已经投递过（精确到内容，不会误伤不同内容）。

    这是**第二道网**：上游（notify 的合并窗口）负责"该不该说"，这里保证"说过的原话不重复说"。
    2026-10-17 实测发现：安全类事件每 30 分钟重复播报同一条摘要。
    """
    window_s = DEDUPE_WINDOW_S if window_s is None else window_s
    if window_s <= 0:
        return False
    path = os.path.join(OUTBOX, datetime.datetime.now(TZ).strftime('%Y-%m-%d') + '.jsonl')
    if not os.path.exists(path):
        return False
    cutoff = (datetime.datetime.now(TZ) - datetime.timedelta(seconds=window_s)).isoformat(timespec='seconds')
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get('text') == text and str(rec.get('at') or '') >= cutoff:
                    return True
    except OSError:
        return False
    return False


def deliver(text, kind='info', level='info', dedupe_key=None, channels=('outbox', 'desktop'),
            dry=False, now=None, force=False):
    """把一条消息送出去。返回投递结果（每个通道的真实结果，不粉饰）。

    force=True 时跳过去重网（用于"内容变了"或确实需要再打扰一次的情况）。
    """
    now = now or datetime.datetime.now(TZ)
    if not dry and not force and _same_text_recent(text):
        # 说过的原话不重复说：仍然记一笔"这次被合并"，但不打扰（04 §4）
        path = os.path.join(OUTBOX, now.strftime('%Y-%m-%d') + '.jsonl')
        os.makedirs(OUTBOX, exist_ok=True)
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'at': now.isoformat(timespec='seconds'), 'kind': kind, 'level': level,
                                'text': text, 'dedupe_key': dedupe_key, 'merged': True,
                                'note': f'{DEDUPE_WINDOW_S} 秒内已投过同样内容，本次不重复打扰'},
                               ensure_ascii=False) + '\n')
        return {'ok': False, 'merged': True, 'text': text, 'results': [],
                'error': f'同样内容 {DEDUPE_WINDOW_S // 60} 分钟内已投过，本次不重复打扰（已记账）'}
    item = {'kind': kind, 'level': level, 'text': text}
    results = []
    if not text.strip():
        return {'ok': False, 'error': '空消息不投递', 'results': []}

    for ch in channels:
        if ch == 'outbox':
            path = os.path.join(OUTBOX, now.strftime('%Y-%m-%d') + '.jsonl')
            if dry:
                results.append({'channel': 'outbox', 'ok': True, 'dry': True, 'path': path})
                continue
            os.makedirs(OUTBOX, exist_ok=True)
            rec = {'at': now.isoformat(timespec='seconds'), 'kind': kind, 'level': level,
                   'text': text, 'dedupe_key': dedupe_key}
            with open(path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            results.append({'channel': 'outbox', 'ok': True, 'path': path})
        elif ch == 'desktop':
            shown = _masked(text, item)
            if dry:
                results.append({'channel': 'desktop', 'ok': True, 'dry': True, 'text': shown})
                continue
            try:
                script = (f'display notification {json.dumps(shown, ensure_ascii=False)} '
                          f'with title "家庭工作台"')
                r = subprocess.run(['/usr/bin/osascript', '-e', script],
                                   capture_output=True, text=True, timeout=10)
                # **诚实边界**：命令执行成功 ≠ 人真的看到了。系统不允许读通知中心数据库，
                # 所以这里只说"已发出"，并把实际展示取决于系统通知/专注模式这件事写进回执。
                results.append({'channel': 'desktop', 'ok': r.returncode == 0,
                                'dispatched': r.returncode == 0,
                                'note': '已发出；是否展示取决于系统通知设置与专注模式（无法机械核验）',
                                'text': shown, 'err': (r.stderr or '').strip()[:120] or None})
            except Exception as e:  # noqa
                results.append({'channel': 'desktop', 'ok': False, 'err': str(e)[:120]})
        elif ch == 'wechat':
            # 小号通道尚未接通 —— 如实报告，不做假投递
            results.append({'channel': 'wechat', 'ok': False, 'not_connected': True,
                            'err': '微信小号通道未接通（需要一个小号与登录态，属用户侧准备）'})
        else:
            results.append({'channel': ch, 'ok': False, 'err': '不认识的通道'})

    ok = any(r.get('ok') for r in results)
    if not dry and ok:
        import sys
        sys.path.insert(0, os.path.join(ROOT, 'app'))
        try:
            import audit
            audit.log(action='notify', target=dedupe_key or kind, channel='投递',
                      authorization='主动性（04）', result='ok',
                      detail=f"通道 {'+'.join(r['channel'] for r in results if r.get('ok'))}：{text[:60]}")
        except Exception:  # noqa
            pass
    return {'ok': ok, 'results': results, 'text': text}


def speak_and_deliver(items, now=None, channels=('outbox', 'desktop'), dry=False):
    """完整链路：notify 判定 → 合成一条 → 投递 → 记账。返回每一步的真实结果。"""
    import sys
    sys.path.insert(0, os.path.join(ROOT, 'app'))
    import notify as N
    decisions = N.run(items, now)                     # 该说的已自动记账（合并窗口）
    to_say = [it for it, ok, why in decisions if ok]
    text = compose(to_say)
    sent = {'ok': True, 'skipped': True, 'results': [], 'text': '',
            'reason': '本次没有需要出声的事项（被合并/静默/额度拦下）'}
    if text:
        sent = deliver(text, kind='digest', level='sec' if any(i.get('level') == 'sec' for i in to_say) else 'info',
                       dedupe_key='digest', channels=channels, dry=dry, now=now)
    return {'spoken': to_say, 'silent': [it for it, ok, why in decisions if not ok],
            'reasons': {f"{it.get('device')}|{it.get('issue')}": why for it, ok, why in decisions},
            'message': text, 'delivery': sent}


def recent(limit=20):
    """最近说过什么（工作台展示用）。"""
    if not os.path.isdir(OUTBOX):
        return []
    rows = []
    import re as _re
    for f in sorted(os.listdir(OUTBOX), reverse=True)[:5]:
        # 只认日期命名的分片；目录里可能有其它 jsonl（实测把审计文件混进来过）
        if not _re.fullmatch(r'\d{4}-\d{2}-\d{2}\.jsonl', f):
            continue
        for line in open(os.path.join(OUTBOX, f), encoding='utf-8'):
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows[-limit:][::-1]


def summary():
    rows = recent(200)
    return {'total': len(rows), 'last_at': rows[0]['at'] if rows else None}


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--channels', default='outbox')
    a = ap.parse_args()
    st = json.load(open(os.path.join(DATA, 'state.json'), encoding='utf-8'))
    out = speak_and_deliver(st.get('attention') or [], channels=tuple(a.channels.split(',')), dry=a.dry)
    print('决定要说：', len(out['spoken']), '项；不说：', len(out['silent']), '项')
    print('消息：', out['message'])
    print('投递：', json.dumps(out['delivery']['results'], ensure_ascii=False))
