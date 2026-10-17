#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
长期维护测试（tools/maintain.py）

这两件事失效时都是**静默**的：日志涨满磁盘、磁盘满了却显示"正常"。所以重点测：
  ① 磁盘三档判定（正常/警戒/严重）边界正确
  ② 只有**超过阈值**的日志才轮转；轮转后保留最后 N 行，且**原文归档一份**（可回溯）
  ③ dry 模式**不改任何东西**
  ④ 归档清理只清临时/日志副本，**证据目录一律不动**
全程用临时目录，不碰生产日志。

用法：python3 tools/test_maintain.py      退出码 0 = 全过
"""
import importlib.util
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='maintain-test-')
spec = importlib.util.spec_from_file_location('mt', os.path.join(ROOT, 'tools', 'maintain.py'))
mt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mt)
mt.LOGS = os.path.join(TMP, 'logs')
mt.ARCHIVE = os.path.join(mt.LOGS, 'archive')
mt.STATE = os.path.join(TMP, 'maintenance.json')
os.makedirs(mt.ARCHIVE, exist_ok=True)

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def main():
    # ① 磁盘三档
    check('磁盘充足 → ok', mt.check_disk(50)['level'] == 'ok')
    check('余量 4GB → warn（低于警戒线 5GB）', mt.check_disk(4)['level'] == 'warn',
          mt.check_disk(4)['message'])
    check('余量 1GB → crit（随时可能写不进去）', mt.check_disk(1)['level'] == 'crit',
          mt.check_disk(1)['message'])
    check('严重档的措辞说清后果', '写不进去' in mt.check_disk(1)['message'])

    # ② 小日志不轮转
    small = os.path.join(mt.LOGS, 'small.log')
    open(small, 'w').write('x\n' * 100)
    r = mt.rotate_logs()
    check('低于阈值的日志不轮转', not r, str(r))

    # 大日志轮转
    big = os.path.join(mt.LOGS, 'big.log')
    with open(big, 'w') as f:
        for i in range(200000):
            f.write(f'line {i} ' + 'y' * 40 + '\n')
    size_before = os.path.getsize(big)
    r = mt.rotate_logs()
    check('超过阈值才轮转', len(r) == 1 and r[0]['file'] == 'big.log', str(r))
    lines_after = open(big, encoding='utf-8').read().splitlines()
    check('轮转后只保留最后 N 行', len(lines_after) == mt.LOG_KEEP_LINES, f'{len(lines_after)} 行')
    check('保留的是**最后**的行（不是开头）', lines_after[-1].startswith('line 199999'), lines_after[-1][:20])
    arch = [f for f in os.listdir(mt.ARCHIVE) if f.startswith('big.log')]
    check('原文归档一份（可回溯）', bool(arch), str(arch[:1]))
    check('轮转确实缩小了体积', os.path.getsize(big) < size_before,
          f'{size_before/1048576:.1f}MB → {os.path.getsize(big)/1048576:.2f}MB')

    # ③ dry 不动东西
    big2 = os.path.join(mt.LOGS, 'big2.log')
    with open(big2, 'w') as f:                       # 要**超过** 5MB 阈值才会进轮转分支
        f.write('z\n' * 3000000)
    n_before = len([f for f in os.listdir(mt.ARCHIVE) if f.startswith('big2')])
    r2 = mt.rotate_logs(dry=True)
    n_after = len([f for f in os.listdir(mt.ARCHIVE) if f.startswith('big2')])
    check('dry 模式不轮转、不归档', n_before == n_after and bool(r2), str(r2[:1]))

    # ④ 归档清理：只清临时/副本，且不碰 evidence
    ev = os.path.join(mt.LOGS, 'evidence', '20260101-P1')
    os.makedirs(ev, exist_ok=True)
    ev_file = os.path.join(ev, 'proof.md')
    open(ev_file, 'w').write('证据')
    old_tmp = os.path.join(mt.ARCHIVE, 'old.tmp')
    open(old_tmp, 'w').write('x')
    os.utime(old_tmp, (0, 0))                       # 设成很久以前
    removed = mt.prune_archive(keep_days=1)
    check('过期临时文件会被清理', 'old.tmp' in removed, str(removed))
    check('**证据目录一律不动**', os.path.exists(ev_file))
    check('清理范围不含 evidence 目录', not any('evidence' in r for r in removed))

    doc = mt.run()
    check('维护结果落盘（含策略与磁盘状态）',
          os.path.exists(mt.STATE) and 'disk' in doc and 'policy' in doc,
          f"disk={doc['disk']['level']} logs={doc['logs_mb']}MB")

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
