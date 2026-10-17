#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
迁移物料校验（镜像与安装包是不是好的、是不是官方那一份）

为什么要有：如果 HA OS 镜像或 UTM 安装包是坏的/下载不全的，**9 点才发现会白等一场**。
这里做三件事：
  ① 与官方发布**逐字节对大小**（GitHub API；`--offline` 可跳过）
  ② `xz -t` 校验压缩流完整性（不落盘）
  ③ **流式**解压读取 qcow2 头 104 字节，验证 magic / 版本 / 虚拟磁盘大小
     （不写 400MB 临时文件 —— 用 `xz -dc | head -c 104` 那种思路，在 Python 里读前若干字节即可）

用法：
  python3 tools/verify_image.py            # 完整校验（含联网比对官方大小）
  python3 tools/verify_image.py --offline  # 只做本地校验
退出码：0 = 全部通过；1 = 有问题
"""
import argparse
import json
import os
import re
import struct
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.path.join(ROOT, 'data', 'images', 'haos_generic-aarch64-18.3.qcow2.xz')
UTM_GLOB_DIR = os.path.join(ROOT, 'installers')
HA_RELEASE = 'https://api.github.com/repos/home-assistant/operating-system/releases/tags/18.3'
UTM_RELEASE = 'https://api.github.com/repos/utmapp/UTM/releases/tags/v4.7.5'
# 本地大小下限（不依赖联网的合理性判断）：明显偏小 = 下载不全。
# 做成可注入，便于测试用**造出来的小文件**验证其它逻辑（实测踩过：测试被这条判失败）
MIN_IMAGE_BYTES = 200 * 1024 * 1024


def remote_sizes(url, names):
    """取官方发布里指定文件名的大小。失败返回 None（不影响本地校验）。"""
    try:
        with urllib.request.urlopen(url, timeout=40) as r:
            rel = json.load(r)
        out = {}
        for a in rel.get('assets') or []:
            if a.get('name') in names:
                out[a['name']] = a.get('size')
        return out
    except Exception:  # noqa
        return None


def xz_ok(path):
    try:
        r = subprocess.run(['xz', '-t', path], capture_output=True, text=True, timeout=600)
        return r.returncode == 0, (r.stderr or '').strip()[:120]
    except Exception as err:  # noqa
        return False, str(err)[:120]


def qcow2_header_via_stream(path, want_bytes=104):
    """流式解压读前 want_bytes 字节（不落盘）。"""
    p = subprocess.Popen(['xz', '-dc', path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        head = p.stdout.read(want_bytes)
    finally:
        p.stdout.close()
        try:
            p.kill()
        except OSError:
            pass
    if len(head) < want_bytes:
        return None, f'解压后读到 {len(head)} 字节（不足 {want_bytes}）'
    magic = head[:4]
    version = struct.unpack('>I', head[4:8])[0]
    cluster_bits = struct.unpack('>I', head[20:24])[0]
    virtual = struct.unpack('>Q', head[24:32])[0]
    return {'magic': magic, 'version': version, 'cluster_bits': cluster_bits,
            'virtual_bytes': virtual, 'virtual_gb': round(virtual / 1073741824, 1)}, ''


def check(offline=False):
    problems, info = [], {}
    if not os.path.exists(IMAGE):
        return ['缺 HA OS 镜像 ' + os.path.relpath(IMAGE, ROOT)], info
    size = os.path.getsize(IMAGE)
    info['image_bytes'] = size

    if not offline:
        names = {'haos_generic-aarch64-18.3.qcow2.xz'}
        rs = remote_sizes(HA_RELEASE, names)
        if not rs:
            # 联网比对不可用（限流/断网）——**如实记一笔**，不当失败，但也不假装比过了
            info['official_check'] = 'unavailable（GitHub API 限流或网络不通）本次只做本地校验'
        if rs and names <= set(rs):
            official = rs['haos_generic-aarch64-18.3.qcow2.xz']
            info['image_official_bytes'] = official
            if official != size:
                problems.append(f'镜像大小与官方不一致：本地 {size} / 官方 {official}')

        import glob
        dmg = glob.glob(os.path.join(UTM_GLOB_DIR, 'UTM*.dmg'))
        if dmg:
            dsize = os.path.getsize(dmg[0])
            info['utm_bytes'] = dsize
            ru = remote_sizes(UTM_RELEASE, {'UTM.dmg'})
            if ru and 'UTM.dmg' in ru:
                info['utm_official_bytes'] = ru['UTM.dmg']
                if ru['UTM.dmg'] != dsize:
                    problems.append(f'UTM 安装包大小与官方不一致：本地 {dsize} / 官方 {ru["UTM.dmg"]}')
        else:
            problems.append('缺 UTM 安装包（installers/UTM*.dmg）')

    ok_xz, detail = xz_ok(IMAGE)
    info['xz_ok'] = ok_xz
    if not ok_xz:
        problems.append(f'压缩流校验失败：{detail}')

    if size < MIN_IMAGE_BYTES:
        problems.append(f'镜像只有 {size / 1048576:.1f} MB，明显偏小（下载不全？）')

    head, err = qcow2_header_via_stream(IMAGE)
    if head is None:
        problems.append(f'读 qcow2 头失败：{err}')
    else:
        info.update({'qcow2_magic': 'QFI\\xfb' if head['magic'] == b'QFI\xfb' else repr(head['magic']),
                     'qcow2_version': head['version'],
                     'virtual_gb': head['virtual_gb']})
        if head['magic'] != b'QFI\xfb':
            problems.append('解压后的文件不是合法 qcow2（magic 不对）')
        if head['virtual_bytes'] <= 0:
            problems.append('qcow2 虚拟磁盘大小为 0')
    return problems, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--offline', action='store_true')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    problems, info = check(offline=a.offline)
    if a.json:
        print(json.dumps({'ok': not problems, 'info': info, 'problems': problems},
                         ensure_ascii=False, indent=1))
        return 0 if not problems else 1
    print('=== 迁移物料校验 ===')
    if 'image_bytes' in info:
        line = f"  HA OS 镜像：{info['image_bytes']} 字节"
        if 'image_official_bytes' in info:
            line += '（与官方逐字节一致 ✅）' if info['image_bytes'] == info['image_official_bytes'] \
                    else f"（官方 {info['image_official_bytes']} ❌）"
        print(line)
    if 'utm_bytes' in info:
        line = f"  UTM 安装包：{info['utm_bytes']} 字节"
        if 'utm_official_bytes' in info:
            line += '（与官方逐字节一致 ✅）' if info['utm_bytes'] == info['utm_official_bytes'] \
                    else f"（官方 {info['utm_official_bytes']} ❌）"
        print(line)
    print(f"  压缩流完整性：{'✅ 通过' if info.get('xz_ok') else '❌ 失败'}")
    if 'qcow2_magic' in info:
        print(f"  解压后 qcow2：magic={info['qcow2_magic']} · v{info['qcow2_version']} · "
              f"虚拟磁盘 {info['virtual_gb']} GB")
    if info.get('official_check'):
        print(f"  ⚠️ {info['official_check']}")
    print()
    if problems:
        print('结论：❌ 有问题 —— ' + '；'.join(problems))
        return 1
    print('结论：✅ 物料可用（镜像与安装包校验通过）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
