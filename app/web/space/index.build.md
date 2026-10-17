# 空间视图（生成物）

- **来源**：`app/prototype/spatial/build_scan.mjs` 读取 `data/floorplan.json` 离线生成
- **重新生成**：`node app/prototype/spatial/build_scan.mjs`
- **为什么是生成物**：房间几何是从米家分区图（扫地机建图输出）里**离线**算出来并规则化的，
  不该在浏览器里每次重算；几何来源可追溯（`data/floorplan.json` 的 `source`/`source_file`）。
- **不是唯一真相源**：页面本身只画几何；房间的异常状态在运行时从 `/api/state`（L2 状态模型）读取。
  读不到实时状态时会**如实说明**"显示的是扫描几何，不是设备状态"。
- **零第三方**：不引用任何外部 JS/CSS，无 `node_modules`。
- **体积**：约 7 KB（规范上限 1.5MB）。
- **与主屏的分工**：主屏的 2.5D 是**实时**空间图（`app/web/app.js` 的 `drawHouse`）；
  本页是**扫描几何的快照视图**（用于核对分区/家具几何是否对得上）。
