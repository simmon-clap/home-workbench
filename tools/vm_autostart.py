#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HA OS 虚拟机的开机自启（P5 · ④ 路线的最后一块自启拼图）

为什么必须有：HA OS 跑在虚拟机里，**Mac 重启后虚拟机不会自己起来** → 表现是"HA 打不开、
工作台全是旧数据"，而且不会报错。colima/容器版有自启，虚拟机也必须一样有。

做法：装一个 LaunchAgent（RunAtLoad），开机执行 `utmctl start <vm-id>`；
并把这条登记进 `data/automation-manifest.json` 的 services 段 —— 这样门禁 Q36 会一起守着。

**迁移前没有虚拟机是正常的**：此时 --check 只报告"尚未建虚拟机"，不算失败；
一旦检测到虚拟机，就**必须**有自启，否则判失败。

用法：
  python3 tools/vm_autostart.py --check              # 检查（门禁与迁移后复核用）
  python3 tools/vm_autostart.py --list               # 列出虚拟机
  python3 tools/vm_autostart.py --install <vm-id>    # 装自启（迁移时用）
环境变量（便于测试）：UTM_CLI · SMART_HOME_LAUNCH_AGENTS · SMART_HOME_MANIFEST
"""
import argparse
import json
import os
import plistlib
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AGENTS = os.environ.get('SMART_HOME_LAUNCH_AGENTS') or os.path.expanduser('~/Library/LaunchAgents')
MANIFEST = os.environ.get('SMART_HOME_MANIFEST') or os.path.join(ROOT, 'data', 'automation-manifest.json')
UTM_CLI = os.environ.get('UTM_CLI') or '/Applications/UTM.app/Contents/MacOS/utmctl'
AGENT_LABEL = 'com.simon.smarthome-vm'


def utm_available():
    return os.path.exists(UTM_CLI)


def list_vms():
    """返回 [{'id':..., 'name':..., 'status':...}]；没有 UTM 就返回 None（区别于"没有虚拟机"）。"""
    if not utm_available():
        return None
    try:
        r = subprocess.run([UTM_CLI, 'list'], capture_output=True, text=True, timeout=25)
    except Exception:  # noqa
        return None
    if r.returncode != 0:
        return None
    vms = []
    for line in (r.stdout or '').splitlines():
        parts = line.split()
        if not parts or parts[0] in ('UUID', '---'):
            continue
        # 分隔线（----）会被误当成一行，实测踩过：把 1 台虚拟机数成 2 台
        if set(parts[0]) <= {'-'}:
            continue
        if len(parts) >= 2 and len(parts[0]) >= 8:      # UUID 开头
            vms.append({'id': parts[0], 'name': ' '.join(parts[1:-1]) or parts[1],
                        'status': parts[-1]})
    return vms


def agent_path():
    return os.path.join(AGENTS, AGENT_LABEL + '.plist')


def installed_vm_id():
    """已装的自启在启动哪台虚拟机（没装返回 None）。"""
    p = agent_path()
    if not os.path.exists(p):
        return None
    try:
        d = plistlib.load(open(p, 'rb'))
    except Exception:  # noqa
        return None
    args = d.get('ProgramArguments') or []
    if 'start' in args:
        i = args.index('start')
        if i + 1 < len(args):
            return args[i + 1]
    return None


def install(vm_id):
    os.makedirs(AGENTS, exist_ok=True)
    plist = {
        'Label': AGENT_LABEL,
        'ProgramArguments': [UTM_CLI, 'start', vm_id],
        'RunAtLoad': True,
        'StandardOutPath': os.path.join(ROOT, 'logs', 'vm-autostart.log'),
        'StandardErrorPath': os.path.join(ROOT, 'logs', 'vm-autostart.err.log'),
    }
    with open(agent_path(), 'wb') as f:
        plistlib.dump(plist, f)
    # 登记进清单，让 Q36 一起守（services 段）
    try:
        m = json.load(open(MANIFEST, encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        m = {'version': 1, 'jobs': [], 'services': []}
    m.setdefault('services', [])
    if not any(s.get('id') == 'haos-vm' for s in m['services']):
        m['services'].append({'id': 'haos-vm', 'what': 'HA OS 虚拟机（Mac 重启后自动启动）',
                              'script': 'utmctl start', 'agent': AGENT_LABEL, 'keep_alive': False,
                              'vm_id': vm_id,
                              'note': 'RunAtLoad：开机启动虚拟机（KeepAlive 不适用：utmctl start 会立即退出）'})
        json.dump(m, open(MANIFEST, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return agent_path()


def check(quiet=False):
    """返回 (是否通过, 明细)。迁移前没有虚拟机 = 通过（但如实说明）。"""
    info = {'utm': utm_available(), 'vms': list_vms(), 'agent': agent_path(),
            'agent_vm': installed_vm_id()}
    if info['vms'] is None:
        info['verdict'] = '尚未装 UTM（迁移前正常）'
        info['ok'] = True
        return info['ok'], info
    if not info['vms']:
        info['verdict'] = '尚未建虚拟机（迁移前正常）'
        info['ok'] = True
        return info['ok'], info
    ids = [v['id'] for v in info['vms']]
    if info['agent_vm'] in ids:
        info['verdict'] = f"已有自启（虚拟机 {info['agent_vm']}）"
        info['ok'] = True
    else:
        info['verdict'] = (f"发现 {len(ids)} 台虚拟机但没有开机自启 —— "
                           f"Mac 重启后 HA 不会自己回来（跑 --install {ids[0]}）")
        info['ok'] = False
    return info['ok'], info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--install', metavar='VM_ID')
    a = ap.parse_args()

    if a.install:
        p = install(a.install)
        print(f'✅ 已装开机自启：{p}（开机执行 {UTM_CLI} start {a.install}）')
        print('   并已登记进 automation-manifest.json 的 services 段（门禁 Q36 会一起守）')
        return 0
    if a.list:
        vms = list_vms()
        if vms is None:
            print('没有 UTM（或 utmctl 不可用）')
            return 0
        for v in vms:
            print(f"  {v['id']}  {v['name']}  [{v['status']}]")
        return 0
    ok, info = check()
    print('=== 虚拟机开机自启检查 ===')
    print(f"  UTM：{'有' if info['utm'] else '没有'}")
    print(f"  虚拟机：{len(info['vms']) if info['vms'] is not None else '未知'}")
    print(f"  已装自启启动的虚拟机：{info['agent_vm'] or '（无）'}")
    print(f"  结论：{'✅ ' if ok else '❌ '}{info['verdict']}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
