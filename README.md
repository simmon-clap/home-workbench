# 家庭工作台（Home Workbench）

> 一个跑在自家常驻 Mac / Linux 上的智能家居中枢：**原生 Home Assistant OS + 自研中文工作台**。
> 目标：**一整天不用打开米家 App**，同时把安全域（门锁/摄像头/在家状态）隔离在对话与第三方生态之外。

**状态：开发者预览 v0.9.0（MIT）** · 面向**开发者**（假设你懂 Home Assistant、Python、基础运维）

## 为什么做这个
米家 App 是"设备列表"，苹果「家庭」是"遥控器"。我们想要的是**一个能回答'家里现在怎么样'、能听一句话去执行、并且对安全域有底线**的工作台。

## 功能
- **状态真相**：设备台账 + 实时状态（来源/可信度/时间），异常设备显式说出且带离线时长
- **三层交互**：全屋 2.5D → 房间 → 设备；控制有回读、失败说原因、可撤销
- **一句话执行**：自然语言 → 意图 → 场景展开 → 执行 → 回读 → 三段式回执（部分失败如实报）
- **主动性与安全域**：安全事件必达；门锁/摄像头等**只提醒不自动执行**，对话通道永不自授权
- **苹果生态**：HomeKit 桥只暴露非安全域设备（家庭 App / Siri / Apple Watch）
- **多端**：手机/iPad PWA + 桌面插件入口；断网有诚实的离线页（不展示旧数据）
- **可审计**：每次动作有时间/主体/来源/结果/回读值
- **房间 3D（开发中）**：RoomPlan 扫描 → 真实尺寸 3D；平面/可编辑模型/整屋数据模型分层

## 架构
```
iPhone/Web ─┐
HomeKit ────┼─→ 家庭工作台（Python 标准库，零第三方运行时）
Apple Watch ┘        │ 官方 REST/WebSocket（长期令牌）
                     ▼
             Home Assistant OS（虚拟机/裸机，桥接局域网）
                     │ xiaomi_home 集成（米家设备）
```
无云依赖、无遥测；可选 Tailscale 私网访问（默认只绑 127.0.0.1）。

## 运行要求
- Home Assistant（OS/Container 均可）+ 小米账号 OAuth
- Python 3.9+（工作台零第三方依赖；Node 仅 3D 构建期用）
- 常驻主机（macOS 已验证；Linux 理论可用）

## 快速开始（开发者）
```bash
git clone <repo> && cd home-workbench
cp docs/CONFIGURATION.md.example .env   # 或直接 export 环境变量
export HA_BASE_URL=http://<HA_HOST>:8123
export HA_TOKEN_FILE=~/.config/smart-home/ha-token   # 长期令牌，不要进仓库
python3 app/state.py        # 生成 data/state.json
python3 app/server.py       # http://127.0.0.1:8300
python3 tools/gate.py       # 109 项自检（部分检查需要你的 HA 在线）
```

## 隐私与数据（重要）
- **真实数据永不出现在仓库**：设备名/房间/状态/审计/备份/令牌/户型全部被 `.gitignore` 排除
- 素材（脱敏截图、demo 数据、架构图）可以进仓库；**数据不行**——这是本项目的硬边界
- 详见 [PRIVACY.md](PRIVACY.md)、[SECURITY.md](SECURITY.md)

## 路线
v0.9.x：开源发布、示例数据、备份加密、离线 CI
v1.0：真实房型 3D（RoomPlan 多房间）、通知通道抽象、多用户/访客
之后：摄像头 AI（Frigate）、iPad 墙面屏、Matter

## 许可证
[MIT](LICENSE)
