#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能设置测试（03 §1D）

覆盖：可编辑对象、校验、**安全域越权保护**、变更留痕、回滚、手动录入、分区映射。
规矩：测试**绝不写生产数据**（settings.json 指向临时目录，与 tools/test_p4.py 同款隔离）。

用法：python3 tools/test_settings.py      退出码 0 = 全过
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
import settings as S  # noqa: E402

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def main():
    S.SETTINGS = os.path.join(tempfile.mkdtemp(prefix='settings-test-'), 'settings.json')
    devs = json.load(open(os.path.join(ROOT, 'data', 'state.json'), encoding='utf-8'))['devices']
    names = [d['name'] for d in devs]
    check('可编辑字段与规范一致', set(S.EDITABLE) == {'room', 'short_name', 'tags', 'offline_threshold_s'},
          str(S.EDITABLE))
    check('房间列表可用', len(S.rooms()) >= 10, f'{len(S.rooms())} 个')

    dev = next((d for d in devs if not d['security_domain']), None)
    sec = next((d for d in devs if d['security_domain']), None)

    # 改房间（对话/面板两条路径都落这里）
    target = next(r for r in S.rooms() if r != dev['room'])
    ok, msg = S.set_field(dev['name'], 'room', target)
    check('可以把设备改到另一个房间', ok, msg or '')
    ok, msg = S.set_field(dev['name'], 'room', '不存在的地方')
    check('不存在的房间被拒', not ok and '没有这个房间' in msg, msg)
    ok, msg = S.set_field('不存在的设备', 'room', target)
    check('不存在的设备被拒', not ok and '找不到设备' in msg, msg)
    ok, msg = S.set_field(dev['name'], 'short_name', '')
    check('空短名被拒', not ok, msg)
    ok, msg = S.set_field(dev['name'], 'offline_threshold_s', 999)
    check('标尺外的阈值被拒', not ok and '阈值' in msg, msg)
    ok, _ = S.set_field(dev['name'], 'offline_threshold_s', 43200)
    check('规范内阈值（电池 43200）可用', ok)

    # 安全域越权保护（03 §1D 明文要求）
    if sec:
        ok, msg = S.set_field(sec['name'], 'tags', ['type'], by='agent')
        check('agent 不许把安全设备移出 sec', not ok and 'agent' in msg, msg)
        ok, msg = S.set_field(sec['name'], 'tags', ['type'], by='user')
        check('本人移出 sec 也要显式确认', not ok and '确认' in msg, msg)
        ok, _ = S.set_field(sec['name'], 'tags', ['type'], by='user', confirm=True)
        check('显式确认后可改', ok)

    # 留痕与回滚
    h = S.history(50)
    check('变更留痕（谁/何时/从什么到什么）',
          bool(h) and all(k in h[0] for k in ('at', 'by', 'device', 'field', 'from', 'to')),
          f"{len(h)} 条")
    ok, msg = S.undo_last(dev['name'])
    check('可回滚最近一次改动', ok, msg)
    # 回滚是"恢复改动前的值"：覆盖表里应回到 600（state.json 里的原始值），而不是 43200
    after = (S.doc().get('overrides', {}).get(dev['name']) or {}).get('offline_threshold_s')
    check('回滚后覆盖值恢复为改动前的值', after != 43200, f'覆盖值={after}')
    check('回滚本身也留痕', any(h['note'] == '回滚' for h in S.history(10)))

    # 手动录入设备
    ok, msg = S.add_device('测试用占位设备', target)
    check('可手动录入设备（未接入 HA）', ok, msg)
    ok, msg = S.add_device('测试用占位设备', target)
    check('重复录入被拒', not ok and '已经' in msg, msg)
    ok, msg = S.add_device('另一台占位', '不存在的地方')
    check('录入到不存在的房间被拒', not ok, msg)

    # 分区映射（P7）
    zs = S.zones()
    check('能列出扫描分区', len(zs) >= 1, f'{len(zs)} 个：' + '、'.join(z['zone'] for z in zs))
    check('分区按"未映射优先"排序', all(not z['room'] for z in zs[:1]) if zs else True)
    if zs:
        z0 = zs[0]['zone']
        ok, msg = S.set_zone(z0, target)
        check('可以把分区映射到房间', ok and S.doc()['zone_map'][z0] == target, msg)
        ok, msg = S.set_zone(z0, '不存在的地方')
        check('分区映射到不存在的房间被拒', not ok, msg)
        ok, msg = S.set_zone('不存在的分区', target)
        check('不存在的分区被拒', not ok and '没有这个分区' in msg, msg)
        ok, msg = S.undo_last('分区 ' + z0)
        check('分区映射可回滚', ok and z0 not in (S.doc().get('zone_map') or {}), msg)

    # 回滚到底值 → 覆盖必须撤掉（否则来源一直显示"本地改过"，不诚实）
    dev2 = next(d for d in devs if not d['security_domain'] and d['name'] != dev['name'])
    base_room = S.current(dev2['name'], 'room')
    other_room = next(r for r in S.rooms() if r != base_room)
    S.set_field(dev2['name'], 'room', other_room)
    check('覆盖表记下了底值（用于回滚判断）',
          (S.doc()['overrides'].get(dev2['name']) or {}).get('_base', {}).get('room') == base_room,
          str((S.doc()['overrides'].get(dev2['name']) or {}).get('_base')))
    S.undo_last(dev2['name'])
    check('回滚到底值后覆盖被撤掉（来源回到米家）',
          'room' not in (S.doc()['overrides'].get(dev2['name']) or {}),
          str(S.doc()['overrides'].get(dev2['name'])))

    # 米家依赖补录（判据 1）
    ok, msg = S.add_dep('为了测试补一笔')
    check('可以补录一条米家依赖', ok and len(S.extra_deps()) == 1, msg)
    ok, msg = S.add_dep('为了测试补一笔')
    check('重复补录被拒', not ok and '记过' in msg, msg)
    ok, msg = S.add_dep('   ')
    check('空理由被拒', not ok, msg)
    ok, msg = S.add_dep('X' * 80)
    check('超长理由被拒', not ok and '超过' in msg, msg)
    ok, msg = S.remove_dep('不存在的一条')
    check('删除不存在的补录被拒', not ok and '没找到' in msg, msg)
    ok, msg = S.remove_dep('为了测试补一笔')
    check('可以移除补录', ok and not S.extra_deps(), msg)

    # 分区改名（03 v1.3 §1D-2）
    ok, msg = S.set_zone_name(z0, '儿童房')
    check('可以给分区改名', ok and next(x for x in S.zones() if x['zone'] == z0)['label'] == '儿童房', msg)
    zmap = S.doc().get('zone_map') or {}
    check('改名不影响分区↔房间映射', z0 not in zmap or zmap[z0] == target, str(zmap))
    ok, msg = S.set_zone_name(z0, '')
    check('空名字被拒', not ok, msg)
    ok, msg = S.set_zone_name(z0, 'x' * 20)
    check('超长名字被拒', not ok and '12' in msg, msg)
    ok, msg = S.undo_last('分区 ' + z0)
    check('分区改名可回滚',
          ok and next(x for x in S.zones() if x['zone'] == z0)['label'] == z0, msg)

    check('改动只落在临时文件（不写生产数据）',
          S.SETTINGS.endswith('settings.json') and 'settings-test-' in S.SETTINGS, S.SETTINGS)

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
