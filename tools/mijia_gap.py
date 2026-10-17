#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
米家依赖清单（判据 1 的检查表）

判据 1 是「一整天不用打开米家」。要证明它，先得知道**现在还有哪些事非去米家不可** ——
这份清单就是那张表，而且**从真实数据算出来**（设备实体解析 + 保守/只读/安全域判定），
不是凭印象列。

分类规则（与 03 / 06 / 08 一致）：
  · 可执行且可回读      → 不用米家
  · 可执行但不可回读    → 不用米家，但**无法确认**（如红外遥控）
  · 安全域设备          → **需要米家手动**（对话与面板都不执行，08 §2）
  · 只读设备            → 本来就不需要控制（传感器/摄像头）
  · 无可用动作的设备    → **需要米家**（HA 里没有可控实体）

用法：python3 tools/mijia_gap.py
产出：data/mijia-dependency.md（人看）+ data/mijia-dependency.json（机器看）
"""
import json
import os
import sys
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
import panel_action as P  # noqa: E402
import settings as SET  # noqa: E402

STATE = os.path.join(ROOT, 'data', 'state.json')
OUT_MD = os.path.join(ROOT, 'data', 'mijia-dependency.md')
OUT_JSON = os.path.join(ROOT, 'data', 'mijia-dependency.json')
TZ = datetime.timezone(datetime.timedelta(hours=8))

# 非设备类依赖：这些不是从设备实体算出来的，是流程性的（如实单列，不混进设备统计）
PROCESS_ITEMS = [
    ('设备配网 / 新增设备', '米家', '新设备要先进米家，我们才能读到（06 §1 接入 8 步）'),
    ('小米账号 OAuth 重新授权', '米家', '仅当集成掉线时；凭证不进对话（08 §6）'),
    ('门锁 / 摄像头 / 燃气 / 水浸 / 烟感 的操作', '米家', '安全域不自动执行，只提醒（08 §2）'),
    ('扫地机启停', '暂未开放', '需实测确认安全路径后再开（避免误触发夜间清扫）'),
    ('耗材更换（滤芯/刷子/拖布）', '线下', '物理动作；我们只做到期提醒'),
    ('路由器设置（客户端隔离等）', '路由器 App', '影响本地集成可达性（2026-10-17 实测踩到）'),
]


# 纯输入设备：只产生事件，没有可控输出（无线开关/按钮/门磁等）。
# 这类设备**本来就不需要控制**，不该算进"依赖米家"（否则清单会虚高）。
INPUT_HINT = ('无线开关', '按钮', '开关（蓝牙', '门铃', '按键')
INPUT_DOMAINS = {'event', 'binary_sensor'}


def classify(dev):
    acts = P.actions_for(dev)
    if dev.get('security_domain'):
        return 'need_mijia', '安全域：只提醒不执行'
    if dev.get('type') in ('sensor', 'camera'):
        return 'readonly', '只读设备，本来就不需要控制'
    if not acts:
        doms = {e.split('.')[0] for e in (dev.get('entities') or [])}
        if any(h in dev['name'] for h in INPUT_HINT) or (doms and doms <= (INPUT_DOMAINS | {'sensor'})):
            return 'input', '输入类设备（只产生事件，没有可控输出）'
        return 'need_mijia', 'HA 里没有可控实体'
    if all(not a['verifiable'] for a in acts.values()):
        return 'no_readback', '能发指令但设备不回传状态'
    return 'ok', '可执行且可回读'


def main():
    if not os.path.exists(STATE):
        print('缺 data/state.json'); return 1
    st = json.load(open(STATE, encoding='utf-8'))
    buckets = {'ok': [], 'no_readback': [], 'readonly': [], 'input': [], 'need_mijia': []}
    for d in st.get('devices') or []:
        kind, why = classify(d)
        buckets[kind].append({'name': d['name'], 'room': d.get('room'),
                              'type': d.get('type'), 'why': why,
                              'actions': sorted(P.actions_for(d).keys())})
    now = datetime.datetime.now(TZ).isoformat(timespec='seconds')
    # 用户补录的依赖（清单外的"今天又为了什么开了米家"）—— 这些才是判据 1 的**真实缺口**
    rec = SET.extra_deps()
    doc = {'generated_at': now,
           'source': 'data/state.json + app/panel_action.actions_for() + 用户补录',
           'judgment': '判据 1 · 一整天不用打开米家',
           'counts': {k: len(v) for k, v in buckets.items()}, 'devices': buckets,
           'recorded_gaps': rec, 'recorded_count': len(rec),
           'process_items': [{'item': a, 'where': b, 'note': c} for a, b, c in PROCESS_ITEMS]}
    json.dump(doc, open(OUT_JSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    need = buckets['need_mijia']
    lines = ['# 米家依赖清单（判据 1 的检查表）', '',
             f'> 生成时间：{now} · 来源：`data/state.json` + 实体解析（**从数据算出，不是手写**）', '',
             '## 一句话', '',
             f"家里 {len(st['devices'])} 台设备里，**{doc['counts']['ok']} 台不用米家**（可执行且可回读）、"
             f"{doc['counts']['no_readback']} 台能发指令但无法确认、{doc['counts']['readonly']} 台只读、"
             f"{doc['counts'].get('input', 0)} 台输入类（按钮等，本来不需控制）、"
             f"**{doc['counts']['need_mijia']} 台仍需米家手动**。", '',
             '## 仍需米家的设备', '', '| 设备 | 房间 | 原因 |', '|---|---|---|']
    for d in need:
        lines.append(f"| {d['name'][:26]} | {d['room']} | {d['why']} |")
    lines += ['', '## 能发指令但无法确认（设备不回传状态）', '', '| 设备 | 房间 | 可用动作 |', '|---|---|---|']
    for d in buckets['no_readback']:
        lines.append(f"| {d['name'][:26]} | {d['room']} | {'、'.join(d['actions'])} |")
    lines += ['', '## 不用米家的设备', '',
              f"共 {doc['counts']['ok']} 台（可执行 + 回读确认）：" +
              '、'.join(d['name'][:14] for d in buckets['ok'][:12]) + ' …', '',
              '## 非设备类依赖（流程性，如实单列）', '', '| 事项 | 去哪里 | 说明 |', '|---|---|---|']
    for it in doc['process_items']:
        lines.append(f"| {it['item']} | {it['where']} | {it['note']} |")
    lines += ['', f"## 你补录的清单外依赖（{len(rec)} 条）", '',
              '> 这些是**判据 1 的真实缺口**：设计里没预料到、但你确实不得不打开米家的场景。', '']
    if rec:
        lines += ['| 什么时候 | 为了什么 | 去哪里 |', '|---|---|---|']
        lines += [f"| {x.get('at', '')[:16]} | {x.get('reason')} | {x.get('where')} |" for x in rec]
    else:
        lines += ['还没有补录。下次为了清单外的事打开米家时，在设置页记一笔即可。']
    lines += ['', '## 怎么用这份清单验证判据 1', '',
              '1. 记一天：每次打开米家时记一笔原因',
              '2. 对照本清单：若原因是"仍需米家的设备"或"非设备类依赖"里的任何一条 → 属于**已知边界**，不算翻车',
              '3. 若是清单外的新原因 → **那就是判据 1 的真实缺口**，加进 `PROCESS_ITEMS` 并想办法补上', '']
    open(OUT_MD, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')

    print(f"不用米家 {doc['counts']['ok']} · 无法确认 {doc['counts']['no_readback']} · "
          f"只读 {doc['counts']['readonly']} · 输入类 {doc['counts'].get('input', 0)} · "
          f"**仍需米家 {doc['counts']['need_mijia']}** · 你补录的清单外依赖 {len(rec)} 条")
    print(f'清单：{os.path.relpath(OUT_MD, ROOT)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
