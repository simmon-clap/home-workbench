# 扫描房间 · 静态背景对照页（生成物）

- **生成器**：`tools/scan_room.py`（Python 标准库，离线生成；不联网、运行期零第三方）
- **几何来源**：`data/3d/rooms/*.json`（`schema=scan_room/v2`，每间一次 RoomPlan 扫描归一化，单位 m）
  - 原始扫描：`data/3d/scans/<房间>-<日期>.json`（cm；同名 `.pdf` 只用于人工核对）
- **重新生成**：
  - 处理一间新扫描：`python3 tools/scan_room.py "<房间>-<日期>"`（同时刷新本页）
  - 只重建本页：`python3 tools/scan_room.py --all`
- **产物**：`app/web/space/scan-room.html`（静态背景对照：等距 3D + 俯视平面 + 家具清单 + 待确认项）；
  `data/3d/rooms/<name>.json`（可读几何，页面不是唯一真相源）与 `.plan.svg`（带尺寸俯视平面）
- **为什么是生成物**：几何是真实测量、不该在浏览器里重算；几何另存可读 JSON，页面仅作对照。
- **运行期零第三方**：内联 SVG + 内联 CSS，无外部 JS/CSS/CDN；不含实时设备状态。
- **产品级 3D 不在这里**：`scan-room-model.html` 由另一条线维护（`app/prototype/scan-room-editor/build-room.mjs`），
  本页只做静态背景对照；两边共用同一份 `data/3d/rooms/*.json`。
- **多间**：本页按 `data/3d/rooms/*.json` 顺序逐个渲染；`<name>.edited.json` 的家具编辑只读合并，不改基础几何。
- **数据增改**：schema v2 只增字段（`schema/bounds/rooms/floor/pending/openings[].type/furniture.catalog|arms`），
  v1 字段名与单位不变；详见 `data/3d/README.md`。
