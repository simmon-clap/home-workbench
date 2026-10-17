# 实验性脚本（不在主流程里）

这里放**探索过但还没进产品**的脚本。它们不是死代码，是研究记录；
真正要接着做时再从这里拿出来，别让它们污染主流程的阅读。

| 脚本 | 探索什么 | 结论 |
|---|---|---|
| `vacuum_map.py` / `vacuum_map_via_ha.py` | 从 HA 侧拿扫地机地图 | HA 侧拿不到（无 camera/image 实体、集成不给地图、无 map 服务） |
| `floorplan_from_shot.py` / `regularize_floorplan.py` | 从照片/截图提取户型 | 原型阶段；正式方案见 `docs/spec/03` 空间结构 |

扫地机地图的**可行路径**已确认（miIO 本地协议读 siid=6/piid=8），见项目记忆与
`data/扫地机地图-可行路径.md`（如有）。不要走小米云私有接口。
