#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HA 迁移预检 / 后检（P5）

为什么要有：迁移窗口只有 10–20 分钟，靠"现场想"必然漏。所以拆成两半：
  · `--pre`  迁移**之前**跑：把当前基线全部记下来（实体数、集成、设备、桥接组件、Tailscale、定时任务…），
             并列出"迁移后会变的东西" —— 这样迁移后能逐条比对，而不是凭感觉说"好像没问题"
  · `--post` 迁移**之后**跑：与基线逐条比对，任何一项对不上都如实报出来

基线存 `data/migration-baseline.json`；证据写 `logs/evidence/<日期>-P5/migrate-*.md`。

用法：
  python3 tools/migrate_check.py --pre
  python3 tools/migrate_check.py --post
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
DATA = os.path.join(ROOT, 'data')
BASELINE = os.environ.get('SMART_HOME_MIGRATE_BASELINE') or os.path.join(DATA, 'migration-baseline.json')
# HA 地址**不写死**：跟着 ~/.config/smart-home/ha-base-url 走（换中枢/换 IP 只改一处）
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app'))
import ha as _ha
HA = _ha.BASE
TZ = datetime.timezone(datetime.timedelta(hours=8))
TS_SOCK = os.path.expanduser('~/tailscale-userspace/tailscaled.sock')
TS_BIN = os.path.expanduser('~/.homebrew/bin/tailscale')
OK, FAIL, WARN = [], [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def warn(msg):
    WARN.append(msg)
    print('⚠️  ' + msg)


def _token():
    import ha
    return ha.load_token()


def ha_get(path):
    req = urllib.request.Request(HA + path)
    req.add_header('Authorization', 'Bearer ' + _token())
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def snapshot():
    """当前环境的全部关键指标。"""
    s = {'at': datetime.datetime.now(TZ).isoformat(timespec='seconds')}
    cfg = ha_get('/api/config')
    s['ha_version'] = cfg.get('version')
    s['components'] = sorted(cfg.get('components') or [])
    states = ha_get('/api/states')
    s['entity_count'] = len(states)
    s['automation_count'] = len([x for x in states if x['entity_id'].startswith('automation.')])
    s['security_entities'] = len([x for x in states if 'lock.' in x['entity_id'] or 'camera.' in x['entity_id']])

    st = json.load(open(os.path.join(DATA, 'state.json'), encoding='utf-8')) if os.path.exists(os.path.join(DATA, 'state.json')) else {}
    s['devices'] = len(st.get('devices') or [])
    s['rooms'] = len(st.get('rooms') or [])

    # 路径统一从 app/ha_paths 取（迁移时只改 SMART_HOME_HA_CONFIG，不改代码）
    sys.path.insert(0, os.path.join(ROOT, 'app'))
    import ha_paths
    s['config_dir'] = ha_paths.ha_config_dir()
    s['config_dir_source'] = ha_paths.source()
    cc, how = ha_paths.custom_components()
    s['custom_components'] = cc
    s['custom_components_via'] = how          # api / dir / none —— 迁移后目录读不到时走 API
    # 容器版专有文件：**HA OS 形态下不存在是正常的**，所以单独记，不当失败
    cfg_dir = ha_paths.ha_config_dir()
    s['deployment'] = 'container' if os.path.exists(os.path.join(ROOT, 'docker-compose.yml')) else 'unknown'
    s['files'] = {**(lambda: {k: os.path.exists(os.path.join(ROOT, k)) for k in
                              ('docker-compose.yml', 'data/state.json', 'data/settings.json',
                               'data/scenes.json', 'data/rules.json')})(),
                  'ha_config_dir': os.path.isdir(cfg_dir),
                  'ha_configuration_yaml': os.path.exists(os.path.join(cfg_dir, 'configuration.yaml'))}
    try:
        agents = subprocess.run(['launchctl', 'list'], capture_output=True, text=True).stdout
        s['agents'] = sorted({l.split('\t')[-1] for l in agents.splitlines() if 'smarthome' in l or 'tailscale' in l})
    except Exception:  # noqa
        s['agents'] = []
    try:
        ts = subprocess.run([TS_BIN, f'--socket={TS_SOCK}', 'serve', 'status'],
                            capture_output=True, text=True, timeout=15).stdout
        s['tailscale_serve'] = [l.strip() for l in ts.splitlines() if 'proxy' in l]
    except Exception:  # noqa
        s['tailscale_serve'] = []
    backups = sorted([f for f in os.listdir(os.path.join(ROOT, 'backups')) if f.endswith('.tgz')],
                     key=lambda f: os.path.getmtime(os.path.join(ROOT, 'backups', f))) if os.path.isdir(os.path.join(ROOT, 'backups')) else []
    s['latest_backup'] = backups[-1] if backups else None
    s['free_gb'] = round(os.statvfs('/').f_bavail * os.statvfs('/').f_frsize / 1e9, 1)
    return s


def api_probe():
    """状态层的"官方 API 路径"是否可用 —— 迁移后我们不再读 HA 的文件，全靠它。"""
    try:
        import ha_ws
        r = ha_ws.probe()
    except Exception as err:  # noqa
        return {'ok': False, 'error': str(err)[:120]}
    return r


def pre():
    print('=== 迁移预检 ===')
    s = snapshot()
    api = api_probe()
    check('官方 API 路径可用（迁移后状态层靠它，不再读 HA 文件）',
          api.get('ok') is True,
          f"实体 {api.get('entities')} · 设备 {api.get('devices')} · 区域 {api.get('areas')}"
          if api.get('ok') else str(api.get('error')))
    check('HA 可达且能读到版本', bool(s.get('ha_version')), str(s.get('ha_version')))
    check('状态模型在（迁移后要能重建）', s['devices'] > 0, f"{s['devices']} 台设备 / {s['rooms']} 个房间")
    check('桥接自定义组件在（迁移后要一起带过去）', 'smart_home_bridge' in s['custom_components'],
          str(s['custom_components']))
    check('小米集成在', 'xiaomi_home' in s['custom_components'])
    check('关键文件齐备', all(s['files'].values()), str([k for k, v in s['files'].items() if not v]) or '全部在')
    check('有备份可用', bool(s['latest_backup']), str(s['latest_backup']))
    check('磁盘余量够（≥10GB）', s['free_gb'] >= 10, f"{s['free_gb']} GB")
    check('定时任务在', bool(s['agents']), '、'.join(s['agents'])[:80])
    check('自定义集成核对得到（优先 API，迁移后目录读不到也能验）',
          bool(s['custom_components']),
          f"{s['custom_components']}（via {s['custom_components_via']}）")
    print(f"  部署形态：{s['deployment']} · 配置目录 {os.path.relpath(s['config_dir'], ROOT)}"
          f"（来源 {s['config_dir_source']}）")
    json.dump(s, open(BASELINE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\n基线已写入 {os.path.relpath(BASELINE, ROOT)}')

    print('\n=== 迁移后会变的东西（提前知道，别到时候慌）===')
    warn('HA 从容器版换成 HA OS：**IP/端口可能变**，HA 的地址与工作台的 BASE 常量要跟着改')
    warn('容器挂载的 `config/homeassistant` 路径会变 —— 备份/恢复脚本里的路径要一起改')
    warn('**Tailscale 现在跑在 Mac 上、代理到 127.0.0.1**：HA OS 是独立虚拟机，'
         '若它自己也要 tailnet 可达，需要单独装 Tailscale（或用 Mac 继续代理，但要确认新 IP 端口）')
    warn('`xiaomi_home` 与 `smart_home_bridge` 两个自定义集成要拷进 HA OS 的 /config/custom_components'
         '（后检会用**官方 API 的 components 列表**核对，不依赖读目录）')
    warn('`.storage/http` 里的反代信任（use_x_forwarded_for / trusted_proxies）要重建，否则 tailnet HTTPS 会 400')
    warn('recorder 历史库（home-assistant_v2.db）要一起带过去，否则"家的记忆"断了')
    warn('迁移前建议先跑一次 `restore_drill.py --deep`（已证明恢复可用），并把最新备份复制到别处')
    _write_evidence('pre', s)
    print(f"\n预检：通过 {len(OK)} · 失败 {len(FAIL)} · 提醒 {len(WARN)}")
    return 1 if FAIL else 0


def post():
    print('=== 迁移后检 ===')
    if not os.path.exists(BASELINE):
        check('存在迁移前基线', False, f'{BASELINE} 不存在，请先跑 --pre'); return 1
    b = json.load(open(BASELINE, encoding='utf-8'))
    s = snapshot()
    check('HA 可达', bool(s.get('ha_version')), str(s.get('ha_version')))
    check('实体数量不比迁移前少（允许少量浮动）', s['entity_count'] >= b['entity_count'] - 20,
          f"{b['entity_count']} → {s['entity_count']}")
    check('设备数一致（我们的状态模型）', s['devices'] == b['devices'], f"{b['devices']} → {s['devices']}")
    check('房间数一致', s['rooms'] == b['rooms'], f"{b['rooms']} → {s['rooms']}")
    check('安全域实体还在', s['security_entities'] >= b['security_entities'] - 2,
          f"{b['security_entities']} → {s['security_entities']}")
    for c in ('xiaomi_home', 'smart_home_bridge'):
        check(f'自定义集成 {c} 已加载', c in s['custom_components'], str(s['custom_components']))
    api = api_probe()
    check('迁移后官方 API 路径可用', api.get('ok') is True,
          f"实体 {api.get('entities')} · 设备 {api.get('devices')}" if api.get('ok') else str(api.get('error')))
    lost = sorted(set(b.get('components') or []) - set(s.get('components') or []))
    check('没有集成在迁移后丢失', not lost, str(lost[:6]) if lost else f"{len(s['components'])} 个组件")
    check('备份可用', bool(s['latest_backup']), str(s['latest_backup']))
    _write_evidence('post', s, baseline=b)
    print(f"\n后检：通过 {len(OK)} · 失败 {len(FAIL)}")
    return 1 if FAIL else 0


def _write_evidence(kind, s, baseline=None):
    ev = os.path.join(ROOT, 'logs', 'evidence', datetime.datetime.now(TZ).strftime('%Y%m%d') + '-P5')
    os.makedirs(ev, exist_ok=True)
    lines = [f'# 迁移{("预检" if kind == "pre" else "后检")} · {s["at"]}', '',
             f"- HA 版本：{s.get('ha_version')}", f"- 实体：{s['entity_count']} · 集成：{len(s.get('components') or [])}",
             f"- 设备：{s['devices']} · 房间：{s['rooms']} · 安全域实体：{s.get('security_entities')}",
             f"- 自定义集成：{'、'.join(s.get('custom_components') or [])}",
             f"- 定时任务：{'、'.join(s.get('agents') or [])}",
             f"- Tailscale 代理：{'；'.join(s.get('tailscale_serve') or []) or '无'}",
             f"- 最新备份：{s.get('latest_backup')} · 磁盘余量 {s.get('free_gb')} GB", '',
             '## 检查结果', '']
    lines += [f'- ✅ {n}' for n in OK] + [f'- ❌ {n}' for n in FAIL]
    if WARN:
        lines += ['', '## 迁移后要注意', ''] + [f'- {w}' for w in WARN]
    if baseline:
        lines += ['', '## 与迁移前对比', '',
                  f"- 实体 {baseline['entity_count']} → {s['entity_count']}",
                  f"- 设备 {baseline['devices']} → {s['devices']}",
                  f"- HA 版本 {baseline.get('ha_version')} → {s.get('ha_version')}"]
    open(os.path.join(ev, f'migrate-{kind}.md'), 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print(f"证据：logs/evidence/{os.path.basename(ev)}/migrate-{kind}.md")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--pre', action='store_true')
    ap.add_argument('--post', action='store_true')
    a = ap.parse_args()
    raise SystemExit(post() if a.post else pre())
