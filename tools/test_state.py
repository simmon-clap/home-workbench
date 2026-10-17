#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据层测试（L2 状态模型正确性）

与门禁的分工：
  门禁（tools/gate.py）= 合规：有没有按规范做（颜色/字号/命名/备份/凭证…）
  测试（本文件）      = 正确：做出来的东西对不对（计数自洽、排序、三要素、不确定性）

用法：python3 tools/test_state.py    退出码 0 = 全过
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOMS = ['客厅', '主卧', '厨房', '餐厅', '次卧', '客卫', '主卫', '书房', '阳台', '办公室']
OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def main():
    p = os.path.join(ROOT, 'data', 'state.json')
    check('state.json 存在且可解析', os.path.exists(p))
    if not os.path.exists(p):
        return summary()
    st = json.load(open(p, encoding='utf-8'))
    devs = st.get('devices') or []
    s = st.get('summary') or {}
    att = st.get('attention') or []

    check('设备数 > 0', len(devs) > 0, f'{len(devs)} 台')

    # 计数自洽
    for k, want in (('total', len(devs)),
                    ('online', sum(1 for d in devs if d['confidence'] == 'online')),
                    ('offline', sum(1 for d in devs if d['confidence'] == 'offline')),
                    ('unknown', sum(1 for d in devs if d['confidence'] == 'unknown')),
                    ('stale', sum(1 for d in devs if d['confidence'] == 'stale')),
                    ('security_domain', sum(1 for d in devs if d['security_domain']))):
        check(f'summary.{k} 与明细一致', s.get(k) == want, f'{s.get(k)} vs {want}')

    # 三要素与不确定性
    miss = [d['name'] for d in devs if not (d.get('source') and d.get('confidence') and d.get('status_at'))]
    check('每台设备都有来源/可信度/状态生效时间', not miss, str(miss[:3]))
    bad = [d['name'] for d in devs if d['confidence'] == 'online' and not d.get('observed_at')]
    check('不允许「在线但无有效读数」', not bad, str(bad[:3]))
    bad2 = [d['name'] for d in devs if not d.get('observed_at') and not d.get('observed_note')]
    check('无读数时间时必须显式说明', not bad2, str(bad2[:3]))

    # 房间与阈值
    check('房间全部合法', all(d['room'] in ROOMS for d in devs), str({d['room'] for d in devs} - set(ROOMS)))
    check('离线阈值只用规范值', all(d['offline_threshold_s'] in (600, 300, 43200) for d in devs))

    # 唯一性
    names = [d['name'] for d in devs]
    check('设备名唯一', len(names) == len(set(names)))

    # 待注意清单：排序与可解释
    levels = [a['level'] for a in att]
    check('安全项排在最前', levels == sorted(levels, key=lambda x: {'sec': 0, 'warn': 1, 'info': 2}[x]), str(levels[:6]))
    check('每条待注意都能回答三问', all(a.get('issue') and a.get('detail') and a.get('suggestion') for a in att))
    sec_n = sum(1 for a in att if a['level'] == 'sec')
    check('安全计数与明细一致', s.get('attention_sec') == sec_n, f"{s.get('attention_sec')} vs {sec_n}")
    if sec_n:
        check('有安全事项时 headline 明说安全', '安全' in (s.get('headline') or ''), s.get('headline'))
    else:
        check('无安全事项时不说安全', '安全' not in (s.get('headline') or ''), s.get('headline'))

    # 安全域清单一致
    sp = os.path.join(ROOT, 'data', 'security-domain.json')
    if os.path.exists(sp):
        listed = set(json.load(open(sp, encoding='utf-8')).get('devices') or [])
        actual = {d['name'] for d in devs if d['security_domain']}
        check('安全域清单与台账一致', listed == actual, str(sorted(listed ^ actual)[:3]))
    else:
        check('安全域清单存在', False, '缺 data/security-domain.json')

    # 与米家一致（改名 0）
    snap = os.path.join(ROOT, 'data', 'registry-snapshots', 'core.device_registry.json')
    if os.path.exists(snap):
        reg = {d.get('name') for d in json.load(open(snap, encoding='utf-8'))['data']['devices']}
        renamed = [n for n in names if n not in reg]
        check('设备名与米家一致（改名 0）', not renamed, str(renamed[:3]))

    # ── 耗材（滤网/刷子/拖布）：米家会显示，我们也必须有 ──
    vac = next((d for d in devs if d['type'] == 'vacuum'), None)
    if vac:
        cons = [r for r in vac['readings'] if r.get('kind') == 'consumable']
        check('扫地机耗材读数存在', len(cons) >= 1,
              f"{len(cons)} 项：" + '、'.join(r['label'] for r in cons))
        ids = [r['entity_id'] for r in vac['readings']]
        check('读数按实体去重', len(ids) == len(set(ids)), f'{len(ids)} 条 / 唯一 {len(set(ids))} 个实体')
        low = [r for r in cons if str(r['value']).isdigit() and float(r['value']) <= 24]
        att_cons = [a for a in att if a.get('kind') == 'consumable']
        check('耗材到期（≤24h）进入待注意', (not low) or bool(att_cons),
              '; '.join(a['issue'] for a in att_cons) or '当前无到期耗材')
        lv = [(r['label'], str(r['value'])) for r in vac['readings']]
        check('读数按（标签,值）也不重复（fault 与 faults 这类同值）', len(lv) == len(set(lv)),
              f'{len(lv)} 条 / 唯一 {len(set(lv))}')
        raw = [r for r in vac['readings'] if r.get('kind') == 'raw_code']
        bogus = [a for a in att if '自报状态码' in (a.get('issue') or '')]
        check('自报状态码带"含义未知"说明，且绝不按耗材告警',
              all('未知' in (r.get('note') or '') for r in raw) and not bogus,
              ('误报：' + str(bogus[:2])) if bogus else f'{len(raw)} 条，无假告警')

    return summary()


def summary():
    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
