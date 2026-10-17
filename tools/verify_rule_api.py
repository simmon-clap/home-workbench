#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
证据脚本：官方配置接口真能管自动化（建 → 回读 → 删，全程自清理）

为什么要有：迁移到 HA OS 后，规则只能通过官方接口落地（写本地文件 HA 读不到、且不报错）。
在迁移前先用**一次真实的建-读-删**证明这条路可用，比"应该能行"强得多。

安全性：
  · 建的自动化用**永不触发**的事件触发器（`smarthome_verify_never`），不会真去动设备
  · 无论中途成不成功，`finally` 里一定删掉
  · 不碰任何已有自动化（id 独占 `smarthome_verify_probe`）

用法：python3 tools/verify_rule_api.py
退出码：0 = 建读删全通且清理干净
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
import ha  # noqa: E402
import ha_ws  # noqa: E402

CONFIG_ID = 'smarthome_verify_probe'
ENTITY = f'automation.{CONFIG_ID}'
CONFIG = {
    'id': CONFIG_ID,
    'alias': '工作台自检（可安全删除）',
    'trigger': [{'platform': 'event', 'event_type': 'smarthome_verify_never'}],
    'action': [{'service': 'light.turn_off', 'target': {'entity_id': ['light.__verify_none__']}}],
}


def main():
    ok, fail = [], []
    cleaned = False

    def check(name, cond, detail=''):
        (ok if cond else fail).append(name)
        print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))

    try:
        check('官方配置接口可用', ha.config_available('automation'))
        saved, detail = ha.config_save('automation', CONFIG_ID, CONFIG)
        check('新建一条自动化（POST /api/config/automation/config/<id>）', saved, detail)

        # 实体 id 不是 CONFIG_ID：YAML 自动化的 entity_id 从 alias 派生（实测踩坑）
        import time as _t
        eid = ha.find_automation_entity(CONFIG_ID)
        if not eid:
            ha.call_service('automation', 'reload', blocking=False)
            for _ in range(8):
                _t.sleep(1)
                eid = ha.find_automation_entity(CONFIG_ID)
                if eid:
                    break
        check('能按 id 属性找到真实实体（不是写死的名字）', bool(eid), str(eid))
        got, state, cost = (ha.read_back(eid, expect='on', timeout=12) if eid
                            else (False, None, 0.0))
        check('HA 里能回读到这个实体（说明真生效了）', got, f'state={state} 用时 {cost:.1f}s')

        # 用 WS 读回原始配置：证明"HA 那边真的存下了我们写的内容"
        w = ha_ws.HaWs().connect()
        try:
            w.auth()
            raw = (w.query('automation/config', entity_id=eid) or {}).get('config') or {}
        finally:
            w.close()
        check('WS 读回原始配置，且 id 与我们写入的一致',
              str(raw.get('id')) == CONFIG_ID, str(raw.get('id')))

        deleted, dd = ha.config_delete('automation', CONFIG_ID)
        check('删除自动化', deleted, dd)
        try:
            ha.get_state(eid)
            still = True
        except Exception:  # noqa
            still = False
        check('删除后实体确实不在了（清理干净）', not still)
        cleaned = True
    finally:
        if not cleaned:
            print('  （自查未走完 → 兜底清理）')
            try:
                ha.config_delete('automation', CONFIG_ID)
                print('  ✅ 已兜底删除自检用的自动化')
            except Exception as err:  # noqa
                print(f'  ⚠️ 兜底清理失败，请手动删除 automations.yaml 里的 {CONFIG_ID}：{err}')

    print(f'\n结果：通过 {len(ok)} · 失败 {len(fail)}' + (f'　失败项 {fail}' if fail else '　全过'))
    print('结论：' + ('官方接口这条路可用 —— 迁移后规则功能不会断'
                    if not fail else '这条路有问题，迁移前必须先解决'))
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
