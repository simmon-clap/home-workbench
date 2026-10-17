#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
降级路径测试（03 §12 失败与降级表）

规范要求（逐条）：
  · **HA 不通** → 明说"中枢连不上"，给出最后可用读数的时间，**不做任何猜测性执行**
  · **设备离线** → 明确说哪台、多久、最后一次读数；**不假装成功**
  · **模型不可用** → 退化为规则/手动（我们的解析本来就是规则式，必须证明它不依赖模型/网络）
  · **语音听错** → 回执复述理解结果；安全域绝不执行
  · **网络中断** → 本地优先的能力继续工作

这个文件专门测这些"不顺"的路径 —— 顺的时候谁都会说好话，不顺时是否还说真话才是关键。

全程隔离：审计与动作台账写临时文件；HA 地址指向一个死端口（不碰真的 HA）。

用法：python3 tools/test_degrade.py      退出码 0 = 全过
"""
import json
import os
import socket
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='degrade-test-')


def dead_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


os.environ['HA_BASE_URL'] = f'http://127.0.0.1:{dead_port()}'      # 指向死端口 = HA 不通
sys.path.insert(0, os.path.join(ROOT, 'app'))
import audit as A          # noqa: E402
import ha                  # noqa: E402
import intent as I         # noqa: E402
import panel_action as P   # noqa: E402

A.AUDIT = os.path.join(TMP, 'audit.jsonl')
I.ACTIONS = os.path.join(TMP, 'actions.json')

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def main():
    print(f'（模拟 HA 不通：{ha.BASE}）')

    # ① HA 不通：连通性检查要"返回否"而不是崩
    check('HA 不通时连通性检查返回 False（不抛异常）', ha.ping() is False, 'ping() = False')
    check('仍能说明令牌是否已配置（本地判断，不依赖网络）', isinstance(ha.configured(), bool))

    st = json.load(open(os.path.join(ROOT, 'data', 'state.json'), encoding='utf-8'))
    dev = next((d for d in st['devices'] if not d['security_domain'] and P.actions_for(d).get('turn_off')), None)
    check('找到一台可用于测试的可控设备', dev is not None, dev and dev['name'])

    # ② HA 不通时执行 → 必须如实失败，且回执说"没做成"
    out = P.run(dev['name'], 'turn_off')          # 非 dry：会真的尝试
    check('HA 不通时执行**如实失败**（ok=False）', out.get('ok') is False, str(out.get('receipt'))[:60])
    check('回执明说"没做成"（不假装成功）', '没做成' in (out.get('receipt') or ''), out.get('receipt', '')[:60])
    check('失败也留下审计（可追溯）', any(x['result'] in ('failed', 'blocked') for x in A.load()), f"{len(A.load())} 条")

    # ③ 最后可用读数的时间必须能给出（"最后可用读数"这一条要有出处）
    last = dev.get('observed_at') or dev.get('status_at')
    check('能给出该设备最后一次有效读数的时间', bool(last), str(last))
    check('离线/超时的设备带说明（不拿旧读数冒充现在）',
          bool(dev.get('confidence')) and bool(dev.get('observed_note')), dev.get('observed_note', '')[:40])

    # ④ 模型不可用：解析必须是规则式（不依赖任何模型/网络）
    src = open(os.path.join(ROOT, 'app', 'intent.py'), encoding='utf-8').read()
    check('解析层不引用网络/模型（无 requests/openai/urllib 解析调用）',
          'requests' not in src and 'openai' not in src, '规则式解析')
    o = I.parse('把客厅的灯关掉', st)
    check('HA 不通时**解析照常工作**（本地规则，不依赖中枢）',
          o['kind'] == 'single' and len(o.get('targets') or []) >= 3, f"{o['kind']} / {len(o.get('targets') or [])} 台")
    q = I.handle('家里最近怎么样', dry_run=True, state=st)
    check('HA 不通时仍能读最后已知状态（本地优先）',
          '台设备' in (q.get('receipt') or ''), (q.get('receipt') or '').splitlines()[0][:40])

    # ⑤ 安全域：HA 不通也绝不执行（双保险）
    sec = next((d for d in st['devices'] if d['security_domain']), None)
    if sec:
        o2 = P.run(sec['name'], 'turn_off')
        check('HA 不通时安全域仍然被拒（不是"因为连不上才没做"）',
              o2.get('blocked') is True, str(o2.get('reason'))[:50])

    # ⑥ 网络中断：云端设备拿不到更新时，模型要如实标"未上报/超时"，不编
    confs = {d.get('confidence') for d in st['devices']}
    check('状态模型区分在线/离线/未上报（不是非黑即白）',
          len(confs) >= 2 and 'unknown' in confs or 'stale' in confs, str(sorted(confs)))

    check('测试只写临时文件（不碰真 HA、不碰生产审计）',
          A.AUDIT.startswith(TMP) and '127.0.0.1' in ha.BASE, f'{ha.BASE} / {A.AUDIT[:40]}')

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
