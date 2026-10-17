#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HA 官方 API 客户端测试（app/ha_ws.py）

为什么重要：这个客户端是"状态层不再依赖 HA 文件"的地基。迁到 HA OS 后，文件在虚拟机里读不到，
全靠它。所以两件事必须钉死：
  ① **连不上/鉴权失败必须如实报错** —— 绝不能返回空表冒充"家里没有设备"
  ② 帧编解码、地址解析这些 plumbing 要正确（错一位就整条链坏掉）

用法：python3 tools/test_ha_ws.py      退出码 0 = 全过
"""
import importlib.util
import json
import os
import socket
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
import ha_ws  # noqa: E402

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def frame(payload: bytes) -> bytes:
    """按 RFC6455 造一个服务端→客户端的未掩码文本帧（用来喂给 recv 做纯离线测试）。"""
    if len(payload) < 126:
        return bytes([0x81, len(payload)]) + payload
    return bytes([0x81, 126]) + struct.pack('>H', len(payload)) + payload


def main():
    # ① 地址解析
    cases = [('http://127.0.0.1:8123', ('127.0.0.1', 8123)),
             ('http://127.0.0.1:8123/', ('127.0.0.1', 8123)),
             ('http://127.0.0.1:8123', ('127.0.0.1', 8123))]
    for base, want in cases:
        got = ha_ws._host_port(base)
        check(f'地址解析 {base}', got == want, str(got))

    # ② 帧解码（短帧 + 126 长度前缀帧），全都走同一段 buffer 逻辑
    w = ha_ws.HaWs.__new__(ha_ws.HaWs)
    w.buf = frame(json.dumps({'a': 1}).encode()) + frame(json.dumps({'b': 'x' * 300}).encode())
    check('短帧解码', w.recv() == {'a': 1})
    check('长帧解码（126 前缀）', w.recv()['b'] == 'x' * 300)

    # ③ 连不上 → 如实报错，不返回空数据
    dead = 'http://127.0.0.1:59999'
    res = ha_ws.probe(base=dead)
    check('连不上时 probe 返回 ok=False', res['ok'] is False, json.dumps(res, ensure_ascii=False)[:80])
    check('错误信息说清"连不上"而不是空成功', '连不上' in (res.get('error') or ''), res.get('error'))
    try:
        ha_ws.fetch_registries(base=dead)
        check('fetch_registries 连不上时抛错（不静默返回空表）', False, '没有抛错')
    except ha_ws.HaWsError:
        check('fetch_registries 连不上时抛错（不静默返回空表）', True)
    except Exception as err:  # noqa
        check('fetch_registries 连不上时抛错（不静默返回空表）', False, type(err).__name__)

    # ④ 纯标准库（不能引第三方）
    src = open(os.path.join(ROOT, 'app', 'ha_ws.py'), encoding='utf-8').read()
    third = [m for m in ('requests', 'websocket', 'aiohttp', 'websockets') if f'import {m}' in src]
    check('只用标准库（无第三方依赖）', not third, str(third))

    # ⑤ 真环境：能连就断言有数据；连不上就确认错误路径（两条都算通过，但如实打印）
    live = ha_ws.probe()
    if live['ok']:
        check('真环境：实体注册表非空', live['entities'] > 0, f"{live['entities']} 条实体")
        check('真环境：设备注册表非空', live['devices'] > 0, f"{live['devices']} 台设备")
        check('真环境：区域注册表非空', live['areas'] > 0, f"{live['areas']} 个区域")
    else:
        check('真环境连不上时如实报错（当前环境如此）', bool(live.get('error')), live.get('error'))

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
