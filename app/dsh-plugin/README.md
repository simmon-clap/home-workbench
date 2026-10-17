# dsh-family-workbench

DSH 的「家庭工作台」独立入口插件（**只装 mini**，不装笔记本那端）。

- 侧边栏一项「家庭工作台」（order 12）
- 主区域用 iframe 指向本机家庭工作台 `http://127.0.0.1:8300/`
- 服务端侧保持最小（无 inject、不改 Host 状态），降低影响 profile 的风险

依据：`~/smart-home/docs/spec/10-开发计划-v1.1` §P6
