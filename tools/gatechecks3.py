#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门禁检查（第三批）：Q21–Q26 / R09。

从 gatechecks2.py 拆出来：11 §5 要求单文件 ≤600 行。只挪位置、不改判定。
"""
import json
import os
import re
import subprocess
import sys

from gatebase import *  # noqa: F401,F403


def q21():
    """功能设置必须真的接到状态模型上（03 §1D）。

    2026-10-17 踩过的坑：接口回"已改为 X"，但 state.py 根本没读 settings.json，
    改房间/手动录入全都不生效 —— 而且当时所有测试都绕过了这条链。
    这条检查只做一件事：**确认那条调用真的在代码里**。
    """
    t = txt(os.path.join(APP, 'state.py'))
    need = ['import settings', '_apply_override(dev)', '_add_manual_devices(out_devices)', 'room_source']
    miss = [k for k in need if k not in t]
    rec('Q21', '功能设置已接入状态模型（03 §1D）', not miss,
        f'缺 {miss}' if miss else '覆盖应用与手动录入都在链路上')

def q22():
    """待决事项必须被提醒到（用户 2026-10-17 要求：要决定就发消息）。"""
    dp = os.path.join(DATA, 'decisions.json')
    if not os.path.exists(dp):
        rec('Q22', '待决事项带提醒（要决定就发消息）', False, '缺 data/decisions.json'); return
    try:
        items = json.load(open(dp, encoding='utf-8'))
    except ValueError:
        rec('Q22', '待决事项带提醒（要决定就发消息）', False, 'decisions.json 解析失败'); return
    openn = [x for x in items if x.get('status') == 'open']
    sys.path.insert(0, APP)
    import briefing
    txt_b = briefing.compose('evening')
    if openn:
        ok = '等你决定' in txt_b
        rec('Q22', '待决事项带提醒（要决定就发消息）', ok,
            f'未决 {len(openn)} 项，简报{"已提醒" if ok else "**没提醒**"}')
    else:
        rec('Q22', '待决事项带提醒（要决定就发消息）', True, '当前无未决项')

def q23():
    """场景结构化（03 §7 · 验收第 8 条）：可见 / 可编辑 / 可停用 / 可回滚 / 能复述。"""
    t = txt(os.path.join(APP, 'scenes.py'))
    if not t:
        rec('Q23', '场景：可见·可编辑·可停用·可回滚·可复述', False, 'app/scenes.py 缺'); return
    need = ['def describe(', 'def set_enabled(', 'def add_step(', 'def remove_step(', 'def undo(']
    miss = [k for k in need if k not in t]
    # 复述必须出现在界面与接口里（不能只在后端有）
    api = txt(os.path.join(APP, 'server.py'))
    ui = txt(os.path.join(APP, 'web', 'settings.js'))
    wired = ('describe' in api or 'view()' in api) and 'scenes' in ui
    rec('Q23', '场景：可见·可编辑·可停用·可回滚·可复述', (not miss) and wired,
        f'缺 {miss}' if miss else ('机制齐备且已接到界面/接口' if wired else '机制有但没接到界面'))

def r09():
    """生成物约束（11 v1.2 §13）：体积上限 + 构建说明 + 运行期零第三方 JS + 非唯一真相源。"""
    gens = declared_generated()
    if not gens:
        rec('R09', '生成物约束（体积/说明/零第三方）', None, '当前没有生成物'); return
    bad, notes = [], []
    for g in gens:
        size_mb = os.path.getsize(g) / 1024 / 1024
        if size_mb > 1.5:
            bad.append(f'{os.path.basename(g)} {size_mb:.2f}MB > 1.5MB')
        d = os.path.dirname(g)
        if not any(f.endswith('.build.md') for f in os.listdir(d)):
            bad.append(f'{os.path.basename(g)} 缺 .build.md 构建说明')
        t = txt(g)
        if re.search(r'<script[^>]+src="https?://', t) or 'node_modules' in t:
            bad.append(f'{os.path.basename(g)} 运行期引用了外部 JS')
        notes.append(f'{os.path.basename(g)} {size_mb:.2f}MB')
    rec('R09', '生成物约束（体积/说明/零第三方）', not bad,
        '; '.join(bad) if bad else ' + '.join(notes))

def q24():
    """自然语言创建规则（03 §7 后半）：能解析、会复述、做不到就明说、落底座要备份+校验+回读。"""
    t = txt(os.path.join(APP, 'rules.py'))
    if not t:
        rec('Q24', '规则：自然语言创建（复述+可行性+回读）', False, 'app/rules.py 缺'); return
    need = ['def parse(', 'def describe(', 'def needs(', 'def commit(', 'def set_enabled(']
    miss = [k for k in need if k not in t]
    # 三条诚实性硬要求：做不到要给替代方案 / 写前备份 / 校验失败要回退 / 必须回读
    checks = {
        '可行性判断': 'condition_feasible' in t,
        '做不到给替代方案': '可以改成不带条件的' in t,
        '写前备份': '.bak-' in t,
        '校验失败回退': 'check_config' in t and '已回退' in t,
        '写入后回读': 'read_back' in t,
    }
    bad = [k for k, v in checks.items() if not v]
    api = txt(os.path.join(APP, 'server.py'))
    wired = '/api/rule/propose' in api and '/api/rule/commit' in api
    ok = (not miss) and (not bad) and wired
    rec('Q24', '规则：自然语言创建（复述+可行性+回读）', ok,
        f'缺 {miss}' if miss else (f'缺 {bad}' if bad else ('机制齐备且已接线' if wired else '没接到接口')))

def q25():
    """投递链（04）："决定要说"必须真的能送到，且旁观者通道必须脱敏、未接通通道不许假装成功。"""
    t = txt(os.path.join(APP, 'outbox.py'))
    if not t:
        rec('Q25', '投递链（脱敏 + 未接通如实报告）', False, 'app/outbox.py 缺'); return
    checks = {
        '有投递入口': 'def deliver(' in t,
        '有完整链路': 'def speak_and_deliver(' in t,
        '旁观者通道脱敏': 'PUBLIC_CHANNELS' in t and 'def _masked(' in t,
        '未接通如实报告': 'not_connected' in t,
        '合并成一条': 'def compose(' in t,
        '可查最近说过什么': 'def recent(' in t,
    }
    bad = [k for k, v in checks.items() if not v]
    api = txt(os.path.join(APP, 'server.py'))
    wired = '/api/outbox' in api and '/api/notify/run' in api
    # 定时触发必须存在（否则"主动性"只是能手动跑）
    agents = os.path.expanduser('~/Library/LaunchAgents')
    has_agent = os.path.exists(os.path.join(agents, 'com.simon.smarthome-notify.plist'))
    ok = (not bad) and wired and has_agent
    rec('Q25', '投递链（脱敏 + 未接通如实报告）', ok,
        f'缺 {bad}' if bad else ('' if (wired and has_agent) else
                                 ('没接到接口' if not wired else '缺定时触发（主动性不会自己发生）')))

def q26():
    """扫地机地图推送钩子：必须真的在盯，且首次运行不许谎报"收到新数据"。"""
    t = txt(os.path.join(TOOLS, 'map_watch.py'))
    if not t:
        rec('Q26', '地图推送钩子（不谎报 + 定时在盯）', False, 'tools/map_watch.py 缺'); return
    checks = {
        '不谎报首次': 'first_run' in t and 'new = {} if first_run' in t,
        '落盘可追溯': "'snapshot': snap" in t,
        '只认有值的项': 'def _meaningful(' in t,
        '认的是地图三个属性': 'p_6_1' in t and 'p_6_3' in t and 'p_6_8' in t,
    }
    bad = [k for k, v in checks.items() if not v]
    agents = os.path.expanduser('~/Library/LaunchAgents')
    has_agent = os.path.exists(os.path.join(agents, 'com.simon.smarthome-mapwatch.plist'))
    ok = (not bad) and has_agent
    rec('Q26', '地图推送钩子（不谎报 + 定时在盯）', ok,
        f'缺 {bad}' if bad else ('' if has_agent else '缺定时（不会自己去盯）'))

def q27():
    """判据 1（头号验收）必须有可追溯的记录机制，且**绝不能自动宣布达标**。"""
    t = txt(os.path.join(TOOLS, 'criterion1.py'))
    if not t:
        rec('Q27', '判据 1 追踪（不自动宣布达标）', False, 'tools/criterion1.py 缺'); return
    checks = {
        '只认 pass/fail 记录': "'pass'" in t and "'fail'" in t and 'unknown' in t,
        '没记录就是未记录': "'unknown'" in t and '今天还没记录' in t,
        '未达标必须写原因': '必须写一句为什么' in t,
        '汇集项必须带来源': "'evidence'" in t,
        '算连续天数': 'def streak(' in t,
    }
    bad = [k for k, v in checks.items() if not v]
    # 简报里必须每天提醒（否则用户想不起来记）
    import sys as _s
    _s.path.insert(0, APP)
    import briefing as _b
    in_brief = '判据 1' in _b.compose('evening')
    rec('Q27', '判据 1 追踪（不自动宣布达标）', (not bad) and in_brief,
        f'缺 {bad}' if bad else ('' if in_brief else '简报里没有这一行，用户会忘记记'))

def q28():
    """备份与恢复演练的机械约束（P5）：
    ① 可再下载的大文件不得进备份（实测踩坑：327MB 的 HA OS 镜像把备份撑到 372MB）
    ② 备份必须有体积自检
    ③ 恢复演练必须有"让 HA 真的拿恢复出的配置校验"的深模式
    """
    bk = txt(os.path.join(TOOLS, 'backup.sh'))
    rd = txt(os.path.join(TOOLS, 'restore_drill.py'))
    if not bk or not rd:
        rec('Q28', '备份体积与深演练', False, '缺 backup.sh 或 restore_drill.py'); return
    checks = {
        '备份排除可再下载的大文件': "--exclude='./data/images'" in bk,
        '备份有体积自检': 'MAX_MB' in bk and '体积自检' in bk,
        '深演练会真跑 HA 校验': '--script' in rd and 'check_config' in rd,
        '深演练含历史库完整性': 'quick_check' in rd,
        '深演练知道 colima 共享目录的坑': 'colima' in rd.lower() or 'logs' in rd and 'archive' in rd,
    }
    bad = [k for k, v in checks.items() if not v]
    rec('Q28', '备份体积与深演练', not bad, f'缺 {bad}' if bad else '体积上限 + 深演练（真校验）都在')

def q29():
    """外部改动入账（宪章第三条"推翻要留痕" + 第四条"不许冒充回执"）。"""
    t = txt(os.path.join(TOOLS, 'state_watch.py'))
    if not t:
        rec('Q29', '外部改动入账（我方 vs 外部）', False, 'tools/state_watch.py 缺'); return
    checks = {
        '区分我方与外部': "'self'" in t and "'external'" in t,
        '首次只建基线': 'first_run' in t and '只建立基线' in t,
        '每条带证据': "'evidence'" in t,
        '记录前后值': "'from'" in t and "'to'" in t,
        '只看我方动作痕迹': 'def self_actions(' in t,
    }
    bad = [k for k, v in checks.items() if not v]
    agents = os.path.expanduser('~/Library/LaunchAgents')
    has_agent = os.path.exists(os.path.join(agents, 'com.simon.smarthome-statewatch.plist'))
    api = txt(os.path.join(APP, 'server.py'))
    wired = '/api/changes' in api
    ui = txt(os.path.join(APP, 'web', 'app.js'))
    shown = 'chgBox' in ui
    ok = (not bad) and has_agent and wired and shown
    why = f'缺 {bad}' if bad else ('' if (has_agent and wired and shown) else
                                   f'{"缺定时" if not has_agent else ""}{"缺接口" if not wired else ""}{"界面没显示" if not shown else ""}')
    rec('Q29', '外部改动入账（我方 vs 外部）', ok, why or '记账 + 定时 + 接口 + 设备详情可见')

def q30():
    """迁移预检/后检（P5）：有基线、有比对、有"迁移后会变什么"的提醒。"""
    t = txt(os.path.join(TOOLS, 'migrate_check.py'))
    if not t:
        rec('Q30', '迁移预检/后检', False, 'tools/migrate_check.py 缺'); return
    checks = {
        '有预检': 'def pre(' in t and '--pre' in t,
        '有后检': 'def post(' in t and '--post' in t,
        '后检与基线逐条比对': 'BASELINE' in t and 'baseline' in t,
        '记基线文件': 'migration-baseline' in t,
        '列出迁移后会变的东西': 'warn(' in t and '迁移后会变' in t,
        '产出证据': '_write_evidence' in t,
    }
    bad = [k for k, v in checks.items() if not v]
    rec('Q30', '迁移预检/后检', not bad, f'缺 {bad}' if bad else '基线 + 逐条比对 + 变化点提醒 + 证据')

def q31():
    """资源实测（05 §8 / P5）：既要测底座，也要测**我们自己的**常驻进程与定时任务。"""
    t = txt(os.path.join(TOOLS, 'resource_audit.py'))
    if not t:
        rec('Q31', '资源实测覆盖自有进程', False, 'tools/resource_audit.py 缺'); return
    checks = {
        '测虚拟机与容器': 'colima' in t and 'stats' in t,
        '测自有常驻进程': 'args' in t and 'server.py' in t,
        '测定时任务': 'launchctl' in t,
        '对照规范预算': '§8' in t or '预算' in t,
        '产出证据': 'evidence' in t,
    }
    bad = [k for k, v in checks.items() if not v]
    rec('Q31', '资源实测覆盖自有进程', not bad, f'缺 {bad}' if bad else '底座 + 自有进程 + 定时任务 + 预算对照')

def q32():
    """苹果侧曝露面红线（05 v1.1 §9-2 · 08 v1.2 §7）：只允许 A 类；安全域/门锁/摄像头/在家 一律不得出现；
    安全类读数只能是只读实体。**这条不通过就说明红线被踩了。**
    """
    t = txt(os.path.join(TOOLS, 'homekit_plan.py'))
    if not t:
        rec('Q32', '苹果曝露面红线（只允许 A 类）', False, 'tools/homekit_plan.py 缺'); return
    plan_path = os.path.join(DATA, 'homekit-exposure.json')
    if not os.path.exists(plan_path):
        rec('Q32', '苹果曝露面红线（只允许 A 类）', False, '清单还没生成（跑 tools/homekit_plan.py）'); return
    try:
        doc = json.load(open(plan_path, encoding='utf-8'))
    except ValueError:
        rec('Q32', '苹果曝露面红线（只允许 A 类）', False, '清单解析失败'); return
    inc = doc.get('include') or []
    bad = []
    for x in inc:
        dom = (x.get('entity_id') or '').split('.')[0]
        if dom in ('lock', 'camera', 'device_tracker', 'person', 'vacuum'):
            bad.append(f"{x.get('device')}→{dom}")
        if x.get('class') == 'A-readonly' and dom not in ('sensor', 'binary_sensor'):
            bad.append(f"{x.get('device')}→安全类暴露了可执行实体")
        nm = (x.get('device') or '') + (x.get('entity_id') or '')
        if any(k in nm for k in ('门锁', '摄像', '在家', '离家', '人体')):
            bad.append(f"{x.get('device')}→名字命中安全/行为类")
    rec('Q32', '苹果曝露面红线（只允许 A 类）', not bad,
        f'越界 {bad[:3]}' if bad else f"{len(inc)} 台可暴露（安全域 0 台）")

def q33():
    """迁移演练准备（P5）：就绪检查 + 手册 + 关键验收点（mDNS / 安全域红线）都在。"""
    t = txt(os.path.join(TOOLS, 'air_check.py'))
    rb = txt(os.path.join(DATA, 'runbook-air-rehearsal.md'))
    if not t or not rb:
        rec('Q33', '迁移演练准备（Air 就绪 + 手册）', False, '缺 air_check.py 或演练手册'); return
    checks = {
        '就绪检查只读不改': 'def check_air(' in t and '--json' in t,
        '未通电时如实说不通': '唤醒' in t and '远程登录' in t,
        '手册含关键验收点 mDNS': 'mDNS' in rb,
        '手册不许假装通过': ('不假装' in rb) or ('未验证' in rb),
        '手册含安全域红线': 'homekit-exposure' in rb and '安全域' in rb,
        '手册含"不碰家里"': '不碰家里' in rb,
    }
    bad = [k for k, v in checks.items() if not v]
    rec('Q33', '迁移演练准备（Air 就绪 + 手册）', not bad,
        f'缺 {bad}' if bad else '只读检查 + 手册 + mDNS/红线验收点')

def q34():
    """降级路径（03 §12）+ 状态新鲜度自愈：不顺的时候还敢不敢说真话。"""
    checks = {}
    t = txt(os.path.join(TOOLS, 'test_degrade.py'))
    checks['有降级测试'] = bool(t) and 'HA 不通' in t and '没做成' in t
    checks['测安全域双保险'] = bool(t) and 'HA 不通时安全域仍然被拒' in t
    sv = txt(os.path.join(APP, 'server.py'))
    checks['刷新接口支持 POST'] = "_refresh" in sv and "if path == '/api/refresh':" in sv
    ui = txt(os.path.join(APP, 'web', 'app.js'))
    checks['UI 有"偏旧就明说"'] = 'staleBar' in ui and '中枢可能连不上' in ui
    checks['UI 打开时自愈'] = 'api/refresh' in ui or "'/api/refresh'" in ui
    agents = os.path.expanduser('~/Library/LaunchAgents')
    checks['状态有定时刷新'] = os.path.exists(os.path.join(agents, 'com.simon.smarthome-state.plist'))
    bad = [k for k, v in checks.items() if not v]
    rec('Q34', '降级路径 + 状态新鲜度自愈', not bad,
        f'缺 {bad}' if bad else 'HA 不通说实话 + 安全域双保险 + 偏旧明说 + 每 5 分钟刷新')

def q35():
    """周期性能力必须有驱动（清单 ↔ LaunchAgent 一致）。

    为什么要有：这个项目反复出现"功能写了、没人驱动它"的缺口 ——
    状态不刷新、通知不投递、备份不执行，都属于这一类，而且**不会报错**，只会静悄悄地不干活。
    """
    import plistlib
    path = os.path.join(DATA, 'automation-manifest.json')
    if not os.path.exists(path):
        rec('Q35', '周期性能力都有驱动（清单↔定时任务）', False, '缺 data/automation-manifest.json'); return
    try:
        m = json.load(open(path, encoding='utf-8'))
    except ValueError:
        rec('Q35', '周期性能力都有驱动（清单↔定时任务）', False, '清单解析失败'); return
    agents_dir = os.path.expanduser('~/Library/LaunchAgents')
    missing, unref = [], []
    for j in m.get('jobs') or []:
        ap = os.path.join(agents_dir, j['agent'] + '.plist')
        if not os.path.exists(ap):
            missing.append(f"{j['id']}（缺 {j['agent']}）")
            continue
        try:
            d = plistlib.load(open(ap, 'rb'))
        except Exception:  # noqa
            missing.append(f"{j['id']}（plist 读不了）")
            continue
        args = ' '.join(d.get('ProgramArguments') or [])
        if os.path.basename(j['script']) not in args:
            unref.append(f"{j['id']}（{j['agent']} 没在跑 {j['script']}）")
    bad = missing + unref
    rec('Q35', '周期性能力都有驱动（清单↔定时任务）', not bad,
        ('缺 ' + '、'.join(bad[:3])) if bad else f"{len(m.get('jobs') or [])} 项都有驱动")

def q36():
    """开机自启覆盖（P5 健壮性）：重启后这套东西要能自己起来。

    2026-10-17 实测缺口：工作台服务是用 nohup 起的 → 重启后工作台（含 Tailscale 入口与
    DSH 插件 iframe）就没了。现在由 LaunchAgent 管，KeepAlive 已实测（kill -9 后自动拉起）。
    """
    import plistlib
    path = os.path.join(DATA, 'automation-manifest.json')
    if not os.path.exists(path):
        rec('Q36', '开机自启覆盖（服务与定时任务）', False, '缺 automation-manifest.json'); return
    m = json.load(open(path, encoding='utf-8'))
    svcs = m.get('services') or []
    if not svcs:
        rec('Q36', '开机自启覆盖（服务与定时任务）', False, '清单里没有 services 段'); return
    bad = []
    for s in svcs:
        agent = s.get('agent') or ''
        if agent.startswith('('):                     # docker restart policy 这类，另判
            continue
        ap = os.path.expanduser(f'~/Library/LaunchAgents/{agent}.plist')
        if not os.path.exists(ap):
            bad.append(f"{s['id']}（缺 {agent}）")
            continue
        try:
            d = plistlib.load(open(ap, 'rb'))
        except Exception:  # noqa
            bad.append(f"{s['id']}（plist 读不了）")
            continue
        if s.get('keep_alive') and not d.get('KeepAlive'):
            bad.append(f"{s['id']}（没有 KeepAlive，崩了不会自己回来）")
        if not (d.get('RunAtLoad') or d.get('KeepAlive')):
            bad.append(f"{s['id']}（既不 RunAtLoad 也不 KeepAlive）")
    # 容器重启策略
    try:
        rp = subprocess.run(['docker', 'inspect', 'homeassistant', '--format',
                             '{{.HostConfig.RestartPolicy.Name}}'],
                            capture_output=True, text=True, timeout=20).stdout.strip()
        if rp not in ('unless-stopped', 'always'):
            bad.append(f'HA 容器重启策略={rp or "未知"}')
    except Exception:  # noqa
        bad.append('查不到 HA 容器重启策略')
    rec('Q36', '开机自启覆盖（服务与定时任务）', not bad,
        ('缺 ' + '；'.join(bad[:3])) if bad else f"{len(svcs)} 个常驻服务都有自启")

def q37():
    """长期维护：日志轮转 + 磁盘守护（这两件事失效时都是静默的）。"""
    t = txt(os.path.join(TOOLS, 'maintain.py'))
    if not t:
        rec('Q37', '长期维护（日志轮转 + 磁盘守护）', False, 'tools/maintain.py 缺'); return
    checks = {
        '有轮转阈值': 'LOG_MAX_BYTES' in t and 'LOG_KEEP_LINES' in t,
        '轮转前归档原文': 'ARCHIVE' in t and 'copy2' in t,
        '磁盘三档判定': 'DISK_WARN_GB' in t and 'DISK_CRIT_GB' in t and "'crit'" in t,
        '不碰证据目录': 'evidence' in t,
        '有 dry 模式': '--dry' in t,
    }
    bad = [k for k, v in checks.items() if not v]
    agents = os.path.expanduser('~/Library/LaunchAgents')
    has_agent = os.path.exists(os.path.join(agents, 'com.simon.smarthome-maintain.plist'))
    # _health 相关代码可能待在 server.py 或拆出去的 server_ext.py（11 §5 的 600 行上限）——
    # 检查要跟着代码走，不能因为换了文件就判"没暴露"（2026-10-17 实测踩到）。
    api = txt(os.path.join(APP, 'server.py')) + txt(os.path.join(APP, 'server_ext.py'))
    exposed = 'disk' in api and 'maintain' in api
    brief = txt(os.path.join(APP, 'briefing.py'))
    only_when_low = "!= 'ok'" in brief or '!= "ok"' in brief
    ok = (not bad) and has_agent and exposed and only_when_low
    why = f'缺 {bad}' if bad else ('' if (has_agent and exposed and only_when_low) else
                                   f'{"缺定时" if not has_agent else ""}{"状态页没暴露" if not exposed else ""}{"简报会滥用告警" if not only_when_low else ""}')
    rec('Q37', '长期维护（日志轮转 + 磁盘守护）', ok, why or '轮转+归档+磁盘三档+仅偏低时提醒+定时')

def q38():
    """24h 在线的物理前提必须可机械复核（否则"整天在线"只是感觉）。"""
    t = txt(os.path.join(TOOLS, 'uptime_check.py'))
    if not t:
        rec('Q38', '24h 在线就绪可复核', False, 'tools/uptime_check.py 缺'); return
    checks = {
        '查睡眠': "pmset_value('sleep')" in t or "'sleep'" in t,
        '查断电自启': "'autorestart'" in t,
        '查自动登录': 'auto_login_user' in t,
        '查自启覆盖': 'autostart_coverage' in t,
        '风险提示（不误判为阻塞）': "'warnings'" in t and 'blocker=False' in t,
        '标注谁来改': 'WHO' in t and '需要你' in t,
    }
    bad = [k for k, v in checks.items() if not v]
    acc = txt(os.path.join(TOOLS, 'acceptance.py'))
    wired = 'uptime_check' in acc
    ok = (not bad) and wired
    rec('Q38', '24h 在线就绪可复核', ok,
        f'缺 {bad}' if bad else ('' if wired else '验收里没接'))

def q39():
    """状态层要能脱离 HA 的文件（迁移到 HA OS 后文件在虚拟机里读不到）。

    2026-10-17 实测：官方 API 提供同样的数据 —— WebSocket 注册表（实体 1025/设备 68/区域 10）
    与 REST 历史。所以状态层可以做到"与部署形态无关"（宪章第八条 可迁移）。
    """
    t = txt(os.path.join(APP, 'ha_ws.py'))
    if not t:
        rec('Q39', '官方 API 路径可用（不依赖 HA 文件）', False, 'app/ha_ws.py 缺'); return
    checks = {
        '只用标准库': not any(f'import {m}' in t for m in ('requests', 'websocket', 'aiohttp')),
        '能取三张注册表': 'entity_registry/list' in t and 'device_registry/list' in t and 'area_registry/list' in t,
        '连不上如实报错（不返回空表）': 'HaWsError' in t and '不返回空表' in t,
        '有探针给迁移检查用': 'def probe(' in t,
    }
    bad = [k for k, v in checks.items() if not v]
    mc = txt(os.path.join(TOOLS, 'migrate_check.py'))
    wired = 'api_probe' in mc
    agent_missing = not os.path.exists(os.path.join(TOOLS, 'test_ha_ws.py'))
    ok = (not bad) and wired and not agent_missing
    rec('Q39', '官方 API 路径可用（不依赖 HA 文件）', ok,
        f'缺 {bad}' if bad else ('' if (wired and not agent_missing) else '迁移检查里没接'))

def q40():
    """状态层要有"官方 API 优先、文件兜底"两条路，并**如实记录用了哪条**。

    为什么必须：迁到 HA OS 后 HA 的文件在虚拟机里读不到，只有 API 这条路。
    而"兜底"必须留痕 —— 否则会分不清"这份状态是 API 来的还是积压文件来的"。
    """
    t = txt(os.path.join(APP, 'state.py'))
    if not t:
        rec('Q40', '状态层 API 优先 + 文件兜底（来源留痕）', False, 'app/state.py 缺'); return
    checks = {
        '有来源开关': 'SMART_HOME_STATE_SOURCE' in t,
        '有 API 注册表路径': 'def read_registries_api(' in t,
        '有 API 状态路径': 'def read_states_api(' in t,
        '有文件兜底': "SOURCE_USED['registries'] = SOURCE_USED['registries'] or 'files'" in t,
        '字段名对齐（area_id→id）': "a.get('area_id')" in t,
        '产物记录来源': "'data_source'" in t,
        'api 模式失败不静默': "if STATE_SOURCE == 'api':" in t and 'raise' in t,
    }
    bad = [k for k, v in checks.items() if not v]
    has_test = os.path.exists(os.path.join(TOOLS, 'test_state_source.py'))
    ok = (not bad) and has_test
    rec('Q40', '状态层 API 优先 + 文件兜底（来源留痕）', ok,
        f'缺 {bad}' if bad else ('' if has_test else '缺等价性测试'))

def q41():
    """校准也要能脱离 HA 的文件（迁移后 recorder 库在虚拟机里）。"""
    t = txt(os.path.join(TOOLS, 'calibrate_offline.py'))
    if not t:
        rec('Q41', '校准可走历史 API（不依赖 recorder 文件）', False, 'tools/calibrate_offline.py 缺'); return
    checks = {
        '有来源开关': 'SMART_HOME_CALIB_SOURCE' in t,
        '有历史 API 路径': 'def fetch_rows_api(' in t and '/api/history/period' in t,
        '每台多取几个实体': 'MAX_ENTITIES_PER_DEVICE' in t,
        '产物记录来源': "'source': source" in t,
        '拿不到数据源就如实退出': '不产出假数据' in t,
        'api 模式失败不静默': "if CALIB_SOURCE == 'api':" in t,
    }
    bad = [k for k, v in checks.items() if not v]
    rec('Q41', '校准可走历史 API（不依赖 recorder 文件）', not bad,
        f'缺 {bad}' if bad else 'API 优先 + 容器兜底 + 来源留痕 + 不产假数据')

def q42():
    """HA OS 虚拟机的开机自启（④ 路线的最后一块拼图）。

    迁移前没有虚拟机是正常的：此时不算失败，只如实说明。
    一旦检测到虚拟机，**没有自启就必须红** —— 否则 Mac 重启后 HA 不会自己回来，而且不报错。
    """
    t = txt(os.path.join(TOOLS, 'vm_autostart.py'))
    if not t:
        rec('Q42', 'HA OS 虚拟机开机自启（迁移后必须）', False, 'tools/vm_autostart.py 缺'); return
    checks = {
        '有 install 装机逻辑': 'def install(' in t and 'RunAtLoad' in t,
        '能读出已装的自启': 'def installed_vm_id(' in t,
        '登记进清单（Q36 一起守）': "'haos-vm'" in t and 'services' in t,
        '迁移前不误判为失败': '尚未建虚拟机' in t,
        '有测试': os.path.exists(os.path.join(TOOLS, 'test_vm_autostart.py')),
    }
    bad = [k for k, v in checks.items() if not v]
    if bad:
        rec('Q42', 'HA OS 虚拟机开机自启（迁移后必须）', False, f'缺 {bad}'); return
    # 真实环境抽查：有虚拟机就必须有自启
    try:
        r = subprocess.run([sys.executable, os.path.join(TOOLS, 'vm_autostart.py'), '--check'],
                           capture_output=True, text=True, timeout=40)
        ok = r.returncode == 0
        last = (r.stdout or '').strip().splitlines()[-1] if r.stdout else ''
        rec('Q42', 'HA OS 虚拟机开机自启（迁移后必须）', ok, last or '检查未通过')
    except Exception as err:  # noqa
        rec('Q42', 'HA OS 虚拟机开机自启（迁移后必须）', False, str(err)[:60])
