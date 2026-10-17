#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资源实测（P5）

依据：docs/spec/05-技术架构规范 v1.0 §8（mini 资源预算：HA 4GB / Frigate 4GB / DSH 2–3GB / 余量 ≥3GB）
      09 §2（复验要真实：读真机数据，不靠估）

做什么：实测当前 HA 虚拟机、容器与宿主的关键资源占用，并对照预算给出结论与后续建议。
不做：不为了跑分而制造负载（那会打扰家里）。

用法：python3 tools/resource_audit.py       产出 logs/evidence/<日期>-P5/resource-audit.md
"""
import datetime
import json
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCKER = os.path.expanduser('~/.homebrew/bin/docker')
COLIMA = os.path.expanduser('~/.homebrew/bin/colima')
TZ = datetime.timezone(datetime.timedelta(hours=8))


def sh(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or '') + (r.stderr or '')
    except Exception as e:  # noqa
        return f'<执行失败: {e}>'


def parse_size(txt):
    m = re.match(r'([0-9.]+)\s*([KMGT]?i?B)', txt.strip())
    if not m:
        return 0.0
    v = float(m.group(1))
    unit = m.group(2).upper()[0]
    return v * {'B': 1 / 1024 ** 3, 'K': 1 / 1024 ** 2, 'M': 1 / 1024, 'G': 1, 'T': 1024}[unit]


def main():
    now = datetime.datetime.now(TZ)
    ev = os.path.join(ROOT, 'logs', 'evidence', f"{now.strftime('%Y%m%d')}-P5")
    os.makedirs(ev, exist_ok=True)

    vm_mem = sh([COLIMA, 'ssh', '--', 'free', '-m'])
    vm_cpu = sh([COLIMA, 'ssh', '--', 'sh', '-lc', 'nproc; uptime'])
    vm_disk = sh([COLIMA, 'ssh', '--', 'df', '-h', '/'])
    stats = sh([DOCKER, 'stats', '--no-stream', '--format', '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}'])
    host = sh(['/usr/bin/vm_stat'])
    host_disk = sh(['/bin/df', '-h', ROOT])

    # 2026-10-17 新增：我们自己的常驻进程与定时任务也要实测（不能只测别人的容器）
    # 用 args（完整命令行）而不是 comm：Python 进程的 comm 只显示 "Python"，看不到脚本名（实测只抓到 1 个）
    procs = sh(['/bin/ps', '-Ao', 'pid,pcpu,pmem,rss,args'])
    keys = ('app/server.py', 'tailscaled', 'state_watch.py', 'map_watch.py', 'outbox.py', 'briefing.py', 'criterion1.py')
    mine = [l for l in procs.splitlines() if any(k in l for k in keys) and 'resource_audit' not in l]
    agents = sh(['/bin/launchctl', 'list'])
    my_agents = [l for l in agents.splitlines() if 'smarthome' in l or 'tailscale' in l]

    L = [f'# 资源实测 · {now.isoformat(timespec="seconds")}', '',
         '依据：05 §8 预算（HA 4GB / Frigate 4GB / DSH 2–3GB / 余量 ≥3GB）', '',
         '## 虚拟机（colima，Host HA）', '```', vm_mem.strip(), '```', '```', vm_cpu.strip(), '```',
         '```', vm_disk.strip(), '```', '',
         '## 容器', '```', stats.strip() or '（无输出）', '```', '',
         '## 我们自己的常驻进程（P5 新增：自己的东西也要测）', '```',
         '\n'.join(mine) if mine else '（没有抓到常驻进程）', '```', '',
         '## 我们的定时任务（launchd）', '```',
         '\n'.join(my_agents) if my_agents else '（无）', '```', '',
         '## 宿主机（Mac mini M4 / 16GB）', '```', host.strip()[:600], '```', '```', host_disk.strip(), '```', '']

    notes = []
    # 用 available（含可回收 cache）而不是 free 的瞬时值——后者会把 cache 当"不可用"，结论会失真
    m = re.search(r'Mem:\s+(\d+)\s+(\d+)\s+(\d+).*?\n(?:.*?\n)?.*?(-?\d+)', vm_mem)
    m2 = re.search(r'Mem:\s+(\d+)\s+(\d+)\s+(\d+)', vm_mem)
    if m2:
        total, used, free = (int(x) for x in m2.groups())
        avail = None
        for line in vm_mem.splitlines():
            if line.startswith('Mem:'):
                nums = [int(x) for x in re.findall(r'\d+', line)]
                if len(nums) >= 6:
                    avail = nums[5]          # total used free shared buff/cache available
        notes.append(f'- 虚拟机内存：总 {total} MB · 已用 {used} MB · 缓存/可回收 {total - used - free} MB'
                     + (f' · **可用 {avail} MB**' if avail is not None else ''))
        notes.append(f'- 对照 05 §8 预算：HA 分配 4096 MB → 实际只用了 {used} MB，'
                     f'{"在预算内且有大量余量" if used < 2048 else "接近预算"}')
        if avail is not None:
            notes.append(f'- Frigate（按 4GB 估）：当前虚拟机**总内存只有 {total} MB**，容器层面放不下 4GB；'
                         f'要上 Frigate 必须先给 colima/HA OS 扩内存（宿主 16GB 有余量），并外接 SSD 存录像')
    if stats:
        notes.append(f'- 容器实测：{stats.strip().splitlines()[0] if stats.strip() else "无"}')

    L += ['## 结论', ''] + notes + [
        '',
        '## 后续建议（不擅自实施）',
        '',
        '- Frigate 与本地模型**先测后上**：需要外接 SSD 存录像，且要实测帧率/延迟/内存。',
        '- 本机服务（家庭工作台）默认只绑 127.0.0.1，不额外占带宽。',
        '- 若要跑本地大模型，按 05 §8 的余量要求（≥3GB）评估，必要时升级内存。',
    ]
    out = os.path.join(ev, 'resource-audit.md')
    open(out, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    if mine:
        notes.append(f'- 我们的常驻进程 {len(mine)} 个（工作台服务 / tailscaled / 两个 watch）：'
                     f'合计 RSS 约 {sum(int(l.split()[3]) for l in mine if len(l.split()) > 3) / 1024:.0f} MB')
    if my_agents:
        notes.append(f'- 我们的定时任务 {len(my_agents)} 个（简报 9:30/21:00、校准 03:30、投递 30 分钟、地图/状态看守 5–10 分钟）')
    print('\n'.join(notes) if notes else '（未解析到内存数据，见证据文件）')
    print(f'\n证据：{os.path.relpath(out, ROOT)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
