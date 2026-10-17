#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据导出（依据 docs/spec/07-数据与记忆规范 v1.0 §6：十年可读）

产出（默认写到 data/export/）：
  state-YYYYMMDD.json     完整状态模型（JSON，字段自解释）
  devices-YYYYMMDD.csv    设备台账（CSV，Excel/Numbers 可直接打开）
  attention-YYYYMMDD.csv  待注意清单（CSV）
  README.txt              这一份导出里有什么、字段什么意思

原则：纯文本 + 开放格式 + 字段自解释，十年后打开还能读懂；不含任何影像与凭证。
用法：python3 app/export.py [--out data/export]
"""
import argparse
import csv
import datetime
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TZ = datetime.timezone(datetime.timedelta(hours=8))

FIELDS = [
    ('room', '房间（与米家一致）'), ('name', '设备名（与米家一致，未改名）'),
    ('manufacturer', '品牌'), ('model', '型号'), ('type', '类型（图形库分类）'),
    ('security_domain', '是否安全域（true=只提醒不自动执行）'),
    ('state', '状态'), ('confidence', '可信度：online/offline/stale/unknown'),
    ('source', '来源（哪来的这条状态）'), ('observed_at', '最后有效读数时间（无则为空）'),
    ('status_at', '当前状态的生效时间'), ('observed_note', '读数的文字说明'),
    ('age_seconds', '距最后有效读数的秒数'), ('offline_threshold_s', '离线判定阈值（秒）'),
    ('entity_id', 'HA 主实体 id'), ('entity_count', '实体数量'),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(ROOT, 'data', 'export'))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    now = datetime.datetime.now(TZ)
    stamp = now.strftime('%Y%m%d')

    state_path = os.path.join(ROOT, 'data', 'state.json')
    if not os.path.exists(state_path):
        raise SystemExit('data/state.json 不存在，请先运行 app/state.py')
    st = json.load(open(state_path, encoding='utf-8'))

    p_json = os.path.join(a.out, f'state-{stamp}.json')
    json.dump(st, open(p_json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    for fname, rows, fields in (
        (f'devices-{stamp}.csv', st.get('devices', []), [f[0] for f in FIELDS]),
        (f'attention-{stamp}.csv', st.get('attention', []),
         ['level', 'kind', 'room', 'device', 'issue', 'detail', 'suggestion']),
    ):
        with open(os.path.join(a.out, fname), 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k) for k in fields})

    readme = [f'智能家居数据导出 · {now.isoformat(timespec="seconds")}',
              '=' * 40,
              f'state-{stamp}.json    完整状态模型（{"devices" if "devices" in st else "?"} + rooms + attention + summary）',
              f'devices-{stamp}.csv   设备台账，字段含义见下',
              f'attention-{stamp}.csv 需要人注意的事项（安全优先）', '',
              '字段说明：']
    readme += [f'  {k:<20} {v}' for k, v in FIELDS]
    readme += ['', '说明：',
               '  1. 设备名与房间名与米家 App 保持一致，本系统不做重命名。',
               '  2. 不确定性是显式的：confidence=unknown 表示从未收到有效读数，不允许当作在线。',
               '  3. 导出内容不含影像、凭证、门锁明细等 C 类数据（08 规范第 7 节）。']
    open(os.path.join(a.out, 'README.txt'), 'w', encoding='utf-8').write('\n'.join(readme) + '\n')

    print(f'✅ 已导出到 {os.path.relpath(a.out, ROOT)}/')
    for f in sorted(os.listdir(a.out)):
        print(f'   {f}  {os.path.getsize(os.path.join(a.out, f))} B')


if __name__ == '__main__':
    main()
