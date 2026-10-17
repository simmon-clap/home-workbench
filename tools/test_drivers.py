#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
周期性能力驱动测试（tools/test_drivers.py）

这个项目反复出现同一类缺口："功能写了、没人驱动它"——状态不刷新、通知不投递、备份不执行。
它们**不会报错**，只会静悄悄地不干活。所以这里机械地查三件事：
  ① 清单里的每一项，脚本真的存在
  ② 每一项都有一个 LaunchAgent，且该 plist 真的在跑那个脚本
  ③ 每一项的日志存在（说明它至少真跑过一次）；并报告日志新鲜度（超过 2×间隔就提醒）

用法：python3 tools/test_drivers.py      退出码 0 = 全过
"""
import json
import os
import plistlib
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
AGENTS = os.path.expanduser('~/Library/LaunchAgents')
OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def main():
    path = os.path.join(DATA, 'automation-manifest.json')
    check('存在周期性能力清单', os.path.exists(path), path)
    if not os.path.exists(path):
        return 1
    m = json.load(open(path, encoding='utf-8'))
    jobs = m.get('jobs') or []
    check('清单非空', bool(jobs), f'{len(jobs)} 项')
    ids = [j.get('id') for j in jobs]
    check('清单里没有重复 id', len(ids) == len(set(ids)))

    missing_script, missing_agent, not_running, no_log = [], [], [], []
    for j in jobs:
        sp = os.path.join(ROOT, j['script'])
        if not os.path.exists(sp):
            missing_script.append(j['id'])
        ap = os.path.join(AGENTS, j['agent'] + '.plist')
        if not os.path.exists(ap):
            missing_agent.append(j['id'])
            continue
        d = plistlib.load(open(ap, 'rb'))
        args = ' '.join(d.get('ProgramArguments') or [])
        if os.path.basename(j['script']) not in args:
            not_running.append(f"{j['id']}→{j['agent']}")
        # 日志存在 = 至少真跑过一次。**直接读 plist 里的 StandardOutPath**（靠猜文件名会误判）
        out_path = d.get('StandardOutPath')
        if not (out_path and os.path.exists(out_path)):
            no_log.append(j['id'])

    check('每一项的脚本都存在', not missing_script, str(missing_script))
    check('每一项都有 LaunchAgent', not missing_agent, str(missing_agent))
    check('每个 LaunchAgent 真的在跑对应脚本', not not_running, str(not_running))
    check('每一项都留下过运行日志（至少跑过一次）', not no_log, str(no_log))

    # 新鲜度：间隔型任务超过 2× 间隔没日志就提醒（只报告，不判失败，避免偶发抖动）
    stale = []
    for j in jobs:
        si = j.get('interval_seconds')
        if not si:
            continue
        ap = os.path.join(AGENTS, j['agent'] + '.plist')
        if not os.path.exists(ap):
            continue
        out_path = plistlib.load(open(ap, 'rb')).get('StandardOutPath')
        if not (out_path and os.path.exists(out_path)):
            continue
        newest = os.path.getmtime(out_path)
        if time.time() - newest > si * 2:
            stale.append(f"{j['id']}（{(time.time() - newest) / 60:.0f} 分钟没动静）")
    if stale:
        print(f'⚠️  可能没在跑：{"、".join(stale)}')
    else:
        print('✅ 间隔型任务日志都新鲜')

    # ── 常驻服务（开机自启 + 崩了会回来）──
    svcs = m.get('services') or []
    check('清单里有常驻服务段', bool(svcs), f'{len(svcs)} 个')
    svc_bad, not_running_now = [], []
    for svc in svcs:
        agent = svc.get('agent') or ''
        if agent.startswith('('):
            continue
        ap = os.path.join(AGENTS, agent + '.plist')
        if not os.path.exists(ap):
            svc_bad.append(svc['id'])
            continue
        d = plistlib.load(open(ap, 'rb'))
        if svc.get('keep_alive') and not d.get('KeepAlive'):
            svc_bad.append(f"{svc['id']}(无KeepAlive)")
        # 现在真的在跑吗？（工作台/tailscaled 这两项可以直接查进程）
        if svc['id'] == 'workbench-server':
            import subprocess as _sp
            out = _sp.run(['/bin/ps', '-Ao', 'args'], capture_output=True, text=True).stdout
            if 'app/server.py' not in out:
                not_running_now.append('workbench-server')
    check('常驻服务都有自启且配了 KeepAlive', not svc_bad, str(svc_bad))
    check('工作台服务此刻真在跑（不是只配了没起）', not not_running_now, str(not_running_now))

    check('清单记录了每项的频率与依据', all(j.get('cadence') and j.get('spec') for j in jobs))
    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    raise SystemExit(main())
