#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
外部改动入账测试（tools/state_watch.py）

这件事的诚实性风险很高：把"我们做的"说成"外部改的"、或反过来，
都会让状态证据链变成假话。所以重点测：
  ① 首次运行只建立基线（不把早已存在的差异说成"外部改动"）
  ② 有我方动作记录 → self；没有 → external
  ③ 没变化的设备不产生记录
  ④ 记录里必须带证据（evidence）与前后值
全程写临时文件，不碰生产数据。

用法：python3 tools/test_statewatch.py      退出码 0 = 全过
"""
import importlib.util
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='statewatch-test-')
os.environ['SMART_HOME_CHANGES'] = os.path.join(TMP, 'changes.jsonl')
os.environ['SMART_HOME_SNAPDIR'] = os.path.join(TMP, 'snap')
sys.path.insert(0, os.path.join(ROOT, 'app'))
spec = importlib.util.spec_from_file_location('sw', os.path.join(ROOT, 'tools', 'state_watch.py'))
sw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sw)

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def main():
    base = sw.snapshot()
    dev = next(iter(base))
    other = list(base)[1]

    ch, n = sw.check_once(verbose=False)
    check('首次运行只建立基线（不产生"外部改动"）', not ch, f'{n} 条')
    check('基线文件已写入', os.path.exists(os.path.join(sw.SNAPDIR, 'last.json')))

    # 无我方记录 → 外部
    sw.snapshot = lambda state=None: {**base, dev: {**base[dev], 'state': 'off'}}
    ch, _ = sw.check_once(verbose=False)
    check('没有我方动作痕迹 → 判为外部改动',
          len(ch) == 1 and ch[0]['source'] == 'external' and ch[0]['device'] == dev,
          json.dumps(ch[0], ensure_ascii=False)[:100] if ch else '无')
    check('外部判定带证据说明', bool(ch and ch[0].get('evidence')), ch[0].get('evidence', '')[:40])

    # 有我方记录 → self
    sw.snapshot = lambda state=None: {**base, dev: {**base[dev], 'state': 'on'}}
    sw.self_actions = lambda window_min=10, now=None: {dev: '我方动作（审计 测试）'}
    ch, _ = sw.check_once(verbose=False)
    check('有我方动作痕迹 → 判为我方执行',
          len(ch) == 1 and ch[0]['source'] == 'self', json.dumps(ch[0], ensure_ascii=False)[:100] if ch else '无')

    # 没变化 → 不记录
    ch, _ = sw.check_once(verbose=False)
    check('状态没变 → 不产生任何记录', not ch, f'{len(ch)} 条')

    # 多台同时变
    sw.snapshot = lambda state=None: {**base, dev: {**base[dev], 'state': 'off'},
                                      other: {**base[other], 'state': 'off'}}
    sw.self_actions = lambda window_min=10, now=None: {}
    ch, _ = sw.check_once(verbose=False)
    check('多台同时变化都记账', len(ch) == 2, f'{len(ch)} 条')

    rows = sw.recent(10)
    check('记录含前后值与时间', all({'at', 'from', 'to', 'source'} <= set(r) for r in rows), f'{len(rows)} 条')
    sm = sw.summary()
    check('汇总区分我方/外部', 'self' in sm and 'external' in sm, str(sm))
    check('按设备可查', len(sw.for_device(dev, 5)) >= 1, f'{dev} 有记录')

    check('测试只写临时文件（不碰生产数据）',
          sw.CHANGES.startswith(TMP) and sw.SNAPDIR.startswith(TMP), sw.CHANGES)

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
