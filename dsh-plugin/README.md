# DSH 桌面端插件：家庭工作台

**状态：已安装并启用**（desktop profile 的 `package.json` 启用清单里有 `dsh-family-workbench`）。

这个目录是**源码**（从已安装的包里取回，之前只剩 profile 里的副本，仓库里没有 —— 那样以后改不了）。

## 它在桌面端的样子
DSH 桌面端左侧/侧栏会出现「家庭工作台」入口，点开内嵌工作台页面（`http://127.0.0.1:8300/`）。
所以工作台服务要先起来：`launchctl kickstart -k gui/$(id -u)/com.simon.smarthome-server`

## 改完怎么装回去
```bash
cd dsh-plugin && npm pack            # 产出 dsh-family-workbench-<ver>.tgz
cp dsh-family-workbench-*.tgz ~/.dsh/plugins/
# 然后让 DSH 重装这个 file: 依赖（桌面端重启或按 DSH 插件管理流程重装）
```

## 红线
插件只做「入口 + 内嵌」，**不把家庭数据带进 DSH 的个人工作区**（宪章第六条 呈现域隔离）。
