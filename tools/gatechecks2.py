#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门禁检查：07 数据与记忆 / 08 安全与隐私 / 09 开发验收 / 11 代码规范。"""
import json
import os
import re
import subprocess
import sys
import urllib.request

from gatebase import *  # noqa


# ═══════════ 07 数据与记忆 ═══════════
def m01():
    bad = []
    for d in devices():
        if not (d.get('source') and d.get('confidence') and d.get('status_at')):
            bad.append(d.get('name'))
        elif not d.get('observed_at') and not d.get('observed_note'):
            bad.append(d.get('name') + '(无时间且未说明)')
    rec('M01', '状态三要素齐备（来源/可信度/时间）', not bad, f'缺 {bad[:3]}' if bad else f'{len(devices())} 台齐备')


def m02():
    _guard = os.environ.get('SMART_HOME_FORBIDDEN_DIR', '')
    leak = bool(_guard) and os.path.realpath(DATA).startswith(_guard)
    rec('M02', '家庭数据与个人工作台分域', not leak, f'数据目录 {os.path.relpath(DATA, ROOT)}')


def m03():
    """C 类 = 影像内容与凭证。只查真正的载荷与字段名，
    不查 entity_id 里恰好出现的 image/video 字样（那不是影像数据）。"""
    def walk(o, path=''):
        if isinstance(o, dict):
            for k, v in o.items():
                yield from walk(v, f'{path}.{k}' if path else k)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                yield from walk(v, path)
        else:
            yield path, o
    bad = []
    for k, v in walk(state()):
        key = k.split('.')[-1].lower()
        if key in ('image', 'video', 'rtsp', 'password', 'token', 'credential', 'snapshot', 'stream_url'):
            bad.append(k)
        if isinstance(v, str) and (v.startswith('rtsp://') or v.startswith('data:image/') or len(v) > 400):
            bad.append(k + '(疑似载荷)')
    rec('M03', 'C 类数据不进上下文（影像/凭证）', not bad, f'发现 {bad[:3]}' if bad else '无影像/凭证字段')


def m04():
    bad = []
    for base, _, fs in os.walk(APP):
        for f in fs:
            if re.search(r'DELETE\s+FROM\s+audit|remove_audit|drop\s+table\s+audit', txt(os.path.join(base, f)), re.I):
                bad.append(f)
    rec('M04', '审计只追加（无删除路径）', not bad, f'发现删除实现 {bad}' if bad else '未发现删除实现')


def m05():
    ok = has(os.path.join(APP, 'export.py'))
    rec('M05', '数据可导出（十年可读）', ok, 'JSON + CSV 导出脚本就位' if ok else 'app/export.py 缺')


# ═══════════ 08 安全与隐私 ═══════════
def s01():
    p = os.path.join(DATA, 'security-domain.json')
    if not has(p):
        rec('S01', '安全域清单存在且可核对', False, '缺 security-domain.json'); return
    listed = set((js(p, {}) or {}).get('devices') or [])
    actual = {d['name'] for d in devices() if d.get('security_domain')}
    ok = bool(listed) and listed == actual
    rec('S01', '安全域清单与台账一致', ok, f'差 {sorted(listed ^ actual)[:3]}' if not ok else f'{len(listed)} 台一致')


def s02():
    hits = []
    for base, dirs, fs in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in ('config', 'vendor', 'backups', '.git', 'registry-snapshots', 'tmp')]
        for f in fs:
            if f.endswith(('.py', '.js', '.html', '.css', '.md', '.json', '.yml', '.yaml', '.sh', '.txt')):
                p = os.path.join(base, f)
                if CRED_PAT.search(txt(p)):
                    hits.append(os.path.relpath(p, ROOT))
    rec('S02', '无凭证进入代码/文档', not hits, f'命中 {hits[:3]}' if hits else '未发现')


def s03():
    _guard = os.environ.get('SMART_HOME_FORBIDDEN_DIR', '')
    leak = bool(_guard) and os.path.realpath(DATA).startswith(_guard)
    rec('S03', '隔离带：家庭域与工作台域不通', not leak, '数据域独立')


def s04():
    """静态检查：代码里不得出现对 lock./camera. 实体的服务调用。
    注意：正则要求实体域名的点号（否则 'blocking=True' 里的 'block' 会误报）。
    本检查有天然上限（变量拼接绕得过），真正的守门是运行期拒执测试（P4）。"""
    bad = []
    pat = re.compile(r"call_service\([^)]*\b(?:lock|camera)\.")
    for base, _, fs in os.walk(APP):
        for f in fs:
            if pat.search(txt(os.path.join(base, f))):
                bad.append(f)
    rec('S04', '代码里安全域动作不可自动执行（静态）', not bad,
        f'发现 {bad}' if bad else '未发现对 lock./camera. 的服务调用')


def s05():
    code = all_js()
    ok = ('安全域' in code) and ('未接通' in code)
    rec('S05', '安全域设备只读、无可执行动作', ok, '安全域标注 + 动作未接通' if ok else '缺标注')


# ═══════════ 09 开发验收与运维 ═══════════
def q01():
    rec('Q01', '门禁脚本可运行', True, os.path.relpath(os.path.abspath(__file__), ROOT))


def q02():
    ev = os.path.join(LOGS, 'evidence')
    if not os.path.isdir(ev):
        rec('Q02', '验收证据留档（含门禁报告）', False, 'logs/evidence 缺'); return
    rounds = sorted(d for d in os.listdir(ev) if os.path.isdir(os.path.join(ev, d)))
    ok = bool(rounds) and any(has(os.path.join(ev, r, 'gate-report.txt')) for r in rounds)
    rec('Q02', '验收证据留档（含门禁报告）', ok, f'{len(rounds)} 份，最新 {rounds[-1] if rounds else "无"}')


def q03():
    s = state()
    ok = bool(s.get('generated_at') and s.get('source') and s.get('devices'))
    rec('Q03', '数据可追溯（生成时间 + 来源）', ok, f"{s.get('source')} @ {str(s.get('generated_at'))[11:16]}")


def q04():
    fs = [f for f in os.listdir(LOGS) if not os.path.isdir(os.path.join(LOGS, f))] if os.path.isdir(LOGS) else []
    rec('Q04', '运行日志存在', bool(fs), f'{len(fs)} 个日志文件')


def q05():
    b = os.path.join(ROOT, 'backups')
    fs = [f for f in os.listdir(b)] if os.path.isdir(b) else []
    rec('Q05', '备份存在（恢复演练见 P5）', bool(fs), f'{len(fs)} 份备份' if fs else 'backups/ 为空')


def q06():
    bad = []
    for f in (os.listdir(TOOLS) if os.path.isdir(TOOLS) else []):
        if re.search(r'\|\s*grep\b', txt(os.path.join(TOOLS, f))):
            bad.append(f)
    rec('Q06', '脚本不吞退出码（不用管道）', not bad, str(bad) if bad else '未发现')


def q07():
    """测试套件（数据层正确性 + 界面/接口链路）必须全绿。"""
    if not server_up():
        rec('Q07', '测试套件全绿（数据层 + 界面）', None, '工作台服务未启动，界面测试无法运行'); return
    res = {}
    # 跑测试前记下审计条数：**测试绝不许改动生产留痕**（实测踩过：演练请求与校验请求写进审计）
    audit_file = os.path.join(DATA, 'audit.jsonl')
    audit_before = sum(1 for _ in open(audit_file, encoding='utf-8')) if os.path.exists(audit_file) else 0
    # 给测试子进程注入随机标记；测试若写生产审计，行里会带 tag → 确定性判定。
    # **不能比行数**：后台服务（投递/巡检）本来就正常写审计，行数一直在变（2026-10-17 实测误报）。
    tag = 'q07b-' + os.urandom(6).hex()
    test_env = dict(os.environ, SMART_HOME_AUDIT_TAG=tag)
    for name in ('test_state.py', 'test_ui.py', 'test_intent.py', 'test_p4.py', 'test_panel.py', 'test_settings.py', 'test_calib.py', 'test_pipeline.py', 'test_exec.py', 'test_http.py', 'test_scenes.py', 'test_rules.py', 'test_outbox.py', 'test_mapwatch.py', 'test_criterion1.py', 'test_statewatch.py', 'test_homekit.py', 'test_aircheck.py', 'test_degrade.py', 'test_drivers.py', 'test_maintain.py', 'test_uptime.py', 'test_ha_ws.py', 'test_state_source.py', 'test_vm_autostart.py', 'test_homekit_config.py', 'test_mdns.py', 'test_preflight.py', 'test_paths.py', 'test_verify_image.py', 'test_post_migration.py', 'test_audit_ha_calls.py', 'test_freeze_snapshot.py', 'test_backup_atomic.py', 'test_dsh_plugin.py'):
        fp = os.path.join(TOOLS, name)
        if not has(fp):
            res[name] = 'missing'
            continue
        try:
            r = subprocess.run([sys.executable, fp], capture_output=True, text=True,
                               timeout=300, env=test_env)
            res[name] = r.returncode
        except Exception as e:  # noqa
            res[name] = f'err:{e}'
    ok = all(v == 0 for v in res.values())
    audit_after = sum(1 for _ in open(audit_file, encoding='utf-8')) if os.path.exists(audit_file) else 0
    polluted = []
    if os.path.exists(audit_file):
        with open(audit_file, encoding='utf-8') as f:
            for line in f:
                if tag in line:
                    polluted.append(line[:80])
    clean = not polluted
    rec('Q07', '测试套件全绿（数据层 + 界面）', ok, ' / '.join(f'{k}={v}' for k, v in res.items()))
    rec('Q07b', '测试不改动生产审计（留痕不被测试污染）', clean,
        (f'测试写入 {len(polluted)} 条：{polluted[:1]}' if not clean
         else f'无测试写入（审计 {audit_before} → {audit_after}，后台服务正常留痕）'))


# ═══════════ 11 代码规范 ═══════════
def py_files():
    out = []
    for d in (APP, TOOLS):
        for base, _, fs in os.walk(d):
            out += [os.path.join(base, f) for f in fs if f.endswith('.py')]
    return sorted(out)


def r01():
    rec('R01', '代码规范文档存在（11）', bool(spec_md('11')), '在' if spec_md('11') else '缺')


def r02():
    import py_compile
    bad = []
    for f in py_files():
        try:
            py_compile.compile(f, doraise=True, cfile='/tmp/_pyc_check.pyc')
        except Exception as e:  # noqa
            bad.append(f'{os.path.basename(f)}: {e}')
    rec('R02', '所有 Python 文件可编译', not bad, str(bad[:2]) if bad else f'{len(py_files())} 个文件通过')


def r03():
    bad = []
    for f in py_files() + [os.path.join(TOOLS, x) for x in os.listdir(TOOLS) if x.endswith('.sh')]:
        head = '\n'.join(txt(f).splitlines()[:25])
        if ('"""' not in head) and ('#' not in head):
            bad.append(os.path.basename(f))
    rec('R03', '每个脚本有文件头说明', not bad, f'缺说明 {bad}' if bad else '全部有')


def r04():
    bad = []
    for f in py_files() + [os.path.join(APP, 'web', x) for x in os.listdir(os.path.join(APP, 'web'))] if os.path.isdir(os.path.join(APP, 'web')) else py_files():
        if os.path.isfile(f) and not is_generated(f) and len(txt(f).splitlines()) > 600:
            bad.append(f'{os.path.basename(f)}({len(txt(f).splitlines())} 行)')
    rec('R04', '单文件 ≤ 600 行', not bad, str(bad) if bad else '全部合规')


def r05():
    bad = []
    if os.path.isdir(TOOLS):
        for f in os.listdir(TOOLS):
            if f.endswith('.sh'):
                t = txt(os.path.join(TOOLS, f))
                if 'set -euo pipefail' not in t and 'set -eu' not in t:
                    bad.append(f)
    rec('R05', 'shell 脚本 set -euo pipefail', not bad, str(bad) if bad else '全部合规')


def r06():
    bad = []
    for f in py_files():
        if re.search(r'except\s*:', txt(f)):
            bad.append(os.path.basename(f))
    rec('R06', '无裸 except', not bad, str(bad) if bad else '未发现')


def r07():
    third = ('requests', 'flask', 'fastapi', 'django', 'pandas', 'numpy', 'aiohttp', 'httpx')
    bad = []
    for f in py_files():
        for m in re.findall(r'^\s*(?:import|from)\s+([a-zA-Z0-9_]+)', txt(f), re.M):
            if m in third:
                bad.append(f'{os.path.basename(f)}:{m}')
    rec('R07', '不引入第三方库（标准库优先）', not bad, str(bad) if bad else '仅标准库')

def q08():
    """场景必须结构化、可见、可编辑（03 §7）。"""
    p = os.path.join(DATA, 'scenes.json')
    if not has(p):
        rec('Q08', '场景结构化可编辑', False, 'data/scenes.json 缺'); return
    doc = js(p, {}) or {}
    scs = doc.get('scenes') or []
    bad = [x.get('id') for x in scs if not (x.get('id') and x.get('name') and isinstance(x.get('steps'), list))]
    bad += [x.get('id') for x in scs for st in x.get('steps', [])
            if not isinstance(st.get('selector'), dict) or 'action' not in st]
    rec('Q08', '场景结构化可编辑（含选择器与动作）', not bad, f'不合规 {bad[:3]}' if bad else f'{len(scs)} 个场景')


def q09():
    """动作留痕：实现存在且只追加（07 §4 审计只追加）。"""
    t = txt(os.path.join(APP, 'intent.py'))
    if not t:
        rec('Q09', '动作留痕（只追加）', False, 'app/intent.py 缺'); return
    ok = ('def record(' in t) and ('actions.json' in t) and not re.search(r'del\s+doc\[|actions\.clear\(', t)
    rec('Q09', '动作留痕（只追加，无删除路径）', ok, 'record() 写入且无删除路径' if ok else '缺实现或存在删除路径')

def a04():
    """审计字段齐备（08 §4）：实现里必须出现 8 个必备字段。"""
    t = txt(os.path.join(APP, 'audit.py'))
    if not t:
        rec('A04', '审计字段齐备（08 §4）', False, 'app/audit.py 缺'); return
    need = ['at', 'actor', 'channel', 'action', 'target', 'authorization', 'result', 'readback']
    miss = [k for k in need if k not in t]
    rec('A04', '审计字段齐备（08 §4）', not miss, f'缺 {miss}' if miss else '8 个字段齐备')


def a05():
    """出声决策：三问 + 安全豁免 + 额度（04 §3–§5）。"""
    t = txt(os.path.join(APP, 'notify.py'))
    if not t:
        rec('A05', '出声决策含三问与安全豁免', False, 'app/notify.py 缺'); return
    ok = all(k in t for k in ('def speak(', '不占额度', '静默', 'merge_window', 'def feedback('))
    rec('A05', '出声决策含三问与安全豁免（04 §3–§5）', ok, '三问/豁免/静默/合并/额度 齐备' if ok else '缺机制')


def s06():
    """运行期实证：安全域请求不得产生任何执行步骤（08 §2）。"""
    import subprocess as sp
    probe = ('import sys;sys.path.insert(0,r"%s");import intent as I;'
             'o=I.handle("把门锁打开");print(o["intent"]["kind"], len(o["steps"]))' % APP)
    try:
        r = sp.run([sys.executable, '-c', probe], capture_output=True, text=True, timeout=60, cwd=ROOT)
        out = (r.stdout or '').strip()
        kind, _, n = out.partition(' ')
        ok = (kind == 'security') and n.strip() == '0'
        rec('S06', '运行期拒执：安全域请求零执行步骤', ok, f'实测 {out}')
    except Exception as e:  # noqa
        rec('S06', '运行期拒执：安全域请求零执行步骤', False, f'探测失败 {e}')

def r08():
    """测试隔离（11 §11 的隐含要求）：测试不得写生产数据文件。"""
    bad = []
    targets = [f for f in (os.listdir(TOOLS) if os.path.isdir(TOOLS) else [])
               if f.endswith('.py') and (f.startswith('test_') or f == 'acceptance.py')]
    for f in targets:
        t = txt(os.path.join(TOOLS, f))
        writes = bool(re.search(r'import\s+(audit|notify|intent)\b', t)) and \
            bool(re.search(r'\.(log|feedback|mark_spoken|mark_missed|save_quota|record|handle)\(', t))
        isolates = ('AUDIT =' in t) or ('ACTIONS =' in t) or ('QUOTA =' in t) or ('SPOKEN =' in t)
        if writes and not isolates:
            bad.append(f)
    rec('R08', '测试不写生产数据（路径隔离）', not bad, f'未隔离 {bad}' if bad else '测试均已隔离')

def q10():
    """恢复演练证据（07 §7：每季度至少一次，不许"应该能恢复"）。"""
    import glob
    import time
    hits = glob.glob(os.path.join(LOGS, 'evidence', '*', 'restore-drill.md'))
    if not hits:
        rec('Q10', '备份恢复演练证据（30 天内）', False, '未找到 restore-drill.md'); return
    newest = max(hits, key=os.path.getmtime)
    days = (time.time() - os.path.getmtime(newest)) / 86400
    rec('Q10', '备份恢复演练证据（30 天内）', days <= 30,
        f'{os.path.relpath(newest, ROOT)}（{days:.1f} 天前）')


def q11():
    """定时简报（04 §3：每天最多 2 次、固定时段、没新料就说没有）。"""
    t = txt(os.path.join(APP, 'briefing.py'))
    if not t:
        rec('Q11', '定时简报实现（早/晚）', False, 'app/briefing.py 缺'); return
    ok = all(k in t for k in ('morning', 'evening', '需要你注意', '它今天做了', '出声额度', '没有'))
    rec('Q11', '定时简报实现（早/晚 · 四段口径 · 没新料说没有）', ok, '口径齐备' if ok else '缺口径')

def q12():
    """多端接入（P6）：PWA 资源齐备 + tailnet 内可达已配置。"""
    web = os.path.join(APP, 'web')
    need = ['manifest.webmanifest', 'icon-192.png', 'icon-512.png', 'apple-touch-icon.png']
    miss = [f for f in need if not os.path.exists(os.path.join(web, f))]
    html = txt(os.path.join(web, 'index.html'))
    meta_ok = ('apple-mobile-web-app-capable' in html) and ('rel="manifest"' in html)
    # manifest 由服务动态提供（app/server.py 里），不落文件也算齐备
    if 'manifest.webmanifest' in miss and 'manifest.webmanifest' in txt(os.path.join(APP, 'server.py')):
        miss.remove('manifest.webmanifest')
    # 离线壳（P6）：断网时给诚实页，且**绝不缓存 /api 与首页**（旧读数不能冒充现在）
    sw = txt(os.path.join(web, 'sw.js'))
    off = txt(os.path.join(web, 'offline.html'))
    shell_ok = ('/offline.html' in sw) and ("startsWith('/api/')" in sw) and ('/api/state' not in off)
    reg_ok = 'serviceWorker.register' in html
    rec('Q12', '多端就绪（PWA 资源 + iOS 全屏 + 离线壳）',
        (not miss) and meta_ok and shell_ok and reg_ok,
        f'缺 {miss}' if miss else ('' if (meta_ok and shell_ok and reg_ok) else
            ('元信息缺' if not meta_ok else ('离线壳缺' if not shell_ok else '未注册 SW'))))


def q13():
    """tailnet 内可达（P6）：tailscale serve 已把 8300 映射出去。"""
    import subprocess as sp
    ts = [os.path.expanduser('~/.homebrew/bin/tailscale'), '--socket',
          os.path.expanduser('~/tailscale-userspace/tailscaled.sock'), 'serve', 'status']
    try:
        r = sp.run(ts, capture_output=True, text=True, timeout=20)
        out = (r.stdout or '') + (r.stderr or '')
        ok = ('127.0.0.1:8300' in out) or ('8300' in out)
        rec('Q13', 'tailnet 内可达（tailscale serve → 8300）', ok,
            out.strip().splitlines()[0] if out.strip() else '无输出')
    except Exception as e:  # noqa
        rec('Q13', 'tailnet 内可达（tailscale serve → 8300）', None, f'tailscale 不可用：{e}')

def q14():
    """桌面端 DSH 插件入口（P6）：必须已装进 mini 的 desktop profile 且客户端入口在。"""
    prof = os.path.expanduser('~/.dsh/profiles/desktop')
    pkg = os.path.join(prof, 'package.json')
    if not os.path.exists(pkg):
        rec('Q14', 'DSH 插件入口已装（只装 mini）', False, '找不到 desktop profile'); return
    d = js(pkg, {}) or {}
    bundles = ((d.get('dsh') or {}).get('profile') or {}).get('bundles') or []
    dep = (d.get('dependencies') or {}).get('dsh-family-workbench')
    client = os.path.join(prof, 'node_modules', 'dsh-family-workbench', 'client', 'client.js')
    ok = ('dsh-family-workbench' in bundles) and bool(dep) and os.path.exists(client)
    rec('Q14', 'DSH 插件入口已装（只装 mini）', ok,
        f'bundle={"√" if "dsh-family-workbench" in bundles else "×"} 依赖={"√" if dep else "×"} 客户端={"√" if os.path.exists(client) else "×"}')

    # 反向确认：笔记本不在本机可达范围（同一 tailnet 但没装插件）
    # 说明：这里只能证明"本机装了"，不能证明"笔记本没装"（物理隔离在对方机器上）。

def q16():
    """定时简报调度（04 §3）：LaunchAgent 已装载 + 有产物 + 落盘幂等。"""
    import glob
    import subprocess as sp
    plist = os.path.expanduser('~/Library/LaunchAgents/com.simon.smarthome-briefing.plist')
    if not os.path.exists(plist):
        rec('Q16', '定时简报调度已装载（早/晚）', False, '找不到 LaunchAgent plist'); return
    try:
        out = sp.run(['/bin/launchctl', 'print', f'gui/{os.getuid()}/com.simon.smarthome-briefing'],
                     capture_output=True, text=True, timeout=15)
        loaded = out.returncode == 0 and 'com.simon.smarthome-briefing' in (out.stdout or '')
    except Exception:  # noqa
        loaded = False
    files = glob.glob(os.path.join(DATA, 'briefings', '*-*.md'))
    tool = os.path.join(TOOLS, 'briefing_run.py')
    idem = os.path.exists(tool) and ('skipped' in txt(tool))
    rec('Q16', '定时简报调度已装载（早/晚 + 幂等）', loaded and bool(files) and idem,
        f"装载={'√' if loaded else '×'} 产物={len(files)} 份 幂等={'√' if idem else '×'}")

def q17():
    """离线生成资源的产物一致性（11 §13 v1.1）：源文件改了没重新生成 = 失败。"""
    import glob
    bad, checked = [], 0
    for build in glob.glob(os.path.join(APP, 'prototype', '*', 'build.mjs')):
        d = os.path.dirname(build)
        outs = [f for f in glob.glob(os.path.join(d, '*')) if os.path.isfile(f) and not f.endswith('build.mjs')]
        outs = [f for f in outs if not f.endswith('.md')]
        if not outs:
            bad.append(f'{os.path.basename(d)}: 无产物'); continue
        checked += 1
        newest = max(outs, key=os.path.getmtime)
        if os.path.getmtime(newest) < os.path.getmtime(build):
            bad.append(f'{os.path.basename(d)}: {os.path.basename(newest)} 比 build.mjs 旧（需重新生成）')
    # 产品目录里的生成物（由原型目录的构建脚本产出）
    pairs = [
        ('space/index.html', 'spatial', 'build_scan.mjs'),
        ('space/house.html', 'spatial', 'build_house.mjs'),
    ]
    for rel_out, proto, script in pairs:
        build = os.path.join(APP, 'prototype', proto, script)
        out = os.path.join(APP, 'web', rel_out.replace('/', os.sep))
        if os.path.exists(build) and os.path.exists(out):
            checked += 1
            if os.path.getmtime(out) < os.path.getmtime(build):
                bad.append(f'{rel_out} 比 {script} 旧（需重新生成）')
    if not checked and not bad:
        rec('Q17', '离线生成资源：产物不旧于源文件（11 §13）', None, '暂无离线生成资源'); return
    rec('Q17', '离线生成资源：产物不旧于源文件（11 §13）', not bad,
        '; '.join(bad) if bad else f'{checked} 组产物均不旧于源文件')

def q18():
    """空间几何来源可追溯（P7）：floorplan.json 必须写明来源与提取方式。"""
    p = os.path.join(DATA, 'floorplan.json')
    if not os.path.exists(p):
        rec('Q18', '空间几何来源可追溯（P7）', False, '缺 data/floorplan.json'); return
    d = js(p, {}) or {}
    rooms = d.get('rooms') or []
    ok = bool(d.get('source')) and bool(rooms) and all(
        r.get('rects') and r.get('bbox') and isinstance(r.get('share'), (int, float)) for r in rooms)
    note = f"{len(rooms)} 个分区 · {'已正规化' if d.get('regularized') else '未正规化'}"
    rec('Q18', '空间几何来源可追溯（P7）', ok,
        f"{d.get('source', '缺来源')[:28]} · {note}" if ok else '缺来源或几何不完整')

def q19():
    """离线阈值校准（06 v1.2 §3）：产物存在、规则写明、24 小时门槛诚实标注。"""
    import glob
    p = os.path.join(DATA, 'offline-calibration.json')
    hits = glob.glob(os.path.join(LOGS, 'evidence', '*', 'calibration.md'))
    if not os.path.exists(p) and not hits:
        rec('Q19', '离线阈值校准有据可查（06 v1.2 §3）', None, '尚未跑过校准（观测未满 24 小时前允许空缺）')
        return
    d = js(p, {}) or {}
    ok = bool(d.get('rule')) and isinstance(d.get('enough_for_24h_rule'), bool) and (
        d.get('enough_for_24h_rule') or d.get('need_more', 0) >= 0)
    honest = (d.get('enough_for_24h_rule') is True) or (d.get('calibrated', 0) < d.get('devices', 1))
    rec('Q19', '离线阈值校准有据可查（06 v1.2 §3）', ok and honest,
        f"观测 {d.get('observation_hours')}h · 可校准 {d.get('calibrated')}/{d.get('devices')} · "
        f"24h 门槛={'已满足' if d.get('enough_for_24h_rule') else '未满足（不启用阈值判定）'}")

def q20():
    """米家依赖清单（判据 1 的检查表）：存在、来源可查、分类与安全域一致。"""
    p = os.path.join(DATA, 'mijia-dependency.json')
    if not os.path.exists(p):
        rec('Q20', '米家依赖清单（判据 1 检查表）', False, '缺 data/mijia-dependency.json（跑 tools/mijia_gap.py）')
        return
    d = js(p, {}) or {}
    st = js(os.path.join(DATA, 'state.json'), {}) or {}
    devs = st.get('devices') or []
    c = d.get('counts') or {}
    sec = {x['name'] for x in devs if x.get('security_domain')}
    need = {x['name'] for x in (d.get('devices') or {}).get('need_mijia', [])}
    recorded = d.get('recorded_gaps') or []          # 注意别叫 rec：会遮蔽本模块的 rec() 函数
    md = txt(os.path.join(DATA, 'mijia-dependency.md'))
    rec_ok = (d.get('recorded_count') == len(recorded)
              and all(x.get('reason', '')[:12] in md for x in recorded))
    ok = (bool(d.get('source')) and bool(d.get('generated_at'))
          and sum(c.values()) == len(devs) and need <= sec and rec_ok)
    rec('Q20', '米家依赖清单（判据 1 检查表）', ok,
        f"不用米家 {c.get('ok')} · 无法确认 {c.get('no_readback')} · 仍需米家 {c.get('need_mijia')}"
        f"（且全部为安全域）· 补录 {d.get('recorded_count', 0)} 条" if ok else '清单与状态不一致、来源缺失或补录没进清单')
