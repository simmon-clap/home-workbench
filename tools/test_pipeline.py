#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端：功能设置 → 状态模型（**这条链才是用户能感知的那条**）

为什么专门做这个测试：2026-10-17 实测发现一个"假成功"——设置页/接口回"已改为 X"，
但 `app/state.py` 从来没有读过 settings.json，**改房间、手动录入设备全都不生效**，
直到我 grep 才发现。当时的测试全是"隔离测模块"或"看页面渲染"，正好绕过这条链。

本测试跑**真管线**（异步隔离子进程）：临时 settings.json + 临时输出路径 → 跑 app/state.py
→ 断言改房间/短名/阈值/手动录入都真的出现在状态模型里。生产数据一律不碰。

用法：python3 tools/test_pipeline.py      退出码 0 = 全过
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def main():
    tmp = tempfile.mkdtemp(prefix='pipeline-test-')
    settings_path = os.path.join(tmp, 'settings.json')
    state_out = os.path.join(tmp, 'state.json')

    base = json.load(open(os.path.join(ROOT, 'data', 'state.json'), encoding='utf-8'))
    dev = next((d for d in base['devices'] if not d['security_domain'] and d['room'] != '书房'), None)
    if not dev:
        check('找到可用于测试的设备', False); return 1
    target = '书房'

    json.dump({'version': 1,
               'overrides': {dev['name']: {'room': target, 'short_name': '端到端短名',
                                           'offline_threshold_s': 43200}},
               'devices': [{'name': '端到端占位设备', 'room': '阳台', 'short_name': '占位', 'by': 'test'}],
               'history': []},
              open(settings_path, 'w', encoding='utf-8'), ensure_ascii=False)

    env = dict(os.environ, SMART_HOME_SETTINGS=settings_path, SMART_HOME_STATE_OUT=state_out)
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'app', 'state.py')],
                       env=env, capture_output=True, text=True, timeout=240)
    check('状态模型可运行（隔离环境下）', r.returncode == 0, (r.stderr or '')[-200:])
    if r.returncode != 0:
        return 1
    out = json.load(open(state_out, encoding='utf-8'))
    got = next((d for d in out['devices'] if d['name'] == dev['name']), None)

    check('**改房间真的生效**（不是只回了个"已改"）', bool(got) and got['room'] == target,
          f"{got and got.get('room')}")
    check('房间来源标注 override', bool(got) and got.get('room_source') == 'override',
          f"{got and got.get('room_source')}")
    check('短名生效', bool(got) and got.get('short_name') == '端到端短名')
    check('离线阈值生效', bool(got) and got.get('offline_threshold_s') == 43200)
    check('房间分组跟着改', any(x['name'] == target and dev['name'] in (x.get('devices') or [])
                                for x in out.get('rooms') or []))
    man = next((d for d in out['devices'] if d['name'] == '端到端占位设备'), None)
    check('手动录入的设备出现在状态模型里', man is not None)
    check('手动设备标注来源 manual', bool(man) and man.get('room_source') == 'manual',
          f"{man and man.get('room_source')}")
    check('未改动的设备来源仍是米家',
          any(d.get('room_source') == 'miyun' for d in out['devices']))

    # 回滚到底值后，覆盖应被撤掉、来源回到米家（同一台设备再跑一次状态模型来验证）
    sp = json.load(open(settings_path, encoding='utf-8'))
    sp['overrides'].pop(dev['name'], None)                 # 相当于回滚到底值后的覆盖表
    json.dump(sp, open(settings_path, 'w', encoding='utf-8'), ensure_ascii=False)
    subprocess.run([sys.executable, os.path.join(ROOT, 'app', 'state.py')],
                   env=env, capture_output=True, text=True, timeout=240)
    out2 = json.load(open(state_out, encoding='utf-8'))
    got2 = next((d for d in out2['devices'] if d['name'] == dev['name']), None)
    check('撤掉覆盖后来源回到米家', bool(got2) and got2.get('room_source') == 'miyun',
          f"{got2 and got2.get('room_source')}")

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
