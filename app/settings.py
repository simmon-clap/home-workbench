#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能设置（设备 ↔ 房间绑定、短名、标签、离线阈值、手动录入设备）

依据：docs/spec/03-功能与交互规范 v1.1 §1D
  · 可编辑对象：设备↔房间绑定 · 展示短名 · 标签(type/sec) · 离线阈值
  · 两条路径：对话改（intent.py 走这里落盘）· 手动改（设置页直接改，不依赖 agent 在线）
  · 变更留痕：改了什么/什么时候/谁改的，可回滚
  · 一致性：只改**映射**，不改设备本身，不改米家原名（06 规则一）
  · 越权保护：安全域标签的改动必须显式确认；**agent 不许悄悄把设备移出安全域**
  · 11-代码规范 v1.0

存储：`data/settings.json`（仓库内、文本可读、随备份一起走）
"""
import datetime
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
SETTINGS = os.environ.get('SMART_HOME_SETTINGS') or os.path.join(DATA, 'settings.json')  # 环境变量供测试隔离用
STATE = os.path.join(DATA, 'state.json')
TZ = datetime.timezone(datetime.timedelta(hours=8))

EDITABLE = ('room', 'short_name', 'tags', 'offline_threshold_s')
TAGS = ('type', 'sec')
THRESHOLDS = (300, 600, 43200)          # 摄像头 / Wi-Fi 市电 / 电池（06 §3 参考值）


def _load(path, default):
    try:
        return json.load(open(path, encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return default


def doc():
    d = _load(SETTINGS, None)
    if not d:
        d = {'version': 1, 'overrides': {}, 'devices': [], 'history': []}
    for k, v in (('overrides', {}), ('devices', []), ('history', [])):
        d.setdefault(k, v)
    return d


def save(d):
    os.makedirs(DATA, exist_ok=True)
    json.dump(d, open(SETTINGS, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def rooms():
    """可用房间（以当前状态模型里出现过的房间为准，加上米家的 10 个固定房间）。"""
    st = _load(STATE, {'devices': []})
    got = {d['room'] for d in st.get('devices', []) if d.get('room')}
    fixed = ['客厅', '餐厅', '厨房', '主卧', '次卧', '书房', '主卫', '客卫', '阳台', '办公室']
    return sorted(got | set(fixed), key=lambda r: (fixed.index(r) if r in fixed else 99, r))


def device_names():
    st = _load(STATE, {'devices': []})
    return [d['name'] for d in st.get('devices', [])]


def is_security(name):
    st = _load(STATE, {'devices': []})
    d = next((x for x in st.get('devices', []) if x['name'] == name), None)
    return bool(d and d.get('security_domain'))


def validate(name, field, value, confirm=None, by='user'):
    """校验一次改动。返回错误字符串或 None。"""
    if field not in EDITABLE:
        return f'不可编辑的字段：{field}'
    if name not in device_names():
        return f'找不到设备「{name}」'
    if field == 'room':
        if value not in rooms():
            return f'没有这个房间：{value}'
    elif field == 'short_name':
        if not isinstance(value, str) or not value.strip():
            return '短名不能为空'
        if len(value.strip()) > 12:
            return '短名不要超过 12 个字'
    elif field == 'tags':
        bad = [t for t in (value or []) if t not in TAGS]
        if bad:
            return f'不认识的标签：{bad}'
        # 越权保护：把安全设备移出 sec 标签，必须显式确认（03 §1D）
        if is_security(name) and 'sec' not in (value or []) and by == 'agent':
            return '安全域设备不允许由 agent 移出 sec 标签（03 §1D 越权保护）'
        if is_security(name) and 'sec' not in (value or []) and not confirm:
            return '这台是安全域设备：移出 sec 标签需要显式确认'
    elif field == 'offline_threshold_s':
        if value not in THRESHOLDS:
            return f'离线阈值只能是 {THRESHOLDS} 之一（秒）'
    return None


def current(name, field):
    """取某设备某字段的当前生效值（含已应用的覆盖）。"""
    st = _load(STATE, {'devices': []})
    d = next((x for x in st.get('devices', []) if x['name'] == name), None)
    if not d:
        return None
    return {'room': d.get('room'), 'short_name': d.get('short_name'),
            'tags': d.get('tags'), 'offline_threshold_s': d.get('offline_threshold_s')}.get(field)


def set_field(name, field, value, by='user', confirm=None, note=None):
    """改一个字段：校验 → 落盘 → 记历史。返回 (是否成功, 说明)。"""
    err = validate(name, field, value, confirm=confirm, by=by)
    if err:
        return False, err
    d = doc()
    ov = d['overrides'].setdefault(name, {})
    base = ov.setdefault('_base', {})
    if field not in base:                      # 第一次覆盖这个字段时，记下米家的"底值"
        base[field] = current(name, field)
    before = ov.get(field, current(name, field))
    ov[field] = value
    d['history'].append({'id': next_hist_id(d),
                             'at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
                         'by': by, 'device': name, 'field': field,
                         'from': before, 'to': value, 'note': note})
    save(d)
    return True, f'{name} 的 {field} 已改为 {value}'


def next_hist_id(d):
    ids = [x.get('id') or 0 for x in (d.get('history') or [])]
    return (max(ids) + 1) if ids else 1


def undo_last(name=None, by='user', entry_id=None):
    """回滚一次改动。

    两种用法：
      · entry_id 给了 → **回滚那一笔**（设置页每条历史后面的"回滚"按钮走这条）
      · 否则回滚该设备（或全局）最近一笔
    为什么要有 entry_id：只按"最近一笔"回滚时，连点两次会变成"回滚上一次回滚"
    （实测把值又改回去了）—— 语义含糊，所以按条目回滚。
    """
    d = doc()
    hist = d.get('history') or []
    idx = None
    if entry_id is not None:
        for i, it in enumerate(hist):
            if it.get('id') == entry_id:
                idx = i
                break
    else:
        for i in range(len(hist) - 1, -1, -1):
            # 已经回滚过的条目不再参与"最近一笔"的挑选（否则会来回反复）
            if not hist[i].get('reverted') and (name is None or hist[i]['device'] == name):
                idx = i
                break
    if idx is None:
        return False, '没有可回滚的改动'
    if hist[idx].get('reverted'):
        return False, '这一笔已经回滚过了'
    h = hist[idx]
    h['reverted'] = True                      # **保留在历史里并标记**，而不是弹掉：
    h['reverted_at'] = datetime.datetime.now(TZ).isoformat(timespec='seconds')   # 否则历史会看起来对不上
    if h['field'] == 'zone_name':                     # 分区改名的回滚
        rn = d.setdefault('zone_names', {})
        zname = h['device'].replace('分区 ', '', 1)
        if h['from'] is None:
            rn.pop(zname, None)
        else:
            rn[zname] = h['from']
        d['history'].append({'id': next_hist_id(d),
                             'at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
                             'by': by, 'device': h['device'], 'field': h['field'],
                             'from': h['to'], 'to': h['from'], 'note': '回滚'})
        save(d)
        return True, '已回滚 ' + h['device'] + ' 的名字'
    if h['field'] == 'zone_room':                     # 分区映射的回滚
        zm = d.setdefault('zone_map', {})
        zname = h['device'].replace('分区 ', '', 1)
        if h['from'] is None:
            zm.pop(zname, None)
        else:
            zm[zname] = h['from']
        d['history'].append({'id': next_hist_id(d),
                                 'at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
                             'by': by, 'device': h['device'], 'field': h['field'],
                             'from': h['to'], 'to': h['from'], 'note': '回滚'})
        save(d)
        return True, '已回滚 ' + h['device'] + ' 到 ' + str(h['from'])
    ov = d['overrides'].setdefault(h['device'], {})
    base = ov.get('_base') or {}
    if h['from'] is None or h['from'] == base.get(h['field']):
        ov.pop(h['field'], None)               # 恢复到底值 = 不再需要覆盖 → 来源回到"米家"
        base.pop(h['field'], None)
        ov['_base'] = base
    else:
        ov[h['field']] = h['from']
    # 空壳清理：只剩空 _base 的覆盖条目直接删掉（否则文件里会积累空对象）
    if not [k for k in ov if not k.startswith('_')]:
        d['overrides'].pop(h['device'], None)
    d['history'].append({'id': next_hist_id(d),
                             'at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
                         'by': by, 'device': h['device'], 'field': h['field'],
                         'from': h['to'], 'to': h['from'], 'note': '回滚'})
    save(d)
    return True, f"已回滚 {h['device']} 的 {h['field']} 到 {h['from']}"


def add_device(name, room, short_name=None, by='user'):
    """手动录入设备（03 §1D：填房间 + 名称即可用）。未接入 HA 的会如实标注。"""
    if not name or not name.strip():
        return False, '设备名不能为空'
    name = name.strip()
    if name in device_names() or name in [m.get('name') for m in doc()['devices']]:
        return False, f'「{name}」已经在设备列表里了'      # 也要查手动录入过的（实测漏过）'
    if room not in rooms():
        return False, f'没有这个房间：{room}'
    d = doc()
    d['devices'].append({'name': name, 'room': room, 'short_name': short_name or name[:8],
                         'added_at': datetime.datetime.now(TZ).isoformat(timespec='seconds'), 'by': by})
    d['history'].append({'id': next_hist_id(d),
                             'at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
                         'by': by, 'device': name, 'field': 'add_device',
                         'from': None, 'to': room, 'note': '手动录入（未接入 HA）'})
    save(d)
    return True, f'已录入「{name}」（{room}）—— 未接入 HA，只作为位置占位，不能控制'


def history(limit=50):
    return list(reversed((doc().get('history') or [])[-limit:]))


# ── 米家依赖补录（判据 1）──
# 为什么要有：判据 1 是「一整天不用打开米家」。清单外的每一次"不得不打开米家"，
# 都是判据的真实缺口；必须能**当场记一笔**，否则过两天就忘了。
DEP_MAX_LEN = 60


def extra_deps():
    return list(doc().get('extra_deps') or [])


def add_dep(reason, where='米家', by='user'):
    """记一笔"今天又为了什么打开了米家"。"""
    reason = (reason or '').strip()
    if not reason:
        return False, '要写一句为什么'
    if len(reason) > DEP_MAX_LEN:
        return False, f'理由别超过 {DEP_MAX_LEN} 个字'
    d = doc()
    items = d.setdefault('extra_deps', [])
    if any(x.get('reason') == reason for x in items):
        return False, '这条已经记过了'
    items.append({'reason': reason, 'where': where or '米家', 'at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
                  'by': by})
    d['history'].append({'id': next_hist_id(d),
                             'at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
                         'by': by, 'device': f'依赖补录 {reason[:12]}', 'field': 'dep_note',
                         'from': None, 'to': reason, 'note': f'在{where or "米家"}做的事'})
    save(d)
    return True, f'已记下：{reason}（{where or "米家"}）'


def remove_dep(reason):
    d = doc()
    items = d.setdefault('extra_deps', [])
    keep = [x for x in items if x.get('reason') != reason]
    if len(keep) == len(items):
        return False, '没找到这条记录'
    d['extra_deps'] = keep
    d['history'].append({'id': next_hist_id(d),
                             'at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
                         'by': 'user', 'device': f'依赖补录 {reason[:12]}', 'field': 'dep_note',
                         'from': reason, 'to': None, 'note': '移除'})
    save(d)
    return True, f'已移除：{reason}'


# ── 分区映射（扫地机地图分区 → 我们的房间名）──
# 为什么需要：从米家分区图提取出的分区叫「房间1/房间2/走廊」，与我们的房间名只有「客厅」
# 天然对得上，其余必须由人确认（03 §1D：映射可改、留痕、可回滚）。
FLOORPLAN = os.path.join(DATA, 'floorplan.json')


def zones():
    """列出扫描得到的分区及其当前映射（未映射的排前面，方便填）。"""
    try:
        fp = json.load(open(FLOORPLAN, encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        return []
    m = doc().get('zone_map') or {}
    rn = doc().get('zone_names') or {}          # 改名覆盖：重新扫描几何也不会丢
    out = []
    for r in fp.get('rooms') or []:
        raw = r.get('name') or '分区'
        out.append({'zone': raw, 'label': rn.get(raw, raw), 'share': r.get('share'),
                    'kind': r.get('kind'), 'room': m.get(raw)})
    return sorted(out, key=lambda z: (z['room'] is not None, -(z['share'] or 0)))


def set_zone_name(zone, new_label, by='user'):
    """给分区改名（如"房间1" → "儿童房"）。

    为什么要覆盖表而不是改 floorplan.json：几何是**生成物**，重新扫描会覆盖它；
    改名属于人的意图，必须活在 settings.json 里才不会被冲掉（03 v1.3 §1D-2）。
    """
    new_label = (new_label or '').strip()
    if not zone:
        return False, '分区不能为空'
    if not new_label:
        return False, '新名字不能为空'
    if len(new_label) > 12:
        return False, '名字别超过 12 个字'
    known = {z['zone'] for z in zones()}
    if known and zone not in known:
        return False, '没有这个分区：' + zone
    d = doc()
    rn = d.setdefault('zone_names', {})
    before = rn.get(zone)
    if new_label == zone:
        rn.pop(zone, None)
    else:
        rn[zone] = new_label
    d['history'].append({'id': next_hist_id(d),
                         'at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
                         'by': by, 'device': '分区 ' + zone, 'field': 'zone_name',
                         'from': before, 'to': rn.get(zone), 'note': '分区改名'})
    save(d)
    return True, f'{zone} 改名为 {new_label}'
    return sorted(out, key=lambda z: (z['room'] is not None, -(z['share'] or 0)))


def set_zone(zone, room, by='user'):
    """把一个扫描分区映射到我们的房间名。"""
    if not zone:
        return False, '分区名不能为空'
    known = {z['zone'] for z in zones()}
    if known and zone not in known:
        return False, '没有这个分区：' + zone
    if room and room not in rooms():
        return False, '没有这个房间：' + room
    d = doc()
    zm = d.setdefault('zone_map', {})
    before = zm.get(zone)
    if room:
        zm[zone] = room
    else:
        zm.pop(zone, None)
    d['history'].append({'id': next_hist_id(d),
                             'at': datetime.datetime.now(TZ).isoformat(timespec='seconds'),
                         'by': by, 'device': '分区 ' + zone, 'field': 'zone_room',
                         'from': before, 'to': room, 'note': '分区映射'})
    save(d)
    return True, (zone + ' → ' + room if room else '已取消 ' + zone + ' 的映射')


def summary():
    d = doc()
    zs = zones()
    return {'overrides': len(d['overrides']), 'manual_devices': len(d['devices']),
            'history': len(d['history']), 'editable': list(EDITABLE) + ['zone_room'],
            'rooms': rooms(), 'thresholds': list(THRESHOLDS),
            'zones': len(zs), 'zones_mapped': sum(1 for z in zs if z.get('room'))}


if __name__ == '__main__':
    print(json.dumps(summary(), ensure_ascii=False, indent=1))
    for h in history(5):
        print(f"  {h['at'][11:19]} {h['by']:5s} {h['device'][:20]:22s} {h['field']:10s} "
              f"{h['from']} → {h['to']}")
