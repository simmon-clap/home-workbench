/**
 * 家庭工作台 · 服务端插件（最小实现）
 *
 * 依据：docs/spec/10-开发计划-v1.1 §P6（桌面端 DSH 独立入口）· 11-代码规范 v1.0
 *
 * 做什么：作为插件存在的服务端锚点（登记名字、记录一次就绪日志）。
 * 界面入口在 client/client.js 里注册（侧边栏一项 + 主区域 iframe 指向本机工作台）。
 * 不做什么：不注册工具、不碰会话、不改动任何 Host 状态 —— 保持最小，降低把 profile 弄坏的风险。
 */
export const name = 'dsh-family-workbench';

/** 不依赖任何 Host 服务，避免影响 profile 加载。 */
export const inject = [];

export function apply(ctx) {
  // 只记一条日志；入口本身由客户端插件注册。
  try {
    ctx?.logger?.info?.('[family-workbench] 桌面入口已就绪（client 侧注册侧边栏与主区域）');
  } catch {
    // 日志失败不影响加载（但也不吞掉其它异常）
  }
}
