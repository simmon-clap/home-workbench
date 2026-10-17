#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
规则（自然语言创建）测试 — 03 §7

重点验证三件事：
  ① 中文两种语序都能听懂（「关掉客厅的灯」/「客厅的灯关了」）
  ② **做不到就明说**：条件房间没有人体传感器时，必须给出"做不了 + 可替代方案"，不许生成假规则
  ③ 落到底座前必须能给出"我理解成……对吗？"的复述；dry 模式绝不写文件

用法：python3 tools/test_rules.py      退出码 0 = 全过
"""
import importlib
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
os.environ['SMART_HOME_RULES'] = os.path.join(tempfile.mkdtemp(prefix='rules-test-'), 'rules.json')
os.environ['SMART_HOME_HA_CONFIG'] = tempfile.mkdtemp(prefix='ha-cfg-test-')
import rules as R  # noqa: E402
importlib.reload(R)

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def main():
    # ① 两种语序
    a = R.parse('每天22:30把客厅的灯关了')
    check('语序一：动词在后（…的灯关了）能听懂',
          a['action'] and a['action']['type'] == 'light' and a['action']['action'] == 'turn_off',
          str(a.get('action')))
    b = R.parse('每天22:30关掉客厅的灯')
    check('语序二：动词在前（关掉…的灯）能听懂',
          b['action'] and b['action']['action'] == 'turn_off', str(b.get('action')))
    c = R.parse('每天7:00拉开客厅的窗帘')
    check('窗帘：开 → open（不是 turn_on）',
          c['action'] and c['action']['type'] == 'cover' and c['action']['action'] == 'open',
          str(c.get('action')))

    # 触发时间
    d = R.parse('每天06:05打开书房的灯')
    check('时间解析到分钟', d['trigger'] == {'type': 'time', 'at': '06:05'}, str(d.get('trigger')))

    # ② 复述（规范 §7 明确要求）
    check('给出"我理解成……对吗？"式复述',
          a['recap'].startswith('我理解成：') and a['recap'].endswith('对吗？'), a['recap'])
    check('复述里含时间与动作', '22:30' in a['recap'] and '关掉' in a['recap'], a['recap'])

    # ③ 做不到就明说
    room_no_sensor = '客厅'
    pres = R.presence_entities()
    if room_no_sensor not in pres:
        e = R.parse('每天22:30如果客厅没人就把客厅的灯关了')
        check('没有人体传感器的房间：条件判定为不可行', e['condition_feasible'] is False)
        need = R.needs(e)
        check('给出"做不了 + 可替代方案"（不许生成假规则）',
              need and '传感器' in need and '可以改成' in need, (need or '')[:60])
    else:
        check('客厅确实有人体传感器（跳过不可行用例）', True, str(list(pres)[:3]))

    # 动作缺失 → 追问一句，不连环问
    f = R.parse('每天22:30看看情况')
    check('没有动作时只追问一句', f['ok'] is False and R.needs(f), R.needs(f))

    # ④ 存储与 dry 提交
    entry = R.add_proposal(a)
    check('提案可存（状态 proposed）', entry['status'] == 'proposed' and R.summary()['proposed'] == 1)
    ents = R.action_entities(a['action'])
    check('能算出作用对象（客厅的灯）', len(ents) >= 1, f'{len(ents)} 个')
    check('作用对象里没有安全域设备',
          all(not e.startswith(('lock.', 'camera.')) for e in ents), str(ents[:2]))
    dry = R.commit(entry['id'], confirm=False)
    check('未确认时只给将写入的内容（dry）', dry.get('dry') is True and 'service:' in (dry.get('yaml') or ''),
          (dry.get('yaml') or '')[:60])
    check('dry 不写 automations.yaml', not os.path.exists(os.path.join(R.HA_CONFIG, 'automations.yaml')))

    # 安全域类型的动作不应出现在规则里（我们只允许 light/cover/ac）
    g = R.parse('每天22:00把门锁打开')
    check('门锁动作不会被当成可自动执行的规则',
          (not g['action']) or g['action']['type'] not in ('lock',), str(g.get('action')))

    extra_rule_entity_tests()

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


def extra_rule_entity_tests():
    """补充：规则回读必须按 attributes.id 找真实实体（2026-10-17 抓到真机 bug 后加的）。

    当时的坑：YAML 自动化的 entity_id 是**从 alias 派生**的，写死 `automation.smarthome_x`
    永远找不到 —— 表现是"保存成功但回读失败"。这条测试防止再退化。
    """
    import importlib.util
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.join(ROOT, 'app'))
    import ha

    rows = [
        {'entity_id': 'automation.gong_zuo_tai_zi_jian', 'attributes': {'id': 'smarthome_verify_probe'}},
        {'entity_id': 'automation.other', 'attributes': {'id': 'something_else'}},
        {'entity_id': 'light.not_automation', 'attributes': {'id': 'smarthome_verify_probe'}},
    ]
    check('按 attributes.id 找到真实实体（不是写死的名字）',
          ha.automation_entity_from_states(rows, 'smarthome_verify_probe') == 'automation.gong_zuo_tai_zi_jian',
          str(ha.automation_entity_from_states(rows, 'smarthome_verify_probe')))
    check('找不到时返回 None（不瞎猜一个）',
          ha.automation_entity_from_states(rows, 'nope') is None)
    check('不会把非 automation 域的实体算进来',
          ha.automation_entity_from_states(
              [{'entity_id': 'light.x', 'attributes': {'id': 'abc'}}], 'abc') is None)

    # 字典形态与 YAML 形态必须描述同一件事（两条路不能各自漂移）
    import rules as _r
    entry = {'id': 'abc', 'recap': '夜里关灯', 'trigger': {'type': 'time', 'at': '23:30'},
             'condition': {'room': '客厅'}, 'action': {'type': 'light', 'action': 'turn_off'}}
    ent = ['light.a', 'light.b']
    d = _r._rule_dict(entry, ent)
    y = _r._yaml_rule(entry, ent)
    check('字典与 YAML 的 id 一致', f"smarthome_{entry['id']}" == d['id'] and d['id'] in y, d['id'])
    check('字典与 YAML 的别名一致', d['alias'] in y, d['alias'])
    check('字典与 YAML 的触发时间一致', '23:30:00' in y and d['trigger'][0]['at'] == '23:30:00')
    check('字典与 YAML 的作用实体一致（都在里面）', all(e in y for e in d['action'][0]['target']['entity_id']))
    check('字典里没有 YAML 里有的多余字段', set(d) <= {'id', 'alias', 'trigger', 'condition', 'action'}, str(set(d)))


extra_rule_entity_tests()


if __name__ == '__main__':
    sys.exit(main())
