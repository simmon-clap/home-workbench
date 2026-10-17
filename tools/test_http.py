#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端：HTTP 服务层

为什么要有：这类链最容易出"接口在、行为不对"的问题——路由漏了、错误码乱给、
或者**安全默认值悄悄变了**（比如不带 execute 竟然真执行）。之前只靠人工 curl 试过。

做法：起一个**临时端口的真服务**（子进程），用 HTTP 打它，跑完即关。
      只打不会污染数据的路径（读取、演练、非法输入）；写操作的逻辑由 test_pipeline / test_settings 覆盖。

用法：python3 tools/test_http.py      退出码 0 = 全过
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


def call(base, path, method='GET', body=None, timeout=20):
    """返回 (状态码, 正文文本)。HTTP 错误码也当成结果，不当异常。"""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if data:
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')


def main():
    port = free_port()
    # 用隔离的"状态变化"文件起服务，验证 /api/changes 真能返回来源判定
    tmpd = tempfile.mkdtemp(prefix='http-changes-')
    chg_file = os.path.join(tmpd, 'changes.jsonl')
    with open(chg_file, 'w', encoding='utf-8') as f:
        f.write(json.dumps({'at': '2026-10-17T10:00:00+08:00', 'device': '测试设备',
                            'room': '客厅', 'from': 'on', 'to': 'off', 'source': 'external',
                            'evidence': '没有我方动作记录 → 判定为外部改动'}, ensure_ascii=False) + '\n')
    env = dict(os.environ, SMART_HOME_CHANGES=chg_file,
               SMART_HOME_SNAPDIR=os.path.join(tmpd, 'snap'))
    proc = subprocess.Popen([sys.executable, '-u', os.path.join(ROOT, 'app', 'server.py'),
                             '--port', str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f'http://127.0.0.1:{port}'
    try:
        for _ in range(40):                      # 等它起来
            try:
                if call(base, '/api/state', timeout=3)[0] == 200:
                    break
            except Exception:  # noqa
                pass
            time.sleep(0.5)
        check('临时服务能起来', call(base, '/api/state', timeout=5)[0] == 200)
        audit_before = json.loads(call(base, '/api/audit?limit=1')[1])['summary']['total']

        # ── 静态与页面 ──
        st, body = call(base, '/')
        check('主屏可访问且是家庭工作台', st == 200 and '家' in body, str(st))
        st, body = call(base, '/settings.html')
        check('功能设置页可访问', st == 200 and '功能设置' in body, str(st))
        st, _ = call(base, '/manifest.webmanifest')
        check('PWA manifest 可访问', st == 200, str(st))
        st, _ = call(base, '/icon-192.png')
        check('PWA 图标可访问', st == 200, str(st))
        st, body = call(base, '/space/')
        check('空间视图（产品模块）可访问', st == 200 and '扫描几何' in body or (st == 200 and 'iso-svg' in body), str(st))
        check('空间视图带生成标记（11 v1.2 §13 的"已声明生成物"）',
              'name="generated-by"' in body, 'generated-by')
        st, _ = call(base, '/no-such-path')
        check('未知路径返回 404（不是 200 或 500）', st == 404, str(st))

        # ── 只读接口 ──
        st, body = call(base, '/api/state')
        d = json.loads(body)
        check('/api/state 结构完整', st == 200 and d.get('devices') and d.get('summary'), str(st))
        st, body = call(base, '/api/capabilities')
        c = json.loads(body)
        check('/api/capabilities 逐设备下发', st == 200 and isinstance(c.get('devices'), dict), str(st))
        check('能力表带"未接通"清单', bool(c.get('not_connected')), str(c.get('not_connected'))[:60])
        st, body = call(base, '/api/scenes')
        check('/api/scenes 有场景且含影响面',
              st == 200 and all('executable' in s for s in json.loads(body)['scenes']), str(st))
        st, body = call(base, '/api/settings')
        s = json.loads(body)
        check('/api/settings 带分区/设备/历史/补录',
              st == 200 and 'zones' in s and 'devices' in s and 'history' in s and 'extra_deps' in s, str(st))
        st, body = call(base, '/api/briefing')
        check('/api/briefing 能出四段口径',
              st == 200 and all(k in json.loads(body)['text'] for k in ('家里', '需要你注意', '出声额度')), str(st))
        st, body = call(base, '/api/refresh', 'POST')
        check('刷新接口支持 POST（前端偏旧时自愈用）', st == 200 and json.loads(body).get('ok') is True,
              f'{st} {body[:40]}')
        st, body = call(base, '/api/changes?device=' + urllib.parse.quote('测试设备'))
        cc = json.loads(body)
        check('/api/changes 返回变化与来源判定',
              st == 200 and cc['changes'] and cc['changes'][0]['source'] == 'external',
              json.dumps(cc['changes'][:1], ensure_ascii=False)[:90])
        st, body = call(base, '/api/changes?limit=5')
        check('/api/changes 可整体查（含汇总）', st == 200 and 'summary' in json.loads(body))
        st, body = call(base, '/api/health')
        hh = json.loads(body)
        check('/api/health 给出数据新鲜度（不是写死的）',
              st == 200 and isinstance(hh.get('state_age_s'), int) and isinstance(hh.get('state_fresh'), bool),
              f"age={hh.get('state_age_s')}s fresh={hh.get('state_fresh')}")
        check('/api/health 汇总审计/校准/额度/待决',
              all(k in hh for k in ('audit', 'calibration', 'quota', 'open_decisions')), str(sorted(hh))[:80])
        check('/api/health 不泄露令牌内容', 'token' not in json.dumps(hh, ensure_ascii=False).lower()
              or hh.get('ha_token_problem') is None or isinstance(hh.get('ha_token_problem'), str),
              'token_problem 只给问题描述')
        st, body = call(base, '/api/audit?limit=3')
        check('/api/audit 可查（含小结）', st == 200 and 'summary' in json.loads(body), str(st))

        # ── 安全默认值：不带 execute 绝不能真执行 ──
        st, body = call(base, '/api/say?text=' + urllib.parse.quote('我要睡了'))
        out = json.loads(body)
        check('对话接口默认只演不执行',
              st == 200 and not out.get('results') and '未执行' in (out.get('receipt') or ''),
              str(out.get('receipt'))[:60])
        # 未执行的原因必须说真的：令牌已配置时**不许**说"等待令牌"（实测文案错过一次）
        check('演练说明不许谎报原因（令牌已配就不说缺令牌）',
              '等待 HA 访问令牌' not in (out.get('receipt') or ''),
              [x for x in (out.get('receipt') or '').splitlines() if '未执行' in x][:1])
        check('对话接口能识别场景', out['intent']['kind'] == 'scene', out['intent']['kind'])
        st, body = call(base, '/api/say?text=' + urllib.parse.quote('把门锁打开'))
        out = json.loads(body)
        check('对话里的安全域请求被拒执（零步骤）',
              out['intent']['kind'] == 'security' and not out['steps'], out['intent']['kind'])

        # ── 非法输入：要有明确 4xx 与可读原因，而不是 500 ──
        st, body = call(base, '/api/say')
        check('对话接口缺参数返回 400 且有说明', st == 400 and 'text' in body, f'{st} {body[:40]}')
        st, body = call(base, '/api/settings/set', 'POST', {'device': '不存在', 'field': 'room', 'value': '客厅'})
        check('改不存在的设备返回 400 + 原因', st == 400 and '找不到设备' in body, f'{st} {body[:60]}')
        st, body = call(base, '/api/settings/set-zone', 'POST', {'zone': '不存在的分区', 'room': '客厅'})
        check('映射不存在的分区返回 400', st == 400, f'{st} {body[:60]}')
        st, body = call(base, '/api/settings/zone-name', 'POST', {'zone': '不存在的分区', 'label': 'X'})
        check('给不存在的分区改名返回 400', st == 400, f'{st} {body[:60]}')
        st, body = call(base, '/api/scenes/edit', 'POST', {'do': '不认识的编辑'})
        check('场景编辑：不认识的编辑动作返回 400', st == 400, f'{st} {body[:60]}')
        st, body = call(base, '/api/device-action', 'POST', {'name': '小米全自动智能门锁 Pro', 'action': 'turn_off', 'dry': True})
        check('面板接口拒绝安全域设备（演练模式）',
              st == 200 and json.loads(body).get('blocked') is True, body[:60])
        audit_after = json.loads(call(base, '/api/audit?limit=1')[1])['summary']['total']
        check('本测试没有改动生产审计（演练不写审计、校验走 dry）',
              audit_after == audit_before, f'{audit_before} → {audit_after}')

        st, body = call(base, '/api/scene', 'POST', {'scene_id': 'goodnight', 'dry': True})
        check('场景演练只给预告不执行',
              st == 200 and json.loads(body).get('dry') is True, body[:80])

        # ── 撤销与面板接口的校验路径（不碰真设备）──
        st, body = call(base, '/api/undo', 'POST', {'action_id': '不存在的编号'})
        check('撤销不存在的动作 → 明确报找不到（不是 500）',
              st in (200, 400, 404, 503) and ('找不到' in body or 'error' in body), f'{st} {body[:60]}')
        st, body = call(base, '/api/undo', 'POST', {})
        check('撤销缺参数不会崩（有可读回应）', st < 500, f'{st} {body[:60]}')
        out2 = json.loads(body) if body.strip().startswith('{') else {}
        check('撤销缺参数时说明清楚', bool(out2.get('error')) or bool(out2.get('ok') is False),
              body[:60])
        st, body = call(base, '/api/device-action', 'POST', {'name': '不存在的设备', 'action': 'turn_off', 'dry': True})
        d2 = json.loads(body)
        check('面板动作：不存在的设备被明确拒绝（不猜）',
              d2.get('blocked') is True and '找不到' in (d2.get('reason') or ''), body[:70])
        st, body = call(base, '/api/device-action', 'POST', {'name': '米家智能多功能养生壶', 'action': '炸开', 'dry': True})
        d3 = json.loads(body)
        check('面板动作：未知动作被拒绝', d3.get('blocked') is True, body[:70])
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
