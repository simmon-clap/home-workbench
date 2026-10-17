#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投递链测试（04 · "决定要说" → "真的送到"）

重点：
  ① 完整链路能跑通（判定 → 合成 → 投递 → 记账）
  ② **隐私脱敏**：旁观者可见的通道（桌面/微信）不得出现安全域细节
  ③ 未接通的通道**如实报 not_connected**，不许假装投递成功
  ④ 多条合并成一条，且计数不自相矛盾（曾经出现"有 3 件安全的事…还有 2 项"）
  ⑤ dry 模式不写任何文件

全部在临时 outbox 目录上跑，不碰生产数据。

用法：python3 tools/test_outbox.py      退出码 0 = 全过
"""
import importlib
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
TMP = tempfile.mkdtemp(prefix='outbox-test-')
os.environ['SMART_HOME_OUTBOX'] = TMP
import outbox as O  # noqa: E402
importlib.reload(O)
import notify as N  # noqa: E402
# **隔离**：合并窗口依赖 spoken 台账。用生产台账会让测试结果随"最近说过什么"漂移
# （2026-10-17 实测踩过：安全事件加了合并后，测试因为生产台账里已有记录而失败）
N.SPOKEN = os.path.join(TMP, 'spoken.jsonl')
N.QUOTA = os.path.join(TMP, 'quota.json')
N.QUIET = os.path.join(TMP, 'quiet-hours.json')
import audit as A  # noqa: E402
A.AUDIT = os.path.join(tempfile.mkdtemp(prefix='outbox-audit-'), 'audit.jsonl')  # 审计隔离到**另一个**目录（放同目录会被 recent() 误读）

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def main():
    # ① 基本投递
    r = O.deliver('客厅·顶灯：离线了', kind='offline', level='warn', channels=('outbox',))
    check('能把消息写进 outbox', r['ok'] and os.path.isdir(TMP), str(r['results']))
    files = os.listdir(TMP)
    check('outbox 按日期分文件', files and files[0].endswith('.jsonl'), str(files))
    check('最近说过什么能读到', len(O.recent()) == 1, str(O.summary()))

    # ② 隐私脱敏（最关键）
    sec = O.deliver('主卧·小米全自动智能门锁 Pro：门锁离线', kind='security', level='sec',
                    channels=('desktop', 'wechat'), dry=True)
    d = next(x for x in sec['results'] if x['channel'] == 'desktop')
    check('桌面通知对安全域脱敏（不出现设备名/门锁字样）',
          '门锁' not in d.get('text', '') and '安全' in d.get('text', ''), d.get('text'))
    check('安全域脱敏后仍点明"有安全的事"', '安全' in d.get('text', ''), d.get('text'))
    check('脱敏文案不报具体件数（宁可不报，不许报错）',
          '1 件' not in d.get('text', '') and '3 件' not in d.get('text', ''), d.get('text'))

    # ③ 未接通通道如实报告
    w = next(x for x in sec['results'] if x['channel'] == 'wechat')
    check('微信通道如实报未接通（不假装成功）',
          w['ok'] is False and w.get('not_connected') is True, str(w.get('err'))[:40])

    # ④ 合并与计数
    one = O.compose([{'level': 'sec', 'room': '主卧', 'device': '门锁', 'issue': '离线'}])
    check('只有安全项时不再说"还有 N 项"', '还有' not in one, one)
    two = O.compose([{'level': 'sec', 'room': '主卧', 'device': '门锁', 'issue': '离线'},
                     {'level': 'warn', 'room': '客厅', 'device': '顶灯', 'issue': '离线'}])
    check('安全+普通各一条且计数正确', '客厅' in two and '安全' in two and '还有' not in two, two)
    many = O.compose([{'level': 'warn', 'room': f'房{i}', 'device': f'设备{i}', 'issue': '离线'} for i in range(7)])
    check('普通项超过 4 条时给出准确余数', many.count('设备') == 4 and '还有 3 项' in many, many)

    # ⑤ 完整链路（用真实 attention 数据，但只投 outbox、dry）
    st = json.load(open(os.path.join(ROOT, 'data', 'state.json'), encoding='utf-8'))
    before = len(O.recent())
    out = O.speak_and_deliver(st.get('attention') or [], channels=('outbox',), dry=True)
    check('完整链路：判定→合成→投递 都能跑', 'spoken' in out and out['delivery']['ok'] is True,
          f"要说 {len(out['spoken'])} 项 / 不说 {len(out['silent'])} 项")
    check('dry 不写文件', len(O.recent()) == before, f'{before} → {len(O.recent())}')
    check('每个决定都带原因（能回答为什么说/不说）',
          all(isinstance(v, str) and v for v in out['reasons'].values()), str(list(out['reasons'].items())[:1]))

    # ⑥ 静默与额度仍由 notify 把关（不因加了投递而绕过）
    check('投递不绕过 notify 的判定（说的是 notify 判定的子集）',
          len(out['spoken']) <= len(st.get('attention') or []))
    q = N.budget()
    check('额度状态可查', 'score' in q and 'level' in q, str(q))

    extra_dedupe_tests()

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


def extra_dedupe_tests():
    """补充：同因合并与"原话不重复投"（2026-10-17 抓到的重复播报后加）。

    规范 04 §4：同一设备同一原因 1 小时内只出一次声。
    实测问题：安全类事件每 30 分钟重复播报同一条摘要（安全分支在合并检查之前就返回 True）。
    """
    item = {'device': '天然气卫士X', 'issue': '安全设备离线', 'detail': 'd', 'suggestion': 's',
            'level': 'sec', 'kind': 'security_offline'}
    first_ok, first_why = N.speak(item)
    check('安全事件第一次必达', first_ok is True, first_why)
    N.mark_spoken(item, first_why)
    second_ok, second_why = N.speak(item)
    check('安全事件窗口内不重复打扰（但原因说清"必达"）',
          second_ok is False and '必达' in second_why and '不重复' in second_why, second_why)

    # 投递层的第二道网：原话不重复投
    O.deliver('原话A', channels=('outbox',))
    again = O.deliver('原话A', channels=('outbox',))
    check('同样内容 1 小时内不重复投递（记为合并）',
          again.get('merged') is True and again.get('ok') is False, str(again.get('error'))[:40])
    fresh = O.deliver('原话B', channels=('outbox',))
    check('内容不同则照常投递', fresh.get('ok') is True)
    forced = O.deliver('原话A', channels=('outbox',), force=True)
    check('force=True 可以强制再投（用于确实需要再打扰）', forced.get('ok') is True)

    # 桌面通道不能冒充"已送达"（系统不允许读通知库，我们只能证明"已发出"）
    import json as _json
    d = O.deliver('桌面通道措辞检查', channels=('desktop',), dry=True)
    check('dry 下桌面通道也只是"将发出"（不冒充送达）', d['results'][0].get('dry') is True, str(d['results'][0])[:60])
    src = open(os.path.join(ROOT, 'app', 'outbox.py'), encoding='utf-8').read()
    check('桌面通道回执写清"已发出 ≠ 已展示"',
          'dispatched' in src and '无法机械核验' in src)

    # "没话可说"不是失败
    empty = O.speak_and_deliver([], channels=('outbox',))
    check('没有需要出声的事项时，回执说明"没话可说"而不是失败',
          empty['delivery'].get('ok') is True and empty['delivery'].get('skipped') is True,
          str(empty['delivery'].get('reason')))


if __name__ == '__main__':
    sys.exit(main())
