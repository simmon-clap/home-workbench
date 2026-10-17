#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
家庭工作台 · 本地服务

依据：docs/spec/05-技术架构规范 v1.0 §2（宿主机跑家庭工作台）· 08 §5（本机访问，不暴露公网）

提供：
  /               主屏（app/web/index.html）
  /static/*       静态资源
  /api/state      L2 状态模型（data/state.json，只读）
  /api/refresh    重新生成状态（调用 app/state.py，只读 HA 数据）

绑定：默认 127.0.0.1（本机）。墙面屏需要局域网访问时用 --host 0.0.0.0 显式打开。
用法：python3 app/server.py [--port 8300] [--host 127.0.0.1]
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, 'app', 'web')
DATA = os.path.join(ROOT, 'data')
STATE = os.path.join(DATA, 'state.json')
PIN_FILE = os.path.expanduser('~/.config/smart-home/workbench-pin')

def tailnet_ip():
    """取本机 tailnet 地址（用户态 tailscale 需要显式 socket）。"""
    for sock in (os.path.expanduser('~/tailscale-userspace/tailscaled.sock'), '/var/run/tailscaled.socket'):
        if os.path.exists(sock):
            try:
                out = subprocess.run([os.path.expanduser('~/.homebrew/bin/tailscale'), '--socket', sock, 'ip', '-4'],
                                     capture_output=True, text=True, timeout=10)
                ip = (out.stdout or '').strip().splitlines()
                if ip:
                    return ip[0].strip()
            except Exception:  # noqa
                continue
    return None

def pin_hash():
    try:
        with open(PIN_FILE, encoding='utf-8') as f:
            v = f.read().strip()
        return hashlib.sha256(v.encode()).hexdigest() if v else None
    except FileNotFoundError:
        return None

def history_series(entity_id, hours=24):
    """某实体在最近 N 小时内的读数序列（只读 recorder 副本，供曲线用）。
    依据 docs/spec/03-功能与交互规范 v1.1 §1C 第 3 条：设备详情要能读到数据（传感器给读数与曲线）。"""
    import shutil
    import sqlite3
    import tempfile
    import time

    import ha_paths as _hp
    ha = _hp.ha_config_dir()
    src = os.path.join(ha, 'home-assistant_v2.db')
    if not os.path.exists(src):
        return {'entity_id': entity_id, 'points': [], 'count': 0, 'error': 'recorder 库不存在'}
    tmp = tempfile.mkdtemp(prefix='ha-hist-')
    try:
        for suf in ('', '-wal', '-shm'):
            if os.path.exists(src + suf):
                shutil.copy(src + suf, os.path.join(tmp, 'ha.db' + suf))
        con = sqlite3.connect(os.path.join(tmp, 'ha.db'))
        since = time.time() - hours * 3600
        rows = list(con.execute(
            'select s.state, s.last_updated_ts, s.attributes_id from states s '
            'join states_meta sm on s.metadata_id = sm.metadata_id '
            'where sm.entity_id = ? and s.last_updated_ts >= ? order by s.last_updated_ts',
            (entity_id, since)))
        unit = ''
        if rows:
            aid = rows[-1][2]
            for (a,) in con.execute('select shared_attrs from state_attributes where attributes_id = ?', (aid,)):
                try:
                    unit = json.loads(a).get('unit_of_measurement', '')
                except Exception:  # noqa
                    unit = ''
        con.close()
        pts = []
        for st, ts, _ in rows:
            try:
                pts.append([int(ts * 1000), float(st)])
            except (TypeError, ValueError):
                continue      # 非数值状态（on/off/unavailable）不进曲线
        return {'entity_id': entity_id, 'hours': hours, 'unit': unit,
                'points': pts, 'count': len(pts)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

from server_ext import HandlersMixin  # noqa: E402


class Handler(HandlersMixin, SimpleHTTPRequestHandler):
    server_version = 'FamilyWorkbench/0.1'

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB, **kw)

    def end_headers(self):
        # 静态资源要求"每次重新验证"（no-cache 不是不缓存，是**不直接用旧副本**）。
        # 2026-10-17 踩坑：没有这个头时改了 app.js 浏览器仍用旧副本 —— 用户会说"你改的东西我没看到"。
        self.send_header('Cache-Control', 'no-cache, must-revalidate')
        super().end_headers()

    def log_message(self, fmt, *args):          # 静默，避免刷屏；写文件日志
        with open(os.path.join(ROOT, 'logs', 'workbench.log'), 'a', encoding='utf-8') as f:
            f.write('%s %s\n' % (self.log_date_time_string(), fmt % args))

    def _is_local(self):
        return self.client_address[0] in ('127.0.0.1', '::1')

    def _authed(self):
        """本机免检；非本机访问时，若配置了 PIN 文件则要求 PIN（cookie 记住 30 天）。"""
        want = pin_hash()
        if want is None or self._is_local():
            return True
        cookie = self.headers.get('Cookie') or ''
        for part in cookie.split(';'):
            k, _, v = part.strip().partition('=')
            if k == 'wbpin' and v == want:
                return True
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(self.path).query)
        if q.get('pin') and hashlib.sha256(q['pin'][0].encode()).hexdigest() == want:
            return True
        return False

    def _login_page(self):
        body = ('<html><head><meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>家庭工作台</title></head><body style="font-family:-apple-system;padding:24px">'
                '<h3>家庭工作台</h3><p>这台设备需要一次 PIN 才能查看（只在家里/你的设备上可访问）。</p>'
                '<form method="POST" action="/login"><input name="pin" type="password" '
                'style="font-size:18px;padding:8px" autofocus><button style="font-size:18px;padding:8px 16px">进入</button>'
                '</form></body></html>')
        raw = body.encode('utf-8')
        self.send_response(401)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _refresh(self):
        rc = subprocess.call([sys.executable, os.path.join(ROOT, 'app', 'state.py')],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return self._json({'ok': rc == 0})

    def do_POST(self):
        path = self.path.split('?')[0]
        if path == '/api/device-action':
            return self._device_action()
        if path == '/api/refresh':
            # 与 GET 同义（UI 用 POST 触发；曾只注册在 GET，前端 POST 拿到 404 —— 实测抓到的）
            return self._refresh()
        if path == '/api/notify/run':
            sys.path.insert(0, os.path.join(ROOT, 'app'))
            import outbox as OB
            b = self._body()
            st = self._load_state()          # 走服务端统一的状态读取（不再自己拼路径）
            out = OB.speak_and_deliver(st.get('attention') or [],
                                       channels=tuple(b.get('channels') or ('outbox',)),
                                       dry=bool(b.get('dry', True)))
            return self._json({'message': out['message'], 'spoken': len(out['spoken']),
                               'silent': len(out['silent']), 'delivery': out['delivery'],
                               'reasons': out['reasons']})
        if path == '/api/3d/edit':
            return self._scan_room_edit()
        if path == '/api/rule/propose':
            return self._rule_propose()
        if path == '/api/rule/enable':
            sys.path.insert(0, os.path.join(ROOT, 'app'))
            import rules as R
            b = self._body()
            out = R.set_enabled(b.get('rule_id', ''), bool(b.get('enabled')))
            return self._json(out, 200 if out.get('ok') else 400)
        if path == '/api/rule/commit':
            return self._rule_commit()
        if path == '/api/scenes/edit':
            return self._scenes_edit()
        if path == '/api/scene':
            sys.path.insert(0, os.path.join(ROOT, 'app'))
            import panel_action as pa
            body = self._body()
            return self._json(pa.run_scene(body.get('scene_id', ''),
                                           dry=str(body.get('dry', '')).lower() in ('1', 'true')))
        if path == '/api/settings/set-zone':
            return self._settings_set_zone()
        if path == '/api/settings/zone-name':
            return self._settings_zone_name()
        if path == '/api/settings/dep':
            return self._settings_dep()
        if path == '/api/settings/set':
            return self._settings_set()
        if path == '/api/settings/undo':
            return self._settings_undo()
        if path == '/api/settings/add-device':
            return self._settings_add_device()
        if path == '/api/undo':
            return self._undo()
        if path == '/login':
            n = int(self.headers.get('Content-Length') or 0)
            from urllib.parse import parse_qs
            form = parse_qs(self.rfile.read(n).decode('utf-8'))
            want = pin_hash()
            pin = (form.get('pin') or [''])[0]
            if want and hashlib.sha256(pin.encode()).hexdigest() == want:
                self.send_response(302)
                self.send_header('Location', '/')
                self.send_header('Set-Cookie', f'wbpin={want}; Path=/; Max-Age=2592000; HttpOnly; SameSite=Lax')
                self.end_headers()
                return
            return self._login_page()
        self.send_error(404)

    def _load_state(self):
        try:
            with open(STATE, encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split('?')[0]
        if not self._authed():
            return self._login_page()
        if path == '/manifest.webmanifest':
            body = json.dumps({'name': '家 · 家庭工作台', 'short_name': '家', 'start_url': '/',
                               'display': 'standalone', 'background_color': '#FDFBF7',
                               'theme_color': '#FDFBF7', 'lang': 'zh-CN',
                               'icons': [{'src': '/icon-192.png', 'sizes': '192x192', 'type': 'image/png'},
                                         {'src': '/icon-512.png', 'sizes': '512x512', 'type': 'image/png'}]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/manifest+json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == '/api/state':
            if not os.path.exists(STATE):
                return self._json({'error': 'state.json 尚未生成'}, 503)
            with open(STATE, encoding='utf-8') as f:
                return self._json(json.load(f))
        if path == '/api/refresh':
            return self._refresh()
        if path == '/api/changes':
            import importlib.util as _iu
            import urllib.parse as _up          # 本文件默认没导入 urllib（曾因此 500）
            _spec = _iu.spec_from_file_location('sw', os.path.join(ROOT, 'tools', 'state_watch.py'))
            _sw = _iu.module_from_spec(_spec); _spec.loader.exec_module(_sw)
            q = _up.parse_qs(_up.urlparse(self.path).query)
            dev = (q.get('device') or [None])[0]
            rows = _sw.for_device(dev, 5) if dev else _sw.recent(int((q.get('limit') or ['20'])[0]))
            return self._json({'changes': rows, 'summary': _sw.summary()})
        if path == '/api/outbox':
            sys.path.insert(0, os.path.join(ROOT, 'app'))
            import outbox as OB
            return self._json({'recent': OB.recent(20), 'summary': OB.summary()})
        if path == '/api/rules':
            sys.path.insert(0, os.path.join(ROOT, 'app'))
            import rules as R
            return self._json({'rules': R.view(), 'summary': R.summary()})
        if path == '/api/health':
            return self._health()
        if path == '/api/settings':
            return self._settings_view()
        if path == '/api/history':
            return self._history()
        if path == '/api/say':
            return self._say()
        if path == '/api/briefing':
            return self._briefing()
        if path == '/api/audit':
            return self._audit()
        if path == '/api/scenes':
            sys.path.insert(0, os.path.join(ROOT, 'app'))
            import panel_action as pa
            import scenes as SC
            return self._json({'scenes': pa.scenes(), 'view': SC.view(), 'summary': SC.summary()})
        if path == '/api/capabilities':
            sys.path.insert(0, os.path.join(ROOT, 'app'))
            import panel_action as pa
            import intent as I
            st = json.load(open(STATE, encoding='utf-8')) if os.path.exists(STATE) else {'devices': []}
            acts = {}
            for d in st.get('devices') or []:
                a = pa.actions_for(d)
                if a:
                    acts[d['name']] = {k: {'label': pa.LABELS.get(k, k), 'verifiable': v['verifiable']}
                                       for k, v in a.items()}
            return self._json({'devices': acts, 'allowed': sorted(pa.ALLOWED),
                               'readonly_types': sorted(I.READONLY_TYPES),
                               'not_connected': ['微信小号通道', '摄像头 AI 识别（Frigate）',
                                                 '3D 渲染', '扫地机启停（需实测，暂不开放夜间接入）']})
        if path == '/api/quota':
            sys.path.insert(0, os.path.join(ROOT, 'app'))
            import notify
            return self._json(notify.budget())
        if path == '/':
            self.path = '/index.html'
        return super().do_GET()

    def _say(self):
        """对话入口：一句话 → 意图/计划/守门/回执。
        当前默认 dry-run（不执行）——真实执行需要 HA 令牌（app/ha.py）；令牌就绪后由 ?execute=1 打开。
        安全域动作无论令牌在不在，都在守门层被拦（08 §2）。"""
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(self.path).query)
        text = (q.get('text') or [''])[0]
        if not text:
            return self._json({'error': 'text 必填'}, 400)
        sys.path.insert(0, os.path.join(ROOT, 'app'))
        import intent as I
        import ha
        want_exec = (q.get('execute') or ['0'])[0] == '1'
        executor = ha.real_executor() if want_exec else None
        if want_exec and executor is None:
            out = I.handle(text, dry_run=True)
            out['note'] = '请求了执行，但未配置 HA 令牌 —— 只做了守门，未执行（不会假装完成）'
            return self._json(out)
        out = I.handle(text, executor=executor, dry_run=(executor is None))
        return self._json(out)

    def _scan_room_edit(self):
        """3D 模型编辑器保存：写 data/3d/rooms/<name>.edited.json 并重建页面。"""
        import subprocess
        b = self._body() or {}
        name = str(b.get('name') or '')
        # 多房间：只接受 data/3d/rooms 下真实存在的扫描（防路径穿越，不写死房间名）
        if (not name or len(name) > 80 or name.startswith('.')
                or '/' in name or '\\' in name):
            return self._json({'ok': False, 'error': '扫描名不合法'}, 400)
        furn = b.get('furniture')
        if not isinstance(furn, list):
            return self._json({'ok': False, 'error': 'furniture 必须是数组'}, 400)
        rooms_dir = os.path.join(ROOT, 'data', '3d', 'rooms')
        base_path = os.path.join(rooms_dir, name + '.json')
        if not os.path.isfile(base_path):
            return self._json({'ok': False, 'error': '未知扫描名'}, 400)
        with open(base_path, encoding='utf-8') as f:
            base = json.load(f)
        out = []
        for i, x in enumerate(furn):
            try:
                out.append({
                    'id': str(x.get('id') or ('edit-%d' % i)),
                    'kind': str(x.get('kind') or 'other'),
                    'label': str(x.get('label') or ''),
                    'name': str(x.get('name') or ''),
                    'x': round(float(x.get('x', 0)), 3), 'y': round(float(x.get('y', 0)), 3),
                    'rot': round(float(x.get('rot', 0)), 1),
                    'w': round(float(x.get('w', 0)), 3), 'd': round(float(x.get('d', 0)), 3),
                    'h': round(float(x.get('h', 0)), 3),
                })
            except (TypeError, ValueError):
                return self._json({'ok': False, 'error': '第 %d 个构件参数不合法' % (i + 1)}, 400)
        base['furniture'] = out
        edited_path = os.path.join(rooms_dir, name + '.edited.json')
        tmp = edited_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(base, f, ensure_ascii=False, indent=1)
        os.replace(tmp, edited_path)
        node = shutil.which('node') or '/usr/local/bin/node'
        build = os.path.join(ROOT, 'app', 'prototype', 'scan-room-editor', 'build-room.mjs')
        try:
            r = subprocess.run([node, build], cwd=ROOT, capture_output=True, text=True, timeout=60)
        except Exception as err:  # noqa
            return self._json({'ok': False, 'error': '重建失败：%s' % err}, 500)
        return self._json({'ok': r.returncode == 0, 'rebuilt': r.returncode == 0,
                           'log': (r.stdout or r.stderr).strip()[-400:]},
                          200 if r.returncode == 0 else 500)

    def _body(self):
        from urllib.parse import parse_qs
        n = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(n).decode('utf-8') if n else ''
        try:
            return json.loads(raw) if raw.strip().startswith('{') else {k: v[0] for k, v in parse_qs(raw).items()}
        except ValueError:
            return {}

    def _device_action(self):
        """面板操作：真执行 + 回读 + 审计 + 可撤销（02 §8 兜底可用）。"""
        sys.path.insert(0, os.path.join(ROOT, 'app'))
        import panel_action
        body = self._body()
        return self._json(panel_action.run(body.get('name', ''), body.get('action', ''),
                                           dry=str(body.get('dry', '')).lower() in ('1', 'true')))

    def _settings_view(self):
        """功能设置页的数据（03 §1D）：可编辑对象、当前值、变更历史。"""
        sys.path.insert(0, os.path.join(ROOT, 'app'))
        import settings as S
        st = json.load(open(STATE, encoding='utf-8')) if os.path.exists(STATE) else {'devices': []}
        devs = [{'name': d['name'], 'room': d.get('room'), 'room_source': d.get('room_source', 'miyun'),
                 'short_name': d.get('short_name'), 'type': d.get('type'),
                 'security_domain': bool(d.get('security_domain')),
                 'tags': d.get('tags') or [], 'offline_threshold_s': d.get('offline_threshold_s')}
                for d in st.get('devices') or []]
        return self._json({'summary': S.summary(), 'devices': devs,
                           'history': S.history(40), 'rooms': S.rooms(), 'zones': S.zones(),
                           'extra_deps': S.extra_deps(),
                           'scenes': __import__('scenes').view(),
                           'rules': __import__('rules').view()})

    def _settings_zone_name(self):
        """分区改名（03 v1.3 §1D-2）：如「房间1」→「儿童房」。"""
        sys.path.insert(0, os.path.join(ROOT, 'app'))
        import settings as S
        b = self._body()
        ok, msg = S.set_zone_name(b.get('zone', ''), b.get('label', ''))
        return self._json({'ok': ok, 'message': msg, 'zones': S.zones()}, 200 if ok else 400)

    def _settings_dep(self):
        """米家依赖补录（判据 1）：记一笔 / 删一笔。"""
        sys.path.insert(0, os.path.join(ROOT, 'app'))
        import settings as S
        b = self._body()
        if b.get('remove'):
            ok, msg = S.remove_dep(b.get('reason', ''))
        else:
            ok, msg = S.add_dep(b.get('reason', ''), b.get('where') or '米家')
        if ok:
            subprocess.call([sys.executable, os.path.join(ROOT, 'tools', 'mijia_gap.py')],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return self._json({'ok': ok, 'message': msg}, 200 if ok else 400)

    def _settings_set_zone(self):
        """扫描分区 → 房间名 的映射（P7：地图分区与设备房间对齐）。"""
        sys.path.insert(0, os.path.join(ROOT, 'app'))
        import settings as S
        b = self._body()
        ok, msg = S.set_zone(b.get('zone', ''), b.get('room') or None)
        return self._json({'ok': ok, 'message': msg}, 200 if ok else 400)

    def _settings_set(self):
        """改一个字段（房间/短名/标签/阈值）。改动立即生效（重建状态模型）。"""
        sys.path.insert(0, os.path.join(ROOT, 'app'))
        import settings as S
        b = self._body()
        ok, msg = S.set_field(b.get('device', ''), b.get('field', ''), b.get('value'),
                              by=b.get('by', 'user'), confirm=b.get('confirm'))
        if ok:
            subprocess.call([sys.executable, os.path.join(ROOT, 'app', 'state.py')],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return self._json({'ok': ok, 'message': msg}, 200 if ok else 400)

    def _settings_undo(self):
        """回滚最近一次设置改动（03 §1D：变更可回滚）。"""
        sys.path.insert(0, os.path.join(ROOT, 'app'))
        import settings as S
        b = self._body()
        ok, msg = S.undo_last(b.get('device'), entry_id=b.get('entry_id'))
        if ok:
            subprocess.call([sys.executable, os.path.join(ROOT, 'app', 'state.py')],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return self._json({'ok': ok, 'message': msg}, 200 if ok else 400)

    def _settings_add_device(self):
        """手动录入设备（03 §1D：填房间 + 名称即可用）。"""
        sys.path.insert(0, os.path.join(ROOT, 'app'))
        import settings as S
        b = self._body()
        ok, msg = S.add_device(b.get('name', ''), b.get('room', ''), b.get('short_name'))
        if ok:
            subprocess.call([sys.executable, os.path.join(ROOT, 'app', 'state.py')],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return self._json({'ok': ok, 'message': msg}, 200 if ok else 400)

    def _undo(self):
        """撤销最近一次面板/对话动作（要真的撤销，读回确认——03 §6）。"""
        sys.path.insert(0, os.path.join(ROOT, 'app'))
        import ha
        import intent as I
        body = self._body()
        ex = ha.real_executor()
        if ex is None:
            return self._json({'ok': False, 'error': '未配置 HA 令牌，无法撤销'}, 503)
        return self._json(I.undo(body.get('action_id', ''), executor=ex))

    def _briefing(self):
        """定时简报（早/晚）——04 §3；内容只讲真实数据，没新料就写"没有"。"""
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(self.path).query)
        kind = (q.get('kind') or [None])[0]
        sys.path.insert(0, os.path.join(ROOT, 'app'))
        import briefing
        return self._json({'kind': kind or 'auto', 'text': briefing.compose(kind)})

    def _audit(self):
        """审计查询（可追问）——04 §6 / 08 §4。"""
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(self.path).query)
        target = (q.get('target') or [None])[0]
        limit = int((q.get('limit') or ['20'])[0])
        sys.path.insert(0, os.path.join(ROOT, 'app'))
        import audit
        return self._json({'summary': audit.summary(), 'rows': audit.load(limit=limit, target=target)})

    def _history(self):
        """设备读数历史（只读 recorder 副本）—— 供设备详情画 24 小时曲线。
        依据 docs/spec/03-功能与交互规范 v1.1 §1C 第 3 条。"""
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(self.path).query)
        eid = (q.get('entity_id') or [''])[0]
        hours = float((q.get('hours') or ['24'])[0])
        if not eid:
            return self._json({'error': 'entity_id 必填'}, 400)
        try:
            data = history_series(eid, hours)
        except Exception as e:  # noqa
            return self._json({'error': str(e)}, 500)
        return self._json(data)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8300)
    ap.add_argument('--host', default=None, help='（兼容旧参数）单地址绑定')
    ap.add_argument('--hosts', default=None, help='逗号分隔的多地址，例如 127.0.0.1')
    ap.add_argument('--tailnet', action='store_true', help='同时绑定 tailnet 地址（手机/iPad 用）')
    a = ap.parse_args()

    hosts = []
    if a.hosts:
        hosts = [h.strip() for h in a.hosts.split(',') if h.strip()]
    elif a.host:
        hosts = [a.host]
    else:
        hosts = ['127.0.0.1']
    if a.tailnet:
        ip = tailnet_ip()
        if ip and ip not in hosts:
            hosts.append(ip)
        elif not ip:
            print('⚠️ 没取到 tailnet 地址，仍只绑本机')

    os.makedirs(os.path.join(ROOT, 'logs'), exist_ok=True)
    if not os.path.exists(STATE):
        subprocess.call([sys.executable, os.path.join(ROOT, 'app', 'state.py')])

    servers = []
    for h in hosts:
        try:
            srv = ThreadingHTTPServer((h, a.port), Handler)
        except OSError as e:
            print(f'⚠️ 绑定 {h}:{a.port} 失败：{e}')
            continue
        servers.append(srv)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print(f'家庭工作台：http://{h}:{a.port}/')
    if not servers:
        raise SystemExit('没有任何地址绑定成功')
    print(f'PIN 保护：{"已开启" if pin_hash() else "未开启（仅 tailnet 可达）"}')
    try:
        while True:
            threading.Event().wait(3600)
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()
