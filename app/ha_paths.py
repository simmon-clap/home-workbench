#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HA 配置目录的**唯一来源**（迁移后不用改代码，只改环境变量）

为什么要有这个文件：容器版里 HA 配置在 `config/homeassistant/`（绑定挂载），迁到 HA OS 后
它在虚拟机里（需要 Samba/SSH 插件或快照取出）。之前有 5 处各写各的路径，迁移时容易漏改一处
而**静默读到旧目录**（表现为"数据是旧的"却不报错）。所以统一到这里：

    SMART_HOME_HA_CONFIG  覆盖路径（不设则用默认的 config/homeassistant）

另外：验证集成是否在，**优先走官方 API**（`/api/config` 的 components 里就有自定义集成），
这样迁移后即使读不到目录也能核对（2026-10-17 实测：`smart_home_bridge`、`xiaomi_home` 都在）。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = os.path.join(ROOT, 'config', 'homeassistant')


def ha_config_dir():
    """当前 HA 配置目录（环境变量优先）。"""
    return os.environ.get('SMART_HOME_HA_CONFIG') or DEFAULT


def source():
    """这份路径是怎么来的（便于排查与如实报告）。"""
    return 'env:SMART_HOME_HA_CONFIG' if os.environ.get('SMART_HOME_HA_CONFIG') else 'default'


def storage_dir():
    return os.path.join(ha_config_dir(), '.storage')


def recorder_db():
    return os.path.join(ha_config_dir(), 'home-assistant_v2.db')


def custom_components():
    """自定义集成清单：**优先走 API**（迁移后目录读不到也能核对），失败再退回目录。"""
    api = components_via_api()
    if api is not None:
        return api, 'api'
    d = os.path.join(ha_config_dir(), 'custom_components')
    if os.path.isdir(d):
        return sorted(x for x in os.listdir(d) if not x.startswith('.')), 'dir'
    return [], 'none'


def components_via_api():
    """从 /api/config 取组件列表里的自定义集成（读不到返回 None，不假装空列表）。"""
    try:
        sys.path.insert(0, os.path.join(ROOT, 'app'))
        import ha
        import urllib.request
        req = urllib.request.Request(ha.BASE + '/api/config')
        req.add_header('Authorization', 'Bearer ' + ha.load_token())
        with urllib.request.urlopen(req, timeout=15) as resp:
            cfg = json.load(resp)
        comps = set(cfg.get('components') or [])
        known = [c for c in ('smart_home_bridge', 'xiaomi_home', 'homekit', 'matter') if c in comps]
        # 只返回"我们自己的"两个自定义集成，避免把内置集成算进来
        return [c for c in known if c in ('smart_home_bridge', 'xiaomi_home')]
    except Exception:  # noqa
        return None


if __name__ == '__main__':
    cc, how = custom_components()
    print(json.dumps({'config_dir': ha_config_dir(), 'source': source(),
                      'custom_components': cc, 'detected_via': how}, ensure_ascii=False, indent=1))
