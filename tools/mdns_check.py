#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HomeKit 桥的 mDNS 发现检测（迁移第 6 步的验收点）

为什么关键：苹果「家庭」App 配对靠 **mDNS 同二层发现**。HA 的 HomeKit 桥配好不代表能被发现 ——
容器版跑在 NAT 后面，HTTP 能通但广播出不去，所以 iPhone 找不到桥。这个检测就是那条"看得见"的判据。

做法：用 macOS 自带的 `dns-sd -B _hap._tcp` 监听几秒，统计能发现的 HomeKit 桥；
同时从 HA API 侧确认 `homekit` 集成是否已配置（两边都要对得上，缺一不算通过）。

用法：
  python3 tools/mdns_check.py                 # 检测并给结论
  python3 tools/mdns_check.py --seconds 6     # 多听一会
  python3 tools/mdns_check.py --json
环境变量：DNS_SD（便于测试替换）· HA_BASE_URL
退出码：0 = 发现到桥；1 = 没发现（迁移未完成或网络不通）
"""
import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
DNS_SD = os.environ.get('DNS_SD') or '/usr/bin/dns-sd'


def ha_homekit_configured():
    """HA 侧是否已启用 homekit 集成（没有就是还没配桥）。"""
    try:
        import ha
        import urllib.request
        req = urllib.request.Request(ha.BASE + '/api/config')
        req.add_header('Authorization', 'Bearer ' + ha.load_token())
        with urllib.request.urlopen(req, timeout=15) as resp:
            cfg = json.load(resp)
        comps = cfg.get('components') or []
        return 'homekit' in comps, cfg.get('version')
    except Exception as err:  # noqa
        return None, str(err)[:80]


def browse(seconds=5, dns_sd=None):
    """监听 _hap._tcp，返回发现的桥（去重后的名字列表）。"""
    exe = dns_sd or DNS_SD
    if not os.path.exists(exe):
        return None, f'找不到 {exe}'
    try:
        r = subprocess.run([exe, '-B', '_hap._tcp', 'local'], capture_output=True, text=True,
                           timeout=max(2, seconds))
        out = (r.stdout or '') + (r.stderr or '')
    except subprocess.TimeoutExpired as err:                     # 正常：dns-sd 会一直跑
        out = ((err.stdout or b'').decode('utf-8', 'replace') if isinstance(err.stdout, bytes)
               else (err.stdout or ''))
        out += ((err.stderr or b'').decode('utf-8', 'replace') if isinstance(err.stderr, bytes)
                else (err.stderr or ''))
    except Exception as err:  # noqa
        return None, str(err)[:80]
    names = []
    for line in out.splitlines():
        if '_hap._tcp' not in line or 'Add' not in line:
            continue
        parts = line.split()
        if len(parts) >= 7:
            names.append(parts[6])
    return sorted(set(names)), out.strip().splitlines()[-1] if out.strip() else ''


def check(seconds=5, dns_sd=None):
    bridges, detail = browse(seconds, dns_sd)
    configured, version = ha_homekit_configured()
    ok = bool(bridges)
    return {'found': bool(bridges), 'bridges': bridges or [], 'browse_detail': detail,
            'ha_homekit_configured': configured, 'ha_version': version,
            'verdict': ('发现 HomeKit 桥：' + '、'.join(bridges or [])) if ok
                       else '**没有发现 HomeKit 桥**（mDNS 出不去，或还没配桥）'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=float, default=5)
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    res = check(a.seconds)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res['found'] else 1
    print('=== HomeKit 桥 mDNS 检测 ===')
    print(f"  HA 侧 homekit 集成：{'已配置' if res['ha_homekit_configured'] else '未配置'}"
          f"（HA {res['ha_version']}）")
    print(f"  局域网 mDNS 发现的桥：{len(res['bridges'])} 个 {res['bridges'] or ''}")
    print(f"  结论：{'✅ ' if res['found'] else '❌ '}{res['verdict']}")
    if not res['found']:
        print('  提示：容器版跑在 NAT 后面时这是正常结果 —— HTTP 通、广播出不去。')
        print('        迁到 HA OS（桥接网卡）后应能发现；若仍发现不了，先查虚拟机是否同一网段。')
    return 0 if res['found'] else 1


if __name__ == '__main__':
    sys.exit(main())
