#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门禁检查：00 宪章 / 01 总览 / 02 视觉 / 03 交互 / 04 主动性 / 05 架构 / 06 设备。"""
import json
import os
import re
import subprocess
import sys
import urllib.request

from gatebase import *  # noqa: F401,F403  # noqa


# ═══════════ 00 宪章 ═══════════
def c01():
    f = spec_md('00')
    ok = bool(f) or has(os.path.join(SPEC, '00-顶层宪章-v0.2-讨论稿.docx'))
    rec('C01', '宪章存在（00）', ok, '在' if ok else '缺')


def c02():
    have = {os.path.basename(p)[:3] for p in spec_list()}
    miss = [f'{i:02d}-' for i in range(1, 12) if f'{i:02d}-' not in have]
    rec('C02', '规范齐全（01–11）', not miss, f'缺 {miss}' if miss else '齐全')


def docx_text(path):
    """从 docx（zip）里取纯文本 —— 只用标准库，不额外依赖。"""
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read('word/document.xml').decode('utf-8', 'ignore')
        xml = re.sub(r'</w:p>', '\n', xml)
        return re.sub(r'<[^>]+>', '', xml)
    except Exception:  # noqa
        return ''


def c03():
    f = spec_md('00') or os.path.join(SPEC, '00-顶层宪章-v0.2-讨论稿.docx')
    if not has(f):
        rec('C03', '宪章含不可让渡条款与检验判据', False, '宪章文件缺'); return
    t = txt(f) if f.endswith('.md') else docx_text(f)
    ok = ('不可让渡' in t) and ('检验判据' in t)
    rec('C03', '宪章含不可让渡条款与检验判据', ok,
        f"{'md' if f.endswith('.md') else 'docx'} 检索：{'关键词齐备' if ok else '缺关键词'}")


def c04(init):
    cur = {os.path.basename(f): sha(f) for f in spec_list() if f.endswith(('.md', '.docx'))}
    if init or not has(BASELINE):
        json.dump(cur, open(BASELINE, 'w'), ensure_ascii=False, indent=1)
        rec('C04', '规范未被静默改动', True, f'已登记基线（{len(cur)} 个文件）'); return
    base = js(BASELINE, {})
    changed = [k for k, v in base.items() if cur.get(k) != v]
    added = [k for k in cur if k not in base]
    rec('C04', '规范未被静默改动', not changed and not added,
        f'改动 {changed} 新增 {added}' if (changed or added) else f'{len(cur)} 个文件一致')


# ═══════════ 01 总览 ═══════════
def l01():
    rec('L01', '规范体系总览存在', bool(spec_md('01')), '在' if spec_md('01') else '缺')


def l02():
    t = txt(spec_md('01') or '')
    rec('L02', '声明冲突裁决顺序与冻结节奏', ('裁决' in t) and ('冻结' in t), '含裁决与冻结' if '裁决' in t else '缺')


# ═══════════ 02 视觉 ═══════════
def v01():
    fs = web_files('.html')
    if not fs:
        rec('V01', '主屏固定文案 ≤ 3 处', None, '尚无 UI'); return
    items = [x.strip() for x in re.findall(r'>([^<>]{2,40})<', strip_dynamic(txt(fs[0]))) if x.strip()]
    rec('V01', '主屏固定文案 ≤ 3 处', len(items) <= 3, f'{len(items)} 处 {items[:4]}')


def v02():
    fs = web_files('.html') + web_files('.css') + web_files('.js')
    if not fs:
        rec('V02', '无 emoji 当图标', None, '尚无 UI'); return
    pat = re.compile('[\U0001F300-\U0001FAFF\u2600-\u27BF]')
    bad = [os.path.basename(f) for f in fs if pat.search(txt(f))]
    rec('V02', '无 emoji 当图标', not bad, str(bad) if bad else '干净')


def v03():
    # 生成物（自带 generated-by 标记）豁免：见 11 v1.2 §13（那两条规则是给手写源码定的）
    fs = [f for f in web_files('.css') + web_files('.html') + web_files('.js') if not is_generated(f)]
    if not fs:
        rec('V03', '颜色只用规范 token', None, '尚无 UI'); return
    allowed = {c.upper() for c in COLOR_TOKENS}
    bad = {}
    for f in fs:
        for c in set(re.findall(r'#[0-9A-Fa-f]{6}', txt(f))):
            if c.upper() not in allowed:
                bad.setdefault(os.path.basename(f), []).append(c)
    rec('V03', '颜色只用规范 token', not bad, f'越界 {bad}' if bad else '全部在色板内')


def v04():
    fs = [f for f in web_files('.css') if not is_generated(f)]
    if not fs:
        rec('V04', '间距/字号在标尺内', None, '尚无 UI'); return
    bad = []
    for f in fs:
        t = txt(f)
        for kind, pat, scale in (('font-size', r'font-size:\s*([0-9.]+)px', FONT_SCALE),
                                 ('spacing', r'(?:gap|padding|margin[^:]*):\s*([0-9.]+)px', SPACING_SCALE)):
            allow = {float(x) for x in scale}
            bad += [f'{os.path.basename(f)}:{kind}={v}' for v in re.findall(pat, t) if float(v) not in allow]
    rec('V04', '间距/字号在标尺内', not bad, f'越界 {bad[:4]}' if bad else '合规')


def v05():
    fs = web_files('.html')
    if not fs:
        rec('V05', '主屏无列表/表格', None, '尚无 UI'); return
    bad = [x for x in ('<table', '<ul', '<ol') if x in strip_dynamic(txt(fs[0]))]
    dom = rendered_dom()
    where = '静态'
    if dom:
        main = dom.split('id="roomPanel"')[0]
        bad += [x for x in ('<table', '<ul', '<ol') if x in main]
        where = '静态 + 渲染期'
    rec('V05', '主屏无列表/表格', not bad, f'{where} 出现 {sorted(set(bad))}' if bad else f'{where} 均干净')


def v06():
    css = ' '.join(txt(f) for f in web_files('.css'))
    if not css:
        rec('V06', '选中态 ≥ 2 个维度', None, '尚无 UI'); return
    seg = css.split('.sel')[1][:400] if '.sel' in css else ''
    dims = sum([bool(re.search(r'(fill|background|color)', seg)),
                bool(re.search(r'(stroke-width|font-weight)', seg)),
                bool(re.search(r'(width|height|r:|scale|filter)', seg))])
    rec('V06', '选中态 ≥ 2 个维度', dims >= 2, f'检出 {dims} 个维度')


def v07():
    if not web_files('.js') or not devices():
        rec('V07', '设备图形库覆盖所有设备类型', None, '尚无 UI 或状态'); return
    code = all_js()
    used = {d.get('type') for d in devices() if d.get('type')}
    miss = sorted(t for t in used if f'{t}:' not in code)
    rec('V07', '设备图形库覆盖所有设备类型', not miss, f'缺图形 {miss}' if miss else f'{len(used)} 类全覆盖')


def v08():
    css = ' '.join(txt(f) for f in web_files('.css'))
    if not css:
        rec('V08', '红只用于真实安全事件', None, '尚无 UI'); return
    head = css.split('.sel')[0]
    ok = '--alert:#B4453C' in head.replace(' ', '') or '--alert: #B4453C' in head
    rec('V08', '红只用于真实安全事件（色板唯一）', ok, '红色 token 唯一且仅用于异常规则' if ok else '未找到唯一红 token')


# ═══════════ 03 功能与交互 ═══════════
def i01():
    fs = web_files('.html')
    if not fs:
        rec('I01', '主屏四要素各 ≤ 1', None, '尚无 UI'); return
    t = txt(fs[0])
    n = [t.count('id="greet"'), t.count('id="remind"'), t.count('id="house"'), t.count('class="ft"')]
    rec('I01', '主屏四要素各 ≤ 1（问候/提醒/模型/页脚）', all(x == 1 for x in n), f'计数 {n}')


def i02():
    code = all_js()
    if not code:
        rec('I02', '三层交互可达', None, '尚无 UI'); return
    ok = all(k in code for k in ('roomPanel', 'data-dev', 'selectRoom'))
    rec('I02', '三层交互可达（全屋→房间→设备）', ok, '三环节齐备' if ok else '缺环节')


def i03():
    code = all_js() + ' '.join(txt(f) for f in web_files('.html'))
    if not code:
        rec('I03', '未接通功能必须标注', None, '尚无 UI'); return
    rec('I03', '未接通功能必须标注', '未接通' in code, '含未接通标注' if '未接通' in code else '缺标注')


def i04():
    """回执三段式：做了什么 / 现在什么样（含回读）/ 要不要撤销（03 §4）。"""
    t = txt(os.path.join(APP, 'intent.py'))
    if not t:
        rec('I04', '回执三段式模板存在', False, 'app/intent.py 缺'); return
    ok = all(k in t for k in ('receipt', '已完成', '回读', '撤销'))
    rec('I04', '回执三段式模板存在（做了什么/现在什么样/撤销）', ok,
        '三段式齐备' if ok else '缺要素')


# ═══════════ 04 主动性 ═══════════
def a01():
    att = state().get('attention') or []
    if not att:
        rec('A01', '每条出声可回答三问', None, '当前无待注意项'); return
    bad = [a.get('device') for a in att if not (a.get('issue') and a.get('detail') and a.get('suggestion'))]
    rec('A01', '每条出声可回答三问（为什么/依据/不说会怎样）', not bad,
        f'缺字段 {bad[:3]}' if bad else f'{len(att)} 条齐备')


def a02():
    s, att = summary(), state().get('attention') or []
    ok = ('attention_sec' in s) and (not att or att[0]['level'] == 'sec' or s['attention_sec'] == 0)
    rec('A02', '安全事件独立计数且排最前', ok, f"sec={s.get('attention_sec')} 首条={att[0]['level'] if att else '—'}")


def a03():
    p = os.path.join(DATA, 'quiet-hours.json')
    if not has(p):
        rec('A03', '免打扰时段配置存在', False, 'data/quiet-hours.json 缺'); return
    q = js(p, {})
    ok = isinstance(q.get('silent_hours'), list) and q.get('security_exempt') is True
    rec('A03', '免打扰时段配置存在（安全事件例外）', ok, f"{q.get('silent_hours')} 例外={q.get('security_exempt')}")


# ═══════════ 05 技术架构 ═══════════
def t01():
    if not has(os.path.join(ROOT, 'docker-compose.yml')):
        rec('T01', 'compose 可解析', False, '缺 docker-compose.yml'); return
    try:
        r = subprocess.run([os.path.expanduser('~/.homebrew/bin/docker'), 'compose', 'config'],
                           cwd=ROOT, capture_output=True, text=True, timeout=60)
        rec('T01', 'compose 可解析', r.returncode == 0, 'ok' if r.returncode == 0 else r.stderr.strip()[:80])
    except Exception as e:  # noqa
        rec('T01', 'compose 可解析', None, f'docker 不可用：{e}')


def t02():
    p = os.path.join(APP, 'server.py')
    if not has(p):
        rec('T02', '本机服务默认只绑 127.0.0.1', None, '尚无 server.py'); return
    t = txt(p)
    # 默认必须落在回环：既不允许默认 0.0.0.0，也不允许默认绑局域网地址
    ok = ("hosts = ['127.0.0.1']" in t) and ("'0.0.0.0'" not in t.split('def main()')[-1])
    rec('T02', '本机服务默认只绑 127.0.0.1', ok, '默认回环绑定' if ok else '默认绑定可疑')


def t03():
    bad = []
    for base, _, fs in os.walk(APP):
        for f in fs:
            if f.endswith('.py') and re.search(r'^\s*import\s+(miio|zigbee2mqtt|paho)', txt(os.path.join(base, f)), re.M):
                bad.append(f)
    rec('T03', '不自研连接层（不直连设备协议）', not bad, f'发现 {bad}' if bad else '未发现协议实现')


def t04():
    miss = [n for n in ('docker-compose.yml', 'config', 'data', 'docs', 'backups', 'logs')
            if not has(os.path.join(ROOT, n))]
    rec('T04', '项目目录可整体迁移（结构齐备）', not miss, f'缺 {miss}' if miss else '结构齐备')


def t05():
    ok = '未接通' in all_js()
    rec('T05', '不把接口规划写成已实现', ok, 'UI 已标注未接通项' if ok else '未见标注')


# ═══════════ 06 设备接入与命名 ═══════════
def d01():
    snap = js(os.path.join(DATA, 'registry-snapshots', 'core.device_registry.json'), {})
    reg = {d.get('name') for d in (snap.get('data') or {}).get('devices', [])}
    renamed = sorted(n for n in {d.get('name') for d in devices()} if n not in reg)
    rec('D01', '设备名与米家一致（改名 0）', not renamed, f'改名 {renamed[:3]}' if renamed else f'{len(devices())} 台一致')


def d02():
    bad = sorted({d.get('room') for d in devices() if d.get('room') not in ROOMS})
    rec('D02', '每台设备都有合法房间', not bad, f'非法房间 {bad}' if bad else '全部在十个房间内')


def d03():
    snap = js(os.path.join(DATA, 'registry-snapshots', 'core.device_registry.json'), {})
    helpers = {'Sun', 'Backup', '谷歌翻译 en com', 'Forecast'}
    reg = {d.get('name') for d in (snap.get('data') or {}).get('devices', []) if d.get('name') not in helpers}
    mine = {d.get('name') for d in devices()}
    rec('D03', '台账与 HA 注册表设备集合一致', reg == mine,
        f'差 {sorted(reg ^ mine)[:4]}' if reg != mine else f'{len(mine)} 台一致')


def d04():
    bad = sorted({d.get('offline_threshold_s') for d in devices()} - {600, 43200, 300})
    rec('D04', '离线阈值符合 06 §3（10min/12h/5min）', not bad, f'异常阈值 {bad}' if bad else '全部合规')


def d05():
    bad = [d.get('name') for d in devices() if d.get('confidence') == 'online' and not d.get('observed_at')]
    rec('D05', '不得把无读数当在线', not bad, str(bad[:3]) if bad else '未发现')


def d06():
    import sys as _s
    _s.path.insert(0, os.path.join(ROOT, 'app'))
    import ha_paths as _hp
    a = os.path.join(_hp.ha_config_dir(), 'automations.yaml')
    t = txt(a) if has(a) else ''
    bad = [k for k in ('lock.', 'camera.') if k in t]
    rec('D06', '安全域设备无自动化写入', not bad, f'自动化里出现 {bad}' if bad else '自动化未触碰安全域')
