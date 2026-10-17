#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
状态层数据来源测试（API vs 文件）

背景：迁到 HA OS 后，HA 的文件在虚拟机里、Mac 读不到，状态层必须能走**官方 API**。
本测试证明三件事：
  ① 两条路（API / 文件）产出的状态**一致**（设备、房间、摘要、待注意）
  ② `mode=api` 且 HA 连不上时**大声失败、不写出任何状态文件**（绝不许假成功）
  ③ `mode=auto` 且 HA 连不上时**文件兜底**，并在产物里**如实记录原因**

全程用独立输出文件，不碰生产 state.json。

用法：python3 tools/test_state_source.py      退出码 0 = 全过
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='state-source-test-')
OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def run(mode, out_name, base=None):
    out = os.path.join(TMP, out_name)
    env = dict(os.environ, SMART_HOME_STATE_SOURCE=mode, SMART_HOME_STATE_OUT=out)
    if base:
        env['HA_BASE_URL'] = base
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'app', 'state.py')],
                       env=env, capture_output=True, text=True, timeout=300)
    data = None
    if os.path.exists(out):
        try:
            data = json.load(open(out, encoding='utf-8'))
        except ValueError:
            data = None
    return r.returncode, data, (r.stderr or '')[-200:]


def main():
    rc_api, api, err_a = run('api', 'api.json')
    rc_fil, fil, err_f = run('files', 'files.json')
    check('两种模式都能跑通', rc_api == 0 and rc_fil == 0, f'api={rc_api} files={rc_fil} {err_a}')

    if api and fil:
        check('两条路的设备数一致', len(api['devices']) == len(fil['devices']),
              f"{len(fil['devices'])} vs {len(api['devices'])}")
        check('两条路的房间数一致', len(api['rooms']) == len(fil['rooms']))
        check('两条路的摘要一致', api['summary'] == fil['summary'],
              f"{api['summary'].get('online')} vs {fil['summary'].get('online')} 在线")
        check('两条路的待注意项数一致', len(api['attention']) == len(fil['attention']),
              f"{len(fil['attention'])} vs {len(api['attention'])}")
        ka = {d['name']: (d['state'], d['confidence'], d['room']) for d in api['devices']}
        kf = {d['name']: (d['state'], d['confidence'], d['room']) for d in fil['devices']}
        diff = [k for k in ka if ka.get(k) != kf.get(k)]
        check('逐台设备的状态/可信度/房间完全一致', not diff, f'不一致 {diff[:3]}' if diff else f'{len(ka)} 台全同')
        check('产物里记录了数据来源（可追溯）',
              api.get('data_source', {}).get('registries') == 'api' and api['data_source'].get('states') == 'api',
              json.dumps(api.get('data_source'), ensure_ascii=False)[:80])
        check('文件模式的来源也如实记录',
              fil.get('data_source', {}).get('registries') == 'files', str(fil.get('data_source')))
    else:
        check('两种模式都产出了状态', False, '缺少产物')

    # ② mode=api + HA 不通 → 大声失败，不写文件
    dead = 'http://127.0.0.1:59999'
    dead_out = os.path.join(TMP, 'dead.json')
    if os.path.exists(dead_out):
        os.remove(dead_out)
    rc, data, err = run('api', 'dead.json', base=dead)
    check('mode=api 且 HA 不通 → 非零退出', rc != 0, f'退出码 {rc}')
    check('mode=api 且 HA 不通 → **不写出状态文件**（没有假成功）',
          not os.path.exists(dead_out), '文件存在' if os.path.exists(dead_out) else '未写出')
    check('错误信息说清连不上', '连不上' in err or 'Connection refused' in err, err[-80:])

    # ③ mode=auto + HA 不通 → 文件兜底 + 如实记录原因
    rc2, auto, err2 = run('auto', 'auto.json', base=dead)
    check('mode=auto 且 HA 不通 → 文件兜底仍能出状态', rc2 == 0 and bool(auto),
          f'退出码 {rc2} 设备 {len((auto or {}).get("devices") or [])}')
    src = (auto or {}).get('data_source') or {}
    check('兜底时**如实记录**为什么没用 API',
          'files' in str(src.get('registries')) and 'API 不可用' in str(src.get('registries')),
          json.dumps(src, ensure_ascii=False)[:100])

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
