#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
24 小时在线就绪检查（P5 加固 / 判据 1 的物理前提）

为什么要有：判据 1「一整天不用打开米家」要求这套东西**整天都在**。而"整天在"取决于几件
物理前提：机器不能睡、断电要能自己回来、重启后要自动登录（否则用户级自启项不会跑）、
各服务要能自己起。这些条件一旦被打破，表现是"页面打不开"——**不会报错，只会静默失效**。

检查项（每条都给"谁来改"）：
  ① 系统睡眠          （sleep = 0 才算通过）
  ② 断电恢复自动开机  （autorestart = 1）
  ③ 重启后自动登录    （否则 ~/Library/LaunchAgents 全部不会启动）
  ④ 网络唤醒          （womp = 1）
  ⑤ 自启覆盖          （清单里的常驻服务与定时任务都有对应驱动）
  ⑥ 风险提示          （自动安装系统更新 = 会在夜里自己重启；网络靠 Wi-Fi = 抖动会掉线）

用法：
  python3 tools/uptime_check.py           # 人看的结论
  python3 tools/uptime_check.py --json    # 机器读
退出码：0 = 就绪；1 = 有阻塞项
"""
import argparse
import json
import os
import plistlib
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
AGENTS = os.path.expanduser('~/Library/LaunchAgents')

# 需要 sudo 才能改的项，明确标注"谁来改"，免得用户以为我能自己搞定
WHO = {'me': '我来做', 'you': '需要你（要密码或点一下）'}


def sh(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout)
        return (r.stdout or '') + (r.stderr or '')
    except Exception as err:  # noqa
        return f'<失败：{err}>'


def pmset_value(key, pmset_out=None):
    text = pmset_out if pmset_out is not None else sh(['pmset', '-g'])
    # 注意：pmset 输出的行**首有空格**（" sleep   0"），行首锚定会匹配不到 —— 实测踩过
    m = re.search(rf'(?m)^\s*{re.escape(key)}\s+(\S+)', text)
    return m.group(1) if m else None


def auto_login_user(loginwindow_out=None):
    text = loginwindow_out if loginwindow_out is not None else sh(
        ['defaults', 'read', '/Library/Preferences/com.apple.loginwindow'])
    m = re.search(r'autoLoginUser\s*=\s*"?([^";\s]+)"?', text)
    return m.group(1) if m else None


def auto_install_updates(swupdate_out=None):
    text = swupdate_out if swupdate_out is not None else sh(
        ['defaults', 'read', '/Library/Preferences/com.apple.SoftwareUpdate.plist'])
    m = re.search(r'AutomaticallyInstallMacOSUpdates\s*=\s*(\d)', text)
    return m.group(1) == '1' if m else None


def primary_network():
    """当前默认路由走哪个接口、是不是 Wi-Fi。"""
    out = sh(['route', '-n', 'get', 'default'])
    iface = None
    m = re.search(r'interface:\s*(\S+)', out)
    if m:
        iface = m.group(1)
    is_wifi = False
    if iface:
        info = sh(['networksetup', '-listallhardwareports'])
        m2 = re.search(rf'Hardware Port: (Wi-Fi|AirPort)\nDevice: {re.escape(iface)}', info)
        is_wifi = bool(m2)
    return {'interface': iface, 'is_wifi': is_wifi}


def autostart_coverage(manifest):
    """清单里的常驻服务与定时任务，是否都有对应的 LaunchAgent。"""
    missing = []
    for j in (manifest.get('jobs') or []):
        if not os.path.exists(os.path.join(AGENTS, j['agent'] + '.plist')):
            missing.append(j['id'])
    for s in (manifest.get('services') or []):
        agent = s.get('agent') or ''
        if agent.startswith('('):
            continue
        if not os.path.exists(os.path.join(AGENTS, agent + '.plist')):
            missing.append(s['id'])
    return missing


def check(sleep=None, autorestart=None, womp=None, login_user='__live__', autoupdate='__live__',
          manifest=None, net=None):
    """纯逻辑版：可注入参数做测试。返回 (是否就绪, 明细)。"""
    if sleep is None:
        sleep = pmset_value('sleep')
    if autorestart is None:
        autorestart = pmset_value('autorestart')
    if womp is None:
        womp = pmset_value('womp')
    if login_user == '__live__':
        login_user = auto_login_user()
    if autoupdate == '__live__':
        autoupdate = auto_install_updates()
    if manifest is None:
        try:
            manifest = json.load(open(os.path.join(DATA, 'automation-manifest.json'), encoding='utf-8'))
        except (FileNotFoundError, ValueError):
            manifest = {}
    if net is None:
        net = primary_network()

    items, blockers = [], []

    def add(name, ok, detail, who=None, fix=None, blocker=True):
        items.append({'item': name, 'ok': bool(ok), 'detail': detail, 'who': who, 'fix': fix})
        if not ok and blocker:
            blockers.append(name)

    add('系统睡眠已禁用', sleep == '0', f'sleep = {sleep}',
        WHO['you'] if sleep != '0' else None,
        'sudo pmset -a sleep 0（要密码）')
    add('断电恢复后自动开机', autorestart == '1', f'autorestart = {autorestart}',
        WHO['you'] if autorestart != '1' else None,
        'sudo pmset -a autorestart 1（要密码）')
    add('重启后自动登录（用户级自启的前提）', bool(login_user), f'autoLoginUser = {login_user or "未配置"}',
        WHO['you'] if not login_user else None,
        '系统设置 → 用户与群组 → 自动登录（要密码）')
    add('网络唤醒', womp == '1', f'womp = {womp}', None, None, blocker=False)

    missing = autostart_coverage(manifest)
    add('自启覆盖（清单里的服务与任务）', not missing,
        f'{len(manifest.get("jobs") or [])} 个任务 + {len(manifest.get("services") or [])} 个服务'
        + (f'，缺 {missing}' if missing else '，全部有驱动'),
        WHO['me'] if missing else None, '补对应 LaunchAgent', blocker=True)

    # 风险提示（不算阻塞，但必须说出来）
    warns = []
    if autoupdate:
        warns.append({'item': '系统自动安装更新已开', 'who': WHO['you'],
                      'detail': '夜里可能自动装 macOS 更新并重启（会中断几分钟到十几分钟）',
                      'fix': '系统设置 → 通用 → 软件更新 → 关闭"自动安装 macOS 更新"'})
    if net and net.get('is_wifi'):
        warns.append({'item': '主网络是 Wi-Fi', 'who': WHO['you'] if False else '你定',
                      'detail': f"当前走 {net.get('interface')}（Wi-Fi）：抖动会让云端设备掉线",
                      'fix': '插网线（en0 空着）会更稳；不插也能跑'})
    return (not blockers), {'items': items, 'warnings': warns, 'blockers': blockers,
                            'network': net, 'auto_update': autoupdate}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    ok, res = check()
    if a.json:
        print(json.dumps({'ready': ok, **res}, ensure_ascii=False, indent=1))
        return 0 if ok else 1
    print('=== 24 小时在线就绪检查 ===')
    for it in res['items']:
        print(('✅ ' if it['ok'] else '❌ ') + it['item'] + f"  —— {it['detail']}")
        if not it['ok'] and it.get('fix'):
            print(f"     → {it['who'] or '你'}：{it['fix']}")
    if res['warnings']:
        print('\n⚠️  风险提示（不阻塞，但要知道）')
        for w in res['warnings']:
            print(f"  · {w['item']}（{w['who']}）：{w['detail']}")
            print(f"    → {w['fix']}")
    print('\n结论：' + ('**就绪**（满足 24 小时在线的物理前提）' if ok
                      else f'有 {len(res["blockers"])} 项阻塞：{res["blockers"]}'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
