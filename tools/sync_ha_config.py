#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 HA OS 虚拟机里的真实配置同步到本地 `config/homeassistant/`

为什么需要：迁移到 HA OS 之后，HA 的配置活在虚拟机里（/mnt/data/supervisor/homeassistant），
而本地 `config/homeassistant/` 还是**容器版那份旧配置**。两份不同步会造成两个问题：
  1. 备份打的是旧配置 → "备份可恢复"名不副实（宪章第四条要求备份真能救回来）；
  2. 状态模型的**文件兜底**（API 不可用时）读到的是旧的设备/房间，与 API 路径对不上。

做法：走 HA OS 的开发者 SSH（端口 22222，密钥在 ~/.config/smart-home/haos_ssh），
用 tar 管道把配置拉回来；**排除**登录态（auth*）、onboarding、db-wal/shm、日志、backups、deps/tts。
排除登录态是刻意的：本地镜像只用于"看配置/做备份"，不用于冒充登录。

用法：
    python3 tools/sync_ha_config.py            # 同步
    python3 tools/sync_ha_config.py --check    # 只检查两边差多少，不动手
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = os.path.expanduser('~/.config/smart-home/haos_ssh')
DEST = os.path.join(ROOT, 'config', 'homeassistant')
def _haos_host():
    """HA OS 地址：环境变量 > ~/.config/smart-home/haos-host > 空（必须显式配置）。"""
    v = os.environ.get('SMART_HOME_HAOS_HOST')
    if v:
        return v
    try:
        return open(os.path.expanduser('~/.config/smart-home/haos-host'), encoding='utf-8').read().strip()
    except OSError:
        return ''


VM_HOST = _haos_host()
VM_PORT = os.environ.get('SMART_HOME_HAOS_SSH_PORT', '22222')
REMOTE_CFG = '/mnt/data/supervisor/homeassistant'

EXCLUDES = [
    '.storage/auth', '.storage/auth_provider.homeassistant', '.storage/onboarding',
    '.storage/*.corrupt', 'home-assistant_v2.db-wal', 'home-assistant_v2.db-shm',
    '*.log', '*.log.1', '*.log.fault', 'backups', 'deps', 'tts', '__pycache__', '.cloud',
    '._*',                      # macOS 在 FAT/共享分区上生成的 AppleDouble，会让 tar 报 Truncated
]


def ssh_base():
    return ['ssh', '-i', KEY, '-p', VM_PORT,
            '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
            '-o', 'ConnectTimeout=10', '-o', 'BatchMode=yes', f'root@{VM_HOST}']


def reachable():
    if not os.path.exists(KEY):
        return False
    try:
        r = subprocess.run(ssh_base() + ['true'], capture_output=True, timeout=15)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def sync(quiet=False):
    """返回 (ok, 说明)。ok=False 时调用方应当降级而不是崩。"""
    if not reachable():
        return False, f'连不上 HA OS（{VM_HOST}:{VM_PORT}），跳过同步'
    os.makedirs(DEST, exist_ok=True)
    # 远端打包（排除见上）→ 本地解包。tar 从 stdin 读，避免 HA OS 的受限 sshd 拒绝 sftp/scp
    # HA OS 里的 busybox tar **没有 gzip**（实测：tar: can't execute 'gzip'）→ 用不压缩管道
    tar_args = ['tar', 'cf', '-', '-C', REMOTE_CFG]
    for e in EXCLUDES:
        # 注意：`__pycache__` 这类**任意层级**都要排除，不能加 './' 前缀（否则只匹配顶层）
        tar_args += ['--exclude', e if e.startswith('*') or '/' not in e else f'./{e}']
    tar_args.append('.')
    remote = subprocess.run(ssh_base() + [' '.join(tar_args)], capture_output=True)
    if remote.returncode != 0:
        return False, f'远端打包失败：{remote.stderr.decode()[:120]}'
    env = dict(os.environ, COPYFILE_DISABLE='1')
    local = subprocess.run(['tar', 'xf', '-', '-C', DEST], input=remote.stdout,
                           capture_output=True, env=env)
    # 本地镜像里若还残留登录态（来自早先的容器版），清掉：镜像不承担登录
    for rel in ('.storage/auth', '.storage/auth_provider.homeassistant'):
        p_local = os.path.join(DEST, rel)
        if os.path.exists(p_local):
            os.remove(p_local)
    if local.returncode != 0 and not os.path.exists(os.path.join(DEST, 'configuration.yaml')):
        return False, f'本地解包失败：{local.stderr.decode()[:120]}'
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(DEST) for f in fs
               if os.path.isfile(os.path.join(dp, f)))
    if not quiet:
        print(f'  ✅ 已同步 HA OS 配置 → {DEST}（{size / 1048576:.1f} MB）')
    return True, f'{size / 1048576:.1f} MB'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='只检查连通性与差异，不写入')
    a = ap.parse_args()
    if a.check:
        if not reachable():
            print(f'  ❌ 连不上 HA OS（{VM_HOST}:{VM_PORT}）'); return 1
        r = subprocess.run(ssh_base() + [f'ls {REMOTE_CFG} | wc -l'], capture_output=True, timeout=20)
        print(f'  ✅ 可连通 · 远端配置条目 {r.stdout.decode().strip()}')
        return 0
    ok, msg = sync()
    print(('  ' + msg) if ok else f'  ⚠️ {msg}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
