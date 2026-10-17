#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ha._req 的「瞬时故障重试」回归测试

背景（2026-10-17 实测）：桥接虚拟机偶发 `No route to host`，一两秒即恢复；
但状态层一次抖动就整体降级成读文件。所以 ha._req 要对**瞬时网络错误**重试，
对 **HTTP 错误（401/404）**立刻失败（那重试也没意义，还浪费时间）。

测法：本地起一个 HTTP 服务，按脚本决定"这次是断连接还是正常响应"。
"""
import http.server
import json
import os
import socketserver
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
import ha  # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=''):
    (PASS if ok else FAIL).append(name)
    print(('✅ ' if ok else '❌ ') + name + (f'  —— {detail}' if detail else ''))


class Handler(http.server.BaseHTTPRequestHandler):
    plan = []          # 每个请求的处置：'drop' = 直接断开；'ok' = 正常；'401' = 未授权
    hits = 0

    def do_GET(self):
        kind = Handler.plan[Handler.hits] if Handler.hits < len(Handler.plan) else 'ok'
        Handler.hits += 1
        if kind == 'drop':
            try:
                self.connection.close()       # 模拟瞬时断连
            except OSError:
                pass
            return
        if kind == '401':
            self.send_response(401); self.end_headers(); self.wfile.write(b'{}'); return
        body = json.dumps({'ok': True, 'hit': Handler.hits}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class Srv(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve():
    srv = Srv(('127.0.0.1', 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f'http://127.0.0.1:{srv.server_address[1]}'


def main():
    srv, base = serve()
    orig_base, orig_tok = ha.BASE, getattr(ha, 'load_token', None)
    ha.BASE = base
    ha.load_token = lambda: 'test-token'          # 不读真实令牌文件
    try:
        # ① 前两次断连、第三次成功 → 应该最终成功（证明会重试）
        Handler.plan, Handler.hits = ['drop', 'drop', 'ok'], 0
        try:
            r = ha._req('/api/config')
            check('瞬时断连会重试直到成功', r.get('hit') == 3, f'实际打了 {Handler.hits} 次，hit={r.get("hit")}')
        except Exception as err:  # noqa
            check('瞬时断连会重试直到成功', False, f'仍然抛错：{str(err)[:60]}')

        # ② 401 是确定性失败 → 只打一次，立刻抛（不重试）
        Handler.plan, Handler.hits = ['401', 'ok', 'ok'], 0
        raised = False
        try:
            ha._req('/api/config')
        except Exception:  # noqa
            raised = True
        check('HTTP 401 不重试、立刻失败', raised and Handler.hits == 1, f'打了 {Handler.hits} 次')

        # ③ 全部断连 → 最终要如实抛错（不许假装成功）
        Handler.plan, Handler.hits = ['drop'] * 10, 0
        raised = False
        try:
            ha._req('/api/config')
        except Exception:  # noqa
            raised = True
        check('一直连不上要如实失败', raised, f'打了 {Handler.hits} 次')
    finally:
        ha.BASE = orig_base
        if orig_tok:
            ha.load_token = orig_tok
        srv.shutdown()

    print(f'\n测试结果：通过 {len(PASS)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
