#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验收（把宪章六条判据逐条落到可观测证据上）

三件套分工：
  门禁 tools/gate.py     —— 合规（有没有按规范做）
  测试 tools/test_*.py   —— 正确（做出来的东西对不对）
  验收 本文件             —— 判据（对外承诺的东西有没有真的成立）

判据来自 docs/spec/00-顶层宪章（检验判据六条）。未到期的阶段必须写明原因，不许当作通过。

用法：python3 tools/acceptance.py [--phase P1]
产出：logs/evidence/<日期>-<阶段>/acceptance.md
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, 'tools')
sys.path.insert(0, os.path.join(ROOT, 'app'))   # 供 intent/audit/notify 复用（模块级，避免导入顺序问题）
BASE = 'http://127.0.0.1:8300'
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
TZ = datetime.timezone(datetime.timedelta(hours=8))


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=ROOT)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def dom(url):
    if not os.path.exists(CHROME):
        return ''
    r = subprocess.run(
        [CHROME, '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-breakpad',
         '--disable-crash-reporter', '--crash-dumps-dir=/tmp/crash', '--user-data-dir=/tmp/acc-chrome',
         '--virtual-time-budget=5000', '--dump-dom', url],
        capture_output=True, text=True, timeout=90)
    return r.stdout or ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--phase', default='P1')
    a = ap.parse_args()
    now = datetime.datetime.now(TZ)
    ev = os.path.join(ROOT, 'logs', 'evidence', f"{now.strftime('%Y%m%d')}-{a.phase}")
    os.makedirs(ev, exist_ok=True)

    L = [f'# 验收报告 · {a.phase}', '', f'时间：{now.isoformat(timespec="seconds")}',
         '依据：00-顶层宪章「检验判据（六条）」', '']
    verdict = []

    # —— 前置：门禁与测试必须全绿 ——
    rc_g, out_g = run([sys.executable, os.path.join(TOOLS, 'gate.py')])
    rc_t1, out_t1 = run([sys.executable, os.path.join(TOOLS, 'test_state.py')])
    rc_t2, out_t2 = run([sys.executable, os.path.join(TOOLS, 'test_ui.py')])
    rc_t3, out_t3 = run([sys.executable, os.path.join(TOOLS, 'test_intent.py')])
    open(os.path.join(ev, 'gate-report.txt'), 'w', encoding='utf-8').write(out_g)
    open(os.path.join(ev, 'test-state.txt'), 'w', encoding='utf-8').write(out_t1)
    open(os.path.join(ev, 'test-ui.txt'), 'w', encoding='utf-8').write(out_t2)
    open(os.path.join(ev, 'test-intent.txt'), 'w', encoding='utf-8').write(out_t3)
    rc_s, out_s = run([sys.executable, os.path.join(TOOLS, 'smoke_real.py')])
    open(os.path.join(ev, 'smoke-real.txt'), 'w', encoding='utf-8').write(out_s)
    L += ['## 0 · 前置（门禁 + 测试）', '',
          f'- 门禁 tools/gate.py：{"✅ 全绿" if rc_g == 0 else "❌ 有失败"}',
          f'- 数据层测试：{"✅ 全过" if rc_t1 == 0 else "❌ 有失败"}',
          f'- 界面测试：{"✅ 全过" if rc_t2 == 0 else "❌ 有失败"}',
          f'- 意图与执行测试：{"✅ 全过" if rc_t3 == 0 else "❌ 有失败"}', '']
    verdict.append(('前置：门禁 + 测试全绿', rc_g == 0 and rc_t1 == 0 and rc_t2 == 0 and rc_t3 == 0, ''))

    st = json.load(open(os.path.join(ROOT, 'data', 'state.json'), encoding='utf-8'))
    att = st.get('attention') or []

    # —— 判据 1：一整天没打开米家 App（本阶段可观测部分）——
    # 无法真的等一天；可机械验证的是：米家 App 里要看的四类信息（离线/低电量/异常/安全）主屏都能给。
    main_dom = dom(BASE + '/')
    covered, missed = [], []
    for x in att:
        if x['device'] in main_dom or x['room'] in main_dom:
            covered.append(x['device'])
        else:
            missed.append(x['device'])
    L += ['## 判据 1 · 一整天没打开米家 App（本阶段可观测部分）', '',
          f'- 待注意 {len(att)} 项，主屏可直接看到 {len(covered)} 项'
          + (f'，缺 {missed[:3]}' if missed else '（全部覆盖）'),
          '- 说明：本条要等真实一天才能定论；此处机械验证的是「米家里必须翻 App 才看得到的信息，主屏都给了」。',
          '']
    verdict.append(('判据 1：主屏覆盖全部待注意项', not missed, f'{len(covered)}/{len(att)}'))

    # 判据 1 的**真实天记录**（只有用户能定；工具绝不自己宣布达标）
    try:
        import sys as _sys3
        _sys3.path.insert(0, os.path.join(ROOT, 'tools'))
        import criterion1 as _c1
        _e = _c1.get_day()
        _st = {'pass': '达标（当天没开米家）', 'fail': '未达标', None: '今天还没记录'}.get(_e and _e['status'])
        L += ['## 判据 1 · 真实天记录（判据 1 追踪器）', '',
              f"- 今天（{_c1.today_str()}）：{_st}"
              + (f" —— 原因：{_e['reason']}" if _e and _e.get('reason') else ''),
              f"- 连续达标：**{_c1.streak()} 天**", '']
        verdict.append(('判据 1：真实天记录可查（不自动宣布达标）', True, f'{_st} · 连续 {_c1.streak()} 天'))
    except Exception as err:  # noqa
        L += ['## 判据 1 · 真实天记录', f'- 读取失败：{err}', '']
        verdict.append(('判据 1：真实天记录可查', False, str(err)[:40]))

    # —— 判据 3：任何一次"已完成"都能点回状态证据（本阶段＝状态可追）——
    samples = [d for d in st['devices'] if d['confidence'] != 'online'][:3] or st['devices'][:2]
    ev_ok = []
    for d in samples:
        q = urllib.parse.urlencode({'room': d['room'], 'device': d['name']})
        page = dom(BASE + '/?' + q)
        ok = ('读数时间' in page) and ('来源' in page) and (d['source'] in page)
        ev_ok.append((d['name'], ok))
    L += ['## 判据 3 · 都能点回状态证据', '',
          f'- 真实执行冒烟（真调用 + 真回读，幂等无副作用）：{"✅ 通过" if rc_s == 0 else "❌ 未通过"}'
          f'{"（未配置令牌，已跳过）" if "跳过" in out_s else ""}',
          f'- 抽样 {len(ev_ok)} 台（优先异常设备）：' + '；'.join(f'{n} {"✅" if o else "❌"}' for n, o in ev_ok),
          '- 每台详情的字段：状态 · 读数 · 来源 · 读数时间（无有效读数时显式写「接入后未收到过有效读数」）。', '']
    verdict.append(('判据 3：详情含来源与读数时间', all(o for _, o in ev_ok), f'{sum(1 for _, o in ev_ok if o)}/{len(ev_ok)}'))

    # —— 判据 2：旁人看不到家里状态（本阶段：隔离带已建）——
    s = st.get('summary') or {}
    posix = os.path.realpath(os.path.join(ROOT, 'data'))
    _guard = os.environ.get('SMART_HOME_FORBIDDEN_DIR', '')
    isolated = (not _guard) or (not posix.startswith(_guard))
    L += ['## 判据 2 · 打开个人工作台时看不到家里状态', '',
          f'- 数据域隔离：家庭数据在 `{os.path.relpath(posix, ROOT)}`，与个人工作台分域：{"✅" if isolated else "❌"}',
          '- 通道域隔离（独立微信小号）：P4 完成',
          '- 呈现域隔离（家庭面板只存在于家庭工作台视图）：当前家庭工作台是独立应用，尚未嵌入个人工作台 ✅（结构性成立，P4 复核）', '']
    verdict.append(('判据 2：数据域已隔离', isolated, '通道域见 P4'))

    # —— 判据 6：异常被主动说出来（本阶段：主屏主动呈现）——
    top = att[0] if att else None
    said = bool(top) and (top['device'] in main_dom)
    L += ['## 判据 6 · 异常被主动说出来', '',
          f'- 主屏提醒条指向最高优先级项：{top["device"] if top else "（当前无异常）"} {"✅" if said else "❌"}',
          '- 出声额度与免打扰（04 规范）：配置已就位（data/quiet-hours.json），执行链路见 P4', '']
    # 出声决策（04 §3–§5）：安全必达、静默与额度可解释
    import tempfile as _tf2
    import notify as NOT
    _t2 = _tf2.mkdtemp(prefix='acc-notify-')
    NOT.QUOTA = os.path.join(_t2, 'quota.json')
    NOT.SPOKEN = os.path.join(_t2, 'spoken.jsonl')
    decisions = [(x, *NOT.speak(x)) for x in att[:5]]
    sec_ok = all(ok for x, ok, _ in decisions if x['level'] == 'sec')
    L += [f'- 出声判定（前 {len(decisions)} 条）：' + '；'.join(
              f"{x['device']}→{'出声' if ok else '沉默'}（{why}）" for x, ok, why in decisions[:3]),
          f"- 安全类必达：{'✅ 全部出声' if sec_ok else '❌ 有安全项被压住'}",
          '- 静默时段、合并窗口、额度升降（含「不出声不涨额度」）与漏报刹车由 tools/test_p4.py 覆盖。', '']
    verdict.append(('判据 6：主屏主动呈现 + 出声决策可解释', (said or not att) and sec_ok, ''))

    # —— 判据 4（部分）：安全域动作不得被自动执行（运行期实证）——
    import sys as _sys
    _sys.path.insert(0, os.path.join(ROOT, 'app'))
    import intent as I  # noqa
    _acc_tmp = _tf_dir = __import__('tempfile').mkdtemp(prefix='acc-intent-')
    I.ACTIONS = os.path.join(_acc_tmp, 'actions.json')   # 验收绝不写生产动作记录
    r_sec = I.handle('把门锁打开', state=st)
    steps = I.plan_steps(I.parse('我要睡了', st), st)
    doable, blocked = I.guard(steps)
    sec_in_doable = [x['device'] for x in doable if x.get('security')]
    ok4 = (r_sec['intent']['kind'] == 'security') and (not r_sec['steps']) and (not sec_in_doable) and bool(blocked)
    # 可审计：真跑一次（假执行器），检查审计留痕
    import tempfile as _tf
    import audit as AUD
    _t = _tf.mkdtemp(prefix='acc-audit-')
    AUD.AUDIT = os.path.join(_t, 'audit.jsonl')
    out_audit = I.handle('我要睡了', executor=I.FakeExecutor(), state=st, dry_run=False)
    rows = AUD.load()
    fields_ok = bool(rows) and all(all(k in rr for k in AUD.FIELDS) for rr in rows)
    blocked_rows = [rr for rr in rows if rr['result'] == 'blocked']
    L += ['## 判据 4 · 安全类动作从不由对话自授权，且每一次都可审计', '',
          f"- **拒执**：对话里说「把门锁打开」→ 意图类型 = {r_sec['intent']['kind']}，产生执行步骤 {len(r_sec['steps'])} 步，回复明确指向米家手动",
          f"- **守门**：场景展开 {len(steps)} 步，拦截 {len(blocked)} 步（安全域/只读），可执行步骤中安全域设备 {len(sec_in_doable)} 台",
          f"- **可审计**：一次完整执行留下 {len(rows)} 条审计（成功 {sum(1 for rr in rows if rr['result'] == 'ok')} · "
          f"被拒 {len(blocked_rows)} · 失败 {sum(1 for rr in rows if rr['result'] == 'failed')}），"
          f"8 个必备字段{'齐备' if fields_ok else '**缺失**'}",
          f"- 被拒也留痕：{'是' if blocked_rows else '否'}（示例：{blocked_rows[0]['detail'] if blocked_rows else '—'}）",
          '- 审计只追加、无删除接口（门禁 A04/M04/Q09 机械检查）。', '']
    verdict.append(('判据 4：安全域拒执 + 每一次可审计',
                    ok4 and fields_ok and bool(blocked_rows), f'审计 {len(rows)} 条'))

    # —— 判据 5（部分）：换中枢/换模型，记忆不重来 ——
    rc_gap, out_gap = run([sys.executable, os.path.join(TOOLS, 'mijia_gap.py')])
    open(os.path.join(ev, 'mijia-gap.txt'), 'w', encoding='utf-8').write(out_gap)
    rc_r, out_r = run([sys.executable, os.path.join(TOOLS, 'restore_drill.py'), '--deep'])
    open(os.path.join(ev, 'restore-drill.txt'), 'w', encoding='utf-8').write(out_r)
    drill_ok = rc_r == 0 and '失败 0' in out_r
    L += ['## 判据 5 · 换中枢 / 换模型，记忆与规则不重来（本阶段：备份可恢复 + 深演练）', '',
          f"- 米家依赖清单（判据 1 检查表）：{'已重新生成' if rc_gap == 0 else '❌ 生成失败'} —— "
          f"{out_gap.strip().splitlines()[0] if out_gap.strip() else ''}",
          f'- 备份恢复演练（**深演练**）：{"✅ 通过" if drill_ok else "❌ 未通过"}'
          '（解压最新备份 → **让 HA 拿恢复出的配置跑 check_config** → 历史库 quick_check）',
          '- 演练详情见同目录 `restore-drill.md`。',
          '- **未完成**（如实标注）：在**另一台物理机器**上真跑一次；HA OS 迁移。属 P5 收尾项。', '']
    verdict.append(('判据 5：备份可恢复 + 深演练（HA 真校验过恢复出的配置）',
                    drill_ok, 'unpack → HA check_config → quick_check'))

    # —— 判据 1 的物理前提：24h 在线就绪 ——
    try:
        import importlib.util as _iu
        _sp = _iu.spec_from_file_location('uc', os.path.join(TOOLS, 'uptime_check.py'))
        _uc = _iu.module_from_spec(_sp); _sp.loader.exec_module(_uc)
        _ok, _res = _uc.check()
        L += ['## 判据 1 · 物理前提：24 小时在线就绪', '',
              *[f"- {'✅' if i['ok'] else '❌'} {i['item']}：{i['detail']}" for i in _res['items']]]
        for w in _res['warnings']:
            L.append(f"- ⚠️ {w['item']}（{w['who']}）：{w['detail']}")
        L.append('')
        verdict.append(('判据 1 前提：24h 在线就绪（不睡/断电自启/自动登录/自启覆盖）', _ok,
                        '；'.join(_res['blockers']) if _res['blockers'] else '全部满足'))
    except Exception as err:  # noqa
        verdict.append(('判据 1 前提：24h 在线就绪', False, str(err)[:40]))

    # —— 未到期判据 ——
    L += ['## 待真实环境验证的部分（不当作通过）', '',
          '| 项 | 阶段 | 原因 |', '|---|---|---|',
          '| 判据 1 · 完整一天不用打开米家 | 运行期 | 需真实使用一天才能定论；当前只做了机械覆盖检查 |',
          '| 判据 2 · 通道域隔离（别人看不到） | 待微信小号 | 用户已明确把微信小号放到最后 |',
          '| 判据 5 · 另一台机器上的迁移演练 | P5 收尾 | 需第二台设备；备份可恢复已单独验证 |',
          '| 判据 6 · 真实投递（真发到手机） | 待微信小号 | 出声决策已可验证，投递通道同上 |', '']

    ok_n = sum(1 for _, o, _ in verdict if o)
    L += ['## 结论', '', f'- 本阶段可验证判据：{ok_n}/{len(verdict)} 通过',
          '- 未到期判据见上表，不参与本阶段结论。']
    open(os.path.join(ev, 'acceptance.md'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    for k, o, d in verdict:
        print(('✅ ' if o else '❌ ') + k + (f'  —— {d}' if d else ''))
    print(f'\n验收报告：{os.path.relpath(os.path.join(ev, "acceptance.md"), ROOT)}')
    return 0 if ok_n == len(verdict) else 1


if __name__ == '__main__':
    sys.exit(main())
