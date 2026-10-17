#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
迁移前的"开始前体检"（一条命令给 GO / NO-GO）

为什么要有：迁移那天要跑七八项检查，人在紧张时最怕漏一项。把它们合成一条命令，
输出一张表 + 一个结论；任何一项不达标就 **NO-GO**（宁可不开始，也不半途出事）。

检查项：
  1. 最新备份新鲜且体积正常（回滚的底牌）
  2. 迁移基线在（迁移后要逐条比对）
  3. `migrate_check --pre` 全过（HA 版本 / 设备数 / 集成 / API 路径 / 磁盘）
  4. `uptime_check`（24h 物理前提：不睡 / 断电自启 / 自动登录 / 自启覆盖）
  5. `vm_autostart --check`（虚拟机自启机制就绪或"迁移前正常"）
  6. `homekit_config --check`（安全域不进的机械保证）
  7. 物料齐（HA OS 镜像 / UTM 安装包 / 迁移执行单 / 白名单）
  8. 全规范门禁（默认跑；`--quick` 跳过，用于应急快速判断）

用法：
  python3 tools/preflight.py            # 完整体检（含门禁，约几分钟）
  python3 tools/preflight.py --quick    # 跳过门禁，其余照跑
  python3 tools/preflight.py --json
退出码：0 = GO；1 = NO-GO
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, 'tools')
DATA = os.path.join(ROOT, 'data')
INSTALLERS = os.environ.get('SMART_HOME_INSTALLERS') or os.path.join(ROOT, 'installers')


def run_py(script, *args, timeout=600):
    try:
        r = subprocess.run([sys.executable, os.path.join(TOOLS, script), *args],
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or '') + (r.stderr or '')
    except Exception as err:  # noqa
        return 99, str(err)[:120]


def tail(text, n=1):
    lines = [ln for ln in (text or '').strip().splitlines() if ln.strip()]
    return lines[-n] if lines else ''


def check_backup(max_age_h=26, backups_dir=None):
    files = sorted(glob.glob(os.path.join(backups_dir or os.path.join(ROOT, 'backups'), '*.tgz')),
                   key=os.path.getmtime)
    if not files:
        return False, '没有备份'
    newest = files[-1]
    age_h = (time.time() - os.path.getmtime(newest)) / 3600
    size_mb = os.path.getsize(newest) / 1048576
    ok = age_h <= max_age_h and 1 < size_mb < 100        # 体积自检：太小可疑、太大说明漏了排除
    return ok, f'{os.path.basename(newest)}（{age_h:.1f} 小时前 · {size_mb:.0f} MB）'


def check_baseline(data_dir=None):
    p = os.path.join(data_dir or DATA, 'migration-baseline.json')
    if not os.path.exists(p):
        return False, '缺 data/migration-baseline.json（先跑 migrate_check.py --pre）'
    try:
        d = json.load(open(p, encoding='utf-8'))
    except ValueError:
        return False, '基线解析失败'
    # 基线里存的是**数字**（devices=64、rooms=10），不是列表 —— 第一版按 len() 写，实测报错
    return True, (f"HA {d.get('ha_version')} · {d.get('devices')} 台设备 · {d.get('rooms')} 个房间 · "
                  f"{d.get('entity_count')} 个实体 · 基线时间 {str(d.get('at'))[:16]}")


def check_migrate_pre():
    rc, out = run_py('migrate_check.py', '--pre')
    return rc == 0, tail(out) or f'退出码 {rc}'


def check_uptime():
    rc, out = run_py('uptime_check.py', timeout=120)
    return rc == 0, tail(out)


def check_vm():
    rc, out = run_py('vm_autostart.py', '--check', timeout=120)
    return rc == 0, tail(out)


def check_homekit():
    rc, out = run_py('homekit_config.py', '--check', timeout=120)
    return rc == 0, tail(out)


def check_materials(data_dir=None, installers=None):
    data_dir = data_dir or DATA
    installers = installers or INSTALLERS
    need = [('HA OS 镜像', os.path.join(data_dir, 'images', 'haos_generic-aarch64-18.3.qcow2.xz')),
            ('UTM 安装包', None),                                  # 通配
            ('迁移执行单', os.path.join(data_dir, '迁移执行单-20261017.md')),
            ('HomeKit 白名单', os.path.join(data_dir, 'homekit-exposure.json')),
            ('HomeKit 配置', os.path.join(data_dir, 'homekit-config.yaml'))]
    missing = []
    for label, path in need:
        if path is None:
            if not glob.glob(os.path.join(installers, 'UTM*.dmg')):
                missing.append(label)
        elif not os.path.exists(path):
            missing.append(label)
    return (not missing), ('齐备' if not missing else '缺 ' + '、'.join(missing))


def check_image_integrity():
    rc, out = run_py('verify_image.py', timeout=900)
    return rc == 0, tail(out)


def check_ha_calls():
    rc, out = run_py('audit_ha_calls.py', timeout=300)
    return rc == 0, tail(out)


def check_gate():
    rc, out = run_py('gate.py', timeout=1800)
    return rc == 0, tail(out) or f'退出码 {rc}'


def run_all(quick=False):
    checks = [('备份新鲜且体积正常', check_backup),
              ('迁移基线在', check_baseline),
              ('迁移预检（migrate_check --pre）', check_migrate_pre),
              ('24h 在线前提（uptime_check）', check_uptime),
              ('虚拟机自启机制', check_vm),
              ('HomeKit 配置自检', check_homekit),
              ('迁移物料齐备', check_materials),
              ('镜像与安装包校验（与官方逐字节比对 + qcow2 头）', check_image_integrity),
              ('HA 调用审计（服务/命令/接口都存在）', check_ha_calls)]
    if not quick:
        checks.append(('全规范门禁（gate.py）', check_gate))
    results = []
    for name, fn in checks:
        try:
            ok, detail = fn()
        except Exception as err:  # noqa
            ok, detail = False, f'检查本身出错：{err}'
        results.append({'check': name, 'ok': bool(ok), 'detail': detail})
    return {'go': all(r['ok'] for r in results), 'quick': quick, 'results': results}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    res = run_all(quick=a.quick)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res['go'] else 1
    print('=== 迁移开始前体检' + ('（快速：跳过门禁）' if a.quick else '') + ' ===')
    for r in res['results']:
        print(('✅ ' if r['ok'] else '❌ ') + r['check'] + f"  —— {r['detail']}")
    print()
    print('结论：' + ('**GO** —— 可以开始迁移' if res['go']
                    else '**NO-GO** —— 先解决上面 ❌ 的项，别带着问题开始'))
    return 0 if res['go'] else 1


if __name__ == '__main__':
    sys.exit(main())
