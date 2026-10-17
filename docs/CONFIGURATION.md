# 配置项（对外版）

本系统**不把家庭信息写死在代码里**。配置全部走环境变量或本机文件，仓库里只保留示例。

## 环境变量
| 变量 | 默认 | 说明 |
|---|---|---|
| `HA_BASE_URL` | `http://127.0.0.1:8123` | Home Assistant 地址（或通过 `~/.config/smart-home/ha-base-url`） |
| `HA_TOKEN_FILE` | `~/.config/smart-home/ha-token` | HA 长期令牌文件（权限 600） |
| `SMART_HOME_HAOS_HOST` | 无（必填） | HA OS 虚拟机地址（备份/同步脚本用） |
| `SMART_HOME_HOMEKIT_PIN` | `827-43-916` | HomeKit 桥配置里的码（注意：HA 2026.10 实际用启动随机码，仅作配置完整性） |
| `SMART_HOME_STATE_SOURCE` | `auto` | `api` / `files` / `auto`：状态层读 HA 的方式 |
| `SMART_HOME_STATE_OUT` | `data/state.json` | 状态产物路径（测试用） |
| `SMART_HOME_WORKBENCH_HOST/PORT` | `127.0.0.1` / `8300` | 工作台监听地址（默认只绑本机） |

## 本机文件（.gitignore 覆盖，永不入库）
- `~/.config/smart-home/ha-token`（HA 令牌）
- `~/.config/smart-home/haos_ssh`（HA OS SSH 私钥）
- `~/.config/smart-home/workbench-pin`（工作台 PIN）
- `data/`、`config/`、`backups/`、`logs/`

## 迁移到别人的机器
1. 复制代码仓库（不含 data/config）
2. 设置上面的环境变量（或用 `~/.config/smart-home/` 文件）
3. 跑 `python3 app/state.py` → `python3 app/server.py`
4. 首次使用需要在自己的 HA 里完成小米 OAuth、建长期令牌

> 发布前还需提供 `config.example.json` 与示例数据（下一步）。
