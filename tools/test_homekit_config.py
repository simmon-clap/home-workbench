#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HomeKit 桥配置生成测试（tools/homekit_config.py）

红线是"**安全域永不进苹果侧**"（宪章第六条 + 05 v1.1 §9-2 + 08 v1.2 §7）。所以测试的重点不是
"配置长得对不对"，而是：
  ① 白名单里**混进任何非 A 类**都必须直接抛错（宁可不生成）
  ② 生成结果里**绝不能出现**门锁/摄像头/报警面板实体
  ③ 只读安全读数（烟感/水浸/燃气）要在 include 里，但**不能出现在可控制列表**
  ④ 有 exclude_domains 兜底；输出稳定（两次生成一致）

用法：python3 tools/test_homekit_config.py      退出码 0 = 全过
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('hk', os.path.join(ROOT, 'tools', 'homekit_config.py'))
hk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hk)

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def main():
    doc = hk.load()
    text = hk.build_yaml(doc)
    problems, info = hk.check(doc)
    check('真白名单能生成且自检通过', not problems, str(problems))
    check('可控制与只读数量与白名单一致', info['total'] == len(doc['include']),
          f"进桥 {info['total']} = 可控 {info['writable']} + 只读 {info['readonly']} / 白名单 {len(doc['include'])}")

    # ② 安全域永不出现
    banned_domains = ('lock.', 'camera.', 'alarm_control_panel.')
    leaked = [ln.strip() for ln in text.splitlines()
              if ln.strip().startswith('- ') and any(ln.strip()[2:].startswith(d) for d in banned_domains)]
    check('生成的 include 里没有门锁/摄像头/报警面板实体', not leaked, str(leaked[:3]))
    banned_names = [e['device'] for e in (doc.get('exclude') or []) if e.get('device')]
    name_leak = [n for n in banned_names if n and f'# {n}' in text]
    check('被排除设备没有以注释以外的形式混进配置', not name_leak, str(name_leak[:3]))

    # ③ 只读读数：在 include 里、不在可控制列表
    writable, readonly = hk.select(doc)
    check('存在只读安全读数（烟感/水浸/燃气）', len(readonly) >= 3, f'{len(readonly)} 个')
    rids = {e['entity_id'] for e in readonly}
    wids = {e['entity_id'] for e in writable}
    check('只读读数的实体在 include_entities 里', all(e in text for e in rids), str(sorted(rids)[:1]))
    check('只读读数**不在**可控制列表里', not (rids & wids), str(sorted(rids & wids)))
    check('只读读数被当作传感器（domain 是 sensor/binary_sensor）',
          all(e['domain'] in ('sensor', 'binary_sensor') for e in readonly),
          str(sorted({e['domain'] for e in readonly})))

    # ① 混进非 A 类必须抛错
    poisoned = dict(doc)
    poisoned['include'] = list(doc['include']) + [{'device': '坏门锁', 'entity_id': 'lock.bad', 'class': 'C'}]
    try:
        hk.build_yaml(poisoned)
        check('白名单混进 C 类时**直接抛错**（宁可不生成）', False, '没有抛错')
    except ValueError as err:
        check('白名单混进 C 类时**直接抛错**（宁可不生成）', '非 A 类' in str(err), str(err)[:60])

    # ④ 兜底与稳定性
    check('有 exclude_domains 兜底（lock/camera）',
          'exclude_domains' in text and 'lock' in text and 'camera' in text)
    check('两次生成输出一致（diff 友好）', hk.build_yaml(doc) == text)
    # 2026-10-17 实测：写 `linked_battery_sensor: null` 会让 HA 拒绝整个 homekit 配置
    check('不输出非法的 linked_battery_sensor: null', 'linked_battery_sensor' not in text)
    check('带端口与 bridge 模式', 'mode: bridge' in text and 'port:' in text)

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
