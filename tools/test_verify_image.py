#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
迁移物料校验的测试（tools/verify_image.py）

价值全在"**坏的东西必须被拒绝**"：镜像下载不全、压缩流损坏、解压出来不是 qcow2，
这三种情况到 9 点才发现就白等一场。所以三个都用**造出来的文件**验证一遍。

用法：python3 tools/test_verify_image.py      退出码 0 = 全过
"""
import importlib.util
import os
import struct
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix='verify-img-test-')
OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def make_qcow2():
    """造一个头部合法的 qcow2（magic + v3 + 64KB 簇 + 32GB 虚拟盘）。"""
    h = bytearray(104)
    h[0:4] = b'QFI\xfb'
    struct.pack_into('>I', h, 4, 3)
    struct.pack_into('>I', h, 20, 16)
    struct.pack_into('>Q', h, 24, 32 * 1024 ** 3)
    return bytes(h) + b'\x00' * 4096


def xz_file(data, name):
    raw = os.path.join(TMP, name + '.raw')
    out = os.path.join(TMP, name + '.qcow2.xz')
    open(raw, 'wb').write(data)
    subprocess.run(['xz', '-kf', raw], check=True)
    os.replace(raw + '.xz', out)
    os.remove(raw)
    return out


def main():
    spec = importlib.util.spec_from_file_location('vi', os.path.join(ROOT, 'tools', 'verify_image.py'))
    vi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vi)
    vi.MIN_IMAGE_BYTES = 0        # 测试用造出来的小文件，关掉"大小下限"这条（真环境那条仍在测）

    good = xz_file(make_qcow2(), 'good')
    vi.IMAGE = good
    problems, info = vi.check(offline=True)
    check('合法镜像 → 校验通过', not problems, str(problems))
    check('读出 qcow2 版本与虚拟盘大小', info.get('qcow2_version') == 3 and info.get('virtual_gb') == 32.0,
          f"v{info.get('qcow2_version')} / {info.get('virtual_gb')}GB")
    check('压缩流校验通过', info.get('xz_ok') is True)

    # 不是 qcow2（比如下成了 HTML 错误页）
    html = xz_file(b'<!DOCTYPE html><html>404</html>' + b' ' * 4096, 'html')
    vi.IMAGE = html
    problems2, info2 = vi.check(offline=True)
    check('解压出来不是 qcow2 → 判失败', any('不是合法 qcow2' in p for p in problems2), str(problems2))

    # 压缩流损坏
    broken = os.path.join(TMP, 'broken.qcow2.xz')
    data = open(good, 'rb').read()
    open(broken, 'wb').write(data[:-20] + b'\x00' * 20)
    vi.IMAGE = broken
    problems3, info3 = vi.check(offline=True)
    check('压缩流损坏 → 判失败', info3.get('xz_ok') is False or bool(problems3),
          str(problems3)[:80])

    # 缺文件
    vi.IMAGE = os.path.join(TMP, '不存在.xz')
    problems4, _ = vi.check(offline=True)
    check('缺镜像 → 判失败且点名', any('缺 HA OS 镜像' in p for p in problems4), str(problems4))

    # 真环境（联网比对官方大小，但**不重新下载**）
    vi.IMAGE = os.path.join(ROOT, 'data', 'images', 'haos_generic-aarch64-18.3.qcow2.xz')
    problems5, info5 = vi.check()
    # **不依赖外部接口**：联网可用就比对；限流/断网时要**如实说明**且不判失败
    # （2026-10-17 实测：GitHub API 403 限流会让这条假红，门禁可信度就是这么被毁掉的）
    if info5.get('image_official_bytes'):
        check('真环境：与官方逐字节一致',
              info5['image_bytes'] == info5['image_official_bytes'], str(info5)[:110])
    else:
        check('真环境：联网比对不可用时如实说明（不假装比过、也不假红）',
              bool(info5.get('official_check')) and not problems5,
              str(info5.get('official_check'))[:80])
    check('真环境：本地校验（压缩流 + qcow2 头）依然全过',
          info5.get('xz_ok') is True and info5.get('qcow2_version') == 3,
          f"xz={info5.get('xz_ok')} v{info5.get('qcow2_version')} 虚拟盘 {info5.get('virtual_gb')}GB")
    check('真环境：镜像大小在合理区间（本地判断，不依赖联网）',
          info5.get('image_bytes', 0) > 200 * 1024 * 1024, str(info5.get('image_bytes')))

    # 接入体检
    src = open(os.path.join(ROOT, 'tools', 'preflight.py'), encoding='utf-8').read()
    check('开工前体检已包含物料校验', 'verify_image' in src)

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
