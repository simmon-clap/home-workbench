# 扫描房间 · 可编辑 3D 模型（生成物）

- **生成器**：`app/prototype/scan-room-editor/build-room.mjs`（Node，Anatomy iso-kit，离线生成）
- **几何来源**：`data/3d/rooms/客厅餐厅-20261017.json`（RoomPlan 扫描，真实尺寸）+ 同名 `.edited.json`（编辑器保存的覆盖版）
- **重新生成**：`node app/prototype/scan-room-editor/build-room.mjs`
- **交互**：悬停 → 构件轮廓高亮（橙色）+ 名称浮标；点击 → 选中并在右侧面板编辑
  语义类型（沙发/桌子/椅子/柜子/电视/门/窗/墙/区域/其他）、名称、宽深高、位置、旋转；
  保存 → `POST /api/3d/edit` → 写入 `.edited.json` 并重建本页（约 1 秒）。
- **尺寸**：工作单位 cm；墙/门/窗剖切 105 cm；真实墙高 264 cm 记录在数据里。
- **零第三方运行时**：SVG 内联，Anatomy kit 只在构建期使用（`kit/iso-kit.mjs`，MIT）。

## 缩略图（工作台客厅面板用）

- `app/web/space/scan-room-thumb.svg`：`build-room.mjs` 生成（自带样式，可独立打开）
- `app/web/space/scan-room-thumb.png`：由 headless Chrome 对该 SVG 截图生成：
  `chrome --headless=new --window-size=940,700 --screenshot=app/web/space/scan-room-thumb.png http://127.0.0.1:8300/space/scan-room-thumb.svg`
- 客厅面板用 CSS 背景图引用 PNG（不依赖异步加载），点开进可编辑页。
