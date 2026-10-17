#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P4 测试：审计留痕 + 出声额度 + 免打扰（不依赖 HA 令牌）

依据：docs/spec/08 §4（审计字段与只追加）· 04 §3–§6（三问/额度/免打扰/漏报刹车）· 11 §11（必须带测试）

用法：python3 tools/test_p4.py      退出码 0 = 全过
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
import audit as A  # noqa: E402
import notify as N  # noqa: E402

TZ = timezone(timedelta(hours=8))
OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def isolate():
    tmp = tempfile.mkdtemp(prefix='p4-test-')
    A.AUDIT = os.path.join(tmp, 'audit.jsonl')
    N.QUOTA = os.path.join(tmp, 'quota.json')
    N.SPOKEN = os.path.join(tmp, 'spoken.jsonl')
    return tmp


def item(level='warn', kind='offline', device='测试设备', issue='离线', detail='最后一次有效读数 10-16 20:00',
         suggestion='检查电源'):
    return {'level': level, 'kind': kind, 'device': device, 'room': '客厅', 'issue': issue,
            'detail': detail, 'suggestion': suggestion}


def main():
    isolate()

    # ── 审计 ──
    e = A.log(action='turn_off', target='light.x', channel='对话', authorization='对话授权',
              result='ok', readback='off')
    check('审计字段齐备（8 项）', all(k in e for k in A.FIELDS), str(sorted(e.keys())))
    A.log(action='refused', target='lock.y', result='blocked', detail='安全域：只提醒')
    A.log(action='turn_on', target='switch.z', result='failed', detail='设备离线')
    rows = A.load()
    check('审计可读取', len(rows) == 3, f'{len(rows)} 条')
    s = A.summary()
    check('审计小结计数正确', s['total'] == 3 and s['ok'] == 1 and s['blocked'] == 1 and s['failed'] == 1, str(s))
    check('审计无删除/修改接口', not any(hasattr(A, f) for f in ('delete', 'remove', 'clear', 'drop')),
          '只提供 log/load/summary')
    with open(A.AUDIT, 'a', encoding='utf-8') as f:
        f.write('这不是JSON\n')
    before = open(A.AUDIT, encoding='utf-8').read()
    A.load()
    check('坏行被跳过但不改写文件（不可篡改）', open(A.AUDIT, encoding='utf-8').read() == before)

    # ── 三问与安全事件 ──
    ok, why = N.speak(item(detail='', issue=''))
    check('三问缺一不出声', ok is False and '三问' in why, why)
    ok, why = N.speak(item(level='sec', kind='security_offline', device='燃气卫士'))
    check('安全事件必达', ok is True and '必达' in why, why)

    # ── 静默时段 ──
    night = datetime(2026, 10, 17, 2, 0, tzinfo=TZ)
    ok, why = N.speak(item(device='A'), now=night)
    check('静默时段内非安全类不出声', ok is False and '静默' in why, why)
    ok, _ = N.speak(item(level='sec', kind='security_offline', device='B'), now=night)
    check('静默时段内安全事件仍出声', ok is True)
    day = datetime(2026, 10, 17, 14, 0, tzinfo=TZ)
    ok, why = N.speak(item(device='A'), now=day)
    check('非静默时段可出声', ok is True, why)

    # ── 合并窗口 ──
    N.mark_spoken(item(device='A', issue='离线'))
    ok, why = N.speak(item(device='A', issue='离线'), now=day)
    check('同设备同原因 60 分钟内只出声一次', ok is False and '已出过声' in why, why)
    ok, _ = N.speak(item(device='A', issue='低电量'), now=day)
    check('同设备不同原因仍可出声', ok is True)

    # ── 额度 ──
    base = N.load_quota()['score']
    n1 = N.feedback('acted', kind='offline')
    check('照做 → 额度上升（明显）', n1['score'] == base + 2, str(n1))
    n2 = N.feedback('ack', kind='offline')
    check('知道了 → 小幅上升', n2['delta'] == 1)
    base2 = n2['score']
    n3 = N.feedback('ignored', kind='offline')
    check('忽略 → 下降', n3['score'] == base2 - 1)
    base3 = n3['score']
    n4 = N.feedback('silent', kind='offline')
    check('**不出声不涨额度**（不许靠憋着攒额度）', n4['score'] == base3 and n4['delta'] == 0)
    n5 = N.feedback('muted', kind='offline', reason='别提醒了')
    check('说“别提醒” → 明显下降', n5['score'] <= base3 - 3, str(n5))
    ok, why = N.speak(item(kind='offline', device='C'), now=day)
    check('“别提醒”当场生效（该类静音）', ok is False and '别提醒' in why.replace('你让这类别提醒', '别提醒'), why)

    # ── 低额度只放"错过就没了" ──
    q = N.load_quota()
    q['score'] = 0
    q['history'] = []
    q['muted_kinds'] = []      # 只测额度这一条规则，先把"别提醒"的静音清掉（避免状态串味）
    N.save_quota(q)
    ok, why = N.speak(item(kind='offline', device='D'), now=day)
    check('低额度时普通提醒不出声', ok is False and '额度低' in why, why)
    ok, _ = N.speak(item(kind='missed', device='E'), now=day)
    check('低额度时「错过就没了」仍出声', ok is True)

    # ── 漏报刹车 ──
    r = N.mark_missed(item(kind='offline', device='F'), note='该说没说')
    check('漏报刹车：记录放宽的类别', 'offline' in r['relaxed_kinds'], str(r))
    check('漏报刹车：同时取消该类静音', 'offline' not in r['muted_kinds'], str(r['muted_kinds']))

    b = N.budget()
    check('额度可查询（分数/等级/历史）', set(b) >= {'score', 'level', 'history_tail'}, str(b['level']))

    # ── 定时简报（04 §3）──
    import briefing as B
    night = datetime(2026, 10, 17, 0, 30, tzinfo=TZ)
    txt_night = B.compose('evening', now=night)
    check('凌晨不说“早上好”', not txt_night.startswith('早上好'), txt_night.splitlines()[0])
    txt = B.compose('evening')
    check('简报含四段口径', all(k in txt for k in ('家里', '需要你注意', '它今天做了', '出声额度')))
    check('简报含静默时段与额度', ('静默时段' in txt) and ('/10' in txt))

    # ── 定时简报落盘（launchd 每天两次调用它；幂等 = 不重复打扰）──
    import importlib.util
    _spec = importlib.util.spec_from_file_location('briefing_run', os.path.join(ROOT, 'tools', 'briefing_run.py'))
    br = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(br)
    _tmp2 = tempfile.mkdtemp(prefix='briefing-test-')
    br.LOG = os.path.join(_tmp2, 'briefing.log')      # 测试不写生产日志
    o1 = br.run('evening', outdir=_tmp2)
    check('简报可落盘（定时任务会调用它）', o1['ok'] and os.path.exists(o1['path']), os.path.basename(o1['path']))
    o2 = br.run('evening', outdir=_tmp2)
    check('同一天同时段幂等（不重复打扰）', o2.get('skipped') is True, o2.get('reason', ''))
    o3 = br.run('evening', force=True, outdir=_tmp2)
    check('--force 可强制重生成', o3.get('skipped') is False)
    check('简报状态可供查询', os.path.exists(os.path.join(_tmp2, 'status.json')))

    # ── 简报里的"米家依赖"必须是真实计数，不许写死 ──
    import shutil as _sh
    import briefing as B
    tmpd = tempfile.mkdtemp(prefix='brief-dep-')
    old_data = B.DATA
    B.DATA = tmpd
    try:
        _sh.copy(os.path.join(ROOT, 'data', 'state.json'), os.path.join(tmpd, 'state.json'))
        json.dump({'counts': {'ok': 41, 'need_mijia': 6}, 'recorded_count': 3,
                   'recorded_gaps': [{'reason': '甲事'}, {'reason': '乙事'}, {'reason': '丙事'}]},
                  open(os.path.join(tmpd, 'mijia-dependency.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        txt2 = B.compose('evening')
        check('简报显示真实的补录条数（不是写死 0）', '你补录的清单外依赖 3 条' in txt2,
              [x for x in txt2.splitlines() if '米家依赖' in x][:1])
        check('简报会列出你最近补录的内容', '乙事' in txt2 and '丙事' in txt2)
        json.dump({'counts': {'ok': 41, 'need_mijia': 6}, 'recorded_count': 0, 'recorded_gaps': []},
                  open(os.path.join(tmpd, 'mijia-dependency.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        check('没有补录时显示 0 条', '你补录的清单外依赖 0 条' in B.compose('evening'))
    finally:
        B.DATA = old_data

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
