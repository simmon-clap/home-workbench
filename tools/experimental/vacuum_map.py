#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扫地机地图抓取（P7 空间结构来源）

依据：docs/spec/10-开发计划-v1.2 §P7 · data/plan-vacuum-map.md
      08 §6（凭证只用不打印）· 11-代码规范 v1.1（标准库；无 AES 时用系统 openssl）

做什么：
  1) `discover`  局域网发现 miIO 设备（UDP 54321 广播，标准做法，无需凭证）
  2) `info`      本地协议握手 → miIO.info（验证令牌可用）
  3) `prop`      读一个属性（如地图元数据 siid=6 piid=8）
  4) `action`    发一个动作（如「请求地图数据」siid=6 aiid=1）并监听推送

令牌来源：HA 的小米集成存储（本机文件，**只读不打印**）。
用法：python3 tools/vacuum_map.py discover
      python3 tools/vacuum_map.py info --ip <机器人IP>
      python3 tools/vacuum_map.py prop --ip <IP> --siid 6 --piid 8
"""
import argparse
import binascii
import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import time

# 实验脚本：多包了一层目录（tools/experimental/），所以往上数三层
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MIOT_DEVICES = os.path.join(ROOT, 'config', 'homeassistant', '.storage', 'xiaomi_home',
                            'miot_devices', '2748266363_cn.dict')
OPENSSL = '/usr/bin/openssl'
HELLO = binascii.unhexlify('21310020' + 'ffffffff' * 6)
PORT = 54321


# ═══════════ 令牌（只读） ═══════════
def load_vacuum_token():
    """从 HA 的小米集成存储里取扫地机令牌。**只返回，不打印。**"""
    raw = open(MIOT_DEVICES, 'rb').read()
    d = None
    for cut in range(0, 64):                       # 文件是「JSON 前缀 + 32 字节尾巴」
        try:
            d = json.loads(raw[:len(raw) - cut].decode('latin-1'))
            break
        except Exception:  # noqa
            continue
    if not d:
        raise SystemExit('读不出设备存储（格式变了？）')
    for k, v in d.items():
        if 'p2114o' in str(v.get('model', '')) or '扫' in str(v.get('name', '')):
            tok = v.get('token')
            if not tok:
                raise SystemExit('这条设备记录里没有 token')
            return {'did': v.get('did'), 'model': v.get('model'), 'name': v.get('name'),
                    'token': tok, 'room': v.get('room_name')}
    raise SystemExit('没找到扫地机记录')


# ═══════════ AES（用系统 openssl，避免引第三方库） ═══════════
def aes_cbc(data, key, iv, decrypt=True):
    args = [OPENSSL, 'enc', '-aes-128-cbc', '-nopad', '-K', key.hex(), '-iv', iv.hex()]
    if not decrypt:
        args.insert(2, '-e')
    else:
        args.insert(2, '-d')
    p = subprocess.run(args, input=data, capture_output=True, timeout=10)
    if p.returncode != 0:
        raise RuntimeError(f'openssl 失败：{p.stderr.decode()[:120]}')
    return p.stdout


# ═══════════ miIO 本地协议 ═══════════
class Miio:
    def __init__(self, ip, token, timeout=4.0):
        self.ip = ip
        self.token = token if isinstance(token, bytes) else bytes.fromhex(token)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout)
        self.stamp = 0
        self.key = None
        self.iv = None

    def handshake(self):
        key = os.urandom(16)
        pkt = HELLO + key
        self.sock.sendto(pkt, (self.ip, PORT))
        data, _ = self.sock.recvfrom(4096)
        if len(data) < 32:
            raise RuntimeError(f'握手回包太短：{len(data)}')
        enc = data[16:32]
        dev_token = aes_cbc(enc, key, key, decrypt=True)
        if dev_token != self.token:
            # 令牌不对时 openssl 仍会返回 16 字节乱码；这里如实报
            raise RuntimeError('握手得到的气令牌与本机存储不一致（设备换了 token？）')
        self.key = hashlib.md5(self.token + key).digest()
        self.iv = hashlib.md5(key + self.token).digest()
        return True

    def _pack(self, payload: bytes):
        self.stamp = int(time.time())
        head = struct.pack('>HHIII', 0x2131, 32 + len(payload), 0, self.stamp, 0)
        # 头部 md5 校验（前 16 字节置零参与计算）
        chk = hashlib.md5(head + self.token + payload).digest()
        return head[:4] + chk + head[4:] + payload

    def send(self, method, params=None):
        body = {'id': self.stamp + 1, 'method': method, 'params': params if params is not None else []}
        raw = json.dumps(body, separators=(',', ':')).encode()
        enc = aes_cbc(raw, self.key, self.iv, decrypt=False)
        self.sock.sendto(self._pack(enc), (self.ip, PORT))

    def recv(self, timeout=None):
        if timeout:
            self.sock.settimeout(timeout)
        data, _ = self.sock.recvfrom(8192)
        if len(data) <= 32:
            return None
        dec = aes_cbc(data[32:], self.key, self.iv, decrypt=True)
        # 去零填充
        dec = dec.rstrip(b'\x00')
        return json.loads(dec.decode('utf-8', 'replace'))


def discover(seconds=4.0):
    """局域网发现：UDP 54321 广播。回复里带 did 与设备地址。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(seconds)
    found = []
    for addr in ('255.255.255.255', os.environ.get('SMART_HOME_BROADCAST', '')):
        if not addr:
            continue
        try:
            s.sendto(HELLO, (addr, PORT))
        except OSError:
            pass
    t0 = time.time()
    while time.time() - t0 < seconds:
        try:
            data, (ip, port) = s.recvfrom(4096)
        except socket.timeout:
            break
        if len(data) >= 32:
            did = struct.unpack('>I', data[8:12])[0]
            found.append({'ip': ip, 'port': port, 'did': did, 'bytes': len(data)})
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['discover', 'info', 'prop', 'action', 'token-check', 'ready'])
    ap.add_argument('--ip')
    ap.add_argument('--siid', type=int)
    ap.add_argument('--piid', type=int)
    ap.add_argument('--aiid', type=int)
    ap.add_argument('--listen', type=float, default=0)
    a = ap.parse_args()

    dev = load_vacuum_token()
    print(f"设备：{dev['name']} · {dev['model']} · did={dev['did']} · 米家房间={dev['room']}")
    print(f"令牌：已从本机存储读取（{len(dev['token'])} 字符，不打印内容）")

    if a.cmd == 'token-check':
        return 0

    if a.cmd == 'ready':
        # 插网线之后跑这一条：能不能本地抓地图，一眼给结论
        import subprocess
        import re as _re
        arp = subprocess.run(['arp', '-an'], capture_output=True, text=True).stdout
        hosts = sorted({m.group(1) for m in _re.finditer(r'\((\d+\.\d+\.\d+\.\d+)\) at', arp)}
                       | {m.group(1) for m in _re.finditer(r'\((\d+\.\d+\.\d+\.\d+)\) at', arp)})
        our = subprocess.run(['/usr/bin/python3', '-c',
                              'import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);'
                              's.connect(("1.1.1.1",80));print(s.getsockname()[0])'],
                             capture_output=True, text=True).stdout.strip()
        gw = '.'.join(our.split('.')[:3]) + '.1'
        print(f'本机 {our} · 网关 {gw} · ARP 邻居 {len(hosts)} 台')
        reach = []
        for ip in ([gw] + [h for h in hosts if h != our])[:24]:
            r = subprocess.run(['ping', '-c1', '-W500', ip], capture_output=True, text=True)
            if r.returncode == 0:
                reach.append(ip)
        print(f'可达：{reach if reach else "只有本机"}')
        beyond_gw = [ip for ip in reach if ip != gw]
        if not beyond_gw:
            print('结论：❌ 局域网仍然不通（只到网关）——网线可能没插好，或隔离仍在')
            print('      下一步：确认 en0 已插线并拿到 IP（ifconfig en0），再跑本命令')
            return 1
        print(f'结论：✅ 能到其他设备了（{len(beyond_gw)} 台）→ 接着跑：')
        print('      python3 tools/vacuum_map.py discover      # 找扫地机')
        print('      python3 tools/vacuum_map.py prop --ip <机器人IP> --siid 6 --piid 8   # 读地图元数据')
        return 0

    if a.cmd == 'discover':
        hits = discover()
        if not hits:
            print('❌ 广播没收到回应（可能：机器人不在同一网段 / 只支持云连接 / 广播被 AP 隔离）')
            return 1
        for h in hits:
            mark = '← 扫地机' if h['did'] and str(h['did']) == str(dev['did']) else ''
            print(f"  {h['ip']}:{h['port']} did={h['did']} {mark}")
        return 0

    ip = a.ip or f"192.168.31.{dev.get('last_octet', '?')}"
    m = Miio(ip, dev['token'])
    print(f'握手 {ip}:{PORT} …')
    m.handshake()
    print('✅ 握手通过（令牌一致）')
    if a.cmd == 'info':
        m.send('miIO.info')
        print(json.dumps(m.recv(), ensure_ascii=False)[:600])
    elif a.cmd == 'prop':
        m.send('get_properties', [{'did': f"prop.{a.siid}.{a.piid}", 'siid': a.siid, 'piid': a.piid}])
        r = m.recv()
        print(json.dumps(r, ensure_ascii=False)[:1500])
    elif a.cmd == 'action':
        m.send('action', {'did': f"action.{a.siid}.{a.aiid}", 'siid': a.siid, 'aiid': a.aiid,
                          'in': []})
        print('动作已发出，等待回复/推送 …')
        for _ in range(6):
            r = m.recv(timeout=3)
            if r is None:
                continue
            s = json.dumps(r, ensure_ascii=False)
            print('  ←', s[:400])
            if a.listen and r.get('method'):
                break
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
