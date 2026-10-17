# 发布计划（2026-10-17 定稿）

## 用户已定
1. **开源**
2. **License：MIT**（代码与文档统一 MIT；第三方依赖保留其原许可证）
3. **目标用户：开发者**（README/安装文档按"懂 HA/Python 的开发者"写，不做小白向导）
4. **发布形态：GitHub 仓库**（源码仓库；不做 HA Add-on/HACS 首发）
5. **隐私红线**：家庭安全相关问题优先级最高；**自己的使用素材可以放，真实数据绝不放**

## 「素材」与「数据」的边界
| 可以放（素材） | 不可以放（数据/隐私） |
|---|---|
| 脱敏截图/录屏（用 demo 数据渲染） | 真实设备名/房间名/家庭名 |
| 示例配置 `config.example.json` | HA 长期令牌、小米 OAuth、SSH 私钥、PIN |
| 演示数据（假设备、假房间名、假状态） | 真实 state/audit/history/备份包 |
| 架构图、规范文档、测试夹具 | 家庭 IP、tailnet 主机名、内网拓扑 |
| 扫描到 3D 的**流程说明**与 demo 几何 | 真实户型扫描（`data/3d/**`） |
| 第三方依赖清单与许可证 | 摄像头画面、门锁/在家状态 |

## 发布前检查（必须全过）
1. `LICENSE` = MIT、`README.md` 面向开发者、`SECURITY.md`/`PRIVACY.md` 定稿
2. `python3 tools/release_audit.py` **PASS**（自动扫描个人标识/凭证/禁止路径）
3. 人工复核 `git ls-files`（只含代码/文档/示例）
4. demo 数据渲染的截图替换所有真实截图
5. `vendor/` 不入库，README 写明第三方安装步骤与许可证
6. 首版打 tag `v0.9.0`，说明"开发者预览"

## 仓库策略
- 当前 `~/smart-home/.git` 继续作为**私有开发仓**（含真实 README/个人材料，不推远端）
- 发布时用 `tools/build_public_repo.py` 生成干净的公开目录（白名单复制 + 脱敏 + 示例数据），推送到 GitHub
- 公开仓**永远不会有** `data/ config/ backups/ logs/ installers/ vm/ vendor/`
