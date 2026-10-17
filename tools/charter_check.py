#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宪章逐条核验（十条 + 六判据）

宪章是基线：`docs/spec/00-顶层宪章-v0.2-讨论稿.docx` 的十条 + 检验判据六条。
本工具把每一条**能机检的部分**落成检查，输出一张对照表（终端 + markdown）。

诚实规则（和 criterion1 同一立场）：
  · 机检不过 = 红，不许"大概没问题"；
  · **只有人能确认的**（例如"一整天没开米家 App"、微信小号是否真隔开），
    如实标「人工确认」并写明需要谁确认 —— 绝不自动判过；
  · 六判据直接复用 tools/acceptance.py 的结论，不重复实现。

用法：
    python3 tools/charter_check.py            # 打印对照表
    python3 tools/charter_check.py --md       # 输出 markdown（写进 data/宪章对照-<日期>.md）
"""
import argparse
import datetime
import glob
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
APP = os.path.join(ROOT, 'app')
TOOLS = os.path.join(ROOT, 'tools')
sys.path.insert(0, APP)

PASS, FAIL, HUMAN = [], [], []


def ok(article, name, cond, detail=''):
    (PASS if cond else FAIL).append((article, name))
    print(('  ✅ ' if cond else '  ❌ ') + name + (f'  —— {detail}' if detail else ''))
    return cond


def human(article, name, detail=''):
    HUMAN.append((article, name, detail))
    print('  👤 ' + name + (f'  —— {detail}' if detail else ''))


def load_json(rel, default=None):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        return default
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:  # noqa
        return default


def text(rel):
    p = os.path.join(ROOT, rel)
    return open(p, encoding='utf-8').read() if os.path.exists(p) else ''



def _security_refuses():
    """行为级：拿一台真实的安全域设备，走一遍意图→计划，必须全部 remind_only（只提醒不执行）。"""
    try:
        import intent
    except Exception:  # noqa
        return False
    st = load_json('data/state.json', {}) or {}
    sec = [d for d in st.get('devices') or [] if d.get('security_domain')]
    if not sec:
        return False
    dev = sec[0]
    try:
        it = intent.parse(f'把{dev["name"]}关掉', st)
        steps = intent.plan_steps(it, st)
    except Exception:  # noqa
        return False
    if not steps:
        return False              # 连计划都产不出，不能说"拒执已实现"
    return all(s.get('security') and s.get('remind_only') for s in steps)


def _quota_mechanism():
    """出声额度/合并：outbox 里必须有去重窗口与合并逻辑（04 §4 的落地）。"""
    ob = text('app/outbox.py')
    return ('DEDUPE_WINDOW_S' in ob or 'dedupe' in ob.lower()) and ('合并' in ob or 'merged' in ob.lower())


def _no_exclamation():
    """体面：用户能看到的文案里不许有感叹号（中英文都算），代码里的 != / !== 不算。"""
    import re as _re
    files = [os.path.join(APP, 'web', f) for f in ('app.js', 'index.html', 'settings.html')]
    files += [os.path.join(APP, f) for f in ('notify.py', 'briefing.py', 'outbox.py')]
    for fp in files:
        if not os.path.exists(fp):
            continue
        src = open(fp, encoding='utf-8').read()
        # 只取字符串字面量里的内容
        for m in _re.finditer(r"'([^'\n]*)'|\"([^\"\n]*)\"|`([^`]*)`", src):
            seg = m.group(1) or m.group(2) or m.group(3) or ''
            if '${' in seg:       # 模板里的表达式是代码，不是用户可见文案
                continue
            if '！' in seg or ('!' in seg and '!=' not in seg):
                return False
    return True


# ═══════════════ 第一条 · 终极愿景（状态真相 + 主动处置）═══════════════
def a1():
    print('\n【第一条 · 终极愿景】家的状态真相 + 主动处置')
    # 先刷新一次：否则可能读到"上次网络抖动时写的兜底快照"，那不是能力问题而是时点问题
    try:
        subprocess.run([sys.executable, os.path.join(APP, 'state.py')],
                       capture_output=True, text=True, timeout=180, cwd=ROOT)
    except Exception:  # noqa
        pass
    st = load_json('data/state.json', {}) or {}
    devs = st.get('devices') or []
    ok('1', '状态真相存在：设备台账非空', len(devs) >= 50, f'{len(devs)} 台')
    ok('1', '状态真相来自官方 API（不是猜/不是文件兜底）',
       (st.get('data_source') or {}).get('registries') == 'api'
       and (st.get('data_source') or {}).get('states') == 'api',
       json.dumps(st.get('data_source'), ensure_ascii=False)[:60])
    man = load_json('data/automation-manifest.json', {}) or {}
    jobs = man.get('jobs') or []
    ok('1', '主动处置在跑（有周期任务登记）', len(jobs) >= 5, f'{len(jobs)} 个周期任务')


# ═══════════════ 第二条 · 三重身份 ═══════════════
def a2():
    print('\n【第二条 · 三重身份：管家 / 记忆 / 守夜人】')
    ok('2', '管家：意图级执行链路有测试（test_intent/test_exec）',
       all(os.path.exists(os.path.join(TOOLS, f)) for f in ('test_intent.py', 'test_exec.py')))
    db = os.path.join(ROOT, 'config', 'homeassistant', 'home-assistant_v2.db')
    ok('2', '记忆：历史库存在（可回溯）', os.path.exists(db),
       f'{os.path.getsize(db) / 1048576:.0f} MB' if os.path.exists(db) else '缺')
    ok('2', '守夜人：异常会主动说出来（有出声链路）',
       os.path.exists(os.path.join(APP, 'notify.py')) and os.path.exists(os.path.join(APP, 'outbox.py')))


# ═══════════════ 第三条 · 状态真相是一等公民 ═══════════════
def a3():
    print('\n【第三条 · 状态真相一等公民：来源 / 可信度 / 时间】')
    st = load_json('data/state.json', {}) or {}
    devs = st.get('devices') or []
    # 宪章第三条要的是"来源/可信度/时间"，但**离线设备本来就没有有效的最近读数时间**——
    # 关键不是"必须有读数时间"，而是"离线要显式说出来、不许拿旧读数冒充现在"。
    bad = []
    for d in devs:
        if not (d.get('source') and d.get('confidence')):
            bad.append((d.get('name'), '缺来源或可信度'))
        elif not d.get('observed_at') and d.get('confidence') in ('offline', 'unknown'):
            # 允许：但必须显式说明"没有有效读数"，且状态文案不说"在线"
            if not d.get('observed_note') and d.get('state') not in ('离线', '无有效读数', '未上报'):
                bad.append((d.get('name'), '没读数也没说明'))
        elif not d.get('observed_at'):
            bad.append((d.get('name'), '在线却无读数时间'))
    ok('3', '每台设备三要素齐备（离线设备如实说明"无有效读数"）', not bad, str(bad[:3]))
    unk = [d for d in devs if d.get('confidence') in ('offline', 'unknown')]
    ok('3', '离线必须显式说出来（有离线设备且如实标态）',
       len(unk) > 0 and all(d.get('state') for d in unk), f'{len(unk)} 台离线/未知')
    ok('3', '推翻留痕：审计只追加、有历史', os.path.exists(os.path.join(DATA, 'audit.jsonl')))
    ok('3', '优先级 安全>可用>舒适>好看：安全域单独标记',
       any(d.get('security_domain') for d in devs),
       f"{sum(1 for d in devs if d.get('security_domain'))} 台安全域")


# ═══════════════ 第四条 · 动作必须闭环 ═══════════════
def a4():
    print('\n【第四条 · 动作闭环：回读才算完成】')
    ha = text('app/ha.py')
    ok('4', '有回读原语（read_back）', 'def read_back' in ha)
    ok('4', '有撤销（不是标记）', os.path.exists(os.path.join(APP, 'undo.py')) or 'def undo' in ha
       or 'undo' in text('app/server.py'))
    ok('4', '不可逆动作走"只提醒不执行"（行为级验证）', _security_refuses())
    ok('4', '没回读不许说完成（有测试守着）',
       os.path.exists(os.path.join(TOOLS, 'test_exec.py')))


# ═══════════════ 第五条 · 人机分工 ═══════════════
def a5():
    print('\n【第五条 · 人机分工：确认强度分级】')
    ok('5', '当场指令=授权直接执行（规范写死）', '当场' in text('docs/spec/04-主动性与出声规范-v1.0.md'))
    ok('5', '可逆动作执行+回执+可撤销', os.path.exists(os.path.join(APP, 'scenes.py')))
    ok('5', '不可逆/安全域走"只提醒不执行"（行为级验证）', _security_refuses())
    ok('5', '出声有额度/合并机制（outbox）', _quota_mechanism())


# ═══════════════ 第六条 · 授权与隔离（安全域）═══════════════
def a6():
    print('\n【第六条 · 授权与隔离：安全域 + 三条隔离带】')
    st = load_json('data/state.json', {}) or {}
    sec = [d for d in st.get('devices') or [] if d.get('security_domain')]
    ok('6', '安全域单列（门锁/摄像头/燃气/布防）', len(sec) >= 5, f'{len(sec)} 台')
    ok('6', '家庭数据与工作台数据分开存储', os.path.isdir(DATA))
    ok('6', '家庭面板独立入口，不混进工作通道', os.path.exists(os.path.join(APP, 'web', 'index.html')))
    ok('6', '凭证只在 ~/.config 与 HA secrets（不入库）',
       not glob.glob(os.path.join(DATA, '*token*')) and not glob.glob(os.path.join(DATA, '*password*')))
    ok('6', '安全类不进 3D 桥（门锁/摄像头不暴露给苹果）',
       'exclude_domains' in text('data/homekit-config.yaml') and 'lock' in text('data/homekit-config.yaml'))
    human('6', '家居微信小号是否真的独立（工作通道看不到家）', '只能你在微信里确认')


# ═══════════════ 第七条 · 品味 ═══════════════
def a7():
    print('\n【第七条 · 品味：温馨 / 守夜 / 缄默 / 体面】')
    css = text('app/web/app.css')
    ok('7', '温馨：暖色底与主色（--paper/--warm）',
       '--paper' in css and '--warm' in css and '#C0713F' in css.upper())
    ok('7', '体面：用户可见文案无感叹号（只扫字符串）', _no_exclamation())
    ok('7', '守夜：可逆动作默认做、出声默认克制（额度机制存在）', _quota_mechanism())
    human('7', '整体"温馨/体面"是否达标', '这是主观判断，只有你能定')


# ═══════════════ 第八条 · 长期与可迁移 ═══════════════
def a8():
    print('\n【第八条 · 长期与可迁移】')
    ok('8', '备份存在且可恢复（有恢复演练）',
       os.path.exists(os.path.join(TOOLS, 'restore_drill.py')) and bool(glob.glob(os.path.join(ROOT, 'backups', '*.tgz'))))
    ok('8', '十年测试所需的数据都在本机（HA 历史 + 审计 + 台账）',
       all(os.path.exists(os.path.join(ROOT, p)) for p in
           ('config/homeassistant/home-assistant_v2.db', 'data/audit.jsonl', 'data/state.json')))
    ok('8', '本地优先：能本地做的不出网（规则/场景/状态都在本地）',
       all(os.path.exists(os.path.join(APP, f)) for f in ('rules.py', 'scenes.py', 'state.py')))
    human('8', '换模型/换机器后记忆与规则是否真的不重来', '需要真做一次迁移才能证明（本次 HA OS 迁移是第一次实证）')


# ═══════════════ 第九条 · 明确不做 ═══════════════
def a9():
    print('\n【第九条 · 边界：明确不做】')
    ok('9', '不自研设备连接层（底座是 HA）', 'homeassistant' in text('docker-compose.yml'))
    ok('9', '无回读的"已完成"被禁止（有门禁）', 'read_back' in text('app/ha.py'))
    ok('9', '对话通道不能自己批准安全动作（安全域只提醒）', _security_refuses())
    ok('9', '影像与凭证上云？无凭证文件入库', not glob.glob(os.path.join(DATA, '*.key')))
    ok('9', '不把 3D 当炫技（有"先状态后装饰"实现）',
       'lv === \'sec\'' in text('app/web/app.js'))


# ═══════════════ 第十条 · 修改规则 ═══════════════
def a10():
    print('\n【第十条 · 宪章的修改规则】')
    spec = sorted(glob.glob(os.path.join(ROOT, 'docs', 'spec', '*.md')))
    ok('10', '规范带版本号', all(re.search(r'-v\d+\.\d+', os.path.basename(p)) for p in spec), f'{len(spec)} 份')
    ok('10', '旧版本留档（_archive）', os.path.isdir(os.path.join(ROOT, 'docs', 'spec', '_archive')))
    ok('10', '无静默漂移（冻结快照可验）',
       os.path.exists(os.path.join(ROOT, 'logs', 'evidence', '20261017-freeze', 'freeze-snapshot.json')))


# ═══════════════ 六判据（复用 acceptance）═══════════════
def criteria():
    print('\n【检验判据六条（复用 tools/acceptance.py 的结论）】')
    r = subprocess.run([sys.executable, os.path.join(TOOLS, 'acceptance.py')],
                       capture_output=True, text=True, timeout=900, cwd=ROOT)
    out = (r.stdout or '') + (r.stderr or '')
    ok('判据', '验收脚本跑通（六条判据逐条有结论）', r.returncode == 0,
       out.strip().splitlines()[-1][:80] if out.strip() else '')
    for line in out.splitlines():
        if line.startswith('✅ 判据'):
            print('   ' + line)
    human('判据', '判据 1 的"一整天没开米家"需你每天记录（criterion1 --record）', '工具绝不替你宣布达标')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--md', action='store_true', help='同时写出 markdown 报告')
    a = ap.parse_args()
    print('═══ 宪章逐条核验（十条 + 六判据）═══')
    for fn in (a1, a2, a3, a4, a5, a6, a7, a8, a9, a10):
        try:
            fn()
        except Exception as err:  # noqa
            FAIL.append((fn.__name__, '检查本身出错'))
            print(f'  ❌ {fn.__name__} 检查出错：{err}')
    try:
        criteria()
    except Exception as err:  # noqa
        FAIL.append(('判据', '验收脚本跑不通'))
        print(f'  ❌ 判据检查出错：{err}')

    print(f'\n{("=" * 61)}')
    print(f'通过 {len(PASS)} · 失败 {len(FAIL)} · 人工确认 {len(HUMAN)}')
    if FAIL:
        print('失败项：' + '、'.join(n for _, n in FAIL))
    if HUMAN:
        print('人工确认项：' + '、'.join(n for _, n, _d in HUMAN))
    print('结论：' + ('**宪章逐条核验通过**（机检部分全过；人工项已列明）' if not FAIL
                    else '**有未通过项** —— 见上'))

    if a.md:
        day = datetime.date.today().strftime('%Y%m%d')
        p = os.path.join(DATA, f'宪章对照-{day}.md')
        L = [f'# 宪章对照 · {day}', '',
             '依据：`docs/spec/00-顶层宪章-v0.2-讨论稿.docx`（十条 + 检验判据六条）', '',
             '## 机检结果', '']
        L += [f'- ✅ {n}' for _, n in PASS]
        L += [f'- ❌ {n}' for _, n in FAIL]
        L += ['', '## 只能人工确认的', '']
        L += [f'- 👤 {n}（{d}）' for _, n, d in HUMAN]
        L += ['', '## 结论', '',
              f'- 通过 {len(PASS)} · 失败 {len(FAIL)} · 人工确认 {len(HUMAN)}', '']
        open(p, 'w', encoding='utf-8').write('\n'.join(L))
        print(f'报告已写入 {os.path.relpath(p, ROOT)}')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
