#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
离线阈值校准（决策 A 的后半段）

背景：用户 2026-10-16 拍板「硬证据优先」——离线只认 HA 的 unavailable；阈值判定**暂缓启用**，
      前提是先用**真实上报节奏**校准（06 v1.2 §3：连续观测 ≥24 小时 → 阈值取节奏 × N，N≥3）。

做什么：从 recorder 只读副本里，按设备统计"相邻两条记录的时间间隔"，算出每台设备的真实节奏，
        据此给出**建议阈值**与"还差多少观测时间"。数据不足就如实说不足，不硬凑。

用法：python3 tools/calibrate_offline.py
产出：data/offline-calibration.json + logs/evidence/<日期>-calib/calibration.md
"""
import datetime
import json
import os
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, 'data', 'state.json')
OUT = os.path.join(ROOT, 'data', 'offline-calibration.json')
TZ = datetime.timezone(datetime.timedelta(hours=8))
DOCKER = os.path.expanduser('~/.homebrew/bin/docker')
MIN_SAMPLES = 6
# **时间跨度**门槛：样本数够 ≠ 可信。2026-10-17 实测踩坑：一天内多次重启 HA 会给所有实体
# 各写一行状态 → 每台设备都"有样本"，于是在只观测 3.4 小时的情况下声称"64/64 可校准"。
# 所以必须同时要求该设备自己的观测跨度 ≥ 1 小时。
MIN_SPAN_S = 3600                      # 少于这么多间隔就不下结论
N_FACTOR = 3                         # 06 v1.2：阈值 = 节奏 × N（N≥3）

# 数据来源：'auto'（历史 API 优先、容器库兜底）· 'api' · 'container'
# 为什么要有 API 路径：迁到 HA OS 后 recorder 库在虚拟机里，docker cp 拿不到 → 只能走官方历史 API。
CALIB_SOURCE = os.environ.get('SMART_HOME_CALIB_SOURCE', 'auto')
HISTORY_HOURS = float(os.environ.get('SMART_HOME_CALIB_HOURS', '24'))
PRIMARY_DOMAINS = ('sensor.', 'binary_sensor.', 'switch.', 'light.', 'climate.', 'fan.',
                   'media_player.', 'cover.')
MAX_ENTITIES_PER_DEVICE = int(os.environ.get('SMART_HOME_CALIB_MAX_ENTS', '5'))


def fetch_db():
    """把 HA 容器里的 recorder 库拷到临时目录（只读副本，不动原库）。"""
    tmp = tempfile.mkdtemp(prefix='calib-')
    db = os.path.join(tmp, 'ha.db')
    # 数据源不可用时**如实退出**：迁到 HA OS 后 recorder 库在虚拟机里，docker cp 会失败。
    # 宁可说"这次观测不了"，也不许产出一份"看起来正常"的空校准（宪章第三条：不许假成功）。
    probe = subprocess.run(['docker', 'exec', 'homeassistant', 'test', '-f',
                            '/config/home-assistant_v2.db'], capture_output=True, text=True)
    if probe.returncode != 0:
        print('⚠️ 拿不到 recorder 库（HA 不在容器里？迁移后需改用 REST 历史 API）')
        print('   本次不做校准，保持上一次结果不变 —— 不产出假数据。')
        return 2
    for src, dst in (('homeassistant:/config/home-assistant_v2.db', db),
                     ('homeassistant:/config/home-assistant_v2.db-wal', db + '-wal')):
        r = subprocess.run([DOCKER, 'cp', src, dst], capture_output=True, text=True)
        if r.returncode != 0 and dst.endswith('-wal'):
            continue                                     # wal 可能不存在，忽略
    return tmp, db


def primary_entities(dev, limit=3):
    """挑这台设备"最可能定期上报"的几个实体。

    为什么不止一个：2026-10-17 实测 —— 只查一个实体时，很多是"很少变化的状态字段"
    （如某传感器的故障位），整段窗口只有 1 条记录，根本算不出节奏。所以按域优先取前 N 个。
    """
    ents = list(dev.get('entities') or [])
    if dev.get('entity_id'):
        ents.insert(0, dev['entity_id'])
    out = []
    for dom in PRIMARY_DOMAINS:
        for e in ents:
            if e.startswith(dom) and e not in out:
                out.append(e)
                if len(out) >= limit:
                    return out
    return out


def fetch_rows_api(state, hours=None):
    """走官方历史 API 取"状态变化时间戳"。返回 (rows, 拿到的实体数)。

    与容器库路径同义：recorder 只记状态变化，两边算出的节奏可比。
    """
    import urllib.request
    import urllib.parse
    sys.path.insert(0, os.path.join(ROOT, 'app'))
    import ha
    hours = HISTORY_HOURS if hours is None else hours
    token = ha.load_token()
    rows, got = [], 0
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    def epoch(iso_s):
        try:
            return datetime.datetime.fromisoformat(str(iso_s).replace('Z', '+00:00')).timestamp()
        except (TypeError, ValueError):
            return None

    def history_of(eid):
        """取一段时间的历史。

        **两个实测坑（2026-10-17）**：
          ① 时间戳必须带时区：不带后缀时 HA 按本地时间解析，窗口会整体偏移 8 小时
          ② **单次查询上限 24 小时**：超过就返回空数组（不报错！）——所以按 24 小时分段拉再合并
        """
        out = []
        for start_iso, end_iso in history_spans(hours, now=now_utc):
            url = history_url(ha.BASE, eid, start_iso, end_iso)
            req = urllib.request.Request(url)
            req.add_header('Authorization', 'Bearer ' + token)
            with urllib.request.urlopen(req, timeout=40) as resp:
                hist = json.load(resp)
            out.extend((hist[0] if hist else []) or [])
        return out

    for dev in state.get('devices') or []:
        eids = primary_entities(dev, limit=MAX_ENTITIES_PER_DEVICE)
        if not eids:
            continue
        got += 1
        for eid in eids:
            try:
                seq = history_of(eid)
            except Exception:  # noqa
                continue                      # 单个实体查不到不影响其它（如实少算，不编）
            for h in seq:
                ts = epoch(h.get('lu') or h.get('last_updated'))
                if ts:
                    rows.append((eid, ts))
    return rows, got


def history_url(base, eid, start, end):
    """构造历史查询 URL。

    两个必须记住的点（2026-10-17 实测踩过，都是**静默失效**）：
      ① 时间戳要带时区，且 **URL 转义** —— `+00:00` 里的 `+` 在 URL 里是空格
      ② 单次查询**上限 24 小时**，超过返回空数组且不报错 → 由 history_spans() 分段
    """
    import urllib.parse
    return (f'{base}/api/history/period/{urllib.parse.quote(start, safe="")}?'
            f'filter_entity_id={urllib.parse.quote(eid)}&minimal_response'
            f'&end_time={urllib.parse.quote(end, safe="")}')


def history_spans(hours, now=None, chunk=24.0):
    """把观测窗口切成 ≤24 小时的段（新的在前），返回 [(start_iso, end_iso), ...]。

    为什么必须分段：HA 单次历史查询超过 24 小时会返回**空数组而不报错** ——
    如果我们只发一次 24h+ 的请求，会安静地"什么都没测到"。
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    out, end, left = [], now, float(hours)
    while left > 0:
        span = min(chunk, left)
        start = end - datetime.timedelta(hours=span)
        out.append((start.isoformat(), end.isoformat()))
        end, left = start, left - span
    return out


def events_of(stamps, merge_s=5):
    """把时间戳聚成"更新事件"。一台设备多个实体同一秒一起更新 → 不聚会出现全是 0 秒间隔（实测）。"""
    events = []
    for t in sorted(stamps):
        if not events or t - events[-1] > merge_s:
            events.append(t)
    return events


def pace_of(events):
    """两个事件之间的间隔 → 中位/p90/建议阈值。样本不足返回 None（不硬凑）。"""
    gaps = [b - a for a, b in zip(events, events[1:])]
    if len(gaps) < MIN_SAMPLES:
        return None
    med = statistics.median(gaps)
    p90 = sorted(gaps)[max(0, int(len(gaps) * 0.9) - 1)]
    return {'samples': len(gaps), 'gap_median_s': int(med), 'gap_p90_s': int(p90),
            'suggested_threshold_s': int(max(600, p90 * N_FACTOR)),
            'confidence': 'medium' if len(gaps) >= 20 else 'low'}


def device_entities(dev):
    ids = set(dev.get('entities') or [])
    if dev.get('entity_id'):
        ids.add(dev['entity_id'])
    return ids


def main():
    if not os.path.exists(STATE):
        print('缺 data/state.json'); return 1
    state = json.load(open(STATE, encoding='utf-8'))

    # 数据来源：API 优先（迁到 HA OS 后 recorder 库在虚拟机里，docker cp 拿不到）
    rows, source, note = None, None, ''
    if CALIB_SOURCE in ('auto', 'api'):
        try:
            rows, got = fetch_rows_api(state)
            source = (f'api（历史 API，窗口 {HISTORY_HOURS:g} 小时，{got} 台设备'
                      f'各取最多 {MAX_ENTITIES_PER_DEVICE} 个主要实体）')
        except Exception as err:  # noqa
            if CALIB_SOURCE == 'api':
                raise
            note = f'；API 不可用（{str(err)[:60]}），改用容器库'
            rows = None
    if rows is None:
        tmp, db = fetch_db()
        if db is None:
            print('⚠️ 拿不到 recorder 库（HA 不在容器里？迁移后应改用历史 API）')
            print('   本次不做校准，保持上一次结果不变 —— 不产出假数据。')
            return 2
        try:
            con = sqlite3.connect(db)
            rows = con.execute(
                'select sm.entity_id, s.last_updated_ts from states s '
                'join states_meta sm on sm.metadata_id = s.metadata_id '
                'order by sm.entity_id, s.last_updated_ts').fetchall()
            con.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        source = 'container（recorder 只读副本）' + note

    per_entity = {}
    for eid, ts in rows:
        per_entity.setdefault(eid, []).append(float(ts))

    now = datetime.datetime.now(TZ).timestamp()
    devices, sampled, calibrated, need_more = [], 0, 0, 0
    for dev in state.get('devices') or []:
        ents = device_entities(dev)
        stamps = sorted(t for e in ents for t in per_entity.get(e, []))
        events = events_of(stamps)
        rec = {'name': dev['name'], 'room': dev.get('room'), 'type': dev.get('type'),
               'records': len(stamps), 'events': len(events),
               'last_age_s': int(now - stamps[-1]) if stamps else None}
        pace = pace_of(events)
        span_s = int(stamps[-1] - stamps[0]) if len(stamps) >= 2 else 0
        rec['span_s'] = span_s
        if pace and span_s >= MIN_SPAN_S:
            rec.update(pace)
            sampled += 1                      # 有初步样本
        else:
            why = 'span_too_short' if pace else 'insufficient'
            rec.update({'gap_median_s': None, 'gap_p90_s': None,
                        'suggested_threshold_s': None, 'confidence': why})
            need_more += 1
        devices.append(rec)

    span_h = (max(t for v in per_entity.values() for t in v) -
              min(t for v in per_entity.values() for t in v)) / 3600 if per_entity else 0
    doc = {'generated_at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
           'observation_hours': round(span_h, 2),
           'source': source,
           'rule': f'阈值 = 节奏 p90 × {N_FACTOR}，下限 600 秒（06 v1.2 §3）',
           'entities': len(per_entity), 'devices': len(devices),
           # **两个概念分开报**（2026-10-17 实测踩坑：只观测 3.4h 却报"64/64 可校准"，把
           # "有样本"说成了"可用"）：
           #   sampled    = 有初步节奏样本的设备数（能看出大致节奏）
           #   calibrated = **达到可用门槛**的设备数（规范 06 §3 要求观测满 24h 才启用阈值判定）
           'sampled': sampled,
           'calibrated': sampled if span_h >= 24 else 0,
           'need_more': need_more,
           'enough_for_24h_rule': span_h >= 24,
           'devices_detail': sorted(devices, key=lambda d: (d['confidence'] != 'insufficient', d['name']))}
    json.dump(doc, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    ev = os.path.join(ROOT, 'logs', 'evidence', f"{datetime.datetime.now(TZ).strftime('%Y%m%d')}-calib")
    os.makedirs(ev, exist_ok=True)
    lines = [f'# 离线阈值校准 · {doc["generated_at"]}', '',
             f'- 观测时长：**{doc["observation_hours"]} 小时**（"≥24 小时"要求：'
             f'{"已满足" if doc["enough_for_24h_rule"] else "**未满足**"}）',
             f'- 规则：{doc["rule"]}',
             f'- **有初步样本**：{sampled} 台 · **达到可用门槛**：{doc["calibrated"]} 台'
             f'（观测 {doc["observation_hours"]} 小时；满 24 小时才启用阈值判定）',
             f'- 样本不足：{need_more} 台', '',
             '| 设备 | 记录数 | 更新事件 | 间隔中位(秒) | p90(秒) | 建议阈值(秒) | 可信度 |',
             '|---|---|---|---|---|---|---|']
    for d in doc['devices_detail'][:20]:
        lines.append(f"| {d['name'][:24]} | {d['records']} | {d.get('events')} | {d['gap_median_s'] or '—'} | "
                     f"{d['gap_p90_s'] or '—'} | {d['suggested_threshold_s'] or '—'} | {d['confidence']} |")
    lines += ['', '## 结论', '',
              f'- 现在**还不能**按 06 v1.2 §3 启用阈值判定：观测 {doc["observation_hours"]} 小时 < 24 小时。',
              '- 当前口径保持「硬证据优先」（只认 HA 的 unavailable），不产生假离线。',
              '- 等观测满 24 小时后重跑本工具，我会把建议阈值提给你确认，再启用。']
    open(os.path.join(ev, 'calibration.md'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')

    print(f"观测 {doc['observation_hours']} 小时 · 有初步样本 {sampled} 台 · "
          f"**达到可用门槛 {doc['calibrated']} 台**（满 24 小时才启用阈值判定）· 样本不足 {need_more} 台")
    for d in doc['devices_detail'][:6]:
        if d['suggested_threshold_s']:
            print(f"   {d['name'][:26]:28s} 间隔中位 {d['gap_median_s']:6d}s · 建议阈值 "
                  f"{d['suggested_threshold_s']:6d}s（{d['confidence']}）")
    print(f'\n证据：{os.path.relpath(os.path.join(ev, "calibration.md"), ROOT)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
