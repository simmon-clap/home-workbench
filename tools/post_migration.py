#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
迁移后的验收清单（一键跑，给"迁完了吗"一个机械答案）

和 `preflight.py` 是镜像关系：开工前问 GO/NO-GO，收尾时问"真的迁成了吗"。
判定不靠感觉 —— 逐条机械核对，**任一条不过就不算迁完**。

核对内容：
  ① 形态翻转：出现 `hassio` 集成（只有 HA OS / Supervised 才有）→ 证明确实换了底座
  ② 两个自定义集成都在（优先走官方 API）
  ③ 状态层已走 API（state.json 的 data_source 记录）
  ④ 基线比对：`migrate_check --post`（设备/房间/集成/服务不漂移）
  ⑤ HomeKit 集成已配置 + **桥能在局域网被 mDNS 发现**（配对的前提）
  ⑥ 虚拟机开机自启已就位（Mac 重启后 HA 能自己回来）
  ⑦ 24h 在线前提仍满足
  ⑧ 全规范门禁 + 验收 7 条

剩下的**只能人做**的事（如实列出，不假装）：
  · iPhone「家庭」App 扫配对码
  · 小米集成重新授权（若 ② 里 xiaomi_home 实体不可用）
  · 确认 Tailscale 入口地址（HA 若换 IP，工作台的 HA 地址与 serve 目标要跟着改）

用法：
  python3 tools/post_migration.py           # 完整验收
  python3 tools/post_migration.py --quick   # 跳过门禁与验收（应急快速看）
  python3 tools/post_migration.py --json
退出码：0 = 全部通过；1 = 还有没到位的地方
"""
import argparse
import json
import os
import subprocess
import time
import sys
import urllib.request

APP_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, 'tools')
DATA = os.path.join(ROOT, 'data')
sys.path.insert(0, os.path.join(ROOT, 'app'))

MANUAL = [
    'iPhone「家庭」App 扫配对码（迁移后一次性）',
    '小米集成重新授权（若 xiaomi_home 实体不可用）',
    '确认 Tailscale 入口：HA 若换 IP，工作台的 HA 地址与 serve 目标要跟着改',
]


def _ha_config():
    try:
        import ha
        req = urllib.request.Request(ha.BASE + '/api/config')
        req.add_header('Authorization', 'Bearer ' + ha.load_token())
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)
    except Exception:  # noqa
        return None


def check_form():
    """形态是否已翻转成 HA OS（出现 hassio 集成）。"""
    cfg = _ha_config()
    if not cfg:
        return False, '读不到 HA 配置（HA 不可达？）'
    comps = set(cfg.get('components') or [])
    if 'hassio' in comps:
        return True, f"已在 HA OS / Supervised 上（HA {cfg.get('version')}）"
    return False, f"**仍是容器版**（没有 hassio，HA {cfg.get('version')}）—— 还没迁到 HA OS"


def check_integrations():
    import ha_paths
    cc, how = ha_paths.custom_components()
    missing = [x for x in ('smart_home_bridge', 'xiaomi_home') if x not in cc]
    return (not missing), f"集成 {cc}（via {how}）" + (f"，缺 {missing}" if missing else '')


def check_state_source():
    """状态层必须走官方 API。

    注意：桥接虚拟机在**高负载**时会短暂 `No route to host`（2026-10-17 实测：
    平时 6 分钟 177 次探测 0 失败，但跑整套门禁+验收时偶尔会撞上）。
    所以这里**先自己重试刷新几次**再判，并把用了几次如实写进结论 —— 不能拿一次瞬时抖动
    判"能力不行"，也不能假装没重试过。
    """
    p = os.path.join(DATA, 'state.json')
    attempts, src = 0, {}
    for i in range(3):
        attempts = i + 1
        try:
            subprocess.run([sys.executable, os.path.join(APP_ROOT, 'state.py')],
                           capture_output=True, timeout=300, cwd=ROOT)
        except Exception:  # noqa
            pass
        if not os.path.exists(p):
            continue
        try:
            d = json.load(open(p, encoding='utf-8'))
        except Exception:  # noqa
            continue
        src = d.get('data_source') or {}
        if src.get('registries') == 'api' and src.get('states') == 'api':
            break
        time.sleep(8)
    ok = src.get('registries') == 'api' and src.get('states') == 'api'
    extra = f'（第 {attempts} 次刷新才拿到 API）' if ok and attempts > 1 else ''
    return ok, f"registries={src.get('registries')} · states={src.get('states')}{extra}"


def check_post_compare():
    try:
        r = subprocess.run([sys.executable, os.path.join(TOOLS, 'migrate_check.py'), '--post'],
                           capture_output=True, text=True, timeout=600)
        out = (r.stdout or '') + (r.stderr or '')
        last = [ln for ln in out.strip().splitlines() if ln.strip()]
        return r.returncode == 0, (last[-1] if last else f'退出码 {r.returncode}')
    except Exception as err:  # noqa
        return False, str(err)[:100]


def check_homekit():
    cfg = _ha_config()
    if not cfg:
        return False, '读不到 HA 配置'
    configured = 'homekit' in set(cfg.get('components') or [])
    try:
        r = subprocess.run([sys.executable, os.path.join(TOOLS, 'mdns_check.py'), '--json'],
                           capture_output=True, text=True, timeout=90)
        found = json.loads(r.stdout or '{}').get('bridges') or []
    except Exception:  # noqa
        found = []
    ok = configured and bool(found)
    return ok, (f"homekit 集成={'已配' if configured else '未配'} · mDNS 发现 {len(found)} 个桥"
                + (f"（{'、'.join(found)}）" if found else ''))


def check_vm_autostart():
    try:
        r = subprocess.run([sys.executable, os.path.join(TOOLS, 'vm_autostart.py'), '--check'],
                           capture_output=True, text=True, timeout=90)
        out = (r.stdout or '').strip().splitlines()
        return r.returncode == 0, (out[-1].strip() if out else '')
    except Exception as err:  # noqa
        return False, str(err)[:100]


def check_uptime():
    try:
        r = subprocess.run([sys.executable, os.path.join(TOOLS, 'uptime_check.py')],
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout or '').strip().splitlines()
        return r.returncode == 0, (out[-1].strip() if out else '')
    except Exception as err:  # noqa
        return False, str(err)[:100]


def check_freeze():
    """与迁移前冻结快照比对：迁移**不该改动我们的代码与规范**（改了就是漂移，要查清）。"""
    import glob
    snaps = sorted(glob.glob(os.path.join(ROOT, 'logs', 'evidence', '*freeze', 'freeze-snapshot.json')))
    if not snaps:
        return False, '找不到冻结快照（先跑 tools/freeze_snapshot.py）'
    try:
        r = subprocess.run([sys.executable, os.path.join(TOOLS, 'freeze_snapshot.py'), '--verify', snaps[-1]],
                           capture_output=True, text=True, timeout=600)
        out = [l for l in (r.stdout or '').strip().splitlines() if l.strip()]
        return r.returncode == 0, (out[-1].strip() if out else '')
    except Exception as err:  # noqa
        return False, str(err)[:100]


def check_gate():
    try:
        r = subprocess.run([sys.executable, os.path.join(TOOLS, 'gate.py')],
                           capture_output=True, text=True, timeout=1800)
        out = [ln for ln in (r.stdout or '').strip().splitlines() if ln.strip()]
        return r.returncode == 0, (out[-1].strip() if out else '')
    except Exception as err:  # noqa
        return False, str(err)[:100]


def check_acceptance():
    try:
        r = subprocess.run([sys.executable, os.path.join(TOOLS, 'acceptance.py')],
                           capture_output=True, text=True, timeout=1800)
        out = [ln for ln in ((r.stdout or '') + (r.stderr or '')).strip().splitlines() if ln.strip()]
        return r.returncode == 0, (out[-1].strip() if out else '')
    except Exception as err:  # noqa
        return False, str(err)[:100]


def run_all(quick=False):
    checks = [('形态已翻转（HA OS / Supervised）', check_form),
              ('自定义集成都在', check_integrations),
              ('状态层已走官方 API', check_state_source),
              ('基线比对（不漂移）', check_post_compare),
              ('HomeKit 已配且 mDNS 可发现', check_homekit),
              ('虚拟机开机自启已就位', check_vm_autostart),
              ('24h 在线前提', check_uptime),
              ('代码/规范零漂移（与冻结快照比对）', check_freeze)]
    if not quick:
        checks += [('全规范门禁', check_gate), ('验收 7 条', check_acceptance)]
    results = []
    for name, fn in checks:
        try:
            ok, detail = fn()
        except Exception as err:  # noqa
            ok, detail = False, f'检查本身出错：{err}'
        results.append({'check': name, 'ok': bool(ok), 'detail': detail})
    return {'done': all(r['ok'] for r in results), 'quick': quick,
            'results': results, 'manual': MANUAL}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    res = run_all(quick=a.quick)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res['done'] else 1
    print('=== 迁移后验收' + ('（快速：跳过门禁与验收）' if a.quick else '') + ' ===')
    for r in res['results']:
        print(('✅ ' if r['ok'] else '❌ ') + r['check'] + f"  —— {r['detail']}")
    print('\n还需要你做的事：')
    for m in res['manual']:
        print(f'  · {m}')
    print()
    print('结论：' + ('**迁移完成**（机械核对的项全过）' if res['done']
                    else '**尚未完成** —— 上面 ❌ 的项还没到位'))
    return 0 if res['done'] else 1


if __name__ == '__main__':
    sys.exit(main())
