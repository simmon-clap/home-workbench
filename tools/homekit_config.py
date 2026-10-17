#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HomeKit 桥配置生成（从白名单到 HA 的 `homekit:` 配置块）

为什么要有：迁移到 HA OS 后要配 HomeKit 桥。这一步如果在窗口内临场手写 YAML，既慢又容易漏掉
"安全域不能暴露"这条红线。所以提前把白名单**机械地**翻成配置，并且用测试钉死红线。

红线（05 v1.1 §9-2 + 08 v1.2 §7 + 宪章第六条）：
  · 只允许 A 类暴露；**B/C 类（安全域：门锁 / 摄像头 / 在家状态）永不暴露**
  · A 类里"只读"的（烟感/水浸/燃气读数）以传感器方式暴露，用于苹果侧的**紧急通知**
  · 命名与房间单向同步自米家 + L2，不反向改

用法：
  python3 tools/homekit_config.py                 # 打印配置块（人看）
  python3 tools/homekit_config.py --yaml          # 只打印 YAML（可直接贴进 configuration.yaml）
  python3 tools/homekit_config.py --check         # 红线自检（门禁/迁移后用）
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPOSURE = os.path.join(ROOT, 'data', 'homekit-exposure.json')
BRIDGE_NAME = '家庭工作台'
# 配对码：**HA 2026.10 实测不读这里的固定码** —— 每次启动由 pyhap 随机生成，
# 在 HA 通知「HomeKit Pairing」/ 启动日志 `Pincode:` 里看（2026-10-17 配对实测：
# 写 827-43-916 会被 iPhone 判"设置代码不正确"，HA 实际用的是随机码）。
# 这里仍写一个合法码只是为了配置完整与可迁移；真正生效的是 HA 启动时生成的那个。
PINCODE = os.environ.get('SMART_HOME_HOMEKIT_PIN', '827-43-916')


def load(path=None):
    return json.load(open(path or EXPOSURE, encoding='utf-8'))


def select(doc):
    """从白名单里选出可暴露实体，并断言安全域**一个都不在里面**。

    实际 schema（2026-10-17 核对过真实文件）：`class` 取值是 **'A'**（可控制）与 **'A-readonly'**
    （只读安全读数：烟感/水浸/燃气），另带 `readonly: true`。**不是**我以为的"A + readonly 标志"——
    所以判据按真实取值写，任何非 A 开头的类都直接抛错。

    返回 (可控制列表, 只读列表)。宁可不生成，也不生成一份错的。
    """
    include = doc.get('include') or []
    bad = [e for e in include if not str(e.get('class') or '').startswith('A')]
    if bad:
        raise ValueError(f'白名单里混进了非 A 类：{[e.get("device") for e in bad][:3]}')
    readonly = [e for e in include
                if e.get('readonly') or str(e.get('class')) == 'A-readonly']
    writable = [e for e in include if e not in readonly]
    return writable, readonly


def banned_entities(doc):
    """明确不该出现的实体（安全域 C 类）。用于自检。"""
    out = set()
    for e in (doc.get('exclude') or []):
        if e.get('entity_id'):
            out.add(e['entity_id'])
    return out


def build_yaml(doc=None, bridge_name=BRIDGE_NAME):
    doc = doc or load()
    writable, readonly = select(doc)
    # 实体 id 去重且排序：输出稳定（diff 友好，也便于测试）
    # **可控制 + 只读读数都要进 include_entities**。
    # 2026-10-17 实测：只读读数（烟感/水浸/燃气）之前只写在 entity_config 里 → 根本没进桥，
    # 苹果侧收不到它们的告警。去掉 entity_config 后测试立刻抓到了这个。
    inc = sorted({e['entity_id'] for e in writable} | {e['entity_id'] for e in readonly})
    lines = [
        '# HomeKit 桥（由 tools/homekit_config.py 依据 data/homekit-exposure.json 生成，勿手改）',
        '# 红线：只暴露 A 类；安全域（门锁/摄像头/在家）永不暴露（05 v1.1 §9-2 / 08 v1.2 §7 / 宪章第六条）',
        'homekit:',
        '  - name: ' + bridge_name,
        '    port: 21064',
        '    mode: bridge',
        f'    pincode: "{PINCODE}"',
        '    filter:',
        '      include_entities:',
    ]
    lines += [f'        - {eid}' for eid in inc]
    lines += [
        '      exclude_domains:',
        '        - lock                    # 安全域：门锁永不暴露',
        '        - camera                  # 安全域：摄像头永不暴露',
        '        - alarm_control_panel',
    ]
    # entity_config：**只写 name**（给 Siri 用短名）。2026-10-17 迁移时踩过的坑是
    # `linked_battery_sensor: null` 非法导致 homekit 集成整段加载失败——所以这里严格只写 name，
    # 且名字里的单引号先去掉，避免 YAML 引号问题。
    named = [e for e in (doc.get('include') or []) if e.get('name')]
    if named:
        lines.append('    entity_config:')
        for e in named:
            nm = str(e['name']).replace("'", '').replace('\n', ' ').strip()
            if not nm:
                continue
            lines.append(f"      {e['entity_id']}:")
            lines.append(f"        name: '{nm}'")
    lines.append('')
    lines.append(f'# 可控制 {len(inc)} 个 · 只读读数 {len(readonly)} 个 · 永不暴露 {len(doc.get("exclude") or [])} 个设备')
    return '\n'.join(lines)


def check(doc=None):
    """红线自检：产物里**绝不能**出现被禁实体；数量与白名单一致。"""
    doc = doc or load()
    text = build_yaml(doc)
    banned = banned_entities(doc)
    leaked = sorted(e for e in banned if e in text)
    writable, readonly = select(doc)
    # include_entities 里应当包含**全部 A 类**（可控制 + 只读读数）——只读那 3 台也要在，
    # 否则苹果侧收不到烟感/水浸/燃气的紧急通知（第一版自检把它们算漏了，实测抓到）
    expect = len({e['entity_id'] for e in writable} | {e['entity_id'] for e in readonly})
    # 只数 include_entities 段里的条目（以前用全文 count，会把 exclude_domains 的 3 行也数进去）
    in_inc, got = False, 0
    for ln in text.splitlines():
        st = ln.strip()
        if st == 'include_entities:':
            in_inc = True; continue
        if in_inc and st.startswith('- '):
            got += 1
        elif in_inc and st and not st.startswith('- ') and not st.startswith('#'):
            in_inc = False
    problems = []
    if leaked:
        problems.append(f'泄露了被禁实体 {leaked[:3]}')
    if got != expect:
        problems.append(f'条目数对不上：期望 {expect}，实际 {got}')
    if 'exclude_domains' not in text:
        problems.append('缺少 exclude_domains 兜底')
    return problems, {'writable': len({e['entity_id'] for e in writable}),
                      'readonly': len(readonly), 'total': expect,
                      'banned': len(banned), 'excluded_devices': len(doc.get('exclude') or []),
                      'bridge': BRIDGE_NAME}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--yaml', action='store_true')
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    doc = load()
    if a.yaml:
        print(build_yaml(doc)); return 0
    problems, info = check(doc)
    if a.check:
        if problems:
            print('❌ HomeKit 配置自检不通过：' + '；'.join(problems)); return 1
        print(f"✅ HomeKit 配置自检通过：可控制 {info['writable']} 个 · 只读读数 {info['readonly']} 个"
              f"（共进桥 {info['total']} 个）· **永不暴露 {info['excluded_devices']} 个安全域设备**")
        return 0
    print(build_yaml(doc))
    print(f"\n（自检：{'通过' if not problems else '不通过 ' + str(problems)}）")
    return 0 if not problems else 1


if __name__ == '__main__':
    sys.exit(main())
