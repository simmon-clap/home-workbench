#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通过 HA 自己的通道取扫地机地图信息

背景（2026-10-17 实测）：
  · HA 里**没有** camera/image 实体，集成 vacuum.py 的 map 只是状态映射表；
  · 米家 App 里也没有「局域网控制」开关，miIO(54321) 对全部 22 台在线主机无回应；
  · 但 xiaomi_home 集成**自己带着证书、已经在跟设备通信**，且客户端有
    `get_prop_async(did, siid, piid)` / `action_async(did, siid, aiid)`；
  · 扫地机的 MIoT 规格里有地图服务：siid=6（piid=8 多层地图信息 read+notify、
    piid=1 地图数据 notify、piid=3 FDS 文件名 notify；动作 aiid=1 请求地图数据）。

所以正路是：在 HA 里加一个只做桥接的小组件（custom_components/smart_home_bridge），
把集成已有的能力暴露成服务，再从外部调用 —— **不引入新凭证、不碰小米云私有接口**。

用法：
  python3 tools/vacuum_map_via_ha.py --check          # 服务是否已加载（需先重启 HA 一次）
  python3 tools/vacuum_map_via_ha.py --fetch          # 取地图信息并落盘
"""
import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

# 实验脚本：多包了一层目录（tools/experimental/），所以往上数三层
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'app'))
DATA = os.path.join(ROOT, 'data')
# HA 地址**不写死**：跟着 ~/.config/smart-home/ha-base-url 走（换中枢/换 IP 只改一处）
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'app'))
import ha as _ha
HA = _ha.BASE
DID = '1037682406'          # 来自实体名 dreame_cn_1037682406_p2114o
BRIDGE = 'smart_home_bridge'


def token():
    import ha
    t = ha.load_token()
    if not t:
        raise SystemExit('没有 HA 令牌（先跑 tools/set-ha-token.sh）')
    return t


def post_service(domain, service, data, return_response=True):
    url = f'{HA}/api/services/{domain}/{service}' + ('?return_response' if return_response else '')
    req = urllib.request.Request(url, data=json.dumps(data).encode(), method='POST')
    req.add_header('Authorization', 'Bearer ' + token())
    req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode('utf-8', 'replace')
            return r.status, (json.loads(body) if body.strip() else {})
    except urllib.error.HTTPError as e:
        return e.code, {'error': e.read().decode('utf-8', 'replace')[:300]}


def services():
    req = urllib.request.Request(f'{HA}/api/services')
    req.add_header('Authorization', 'Bearer ' + token())
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def check():
    try:
        svcs = services()
    except Exception as e:  # noqa
        print('❌ 连不上 HA：', e)
        return 1
    bridge = next((s for s in svcs if s['domain'] == BRIDGE), None)
    if not bridge:
        print('❌ 桥接服务还没加载 —— 需要**重启一次 HA**（新自定义组件只在启动时加载）')
        print('   重启后本命令应显示：get_prop / call_action / vacuum_map')
        print('   重启会中断 HA 约 20–40 秒；家里当前没有配置任何自动化，设备状态会自动恢复。')
        return 2
    print('✅ 桥接已加载：', ', '.join(sorted(bridge['services'].keys())))
    return 0


def fetch(request_first=True):
    st, out = post_service(BRIDGE, 'vacuum_map', {'did': DID, 'request': request_first})
    if st != 200 or not isinstance(out, dict):
        print('❌ 取地图失败：', json.dumps(out, ensure_ascii=False)[:300])
        return 1
    payload = out.get('service_response') or out
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, 'vacuum-map-raw.json')
    json.dump({'at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
               'did': DID, 'payload': payload},
              open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'✅ 已保存 {os.path.relpath(path, ROOT)}')
    for k in ('multi_floor', 'map_data', 'fds_name', 'request_result', 'request_error', 'errors'):
        if k in payload:
            v = payload[k]
            print(f'   {k}: {str(v)[:160]}')
    return 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--fetch', action='store_true')
    ap.add_argument('--no-request', action='store_true', help='不先发"请求地图数据"动作，直接读')
    a = ap.parse_args()
    if a.check or not (a.fetch):
        rc = check()
        if not a.fetch:
            raise SystemExit(rc)
        if rc != 0:
            raise SystemExit(rc)
    raise SystemExit(fetch(request_first=not a.no_request))
