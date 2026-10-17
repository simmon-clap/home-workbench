#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
地图推送钩子测试（tools/map_watch.py）

为什么要测：这个钩子会在"设备推数据上来"时自动落盘。它最容易出的错是**谎报**——
首次运行就把早就有的数据说成"收到新推送"。所以重点测：
  ① 首次运行只建立基线，不报"新数据"
  ② 值发生变化才算出新数据，且要落盘
  ③ 同样的值不重复存
  ④ 全是 unknown（设备没推）时**如实说没有**，不营造"收到了"

全程用临时目录，不碰生产数据。

用法：python3 tools/test_mapwatch.py      退出码 0 = 全过
"""
import importlib.util
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUSH = tempfile.mkdtemp(prefix='mapwatch-test-')
os.environ['SMART_HOME_PUSH_DIR'] = PUSH
sys.path.insert(0, os.path.join(ROOT, 'app'))

spec = importlib.util.spec_from_file_location('mw', os.path.join(ROOT, 'tools', 'map_watch.py'))
mw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mw)
mw.PUSH = PUSH

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def snap(map_data=None, obj=None, multi=None):
    def cell(v):
        return {'state': v, 'attributes': {}, 'last_updated': 'x'}
    return {'map_data': cell(map_data if map_data is not None else 'unknown'),
            'object_name': cell(obj if obj is not None else 'unknown'),
            'multi_floor': cell(multi if multi is not None else 'unknown')}


def main():
    # ① 首次运行：有旧数据也不能叫"新推送"
    mw.snapshot = lambda: snap(multi='{"obj_name":"x"}')
    ok, path, new = mw.check_once(verbose=False)
    check('首次运行只建立基线，不谎报"收到新数据"', ok is False and not new, f'new={new}')
    check('没有落盘成 push 文件', not any(f.startswith('push-') for f in os.listdir(PUSH)))

    # ② 值变化 → 算出新数据并落盘
    mw.snapshot = lambda: snap(map_data='AAECAwQ=', multi='{"obj_name":"x"}')
    ok, path, new = mw.check_once(verbose=False)
    check('值变化时判定为"收到了"', ok is True and new.get('map_data') == 'AAECAwQ=')
    check('新数据落盘', path and os.path.exists(path), os.path.basename(path or ''))
    saved = json.load(open(path, encoding='utf-8'))
    check('落盘内容含原始快照（可追溯）', 'snapshot' in saved and 'new' in saved)

    # ③ 同样的值不重复存
    n_before = len([f for f in os.listdir(PUSH) if f.startswith('push-')])
    ok2, _, new2 = mw.check_once(verbose=False)
    n_after = len([f for f in os.listdir(PUSH) if f.startswith('push-')])
    check('同样的值不重复落盘', ok2 is False and n_after == n_before, f'{n_before} → {n_after}')

    # ④ 全是 unknown → 如实说没有
    mw.snapshot = lambda: snap()
    ok3, path3, new3 = mw.check_once(verbose=False)
    check('设备没推时如实报"没有新数据"', ok3 is False and not new3, str(new3))

    # ⑤ 部分 unknown 只报有值的那些
    mw.snapshot = lambda: snap(obj='2748266363/1037682406/9')
    ok4, _, new4 = mw.check_once(verbose=False)
    check('只有真的推了的那一项算新数据',
          ok4 is True and set(new4) == {'object_name'}, str(new4))

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
