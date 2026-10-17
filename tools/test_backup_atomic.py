#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
备份原子性 + 演练"坏包要说人话"的测试

2026-10-17 实测踩到的真问题：
  · 同一条时间线上 backup 与 restore_drill 同时跑 → 演练读到**半个备份包** →
    抛 `EOFError: Compressed file ended before the end-of-stream marker`（堆栈，人看不懂，
    而且会被误判成"备份坏了"）
  · 根因：`backup.sh` 直接写最终文件名，任何读者都可能看到半成品
  · 附带发现：我下载的 UTM 安装包（238MB）在项目里，被打进了备份（体积自检拦住）

现在：备份写临时文件 → 校验 → **原子改名**；演练**先验完整性**再说别的。

用法：python3 tools/test_backup_atomic.py      退出码 0 = 全过
"""
import glob
import importlib.util
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='backup-atomic-')
OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def main():
    sh = open(os.path.join(ROOT, 'tools', 'backup.sh'), encoding='utf-8').read()
    check('备份写临时文件（不是直接写最终名）', '.partial' in sh and 'TMP=' in sh)
    check('改名之前先校验完整性', "tar -tzf \"$TMP\"" in sh)
    check('用 mv 原子改名', 'mv -f "$TMP" "$OUT"' in sh)
    check('校验失败要丢弃、不污染 backups/', '已丢弃' in sh)
    check('排除可再下载的大件（installers / data/images）',
          "./installers" in sh and './data/images' in sh)

    # 真跑一次：无残留半成品，最新包完整，体积正常
    before = set(glob.glob(os.path.join(ROOT, 'backups', '*.partial*')))
    subprocess.run(['/bin/bash', os.path.join(ROOT, 'tools', 'backup.sh')],
                   capture_output=True, text=True, timeout=600)
    after = set(glob.glob(os.path.join(ROOT, 'backups', '*.partial*')))
    check('跑完不留半成品文件', before == after, str(sorted(after - before))[:80])
    newest = max(glob.glob(os.path.join(ROOT, 'backups', '*.tgz')), key=os.path.getmtime)
    r = subprocess.run(['tar', '-tzf', newest], capture_output=True, text=True)
    check('最新包完整性通过', r.returncode == 0, os.path.basename(newest))
    mb = os.path.getsize(newest) / 1048576
    check('体积在合理范围（<100MB，没把可再下载的大件打进去）', mb < 100, f'{mb:.1f} MB')

    # 演练遇到坏包：要给人话，不要堆栈
    spec = importlib.util.spec_from_file_location('rd', os.path.join(ROOT, 'tools', 'restore_drill.py'))
    rd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rd)
    bad_dir = os.path.join(TMP, 'backups')
    os.makedirs(bad_dir, exist_ok=True)
    src = open(newest, 'rb').read()
    open(os.path.join(bad_dir, 'smart-home-broken.tgz'), 'wb').write(src[:20000])  # 截断
    old = rd.BACKUPS
    try:
        rd.BACKUPS = bad_dir
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = rd.main()
        out = buf.getvalue()
    finally:
        rd.BACKUPS = old
    check('坏包时演练判失败（不继续解压）', code == 1, f'返回 {code}')
    check('坏包时给出人话而不是堆栈',
          '备份包不完整' in out and 'Traceback' not in out, out.strip().splitlines()[-1][:70] if out.strip() else '')
    check('坏包时提醒"别删旧备份"', '不要删旧备份' in out)

    # ── 保留策略：按天，不按份（2026-10-17 实测：一天跑十几次就把 14 份占满、挤掉历史）──
    import re as _re
    import tempfile as _tf
    d = _tf.mkdtemp(prefix='retention-', dir=os.path.expanduser('~'))
    try:
        # 20 个不同的天 + 最后一天 3 份（测"同一天只留最新"）
        names = [f'202610{d:02d}-0900' for d in range(1, 20)]
        names += ['20261020-0800', '20261020-1200', '20261020-1230']
        for n in names:
            open(os.path.join(d, f'smart-home-{n}.tgz'), 'wb').write(b'x' * 10)
        # 直接复用 backup.sh 里的保留脚本逻辑（同一段代码路径）
        import subprocess as _sp
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backup.sh')
        body = open(script, encoding='utf-8').read()
        m = _re.search(r"<<'PRUNE'\n(.*?)\nPRUNE", body, _re.S)
        code = _sp.run([sys.executable, '-', d], input=m.group(1), text=True,
                       capture_output=True)
        left = sorted(os.listdir(d))
        check('保留策略按天：同一天只留最新一份',
              'smart-home-20261020-1230.tgz' in left
              and not any(n.endswith(('-0800.tgz', '-1200.tgz')) for n in left),
              f'剩下 {len(left)} 份')
        check('保留策略按天：只留最近 14 天', len(left) == 14
              and 'smart-home-20261006-0900.tgz' not in left
              and 'smart-home-20261007-0900.tgz' in left,
              f'{len(left)} 份：{left[:2]}…{left[-1:]}')
    finally:
        import shutil as _sh
        _sh.rmtree(d, ignore_errors=True)

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
