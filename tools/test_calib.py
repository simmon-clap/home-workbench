#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
离线阈值校准的单元测试

为什么单独测：这里踩过一个坑——一台设备有多个实体、同一秒一起更新，
不把时间戳聚成"更新事件"就会算出全是 0 秒间隔，进而给出荒谬的建议阈值。
本测试就是"再也不许发生"的机械保证。

用法：python3 tools/test_calib.py      退出码 0 = 全过
"""
import importlib.util
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('calib', os.path.join(ROOT, 'tools', 'calibrate_offline.py'))
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def main():
    # 同一秒的多个实体 → 聚成一个事件
    burst = [100.0, 100.2, 100.4, 100.9, 160.0, 160.3, 220.0]
    ev = C.events_of(burst)
    check('同一秒的多次更新聚成一个事件', len(ev) == 3, f'{len(burst)} 个时间戳 → {len(ev)} 个事件')

    # 事件间隔 = 真实节奏（60 秒），而不是 0
    pace = C.pace_of([100.0, 160.0, 220.0, 280.0, 340.0, 400.0, 460.0])
    check('节奏按事件间隔算（不是 0 秒）', pace and pace['gap_median_s'] == 60, str(pace))
    check('建议阈值 = p90 × 3 且不低于 600 秒',
          pace and pace['suggested_threshold_s'] == max(600, pace['gap_p90_s'] * 3), str(pace))

    # 样本不足时**不下结论**（不硬凑）
    short = C.pace_of([0.0, 60.0, 120.0])
    check('样本不足时返回 None（不硬凑阈值）', short is None, str(short))

    # 抖动大的设备阈值更高（这正是固定 600 秒会误判的原因）
    steady = C.pace_of([i * 60.0 for i in range(12)]) or {}          # 稳定 60s
    jittery = C.pace_of([0, 300, 600, 900, 1200, 1500, 3000, 3300, 3600, 3900, 4200, 4500]) or {}
    check('抖动大的设备建议阈值更高',
          (jittery.get('suggested_threshold_s') or 0) >= (steady.get('suggested_threshold_s') or 0),
          f"稳 {steady.get('suggested_threshold_s')} vs 抖 {jittery.get('suggested_threshold_s')}")

    # 真实产物：必须诚实写明 24 小时规则是否满足
    p = os.path.join(ROOT, 'data', 'offline-calibration.json')
    if os.path.exists(p):
        d = json.load(open(p, encoding='utf-8'))
        check('校准产物含观测时长与规则', 'observation_hours' in d and 'rule' in d)
        check('诚实标注是否满足 24 小时规则',
              isinstance(d.get('enough_for_24h_rule'), bool),
              f"{d.get('observation_hours')} 小时 → 满足={d.get('enough_for_24h_rule')}")
        # 2026-10-17 调整语义：**"有初步样本" ≠ "达到可用门槛"**。
        # 之前把两者混成一个数字，导致只观测 3.4h 就报"64/64 可校准"（实测抓到的假指标）。
        check('未满 24 小时时，达到可用门槛的设备数必须为 0（不许把"有样本"说成"可用"）',
              d.get('enough_for_24h_rule') or d.get('calibrated', 1) == 0,
              f"有初步样本 {d.get('sampled')} · 达到可用门槛 {d.get('calibrated')} · 满足24h={d.get('enough_for_24h_rule')}")
        check('两个数字分开记录（有样本 / 达到门槛）',
              'sampled' in d and 'calibrated' in d,
              f"sampled={d.get('sampled')} calibrated={d.get('calibrated')}")

    # ── 历史 API 的两个静默坑（2026-10-17 实测抓到）──
    import importlib.util as _iu
    _sp = _iu.spec_from_file_location('co', os.path.join(ROOT, 'tools', 'calibrate_offline.py'))
    _co = _iu.module_from_spec(_sp); _sp.loader.exec_module(_co)
    u = _co.history_url('http://x', 'sensor.a', '2026-10-17T01:00:00+00:00', '2026-10-17T02:00:00+00:00')
    check('历史 URL 把时区里的 + 转义（否则 HA 解析失败 → 静默空结果）', '%2B00%3A00' in u or '%2B' in u, u[:100])
    check('历史 URL 带 end_time', 'end_time=' in u)
    spans = _co.history_spans(50, now=datetime.datetime(2026, 10, 17, 12, 0, tzinfo=datetime.timezone.utc))
    check('超过 24 小时的窗口会被分段（单次超 24h 会静默返回空）', len(spans) >= 3, f'{len(spans)} 段')
    widths = []
    for a, b in spans:
        ta = datetime.datetime.fromisoformat(a); tb = datetime.datetime.fromisoformat(b)
        widths.append(round((tb - ta).total_seconds() / 3600, 2))
    check('每段都不超过 24 小时', all(w <= 24.0 for w in widths), str(widths))
    check('分段总长等于请求窗口', abs(sum(widths) - 50) < 0.01, f'{sum(widths)} 小时')

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
