#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
场景结构化测试（03 §7 · 验收第 8 条）

规范要求：结构化场景必须**可见、可编辑、可停用、可回滚**，并能**自然语言复述**。
本测试逐条验证，且全部在隔离文件上跑（`SMART_HOME_SCENES` 指到临时文件），不碰生产数据。

用法：python3 tools/test_scenes.py      退出码 0 = 全过
"""
import importlib
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))

TMP = os.path.join(tempfile.mkdtemp(prefix='scenes-test-'), 'scenes.json')
os.environ['SMART_HOME_SCENES'] = TMP
import scenes as SC  # noqa: E402
importlib.reload(SC)

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def main():
    check('场景文件初始可读（默认 4 个场景）', len(SC.list_scenes()) >= 3, str(SC.summary()))

    # ① 可见：每个场景都能被人读懂
    v = SC.view()
    check('可见：每个场景都有复述', all(x['describe'] for x in v), str(v[0]['describe']))
    check('复述含动作与对象的人话', '关掉' in v[0]['describe'] or '拉开' in v[0]['describe'], v[0]['describe'])
    check('可见：给出步骤数与真实索引',
          all('index' in st for x in v for st in x['step_list']), str(v[0]['step_list'][:1]))

    # ② 可停用
    sid = v[0]['id']
    ok, msg = SC.set_enabled(sid, False)
    check('可停用', ok and not SC.get(sid)['enabled'], msg)
    ok, msg = SC.set_enabled(sid, True)
    check('可再启用', ok and SC.get(sid)['enabled'], msg)
    ok, msg = SC.set_enabled('不存在的场景', False)
    check('停用不存在的场景被拒', not ok, msg)

    # ③ 可编辑：加一步 / 删一步
    before = len(SC.get(sid)['steps'])
    ok, msg = SC.add_step(sid, 'turn_on', 'light', room='书房')
    check('可加一步', ok and len(SC.get(sid)['steps']) == before + 1, msg)
    check('加完的复述跟着变', '书房的灯打开' in SC.describe(SC.get(sid)), SC.describe(SC.get(sid)))
    ok, msg = SC.add_step(sid, 'turn_on', '不存在的类型')
    check('加不认识的类型被拒', not ok, msg)
    ok, msg = SC.add_step(sid, '炸开', 'light')
    check('加不支持的动作被拒', not ok, msg)
    ok, msg = SC.add_step(sid, 'lock', 'lock')
    check('安全域动作自动标成"只提醒"',
          ok and SC.get(sid)['steps'][-1].get('remind_only') is True, msg)
    ok, msg = SC.remove_step(sid, before)                  # 删掉刚加的 light 步
    check('可删一步', ok and len(SC.get(sid)['steps']) == before + 1, msg)
    ok, msg = SC.remove_step(sid, 999)
    check('删越界序号被拒', not ok, msg)

    # ④ 可回滚
    n_before = len(SC.get(sid)['steps'])
    SC.add_step(sid, 'turn_off', 'light', room='客厅')
    n_added = len(SC.get(sid)['steps'])
    ok, msg = SC.undo(sid)
    check('可回滚最近一次改动（加的一步被撤销）',
          ok and len(SC.get(sid)['steps']) == n_before == n_added - 1, msg)
    SC.set_enabled(sid, False)
    ok, msg = SC.undo(sid)
    check('可回滚停用（恢复启用）', ok and SC.get(sid)['enabled'] is True, msg)

    # ⑤ 与执行链共用同一份结构：解释器能读
    import intent as I
    steps = I.plan_steps({'kind': 'scene', 'scene': sid}, {'devices': []})
    check('场景结构与执行链兼容（可被解释器展开）', isinstance(steps, list), f'{len(steps)} 步')

    check('测试只写临时文件（不碰生产 scenes.json）',
          SC.SCENES == TMP and os.path.exists(TMP), SC.SCENES)

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
