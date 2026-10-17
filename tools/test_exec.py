#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端：面板动作 / 场景执行（真链路，注入假执行器）

为什么要有：2026-10-17 发现「功能设置」是一处"假成功"（接口回成功、链路没通）。
同样的风险也在另外两条链上——之前只测过"演练(dry)"与"守门"，**没测过真执行那一段**：
  计划 → 守门 → 执行 → 回读 → 回执 → 审计 → 可撤销

做法：把 `ha.real_executor()` 换成假执行器（记录调用、可模拟失败与回读不符），
      于是整条业务链跑真代码，**但不碰任何真实设备**；审计与动作记录写到临时文件。

用法：python3 tools/test_exec.py      退出码 0 = 全过
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
import audit as A  # noqa: E402
import ha  # noqa: E402
import intent as I  # noqa: E402
import panel_action as P  # noqa: E402

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


class FakeExec:
    """假执行器：记下调用，按脚本回读。"""

    def __init__(self, fail=None, mismatch=None):
        self.calls = []
        self.fail = set(fail or [])
        self.mismatch = set(mismatch or [])

    def call(self, step):
        if step.get('security') or step.get('remind_only'):
            raise AssertionError('安全域步骤不该到达执行器')
        self.calls.append(step)
        if step['device'] in self.fail:
            raise RuntimeError('设备离线')

    def read_back(self, step, timeout=None):
        if step['device'] in self.mismatch:
            return False, ('on' if step.get('expect') == 'off' else 'off'), 0.1
        return True, step.get('expect'), 0.1


def main():
    tmp = tempfile.mkdtemp(prefix='exec-test-')
    A.AUDIT = os.path.join(tmp, 'audit.jsonl')
    I.ACTIONS = os.path.join(tmp, 'actions.json')
    devices = json.load(open(os.path.join(ROOT, 'data', 'state.json'), encoding='utf-8'))['devices']
    ok_dev = next((d for d in devices if P.actions_for(d).get('turn_off')), None)
    sec_dev = next((d for d in devices if d['security_domain']), None)
    check('找到可用于测试的可控设备', ok_dev is not None)

    # ── 面板动作：真执行链 ──
    fake = FakeExec()
    ha.real_executor = lambda: fake                    # 只替换执行器，其余走真代码
    out = P.run(ok_dev['name'], 'turn_off')
    check('面板动作执行成功', out.get('ok') is True, str(out.get('receipt')))
    check('回执含回读结果', '回读' in (out.get('receipt') or ''), out.get('receipt', ''))
    check('真的调用了执行器一次', len(fake.calls) == 1, f"{len(fake.calls)} 次")
    check('审计记了这次成功', any(x['result'] == 'ok' for x in A.load()), f"{len(A.load())} 条")
    check('动作可撤销（有 action_id）', bool(out.get('action_id')), str(out.get('action_id')))

    # ── 执行失败 ──
    fake2 = FakeExec(fail=[ok_dev['name']])
    ha.real_executor = lambda: fake2
    out2 = P.run(ok_dev['name'], 'turn_off')
    check('执行失败时如实报"没做成"', out2.get('ok') is False and '没做成' in (out2.get('receipt') or ''),
          out2.get('receipt', ''))
    check('失败也进审计', any(x['result'] == 'failed' for x in A.load()))

    # ── 回读与预期不符 ──
    fake3 = FakeExec(mismatch=[ok_dev['name']])
    ha.real_executor = lambda: fake3
    out3 = P.run(ok_dev['name'], 'turn_off')
    check('回读不符判为失败', out3.get('ok') is False and '没做成' in (out3.get('receipt') or ''),
          out3.get('receipt', ''))

    # ── 安全域：根本不会走到执行器 ──
    fake4 = FakeExec()
    ha.real_executor = lambda: fake4
    if sec_dev:
        out4 = P.run(sec_dev['name'], 'turn_off')
        check('安全域动作被守门拦下且执行器零调用',
              out4.get('blocked') is True and not fake4.calls, str(out4.get('reason')))

    # ── 场景：多步执行 + 拦截项 + 撤销 ──
    fake5 = FakeExec()
    ha.real_executor = lambda: fake5
    sc = P.run_scene('goodnight')
    check('场景真的执行了多步', out_ok := sc.get('ok') is True, str(sc.get('receipt')))
    check('场景回执含完成数与拦截数',
          '项完成' in (sc.get('receipt') or '') and '拦截' in (sc.get('receipt') or ''), sc.get('receipt', ''))
    check('场景执行确实调用了执行器', len(fake5.calls) >= 3, f"{len(fake5.calls)} 步")
    check('场景里的安全域步骤从不到达执行器',
          all(not c.get('security') for c in fake5.calls))
    check('场景可撤销', bool(sc.get('action_id')), str(sc.get('action_id')))

    # ── 撤销：反向执行 + 再次回读 ──
    undo = I.undo(sc['action_id'], executor=fake5)
    check('撤销执行成功', undo.get('ok') is True, str(undo.get('error') or ''))
    check('撤销每一步都有回读值',
          bool(undo.get('results')) and all(r.get('readback') is not None for r in undo['results']),
          f"{len(undo.get('results') or [])} 步")

    # ── dry 仍然不执行（面板与场景都要有这条保险）──
    fake6 = FakeExec()
    ha.real_executor = lambda: fake6
    before_n = len(A.load())
    P.run(ok_dev['name'], 'turn_off', dry=True)
    P.run_scene('goodnight', dry=True)
    check('演练模式绝不调用执行器', not fake6.calls, f"{len(fake6.calls)} 次")
    # 演练**不该写审计**：它什么都没做，写进去就是污染（实测被测试刷出 157 条"被拒"）
    if sec_dev:
        P.run(sec_dev['name'], 'turn_off', dry=True)
    P.run('不存在的设备', 'turn_off', dry=True)
    check('演练不写审计（不污染留痕）', len(A.load()) == before_n,
          f'演练前 {before_n} 条 → 演练后 {len(A.load())} 条')
    P.run(sec_dev['name'] if sec_dev else ok_dev['name'], 'turn_off')
    check('真请求被拒时仍然写审计', len(A.load()) > before_n, f"{len(A.load())} 条")

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
