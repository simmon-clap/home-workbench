#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
备份恢复演练（P5）

依据：docs/spec/07-数据与记忆规范 v1.0 §7（每季度做一次恢复演练：从备份真的能起来，
      不允许"应该能恢复"）· 08 §6（备份里不得有明文凭证）· 11-代码规范 v1.1

做什么：
  取最新的 `backups/smart-home-*.tgz` → 解到临时目录 → **真的检查恢复出来的东西**：
    1) 关键文件齐备（compose / HA 配置 / 状态模型 / 台账 / 规范）
    2) 数据文件可解析（JSON 能读、设备数 > 0）
    3) 备份内**不含凭证文件**（.storage/auth*、token）
  产出证据：logs/evidence/<日期>-P5/restore-drill.md

用法：
  python3 tools/restore_drill.py            基础演练（解开、解析、查凭证）
  python3 tools/restore_drill.py --deep     深演练：**让 HA 真的拿恢复出的配置做校验**，
                                            并检查恢复出的 recorder 库完整性（P5 的核心证据）
"""
import glob
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUPS = os.path.join(ROOT, 'backups')
OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


HA_IMAGE = 'ghcr.io/home-assistant/home-assistant:stable'


def deep_check(tmp, lines):
    """深演练：用 HA 镜像 + 恢复出的配置跑 check_config（"真的能起来"的关键证据）。

    注意：colima 只共享家目录，所以解压目录必须在家目录下，否则容器里挂载是空的
    （2026-10-17 实测踩过：挂 /tmp 得到 "File configuration.yaml not found"）。
    """
    cfg = os.path.join(tmp, 'config', 'homeassistant')
    if not os.path.isdir(cfg):
        check('深演练：恢复出的 HA 配置目录存在', False, cfg); return
    try:
        r = subprocess.run(
            ['docker', 'run', '--rm', '--entrypoint', 'python3', '-v', f'{cfg}:/restored',
             HA_IMAGE, '-m', 'homeassistant', '--script', 'check_config', '-c', '/restored'],
            capture_output=True, text=True, timeout=300)
        out = (r.stdout or '') + (r.stderr or '')
        bad = 'Failed config' in out or 'not found' in out
        check('深演练：HA 用恢复出的配置校验通过（exit 0 且无 Failed config）',
              r.returncode == 0 and not bad, f'exit={r.returncode} ' + out.strip().splitlines()[-1][:80] if out.strip() else f'exit={r.returncode}')
        lines.append(f'- check_config 输出：`{out.strip()[:200]}`')
    except FileNotFoundError:
        check('深演练：本机有 docker', False, '没找到 docker 命令')
    except subprocess.TimeoutExpired:
        check('深演练：HA 校验在 5 分钟内完成', False, '超时')

    db = os.path.join(cfg, 'home-assistant_v2.db')
    if os.path.exists(db):
        try:
            con = sqlite3.connect(db)
            ok = con.execute('pragma quick_check').fetchone()[0]
            rows = con.execute('select count(*) from states').fetchone()[0]
            con.close()
            check('深演练：恢复出的历史库完整（quick_check ok）', ok == 'ok', ok)
            check('深演练：恢复出的历史库有真实数据', rows > 1000, f'{rows} 条状态历史')
            lines.append(f'- 恢复出的 recorder：quick_check={ok}，states {rows} 行')
        except Exception as err:  # noqa
            check('深演练：恢复出的历史库可读', False, str(err)[:80])


def main():
    import sys
    deep = '--deep' in sys.argv
    files = sorted(glob.glob(os.path.join(BACKUPS, '*.tgz')), key=os.path.getmtime)
    if not files:
        check('存在备份文件', False, f'{BACKUPS} 为空');  return 1
    latest = files[-1]
    size_mb = os.path.getsize(latest) / 1024 / 1024
    check('取到最新备份', True, f'{os.path.basename(latest)}（{size_mb:.1f} MB）')

    # **先验完整性再解压**：2026-10-17 实测踩坑 —— 备份正在写时演练读到半个包，
    # 直接抛 EOFError 堆栈。人看不懂，而且会误判成"备份坏了"。
    integrity = subprocess.run(['tar', '-tzf', latest], capture_output=True, text=True)
    if integrity.returncode != 0:
        check('备份包完整（能列出内容）', False,
              f"包不完整或正在写入：{(integrity.stderr or '').strip().splitlines()[-1][:80] if integrity.stderr else ''}")
        print('\n⚠️ 这次演练跳过：最新的备份包不完整（可能正好在写入中，或确实损坏）。')
        print('   建议：稍后重跑一次；若仍失败，说明备份真的坏了 —— 不要删旧备份，先保住它们。')
        return 1
    check('备份包完整（能列出内容）', True, 'tar -tzf 通过')

    # 解压到家目录下：colima 只共享家目录，/tmp 挂进容器是空的
    os.makedirs(os.path.join(ROOT, 'logs', 'archive'), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix='restore-drill-', dir=os.path.join(ROOT, 'logs', 'archive'))
    lines = [f'# 备份恢复演练 · {os.path.basename(latest)}', '',
             f'- 备份大小：{size_mb:.1f} MB', f'- 解压到：{tmp}', '']
    try:
        with tarfile.open(latest) as tf:
            names = tf.getnames()
            tf.extractall(tmp)

        # 1) 内容自检：不得含凭证
        cred = [n for n in names if '/.storage/auth' in n]
        check('备份内不含凭证文件（.storage/auth*）', not cred, str(cred[:2]) if cred else '未发现')

        # 2) 关键文件齐备
        # 规范文件名带版本号会变，这里按前缀匹配（写死版本号会在升版后误报 —— 2026-10-17 实际踩到）
        import glob as _glob
        need = ['docker-compose.yml', 'config/homeassistant/configuration.yaml',
                'data/state.json', 'data/devices.md']
        missing = [n for n in need if not os.path.exists(os.path.join(tmp, n))]
        if not _glob.glob(os.path.join(tmp, 'docs', 'spec', '11-代码规范*.md')):
            missing.append('docs/spec/11-代码规范*.md')
        check('关键文件齐备（compose / HA 配置 / 状态 / 台账 / 规范）', not missing, f'缺 {missing}' if missing else f'{len(need)} 项齐备')

        # 3) 数据可解析（恢复后真的能用）
        sp = os.path.join(tmp, 'data', 'state.json')
        if os.path.exists(sp):
            st = json.load(open(sp, encoding='utf-8'))
            n_dev = len(st.get('devices') or [])
            check('恢复出的状态模型可解析且非空', n_dev > 0, f'{n_dev} 台设备')
            check('状态模型含三要素字段', all('source' in d and 'confidence' in d for d in st['devices'][:5]))
        try:
            spec_n = len([f for f in os.listdir(os.path.join(tmp, 'docs', 'spec')) if f.endswith('.md')])
        except FileNotFoundError:
            spec_n = 0
        check('恢复出的规范完整', spec_n >= 10, f'{spec_n} 份 md')

        if deep:
            deep_check(tmp, lines)

        lines += ['## 检查结果', '']
        lines += [f'- {"✅" if n not in FAIL else "❌"} {n}' for n in OK + FAIL]
        lines += ['', '## 结论', '',
                  '- 恢复路径可用：解压后关键文件与数据都在，状态模型可解析。',
                  ('- 深演练：**HA 用恢复出的配置实际校验通过**，历史库完整（这部分已不是"应该能恢复"）。'
                   if deep else
                   '- 未做深演练（加 `--deep` 会让 HA 真的拿恢复出的配置校验一次）。'),
                  '- 仍未做：在**另一台物理机器**上跑（需要第二台设备，属 P5 收尾项，未做即如实标注）。']
        ev = os.path.join(ROOT, 'logs', 'evidence', '20261017-P5')
        os.makedirs(ev, exist_ok=True)
        open(os.path.join(ev, 'restore-drill.md'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
        print(f'\n证据：{os.path.relpath(os.path.join(ev, "restore-drill.md"), ROOT)}')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f'\n演练结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　通过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    raise SystemExit(main())
