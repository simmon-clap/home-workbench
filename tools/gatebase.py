#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门禁基座：常量与公共工具（依据 docs/spec/11-代码规范 v1.1 §3 文件拆分要求）。"""
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, 'docs', 'spec')
DATA = os.path.join(ROOT, 'data')
APP = os.path.join(ROOT, 'app')
WEB = os.path.join(APP, 'web')
TOOLS = os.path.join(ROOT, 'tools')
LOGS = os.path.join(ROOT, 'logs')
BASELINE = os.path.join(DATA, 'spec-baseline.sha256')
WB_URL = 'http://127.0.0.1:8300'

ROOMS = ['客厅', '主卧', '厨房', '餐厅', '次卧', '客卫', '主卫', '书房', '阳台', '办公室']
COLOR_TOKENS = {
    '#FDFBF7', '#F6EEE3', '#FFFFFF', '#2F2A25', '#8A8078', '#E9E1D6', '#C0713F', '#FBEDE1',
    '#F3C877', '#B4453C', '#FBEAE7', '#B98A3E', '#FBF3E3', '#6E8F72', '#EDF3ED', '#9E4F20',
    '#B4643A', '#FFEEDA', '#FFF3E2', '#FBF7F1', '#FCF8F3', '#F3EEE6', '#4E463C', '#9C9184',
    '#D9887E', '#DDBE8A', '#E2D5C2', '#F1E5D4', '#EADCC7', '#FDF0EC', '#FCF6EA', '#FFFDF9',
    '#F6E0DA', '#F2D8D2', '#F7ECD9', '#F3E5CE', '#C4CAD2', '#D8D0C4', '#CFC7BB', '#FFFCF6',
    '#FBE7D2', '#EDD9C6', '#F7ECEA', '#F2F4F7',
}
SPACING_SCALE = {0, 1, 2, 3, 4, 6, 8, 10, 11, 12, 14, 16, 20, 22, 24, 28, 32, 40, 44, 48, 56, 64, 96}
FONT_SCALE = {10, 10.5, 11, 11.5, 12, 12.5, 13, 13.5, 14, 15, 16, 16.5, 18, 20, 22, 24, 25, 26, 28, 30, 32}
CRED_PAT = re.compile(r'(sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|eyJ[A-Za-z0-9_\-]{20,}\.|password\s*[:=]\s*["\'][^"\']{6,})')

R = []


def rec(cid, name, ok, detail=''):
    R.append((cid, name, 'PASS' if ok is True else ('SKIP' if ok is None else 'FAIL'), detail))


def has(p): return os.path.exists(p)


def txt(p):
    try:
        return open(p, encoding='utf-8', errors='ignore').read()
    except Exception:  # noqa
        return ''


def js(p, default=None):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:  # noqa
        return default


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(65536), b''):
            h.update(c)
    return h.hexdigest()


def spec_list():
    return [os.path.join(SPEC, f) for f in sorted(os.listdir(SPEC))] if os.path.isdir(SPEC) else []


def spec_md(n):
    for f in spec_list():
        if os.path.basename(f).startswith(n) and f.endswith('.md'):
            return f
    return None


def web_files(ext):
    out = []
    if os.path.isdir(WEB):
        for base, _, fs in os.walk(WEB):
            out += [os.path.join(base, f) for f in fs if f.endswith(ext)]
    return sorted(out)


def strip_dynamic(html):
    html = re.sub(r'<script[\s\S]*?</script>', '', html, flags=re.I)
    html = re.sub(r'<style[\s\S]*?</style>', '', html, flags=re.I)
    html = re.sub(r'<svg[\s\S]*?</svg>', '', html, flags=re.I)
    return re.sub(r'<head[\s\S]*?</head>', '', html, flags=re.I)


def all_js():
    return ' '.join(txt(f) for f in web_files('.js'))


def state(): return js(os.path.join(DATA, 'state.json'), {}) or {}
def summary(): return state().get('summary') or {}
def devices(): return state().get('devices') or []


def server_up():
    try:
        urllib.request.urlopen(WB_URL + '/', timeout=2).read(32)
        return True
    except Exception:  # noqa
        return False


def rendered_dom():
    if not server_up():
        return None
    chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    if not os.path.exists(chrome):
        return None
    try:
        out = subprocess.run(
            [chrome, '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-breakpad',
             '--disable-crash-reporter', '--crash-dumps-dir=/tmp/crash', '--user-data-dir=/tmp/gate-chrome',
             '--virtual-time-budget=4000', '--dump-dom', WB_URL + '/'],
            capture_output=True, text=True, timeout=90)
        return out.stdout or None
    except Exception:  # noqa
        return None

# ── 已声明的生成物（11 v1.2 §13 豁免）──
# 判定靠**产物自描述**：内联渲染的产物里带 <meta name="generated-by" content="...">。
# 为什么不靠文件名白名单：白名单会随文件增多而腐坏，自描述标记跟着产物走。
GENERATED_MARK = 'name="generated-by"'


def is_generated(path):
    try:
        with open(path, encoding='utf-8', errors='ignore') as f:
            head = f.read(4096)
        return GENERATED_MARK in head
    except OSError:
        return False


def declared_generated():
    """扫出所有带生成标记的产物（用于统计与体积检查）。"""
    out = []
    for base, _, fs in os.walk(APP):
        for f in fs:
            p = os.path.join(base, f)
            if is_generated(p):
                out.append(p)
    return out
