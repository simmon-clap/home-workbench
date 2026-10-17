#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
接住扫地机推上来的地图数据（"钩子先装好，数据来了自动收"）

背景（2026-10-17）：已经拿到地图服务里的**文件引用**
  siid=6 piid=8 多层地图信息 → {"obj_name": ".../9", "md5": "..."}
但真正的几何数据在 notify 类属性上（设备**主动推**才有）：
  · piid=1 地图数据
  · piid=3 中转地图数据在 FDS 上的文件名
直接读返回 None（push-only）。所以这里只做一件事：**盯着**，一旦有内容就存下来。

用法：
  python3 tools/map_watch.py --once        # 查一次（给定时任务用）
  python3 tools/map_watch.py --watch 600   # 盯 10 分钟
  python3 tools/map_watch.py --status      # 看已经收到过什么
"""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
DATA = os.path.join(ROOT, 'data')
PUSH = os.environ.get('SMART_HOME_PUSH_DIR') or os.path.join(DATA, 'vacuum-map-push')
# HA 地址**不写死**：跟着 ~/.config/smart-home/ha-base-url 走（换中枢/换 IP 只改一处）
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app'))
import ha as _ha
HA = _ha.BASE
TZ = datetime.timezone(datetime.timedelta(hours=8))

ENTITIES = {
    'map_data': 'sensor.dreame_cn_1037682406_p2114o_map_data_p_6_1',
    'object_name': 'sensor.dreame_cn_1037682406_p2114o_object_name_p_6_3',
    'multi_floor': 'sensor.dreame_cn_1037682406_p2114o_mult_map_info_p_6_8',
}


def _token():
    import ha
    t = ha.load_token()
    if not t:
        raise SystemExit('没有 HA 令牌（先跑 tools/set-ha-token.sh）')
    return t


def _get(path):
    req = urllib.request.Request(HA + path)
    req.add_header('Authorization', 'Bearer ' + _token())
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {'error': e.code, 'body': e.read().decode('utf-8', 'replace')[:200]}
    except Exception as e:  # noqa
        return {'error': str(e)}


def snapshot():
    """读三个地图相关实体的当前状态（含属性）。"""
    out = {}
    for key, eid in ENTITIES.items():
        d = _get('/api/states/' + eid)
        if isinstance(d, dict) and 'state' in d:
            out[key] = {'entity_id': eid, 'state': d['state'], 'attributes': d.get('attributes') or {},
                        'last_updated': d.get('last_updated')}
        else:
            out[key] = {'entity_id': eid, 'state': None, 'error': d.get('error')}
    return out


def _meaningful(snap):
    """有没有"真数据"（不是 unknown / 空）。"""
    got = {}
    for k, v in snap.items():
        s = v.get('state')
        if s not in (None, 'unknown', 'unavailable', ''):
            got[k] = s
    return got


def _state_file():
    os.makedirs(PUSH, exist_ok=True)
    return os.path.join(PUSH, 'last-seen.json')


def check_once(verbose=True):
    snap = snapshot()
    got = _meaningful(snap)
    first_run = not os.path.exists(_state_file())
    prev = {}
    if not first_run:
        try:
            prev = json.load(open(_state_file(), encoding='utf-8')).get('values') or {}
        except ValueError:
            prev = {}
    # 首次运行只建立基线：**不能把早就有的数据说成"收到新推送"**（那是谎报）
    new = {} if first_run else {k: v for k, v in got.items() if prev.get(k) != v}

    with open(_state_file(), 'w', encoding='utf-8') as f:
        json.dump({'at': datetime.datetime.now(TZ).isoformat(timespec='seconds'), 'values': got}, f,
                  ensure_ascii=False, indent=1)

    if new:
        ts = datetime.datetime.now(TZ).strftime('%Y%m%d-%H%M%S')
        path = os.path.join(PUSH, f'push-{ts}.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
                       'new': new, 'snapshot': snap}, f, ensure_ascii=False, indent=1)
        if verbose:
            print(f'🎯 收到新数据：{", ".join(new)} → {os.path.relpath(path, ROOT)}')
            for k, v in new.items():
                print(f'   {k}: {str(v)[:120]}')
        return True, path, new
    if verbose:
        if got:
            print('已见过的数据还在（没有新的）：', ', '.join(f'{k}={str(v)[:40]}' for k, v in got.items()))
        else:
            print('还没有推送数据（三个 notify 属性都还是 unknown）—— 等设备清扫/打开地图时自然会来')
    return False, None, {}


def status():
    rows = sorted(f for f in os.listdir(PUSH) if f.startswith('push-')) if os.path.isdir(PUSH) else []
    print(f'已收到 {len(rows)} 次推送')
    for r in rows[-5:]:
        p = os.path.join(PUSH, r)
        try:
            d = json.load(open(p, encoding='utf-8'))
            print(f'  {r}  新数据: {", ".join((d.get("new") or {}).keys())}')
        except ValueError:
            print(f'  {r}  (解析失败)')
    if os.path.exists(_state_file()):
        d = json.load(open(_state_file(), encoding='utf-8'))
        print('  最近一次检查:', d.get('at'), '| 当时的值:', {k: str(v)[:30] for k, v in (d.get('values') or {}).items()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--watch', type=int, default=0, help='盯多少秒')
    a = ap.parse_args()
    if a.status:
        status(); return 0
    if a.watch:
        end = time.time() + a.watch
        print(f'开始盯 {a.watch} 秒（每 15 秒查一次）…')
        while time.time() < end:
            check_once(verbose=True)
            time.sleep(15)
        return 0
    check_once(verbose=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
