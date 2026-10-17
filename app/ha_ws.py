#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HA 官方 API 客户端（WebSocket · 纯标准库）

为什么要有：我们的状态层（L2）现在**直接读 HA 的文件**（`.storage/core.*_registry` + recorder 的
sqlite）。这在容器版能用，但一旦迁到 **HA OS**，那些文件在虚拟机里、Mac 读不到 —— 迁移就会撞墙。
官方 API 提供同样的数据：
  · WebSocket：`config/entity_registry/list` / `config/device_registry/list` / `config/area_registry/list`
  · REST：`/api/history/period`（recorder 历史）、`/api/states`（当前状态）

2026-10-17 实测（容器版 HA 2026.10.1）：WS 拿到实体 1025 条、设备 68 条、区域 10 条；
history REST 正常返回。所以状态层可以做到**与部署形态无关**——这正是宪章第八条"可迁移"要的。

诚实规则：连不上/鉴权失败就**如实抛出**，绝不返回空数据冒充"家里没有设备"。
"""
import base64
import json
import os
import socket
import time
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
DEFAULT_BASE = os.environ.get('HA_BASE_URL', 'http://127.0.0.1:8123')


class HaWsError(RuntimeError):
    pass


def _default_base():
    """与 ha.py 保持**同一个地址来源**（env > ~/.config/smart-home/ha-base-url > 默认）。

    2026-10-17 实测踩坑：ha_ws 只看环境变量、不看配置文件 → 迁移后注册表读不到，
    悄悄退回读文件（结果看着对、但已经不是在读新中枢了）。
    """
    try:
        import ha
        return ha.BASE
    except Exception:  # noqa
        return os.environ.get('HA_BASE_URL', DEFAULT_BASE)


def _host_port(base=None):
    base = base or _default_base()
    scheme, _, rest = base.partition('://')
    host, _, port = rest.partition(':')
    # 不带端口时按协议给默认值（http→80、https→443）。
    # 2026-10-17 实测踩坑：以前一律默认 8123，遇到 HA OS（Core 代理在 80）会发出错误 Host → 307
    default = '443' if scheme == 'https' else '80'
    return host or '127.0.0.1', int((port or default).split('/')[0])


def _token():
    import ha
    t = ha.load_token()
    if not t:
        raise HaWsError('没有 HA 令牌（先跑 tools/set-ha-token.sh）')
    return t


class HaWs:
    """极简 WebSocket 客户端：只做 HA 需要的那几件事（握手 / 鉴权 / 查询）。"""

    def __init__(self, base=None, timeout=10):
        self.host, self.port = _host_port(base)
        self.timeout = timeout
        self.sock = None
        self.buf = b''
        self._next_id = 1

    def connect(self):
        key = base64.b64encode(os.urandom(16)).decode()
        # 与 ha._req 一致：桥接虚拟机偶发瞬时断连，**建连阶段重试几次**再报错
        last = None
        for attempt in range(6):
            try:
                self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
                break
            except OSError as err:
                last = err
                if attempt < 5:
                    time.sleep(2.0 * (attempt + 1))   # ≈ 30 秒总窗口
        else:
            raise HaWsError(f'连不上 HA（{self.host}:{self.port}）：{last}') from last
        # Host 头**不能带默认端口**：HA 按 Host 比较并 307 跳转（实测：写成 host:80 会跳走）
        host_hdr = self.host if self.port in (80, 443) else f'{self.host}:{self.port}'
        self.sock.sendall((
            f'GET /api/websocket HTTP/1.1\r\nHost: {host_hdr}\r\nUpgrade: websocket\r\n'
            f'Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n'
        ).encode())
        self.buf = b''
        while b'\r\n\r\n' not in self.buf:               # 读完 HTTP 响应头
            chunk = self.sock.recv(4096)
            if not chunk:
                raise HaWsError('握手时连接被关闭')
            self.buf += chunk
        head, _, rest = self.buf.partition(b'\r\n\r\n')
        if b'101' not in head.split(b'\r\n')[0]:
            raise HaWsError(f'WebSocket 握手失败：{head.splitlines()[:1]}')
        self.buf = rest                                  # **保留残留字节**（hello 帧可能已在里面）
        return self

    def _need(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise HaWsError('连接被关闭')
            self.buf += chunk

    def recv(self):
        self._need(2)
        length = self.buf[1] & 0x7f
        off = 2
        if length == 126:
            self._need(4)
            length = struct.unpack('>H', self.buf[2:4])[0]
            off = 4
        elif length == 127:
            self._need(10)
            length = struct.unpack('>Q', self.buf[2:10])[0]
            off = 10
        self._need(off + length)
        payload = self.buf[off:off + length]
        self.buf = self.buf[off + length:]
        try:
            return json.loads(payload.decode('utf-8'))
        except ValueError as err:
            raise HaWsError(f'帧解析失败：{err}') from err

    def send(self, obj):
        data = json.dumps(obj).encode('utf-8')
        header = bytearray([0x81])
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        else:
            header.append(0x80 | 126)
            header += struct.pack('>H', n)
        mask = os.urandom(4)
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def auth(self, token=None):
        hello = self.recv()
        if hello.get('type') != 'auth_required':
            raise HaWsError(f"意外的握手消息：{hello.get('type')}")
        self.send({'type': 'auth', 'access_token': token or _token()})
        res = self.recv()
        if res.get('type') != 'auth_ok':
            raise HaWsError(f"鉴权失败：{res.get('message') or res.get('type')}")
        return res

    def query(self, msg_type, **kw):
        mid = self._next_id
        self._next_id += 1
        self.send({'id': mid, 'type': msg_type, **kw})
        while True:
            res = self.recv()
            if res.get('id') != mid:
                continue                                  # 跳过事件推送等无关帧
            if not res.get('success', True):
                raise HaWsError(f"{msg_type} 失败：{(res.get('error') or {}).get('message')}")
            return res.get('result')

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None


def fetch_registries(base=None, timeout=10):
    """一次连接取三张注册表（实体/设备/区域）。连不上就抛错，不返回空表。"""
    w = HaWs(base=base, timeout=timeout).connect()
    try:
        w.auth()
        return {
            'entities': w.query('config/entity_registry/list') or [],
            'devices': w.query('config/device_registry/list') or [],
            'areas': w.query('config/area_registry/list') or [],
        }
    finally:
        w.close()


def probe(base=None):
    """连通性 + 数据量探针（给迁移检查用），失败返回问题描述而不是抛异常。"""
    try:
        reg = fetch_registries(base=base)
        return {'ok': True, 'entities': len(reg['entities']), 'devices': len(reg['devices']),
                'areas': len(reg['areas'])}
    except Exception as err:  # noqa
        return {'ok': False, 'error': str(err)[:200]}


if __name__ == '__main__':
    print(json.dumps(probe(), ensure_ascii=False))
