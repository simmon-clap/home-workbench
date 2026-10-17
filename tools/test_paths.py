#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HA 配置路径统一来源测试（app/ha_paths.py）

为什么重要：迁移时最容易犯的错不是"改错了"，而是**有一处忘了改** —— 于是静默读到旧目录，
表现为"数据是旧的"却不报错。所以这里钉三件事：
  ① 默认路径不变（迁移前行为完全一致）
  ② 环境变量能整体切换（state / rules / 状态层都跟着走）
  ③ 自定义集成核对**优先走官方 API**（迁移后目录读不到也能验），且读不到时如实返回，不假装空列表
  ④ 代码里不再有各写各的 `config/homeassistant`（除解析器本身与 shell 脚本）

用法：python3 tools/test_paths.py      退出码 0 = 全过
"""
import importlib.util
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def fresh(env_value='__unset__'):
    """按指定的环境变量重新导入模块（避免模块缓存干扰）。"""
    for m in ('ha_paths', 'state', 'rules'):
        sys.modules.pop(m, None)
    if env_value == '__unset__':
        os.environ.pop('SMART_HOME_HA_CONFIG', None)
    else:
        os.environ['SMART_HOME_HA_CONFIG'] = env_value
    import ha_paths
    return ha_paths


def main():
    hp = fresh()
    check('默认路径就是 config/homeassistant', hp.ha_config_dir() == os.path.join(ROOT, 'config', 'homeassistant'),
          hp.ha_config_dir())
    check('默认来源标注为 default', hp.source() == 'default')
    check('storage / recorder 路径跟着走',
          hp.storage_dir().endswith('.storage') and hp.recorder_db().endswith('home-assistant_v2.db'))

    hp2 = fresh('/tmp/别的地方-ha')
    check('环境变量能整体切换', hp2.ha_config_dir() == '/tmp/别的地方-ha', hp2.ha_config_dir())
    check('切换后来源标注为 env', hp2.source() == 'env:SMART_HOME_HA_CONFIG')
    import state, rules
    check('状态层跟着环境变量走（迁移时不用改代码）', state.HA == '/tmp/别的地方-ha', state.HA)
    check('规则落点跟着环境变量走', rules.HA_CONFIG == '/tmp/别的地方-ha', rules.HA_CONFIG)

    hp3 = fresh()
    cc, how = hp3.custom_components()
    check('自定义集成核对得到', bool(cc), f'{cc}（via {how}）')
    check('优先走官方 API（迁移后目录读不到也能验）', how == 'api', how)
    check('核对里包含我们的两个集成',
          all(x in cc for x in ('smart_home_bridge', 'xiaomi_home')), str(cc))

    # 读不到 API 时如实返回（不假装空列表）
    # 注意：app/ha.py 的 BASE 是**导入时**固化的常量，改环境变量没用 —— 直接改常量（实测踩过）
    import ha
    saved_base = ha.BASE
    ha.BASE = 'http://127.0.0.1:59999'
    try:
        api_none = hp3.components_via_api()
    finally:
        ha.BASE = saved_base
    check('API 读不到时返回 None（不假装"没有自定义集成"）', api_none is None, str(api_none))

    # ④ 不再有各写各的路径
    # 判定收紧为"**真的在构造路径**"：只抓 os.path.join 里同时出现 config 与 homeassistant 的写法。
    # 文档字符串、warn() 文案里提到路径是正常的，不该算违规（第一版误报过）
    offenders = []
    pattern = re.compile(r"os\.path\.join\([^)]*['\"]config['\"][^)]*['\"]homeassistant['\"]")
    for path in ('app/state.py', 'app/server.py', 'app/rules.py', 'tools/gatechecks.py',
                 'tools/migrate_check.py'):
        src = open(os.path.join(ROOT, path), encoding='utf-8').read()
        for ln, line in enumerate(src.splitlines(), 1):
            if pattern.search(line):
                offenders.append(f'{path}:{ln}')
    check('除解析器外没有各写各的 config 路径', not offenders, str(offenders))

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
