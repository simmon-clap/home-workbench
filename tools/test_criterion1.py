#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
判据 1 追踪器测试（tools/criterion1.py）

这个工具最大的风险是**自己宣布达标**——那是整个项目的头号判据，不能伪造。
所以重点测：
  ① 没记录时**绝不自动算达标**（unknown 就是 unknown，连续天数不涨）
  ② 记 fail 必须写原因（否则回溯不了）
  ③ 连续达标只在连续 pass 时增长，中间有 fail/unknown 就断
  ④ 自动汇集的"值得留意"项必须带来源（不许凭空断言）

全程写临时文件，不碰生产数据。

用法：python3 tools/test_criterion1.py      退出码 0 = 全过
"""
import importlib
import importlib.util
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMPDIR = tempfile.mkdtemp(prefix='criterion1-test-')
os.environ['SMART_HOME_CRITERION1'] = os.path.join(TMPDIR, 'criterion1.json')
sys.path.insert(0, os.path.join(ROOT, 'app'))
spec = importlib.util.spec_from_file_location('c1', os.path.join(ROOT, 'tools', 'criterion1.py'))
c1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c1)

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def main():
    day = c1.today_str()
    check('初始状态是"未记录"，不是"达标"', c1.get_day(day) is None and c1.streak() == 0)

    rep = c1.report()
    first = rep.splitlines()[0]
    check('报告第一行明说"还没记录"（不暗示达标）', '还没记录' in first and '达标（' not in first, first)

    ok, msg = c1.record('fail')
    check('记"未达标"必须写原因', not ok and '为什么' in msg, msg)
    ok, msg = c1.record('fail', '扫地机卡住，米家里点了继续')
    check('带原因的未达标可以记', ok and c1.get_day(day)['status'] == 'fail', msg)
    check('未达标时连续天数为 0', c1.streak() == 0)

    ok, msg = c1.record('pass')
    check('可以改记为达标（同一天覆盖）', ok and c1.get_day(day)['status'] == 'pass', msg)
    check('达标后连续 1 天', c1.streak() == 1, f'{c1.streak()} 天')

    # 补两天历史：昨天 pass、前天 fail → 连续应为 2（今天+昨天）
    import datetime
    now = datetime.datetime.now(c1.TZ)
    c1.record('pass', now=now - datetime.timedelta(days=1))
    c1.record('fail', '前天在米家里重置了滤芯', now=now - datetime.timedelta(days=2))
    check('连续达标按"连续 pass"计算（中间有 fail 就断）', c1.streak() == 2, f'{c1.streak()} 天')

    # 今天未记录时，从昨天往回数
    d = c1.doc()
    d['days'] = [x for x in d['days'] if x['date'] != day]
    c1.save(d)
    check('今天没记录 → 从昨天往回数（不计今天）', c1.streak() == 1, f'{c1.streak()} 天')

    ev = c1.suspicious_events()
    check('自动汇集的每一条都带来源（不许凭空断言）',
          all(x.get('evidence') for x in ev), str(ev[:1]))

    check('测试只写临时文件（不碰生产数据）', c1.FILE.startswith(TMPDIR), c1.FILE)

    extra_briefing_ask_tests()

    extra_staleness_tests()

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0




def extra_briefing_ask_tests():
    """补充：简报在"今天还没记录"时必须给出**能直接照做的一句话**。

    为什么：判据 1 是头号验收，只有用户知道答案。如果简报只报"还没记录"而不说该怎么记，
    这条日常闭环就只是噪音（2026-10-17 补的）。
    """
    import importlib
    import json as _json
    import tempfile as _tf
    import briefing as B
    import criterion1 as C

    tmp = _tf.mkdtemp(prefix='crit-brief-')
    old = C.FILE
    try:
        # ① 清空记录 → 应出现"回我一句"
        C.FILE = os.path.join(tmp, 'c1.json')
        open(C.FILE, 'w', encoding='utf-8').write('{"version": 1, "days": []}')
        text = B.compose()
        blob = text if isinstance(text, str) else _json.dumps(text, ensure_ascii=False)
        check('未记录时简报给出可照做的提示（回我一句"没开米家"）',
              '回我一句' in blob and '没开米家' in blob, blob[:80].replace('\n', ' '))

        # ② 已记录 → 不该再啰嗦
        today = __import__('datetime').datetime.now(C.TZ).date().isoformat()
        # 注意 schema：`days` 是**列表**，每条 {date,status,reason,by,at}
        # （第一版写成字典，导致 streak() 抛错被简报的 except 吞掉 → 测出"没有达标行"）
        _json.dump({'version': 1, 'days': [{'date': today, 'status': 'pass', 'reason': '',
                                            'by': 'user', 'at': today + 'T09:00:00+08:00'}]},
                   open(C.FILE, 'w', encoding='utf-8'), ensure_ascii=False)
        blob2 = B.compose()
        blob2 = blob2 if isinstance(blob2, str) else _json.dumps(blob2, ensure_ascii=False)
        check('已记录时不再重复要答案', '回我一句' not in blob2)
        check('已记录时仍显示达标与连续天数', '达标' in blob2 and '连续达标' in blob2)
    finally:
        C.FILE = old



def extra_staleness_tests():
    """补充：简报必须说明数据新鲜度（迁移/故障期间尤其重要）。

    宪章第三条：不许拿旧读数冒充现在。迁移期间状态刷新会失败，简报仍照常发 ——
    不说明就是误导（2026-10-17 补）。
    """
    import json as _json
    import tempfile as _tf
    import io as _io
    import datetime as _dt
    from contextlib import redirect_stdout
    import briefing as B

    tmp = _tf.mkdtemp(prefix='brief-stale-')
    st = _json.load(open(os.path.join(ROOT, 'data', 'state.json'), encoding='utf-8'))
    old = B.DATA
    try:
        # ① 数据新鲜 → 不出现"分钟前"的告警
        st['generated_at'] = _dt.datetime.now().astimezone().isoformat(timespec='seconds')
        _json.dump(st, open(os.path.join(tmp, 'state.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        B.DATA = tmp
        buf = _io.StringIO()
        with redirect_stdout(buf):
            print(B.compose())
        fresh = buf.getvalue()
        check('数据新鲜时简报不出现新鲜度告警（不吓人）', '分钟前的' not in fresh,
              [l for l in fresh.splitlines() if '分钟前' in l][:1])

        # ② 数据 40 分钟前 → 必须明说"不是现在"
        st['generated_at'] = (_dt.datetime.now().astimezone()
                              - _dt.timedelta(minutes=40)).isoformat(timespec='seconds')
        _json.dump(st, open(os.path.join(tmp, 'state.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        buf2 = _io.StringIO()
        with redirect_stdout(buf2):
            print(B.compose())
        stale = buf2.getvalue()
        check('数据偏旧时简报明说"这份状态是 X 分钟前的"', '分钟前的' in stale,
              [l for l in stale.splitlines() if '分钟前' in l][:1])
        check('并且说清"下面说的是最后一次可用读数，不是现在"', '不是现在' in stale)
    finally:
        B.DATA = old

if __name__ == '__main__':
    sys.exit(main())
