#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
审计：我们调用的 HA 服务 / 接口 / WS 命令**是否真实存在**

为什么要有：2026-10-17 抓到过一个同类潜伏 bug（规则回读写死的实体名永远不存在，
功能从没真机上跑通过）。这类问题的共性是**代码里引用的名字在 HA 那边根本不存在**，
而单元测试用假数据是查不出来的 —— 只有拿 HA 的真实清单对照才行。

做法（全部只读）：
  ① 取 HA 的 `/api/services` 真实服务清单
  ② 扫我们代码里的 `call_service('域','服务')`、`panel_action.DOMAIN_ACTIONS` 的域→服务映射、
     场景步骤里用的服务
  ③ 用 WebSocket 真连一次，验证我们用到的命令类型存在（注册表三件套 + `automation/config`）
  ④ 验证官方配置接口的域可用（`automation`）

用法：python3 tools/audit_ha_calls.py [--json]
退出码：0 = 全部存在；1 = 有引用不存在的东西
"""
import argparse
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, 'app')
sys.path.insert(0, APP)

# 我们用到的 WS 命令（真连一次验证）
WS_COMMANDS = ['config/entity_registry/list', 'config/device_registry/list',
               'config/area_registry/list', 'automation/config']
# 我们用到的官方配置接口域
CONFIG_DOMAINS = ['automation']


def ha_services():
    import ha
    req = urllib.request.Request(ha.BASE + '/api/services')
    req.add_header('Authorization', 'Bearer ' + ha.load_token())
    with urllib.request.urlopen(req, timeout=25) as resp:
        rows = json.load(resp)
    return {d['domain']: set((d.get('services') or {}).keys()) for d in rows}


def static_calls():
    """扫代码里的 call_service('域','服务') 字面量。"""
    out = set()
    pat = re.compile(r"call_service\(\s*['\"]([a-z_]+)['\"]\s*,\s*['\"]([a-z_]+)['\"]")
    for root, _dirs, files in os.walk(ROOT):
        if any(x in root for x in ('/.git', '/logs', '/backups', '/data/images', 'node_modules')):
            continue
        for fn in files:
            if not fn.endswith('.py'):
                continue
            # 排除测试文件与本工具自身：测试里会**故意**写假调用用于验证，
            # 扫进来会造成假阳性（实测踩过：审计把自己的测试当成了"引用不存在的服务"）
            if fn.startswith('test_') or fn == 'audit_ha_calls.py':
                continue
            p = os.path.join(root, fn)
            try:
                src = open(p, encoding='utf-8').read()
            except OSError:
                continue
            for m in pat.finditer(src):
                out.add((m.group(1), m.group(2)))
    return out


def mapping_calls():
    """panel_action 里域→服务的静态映射。"""
    import panel_action as P
    out = set()
    for dom, acts in (P.DOMAIN_ACTIONS or {}).items():
        for _act, spec in acts.items():
            if spec and spec[0]:
                out.add((dom, spec[0]))
    if getattr(P, 'BUTTON_WORDS', None) is not None:
        out.add(('button', 'press'))
    return out


def scene_calls():
    """场景步骤里实际用到的服务（从我们的场景数据里取）。"""
    out = set()
    p = os.path.join(ROOT, 'data', 'scenes.json')
    if not os.path.exists(p):
        return out
    try:
        doc = json.load(open(p, encoding='utf-8'))
    except ValueError:
        return out
    for sc in (doc.get('scenes') or []):
        for st in (sc.get('steps') or []):
            svc = st.get('service') or ''
            if '.' in svc:
                d, _, s = svc.partition('.')
                out.add((d, s))
    return out


def ws_check():
    """真连一次 WS，验证命令存在。"""
    import ha_ws
    out = {}
    w = ha_ws.HaWs().connect()
    try:
        w.auth()
        for cmd in WS_COMMANDS:
            kwargs = {'entity_id': 'automation.__audit_probe__'} if cmd == 'automation/config' else {}
            try:
                w.query(cmd, **kwargs)
                out[cmd] = True
            except ha_ws.HaWsError as err:
                msg = str(err)
                # 命令存在但实体不存在 = 命令是好的（这正是我们要区分的）
                out[cmd] = 'Entity not found' in msg or 'not found' in msg.lower()
            except Exception:  # noqa
                out[cmd] = False
    finally:
        w.close()
    return out


def config_domains_check():
    import ha
    return {d: ha.config_available(d) for d in CONFIG_DOMAINS}


def entity_audit():
    """实体侧审计：状态里记的实体是否真的存在、动作目标是否有效、安全域是否被误放行。

    为什么：服务名对了不代表实体还在（改过配对/重装集成后 entity_id 会变）。
    动作指向一个不存在的实体 → 用户点一下就是失败，而且只有点了才知道。
    """
    import ha
    import panel_action as P
    problems = []
    st = json.load(open(os.path.join(ROOT, 'data', 'state.json'), encoding='utf-8'))
    req = urllib.request.Request(ha.BASE + '/api/states')
    req.add_header('Authorization', 'Bearer ' + ha.load_token())
    with urllib.request.urlopen(req, timeout=25) as resp:
        rows = json.load(resp)
    have = {x['entity_id'] for x in rows}
    gone, bad_targets, sec_actions, controllable = [], [], [], 0
    for d in st.get('devices') or []:
        ents = list(d.get('entities') or [])
        if d.get('entity_id'):
            ents.append(d['entity_id'])
        miss = [e for e in ents if e not in have]
        if miss:
            gone.append(f"{d['name']}→{miss[:1]}")
        acts = P.actions_for(d)
        if not d.get('security_domain') and acts:
            controllable += 1
        for a, spec in acts.items():
            if spec['entity_id'] not in have:
                bad_targets.append(f"{d['name']}.{a}→{spec['entity_id']}")
        if d.get('security_domain') and acts:
            sec_actions.append(d['name'])
    if gone:
        problems.append('状态里有已不存在的实体：' + '、'.join(gone[:3]))
    if bad_targets:
        problems.append('动作指向不存在的实体：' + '、'.join(bad_targets[:3]))
    if sec_actions:
        problems.append('安全域被解析出可执行动作：' + '、'.join(sec_actions[:3]))
    return problems, {'entities_in_ha': len(have), 'devices': len(st.get('devices') or []),
                      'devices_missing_entities': len(gone), 'bad_action_targets': len(bad_targets),
                      'controllable_devices': controllable}


def run():
    problems, info = [], {}
    try:
        have = ha_services()
    except Exception as err:  # noqa
        return [f'取 HA 服务清单失败：{str(err)[:100]}'], info

    called = static_calls() | mapping_calls() | scene_calls()
    missing = sorted(f'{d}.{s}' for d, s in called if d not in have or s not in have[d])
    info['services_checked'] = sorted(f'{d}.{s}' for d, s in called)
    if missing:
        problems.append('引用了 HA 不存在的服务：' + '、'.join(missing))

    wsr = ws_check()
    info['ws_commands'] = wsr
    bad_ws = [k for k, v in wsr.items() if not v]
    if bad_ws:
        problems.append('WS 命令不可用：' + '、'.join(bad_ws))

    cd = config_domains_check()
    info['config_domains'] = cd
    bad_cd = [k for k, v in cd.items() if not v]
    if bad_cd:
        problems.append('官方配置接口域不可用：' + '、'.join(bad_cd))

    try:
        ep, ei = entity_audit()
        info['entities'] = ei
        problems.extend(ep)
    except Exception as err:  # noqa
        problems.append(f'实体审计出错：{str(err)[:80]}')
    return problems, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    problems, info = run()
    if a.json:
        print(json.dumps({'ok': not problems, 'info': info, 'problems': problems},
                         ensure_ascii=False, indent=1))
        return 0 if not problems else 1
    print('=== HA 调用审计（我们引用的名字真的存在吗）===')
    print(f"  服务引用 {len(info.get('services_checked') or [])} 个：" +
          ('全部存在 ✅' if not any('服务' in p for p in problems) else '有不存在 ❌'))
    for k, v in (info.get('ws_commands') or {}).items():
        print(f"  WS 命令 {k:34s} {'✅' if v else '❌'}")
    for k, v in (info.get('config_domains') or {}).items():
        print(f"  配置接口 {k:32s} {'✅' if v else '❌'}")
    e = info.get('entities') or {}
    if e:
        print(f"  实体：HA 里 {e.get('entities_in_ha')} 个 · 状态记录 {e.get('devices')} 台设备"
              f" · 失效实体 {e.get('devices_missing_entities')} · 动作坏目标 {e.get('bad_action_targets')}"
              f" · 可控设备 {e.get('controllable_devices')}")
    print()
    if problems:
        print('结论：❌ ' + '；'.join(problems))
        return 1
    e = info.get('entities') or {}
    print('结论：✅ 服务/命令/接口都存在' +
          (f"，且 {e.get('devices')} 台设备的实体与动作目标**全部有效**" if e else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
