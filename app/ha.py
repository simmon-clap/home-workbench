#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Home Assistant 客户端（L3 执行层的地基）

依据：docs/spec/05-技术架构规范 v1.0 §4（读状态用 API、执行后**必须回读**）· 08 §6（凭证不进代码/日志）
      11-代码规范 v1.0 §8（凭证只从 ~/.config/smart-home/ 读）

凭证：读取 `~/.config/smart-home/ha-token`（600 权限，仓库之外，不进备份）。
      文件不存在时**明确报未配置**，绝不假装能用（09 §1 真话优先）。

自检：python3 app/ha.py            # 只报告令牌是否存在 + 能否连上 HA，不打印令牌内容
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _base_from_config():
    """地址优先级：环境变量 > ~/.config/smart-home/ha-base-url > 默认。

    迁移到 HA OS 后地址变成局域网 IP，**定时任务的 LaunchAgent 不带环境变量**，
    所以必须支持配置文件，否则那些任务会静默地连不上（2026-10-17 为此加的）。
    """
    env = os.environ.get('HA_BASE_URL')
    if env:
        return env
    try:
        with open(os.path.expanduser('~/.config/smart-home/ha-base-url')) as f:
            v = f.read().strip()
        if v:
            return v
    except OSError:
        pass
    return 'http://127.0.0.1:8123'


BASE = _base_from_config()
TOKEN_PATH = os.path.expanduser('~/.config/smart-home/ha-token')


class NotConfigured(RuntimeError):
    """令牌未配置 —— 调用方必须如实告知用户，不得降级成猜测。"""


def token_problem():
    """令牌文件的问题描述（不泄露内容）。None = 没问题。"""
    try:
        with open(TOKEN_PATH, encoding='utf-8') as f:
            t = f.read().strip()
    except FileNotFoundError:
        return f'未配置：{TOKEN_PATH} 不存在'
    if not t:
        return '文件是空的'
    if ' ' in t or '\n' in t:
        return '内容里有空格/换行 —— 多半粘贴成了命令行而不是令牌'
    if not t.startswith('eyJ'):
        return f'格式不对：HA 长期令牌应以 eyJ 开头，当前以「{t[:3]}…」开头（长度 {len(t)}）'
    if len(t) < 100:
        return f'长度可疑：只有 {len(t)} 字符（HA 长期令牌通常 180+），可能复制不全'
    return None


def load_token():
    """读取令牌；**形状不对就当作没配置**（避免"看起来配好了"的假成功）。"""
    if token_problem() is not None:
        return None
    with open(TOKEN_PATH, encoding='utf-8') as f:
        return f.read().strip()


def configured():
    return load_token() is not None


# 瞬时网络故障重试：2026-10-17 实测，桥接虚拟机偶发 "No route to host"（一两秒即恢复），
# 一次抖动就让整个状态快照降级成读文件太脆弱。所以：**只重试瞬时错误**，
# HTTP 错误（401/404 等）属于确定性失败，立刻抛出，不浪费重试。
# 实测（2026-10-17）：桥接虚拟机在网络/CPU 高负载时会短暂"No route to host"
# （监视 6 分钟 177 次探测 0 失败，说明是偶发；但跑门禁+验收这种重负载时会撞上）。
# 所以重试窗口放到 ~30 秒，把它当瞬时抖动处理，而不是让整个状态快照降级。
RETRY_ATTEMPTS = int(os.environ.get('SMART_HOME_HA_RETRIES', '6'))
RETRY_DELAY_S = float(os.environ.get('SMART_HOME_HA_RETRY_DELAY', '2.0'))


def _req(path, method='GET', body=None, token=None):
    tok = token or load_token()
    if not tok:
        raise NotConfigured(f'未配置 HA 访问令牌：请把长期访问令牌写入 {TOKEN_PATH}（权限 600）')
    data = json.dumps(body).encode('utf-8') if body is not None else None
    last = None
    for attempt in range(RETRY_ATTEMPTS):
        r = urllib.request.Request(BASE + path, data=data, method=method)
        r.add_header('Authorization', 'Bearer ' + tok)
        r.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(r, timeout=15) as resp:
                raw = resp.read().decode('utf-8')
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError:
            raise                      # 4xx/5xx 是确定性的，不重试
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as err:
            last = err
            if attempt + 1 < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY_S * (attempt + 1))   # 2,4,6,8,10 秒退避 ≈ 总窗口 30 秒
    raise last


def reachable():
    """HA 是否真的可用：**实际调一次 API**（带 30 秒重试窗口）。

    比 TCP 探测/HTTP 探测都准：HA OS 的 `/` 会跳转，TCP 也可能被瞬时抖动影响，
    但"能读到 /api/config"就是真的能干活。
    """
    try:
        _req('/api/config')
        return True
    except Exception:  # noqa
        return False


def ping():
    """连通性检查（不打印令牌）—— **只判 TCP 能不能连上**。

    为什么不用 HTTP 状态：HA OS 的 `/` 会 302 跳到 /lovelace（带 Host 头时尤其如此），
    urlopen 跟随后可能落到需要登录的页面或不可达地址，于是"明明活着却报不可达"。
    2026-10-17 实测踩坑：设置页一直显示「HA: 不可达」，其实一切正常。
    TCP 连上 = 服务在；连不上才是真的不可达。
    """
    try:
        import socket
        import urllib.parse
        u = urllib.parse.urlsplit(BASE)
        host = u.hostname
        port = u.port or (443 if u.scheme == 'https' else 80)
        if not host:
            return False
        with socket.create_connection((host, port), timeout=5):
            return True
    except Exception:  # noqa
        return False

def get_state(entity_id):
    """读一个实体的当前状态（含 attributes / last_updated）。"""
    return _req(f'/api/states/{entity_id}')


def call_service(domain, service, entity_id=None, data=None, blocking=True):
    """调用服务（domain.service）。**调用方必须随后回读**（05 §4）。"""
    body = dict(data or {})
    if entity_id:
        body['entity_id'] = entity_id
    q = '?return_response' if blocking else ''
    return _req(f'/api/services/{domain}/{service}{q}', method='POST', body=body)


def read_back(entity_id, expect=None, timeout=8.0, interval=0.5):
    """回读：等到状态变成期望值（或超时）。返回 (是否达成, 实际状态, 耗时秒)。

    期望值可以是字符串（状态相等）或 callable(state)->bool。expect=None 表示只看状态是否刷新。
    """
    t0 = time.time()
    before = None
    try:
        before = get_state(entity_id).get('last_updated')
    except Exception:  # noqa
        pass
    while time.time() - t0 < timeout:
        try:
            st = get_state(entity_id)
        except Exception as e:  # noqa
            time.sleep(interval)
            continue
        state = st.get('state')
        if callable(expect):
            ok = bool(expect(st))
        elif expect is not None:
            ok = (state == expect)
        else:
            ok = st.get('last_updated') != before
        if ok:
            return True, state, round(time.time() - t0, 2)
        time.sleep(interval)
    try:
        state = get_state(entity_id).get('state')
    except Exception:  # noqa
        state = None
    return False, state, round(time.time() - t0, 2)


class HaExecutor:
    """真实执行器：把 intent 的步骤落到 HA 上，并**回读**确认（05 §4）。

    双保险：即便上层守门漏了，这里也会拒绝安全域设备（08 §2）。
    """

    def __init__(self, timeout=8.0):
        self.timeout = timeout
        self.log = []

    def call(self, step):
        if step.get('security') or step.get('remind_only'):
            raise RuntimeError('安全域动作不允许自动执行（08 §2）——请去米家手动操作')
        if not step.get('entity_id'):
            raise RuntimeError('步骤缺少 entity_id')
        # 不用 return_response：多数开关类服务不支持，会 400
        res = call_service(step['domain'], step['service'], step['entity_id'], blocking=False)
        self.log.append({'entity_id': step['entity_id'], 'service': step['service']})
        return res

    def read_back(self, step, timeout=None):
        return read_back(step['entity_id'], expect=step.get('expect'), timeout=timeout or self.timeout)


def real_executor():
    """有令牌就返回真实执行器，没有就 None（调用方必须如实降级，不许假装）。"""
    return HaExecutor() if configured() else None


if __name__ == '__main__':
    print(f'HA 地址：{BASE}')
    print(f'HA 连通：{"✅" if ping() else "❌"}')
    print(f'令牌文件：{TOKEN_PATH}')
    prob = token_problem()
    print(f'令牌状态：{"✅ 形状正常（内容不打印）" if prob is None else "⛔️ " + prob}')
    if prob is None:
        try:
            me = _req('/api/')
            print(f'API 可用：✅ {me.get("message", "")}')
        except Exception as e:  # noqa
            print(f'API 不可用：❌ {type(e).__name__}: {e}（令牌可能是过期的或被删了）')
    else:
        print('正确做法：HA → 左下你的用户名 → 安全 → 长期访问令牌 → 创建 → **复制**，')
        print('          然后在终端执行：umask 077 && pbpaste > ~/.config/smart-home/ha-token')

# ── 官方配置接口（Config View）─────────────────────────────────────────────
# 为什么用这条路而不是直接写 automations.yaml：
#   迁移到 HA OS 后 HA 的配置在虚拟机里，Mac 写本地文件**不会生效，而且不报错**。
#   官方接口由 HA 自己写文件，并在保存后**自动触发 reload**（源码 components/config/automation.py），
#   容器版与 HA OS 都能用。2026-10-17 实测：GET /api/config/automation/config/<id> 存在。
# 端点：GET/POST/DELETE /api/config/<domain>/config/<config_id>

def config_get(domain, config_id):
    return _req(f'/api/config/{domain}/config/{config_id}')


def config_save(domain, config_id, data):
    """保存一条配置（automation/scene/script 等）。返回 (ok, 详情)。"""
    try:
        _req(f'/api/config/{domain}/config/{config_id}', method='POST', body=dict(data))
        return True, 'saved'
    except urllib.error.HTTPError as err:
        try:
            msg = json.loads(err.read().decode('utf-8')).get('message')
        except Exception:  # noqa
            msg = str(err)
        return False, f'HTTP {err.code}：{msg}'
    except Exception as err:  # noqa
        return False, str(err)[:120]


def config_delete(domain, config_id):
    try:
        _req(f'/api/config/{domain}/config/{config_id}', method='DELETE')
        return True, 'deleted'
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return True, '本来就不存在'
        return False, f'HTTP {err.code}'
    except Exception as err:  # noqa
        return False, str(err)[:120]


def config_available(domain='automation'):
    """接口是否可用（拿一个不存在的 id 探测：404 说明视图在，只是没这条）。"""
    try:
        _req(f'/api/config/{domain}/config/__probe__')
        return True
    except urllib.error.HTTPError as err:
        return err.code in (404, 400)
    except Exception:  # noqa
        return False

def find_automation_entity(config_id):
    """按配置 id 找自动化的**真实实体 id**。

    2026-10-17 实测踩坑：YAML 自动化的 entity_id 是**从 alias 派生**的（如
    `automation.gong_zuo_tai_zi_jian`），**不是** `automation.<我们写的 id>`；`id` 只作为
    attribute 暴露。所以回读必须按 `attributes.id` 去找 —— 否则会"保存成功但回读失败"。
    """
    try:
        with urllib.request.urlopen(_req_path('/api/states')) as resp:
            rows = json.load(resp)
    except Exception:  # noqa
        rows = []
    return automation_entity_from_states(rows, config_id)


def automation_entity_from_states(rows, config_id):
    """从状态列表里按 `attributes.id` 找 automation 实体（纯函数，便于测试）。"""
    for x in rows or []:
        eid = x.get('entity_id') or ''
        if not eid.startswith('automation.'):
            continue
        if str((x.get('attributes') or {}).get('id') or '') == str(config_id):
            return eid
    return None


def _req_path(path):
    req = urllib.request.Request(BASE + path)
    req.add_header('Authorization', 'Bearer ' + load_token())
    return req

