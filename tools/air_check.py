#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MacBook Air 演练就绪检查（P5 · 迁移前置）

用途：真迁移是唯一有停机的操作。先用 Air 把整场迁移**演练一遍**（不碰家里），
      再在 mini 上重放。这个脚本只做"能不能开始"的判断，不做安装（安装需用户明确同意）。

检查项：
  ① Air 在 tailnet 里吗 / SSH 通吗（免密是否还有）
  ② Air 的硬件与系统（内存、磁盘余量、CPU、macOS 版本）
  ③ 虚拟化环境（QEMU 或 UTM 是否已装；brew 是否可用）
  ④ 本地这边的物料（HA OS 镜像、最新备份、迁移手册）
  ⑤ 打印"接下来会做什么、要装什么"（不做则不装）

用法：
  python3 tools/air_check.py            # 只检查，不改任何东西
  python3 tools/air_check.py --json     # 机器可读输出
"""
import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AIR_IPS = [x for x in os.environ.get('SMART_HOME_AIR_IPS', '').split(',') if x]  # tailnet 地址（本机配置）
SSH_OPTS = ['-o', 'ConnectTimeout=8', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new']


def sh(cmd, timeout=25):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or '') + (r.stderr or '')
    except Exception as err:  # noqa
        return f'<失败：{err}>'


def check_air():
    out = {'reachable': False, 'ip': None, 'info': {}}
    for ip in AIR_IPS:
        r = subprocess.run(['ssh'] + SSH_OPTS + [ip, 'echo AIR_OK'],
                           capture_output=True, text=True, timeout=20)
        if 'AIR_OK' in (r.stdout or ''):
            out['reachable'] = True
            out['ip'] = ip
            info = sh(['ssh'] + SSH_OPTS + [ip,
                       'sw_vers -productVersion; sysctl -n hw.memsize; sysctl -n hw.ncpu; '
                       'df -k / | tail -1 | awk \'{print $4}\'; '
                       'ls -d /Applications/UTM.app 2>/dev/null && echo UTM_YES || echo UTM_NO; '
                       'which qemu-system-aarch64 || echo QEMU_NO; '
                       'which brew || echo BREW_NO; '
                       'sysctl -n kern.hv_support 2>/dev/null || echo HV_UNKNOWN'])
            lines = [l for l in info.splitlines() if l.strip()]
            out['info'] = {
                'macos': lines[0] if len(lines) > 0 else None,
                'mem_gb': round(int(lines[1]) / 1073741824) if len(lines) > 1 and lines[1].isdigit() else None,
                'cpu': lines[2] if len(lines) > 2 else None,
                'disk_free_gb': round(int(lines[3]) / 1048576, 1) if len(lines) > 3 and lines[3].isdigit() else None,
                'utm': 'UTM_YES' in info,
                'qemu': 'QEMU_NO' not in info and 'qemu' in info.lower(),
                'brew': 'BREW_NO' not in info,
                'virtualization': 'HV_UNKNOWN' not in info and '1' in info.split('HV_')[-1][:2],
            }
            break
    return out


def local_materials():
    img_dir = os.path.join(ROOT, 'data', 'images')
    imgs = [f for f in os.listdir(img_dir)] if os.path.isdir(img_dir) else []
    bk = os.path.join(ROOT, 'backups')
    backups = sorted([f for f in os.listdir(bk) if f.endswith('.tgz')],
                     key=lambda f: os.path.getmtime(os.path.join(bk, f))) if os.path.isdir(bk) else []
    return {
        'haos_image': imgs,
        'latest_backup': backups[-1] if backups else None,
        'backup_mb': round(os.path.getsize(os.path.join(bk, backups[-1])) / 1048576, 1) if backups else None,
        'runbooks': [f for f in os.listdir(os.path.join(ROOT, 'data')) if f.startswith('runbook-')],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    air = check_air()
    mat = local_materials()
    result = {'air': air, 'materials': mat}

    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0

    print('=== MacBook Air 演练就绪检查 ===')
    if air['reachable']:
        i = air['info']
        print(f"✅ Air 可达（{air['ip']}）")
        print(f"   macOS {i.get('macos')} · 内存 {i.get('mem_gb')} GB · CPU {i.get('cpu')} 核 · 磁盘余量 {i.get('disk_free_gb')} GB")
        print(f"   虚拟化支持：{'是' if i.get('virtualization') else '未知/否'} · QEMU：{'已装' if i.get('qemu') else '未装'} · UTM：{'已装' if i.get('utm') else '未装'} · brew：{'有' if i.get('brew') else '无'}")
        if not i.get('qemu') and not i.get('utm'):
            print('   → 需要在 Air 上装虚拟化环境（QEMU 可脚本化 / UTM 图形界面）——**等你点头才装**')
        if (i.get('mem_gb') or 0) < 8:
            print('   ⚠️ 内存 < 8GB：HA OS 演练可能吃紧（HA 自身建议 2GB+，加 macOS 开销）')
    else:
        print('❌ Air 现在连不上（Tailscale 显示 idle / SSH 超时）')
        print('   请在 Air 上：① 唤醒（合盖休眠最常见）② 打开 系统设置 → 通用 → 共享 → 远程登录')
        print('   然后重跑本命令。')

    print('\n=== 本地物料 ===')
    print(f"   HA OS 镜像：{', '.join(mat['haos_image']) or '没有（需要先下载）'}")
    print(f"   最新备份：{mat['latest_backup']}（{mat['backup_mb']} MB）")
    print(f"   手册：{', '.join(mat['runbooks'])}")

    print('\n=== 演练会做什么（不碰家里）===')
    for s in ['① 在 Air 上装虚拟化环境（QEMU 或 UTM）',
              '② 用 HA OS 镜像起一台虚拟机（桥接网卡，Air 自己的网络）',
              '③ 把我们最新备份里的配置与历史库恢复进这台 HA OS',
              '④ 跑 check_config + 实体/设备比对（对照 data/migration-baseline.json）',
              '⑤ 把 Tailscale/HTTPS 入口在 Air 上复现一次（验证迁移后的远程通道方案）',
              '⑥ 记证据到 logs/evidence/<日期>-P5/，然后关掉虚拟机']:
        print('   ' + s)
    print('\n   演练通过后，在 mini 上重放同样的步骤 —— 那时停机可以压到 10 分钟内。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
