#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""门禁检查（第四批）：Q43–Q46。

从 gatechecks3.py 拆出来：11 §5 要求单文件 ≤600 行。只挪位置、不改判定。
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, 'app')
DATA = os.path.join(ROOT, 'data')
TOOLS = os.path.join(ROOT, 'tools')
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from gatebase import rec, txt  # noqa: E402

def q43():
    """HomeKit 桥配置必须由白名单**机械生成**，且安全域永不进苹果侧。

    迁移到 HA OS 后要配 HomeKit 桥。如果在窗口内临场手写 YAML，最容易漏掉"安全域不能暴露"
    这条红线。所以生成器 + 测试在迁移前就备好（宪章第六条 / 05 v1.1 §9-2 / 08 v1.2 §7）。
    """
    t = txt(os.path.join(TOOLS, 'homekit_config.py'))
    if not t:
        rec('Q43', 'HomeKit 配置由白名单机械生成（安全域不进）', False, 'tools/homekit_config.py 缺'); return
    checks = {
        '非 A 类直接抛错': '非 A 类' in t,
        '有 exclude_domains 兜底': 'exclude_domains' in t,
        '识别 A-readonly（真实 schema）': 'A-readonly' in t,
        '有自检模式': '--check' in t,
        '有测试': os.path.exists(os.path.join(TOOLS, 'test_homekit_config.py')),
    }
    bad = [k for k, v in checks.items() if not v]
    if bad:
        rec('Q43', 'HomeKit 配置由白名单机械生成（安全域不进）', False, f'缺 {bad}'); return
    try:
        r = subprocess.run([sys.executable, os.path.join(TOOLS, 'homekit_config.py'), '--check'],
                           capture_output=True, text=True, timeout=60)
        out = (r.stdout or '').strip()
        ok = r.returncode == 0
        rec('Q43', 'HomeKit 配置由白名单机械生成（安全域不进）', ok, out[:70] or '自检未通过')
    except Exception as err:  # noqa
        rec('Q43', 'HomeKit 配置由白名单机械生成（安全域不进）', False, str(err)[:60])

def q44():
    """迁移验收点：HomeKit 桥必须能在局域网被 mDNS 发现（这是配对的前提）。"""
    t = txt(os.path.join(TOOLS, 'mdns_check.py'))
    if not t:
        rec('Q44', 'mDNS 发现检测（配对的前提）', False, 'tools/mdns_check.py 缺'); return
    checks = {
        '用 dns-sd 浏览 _hap._tcp': '_hap._tcp' in t and 'dns-sd' in t,
        '同时看 HA 侧是否配了 homekit': 'ha_homekit_configured' in t,
        '没发现时如实说没发现': '没有发现' in t,
        '找不到 dns-sd 时不假装成功': '找不到' in t,
        '有测试': os.path.exists(os.path.join(TOOLS, 'test_mdns.py')),
    }
    bad = [k for k, v in checks.items() if not v]
    rec('Q44', 'mDNS 发现检测（配对的前提）', not bad,
        f'缺 {bad}' if bad else 'dns-sd 浏览 + HA 侧核对 + 如实报告')


def q45():
    """迁移开工前必须能一条命令给出 GO / NO-GO（缺一项就不开工）。"""
    t = txt(os.path.join(TOOLS, 'preflight.py'))
    if not t:
        rec('Q45', '开工前体检（GO / NO-GO）', False, 'tools/preflight.py 缺'); return
    need = ['备份', 'migration-baseline', 'migrate_check.py', 'uptime_check.py',
            'vm_autostart.py', 'homekit_config.py', '物料', 'gate.py']
    missing = [k for k in need if k not in t]
    has_test = os.path.exists(os.path.join(TOOLS, 'test_preflight.py'))
    nodo = 'NO-GO' in t
    ok = (not missing) and has_test and nodo
    rec('Q45', '开工前体检（GO / NO-GO）', ok,
        f'缺 {missing}' if missing else ('' if (has_test and nodo) else '缺测试或判定'))

def q46():
    """HA 配置目录必须只有一个来源（迁移时改环境变量，不改代码）。

    为什么：迁移时最容易犯的错不是"改错了"，而是**有一处忘了改** —— 静默读到旧目录，
    表现为"数据是旧的"却不报错。所以路径统一到 app/ha_paths.py，并机械检查没有各写各的。
    """
    t = txt(os.path.join(APP, 'ha_paths.py'))
    if not t:
        rec('Q46', 'HA 配置路径唯一来源（迁移只改环境变量）', False, 'app/ha_paths.py 缺'); return
    checks = {
        '有环境变量开关': 'SMART_HOME_HA_CONFIG' in t,
        '有来源标注': 'def source(' in t,
        '集成核对优先走 API': 'components_via_api' in t,
        '读不到时不假装空列表': 'return None' in t,
        '有测试': os.path.exists(os.path.join(TOOLS, 'test_paths.py')),
    }
    bad = [k for k, v in checks.items() if not v]
    if bad:
        rec('Q46', 'HA 配置路径唯一来源（迁移只改环境变量）', False, f'缺 {bad}'); return
    users = []
    for rel in ('app/state.py', 'app/server.py', 'app/rules.py', 'tools/migrate_check.py',
                'tools/gatechecks.py'):
        if 'ha_paths' not in txt(os.path.join(ROOT, rel)):
            users.append(rel)
    ok = not users
    rec('Q46', 'HA 配置路径唯一来源（迁移只改环境变量）', ok,
        f'这些地方没走统一来源：{users}' if users else '5 处调用点都走 ha_paths（含集成优先走 API）')

def q47():
    """迁移物料必须**验过真伪**才开工（镜像/安装包下载不全的话，窗口内白等）。"""
    t = txt(os.path.join(TOOLS, 'verify_image.py'))
    if not t:
        rec('Q47', '迁移物料校验（镜像与安装包）', False, 'tools/verify_image.py 缺'); return
    checks = {
        '与官方大小比对': 'api.github.com' in t or 'remote_sizes' in t,
        '压缩流完整性': "'xz', '-t'" in t or 'xz_ok' in t,
        '流式读 qcow2 头（不落 400MB 临时文件）': 'qcow2_header_via_stream' in t,
        '有 offline 模式': '--offline' in t,
        '有测试': os.path.exists(os.path.join(TOOLS, 'test_verify_image.py')),
    }
    bad = [k for k, v in checks.items() if not v]
    if bad:
        rec('Q47', '迁移物料校验（镜像与安装包）', False, f'缺 {bad}'); return
    ok_off, info = None, {}
    try:
        import importlib.util as _iu
        sp = _iu.spec_from_file_location('vi', os.path.join(TOOLS, 'verify_image.py'))
        vi = _iu.module_from_spec(sp); sp.loader.exec_module(vi)
        problems, info = vi.check(offline=True)
        ok_off = not problems
    except Exception as err:  # noqa
        rec('Q47', '迁移物料校验（镜像与安装包）', False, f'本地校验出错：{err}'); return
    pre = txt(os.path.join(TOOLS, 'preflight.py'))
    rec('Q47', '迁移物料校验（镜像与安装包）', ok_off and 'verify_image' in pre,
        f"镜像 {info.get('image_bytes')} 字节 · qcow2 v{info.get('qcow2_version')} · "
        f"虚拟盘 {info.get('virtual_gb')}GB")

def q48():
    """迁移后验收必须一键可跑，且**没成就不能报成功**。"""
    t = txt(os.path.join(TOOLS, 'post_migration.py'))
    if not t:
        rec('Q48', '迁移后验收（一键，机械判定的"迁完了吗"）', False, 'tools/post_migration.py 缺'); return
    checks = {
        '认形态翻转（hassio）': 'hassio' in t,
        '验 mDNS 可发现': 'mdns_check' in t,
        '验虚拟机自启': 'vm_autostart' in t,
        '验基线不漂移': 'migrate_check' in t,
        '列出人工待办': 'MANUAL' in t,
        '有测试': os.path.exists(os.path.join(TOOLS, 'test_post_migration.py')),
    }
    bad = [k for k, v in checks.items() if not v]
    rec('Q48', '迁移后验收（一键，机械判定的"迁完了吗"）', not bad,
        f'缺 {bad}' if bad else '形态/集成/状态源/基线/mDNS/自启/24h/门禁/验收 九项 + 人工待办')

def q49():
    """规则落地必须走**官方配置接口**，且回读要按 `attributes.id` 找真实实体。

    为什么：① 迁到 HA OS 后写本地 automations.yaml **HA 读不到且不报错**
            ② 2026-10-17 实测抓到：YAML 自动化的 entity_id 从 **alias 派生**，写死
               `automation.smarthome_x` 永远找不到 —— 表现为"保存成功但回读失败"（潜伏 bug）
    """
    r = txt(os.path.join(APP, 'rules.py'))
    h = txt(os.path.join(APP, 'ha.py'))
    if not r or not h:
        rec('Q49', '规则走官方接口 + 回读按 id 属性找实体', False, 'rules.py / ha.py 缺'); return
    checks = {
        '有写盘方式开关': 'SMART_HOME_RULE_WRITE' in r,
        '走官方配置接口': 'config_save' in r and 'config_available' in r,
        '保留写文件兜底': '_write_mode' in r and 'automations.yaml' in r,
        '回读按 id 属性找': 'find_automation_entity' in r and 'find_automation_entity' in h,
        '有纯函数可测': 'automation_entity_from_states' in h,
        '真机验证脚本': os.path.exists(os.path.join(TOOLS, 'verify_rule_api.py')),
        '有测试': os.path.exists(os.path.join(TOOLS, 'test_rules.py')),
    }
    bad = [k for k, v in checks.items() if not v]
    rec('Q49', '规则走官方接口 + 回读按 id 属性找实体', not bad,
        f'缺 {bad}' if bad else '官方接口优先 + 文件兜底 + 按 attributes.id 回读 + 真机验证脚本')

def q50():
    """审计我们引用的 HA 名字真的存在（防"引用了不存在的东西"这类潜伏 bug）。"""
    t = txt(os.path.join(TOOLS, 'audit_ha_calls.py'))
    if not t:
        rec('Q50', 'HA 调用审计（服务/命令/接口都存在）', False, 'tools/audit_ha_calls.py 缺'); return
    checks = {
        '对真实服务清单': '/api/services' in t,
        '扫字面量调用': 'def static_calls(' in t,
        '扫域→服务映射': 'def mapping_calls(' in t,
        '扫场景步骤': 'def scene_calls(' in t,
        '真连 WS 验证命令': 'def ws_check(' in t,
        '实体审计（动作目标有效+安全域不误放行）': 'def entity_audit(' in t,
        '有测试': os.path.exists(os.path.join(TOOLS, 'test_audit_ha_calls.py')),
    }
    bad = [k for k, v in checks.items() if not v]
    if bad:
        rec('Q50', 'HA 调用审计（服务/命令/接口都存在）', False, f'缺 {bad}'); return
    try:
        r = subprocess.run([sys.executable, os.path.join(TOOLS, 'audit_ha_calls.py')],
                           capture_output=True, text=True, timeout=300)
        last = [l for l in (r.stdout or '').strip().splitlines() if l.strip()]
        rec('Q50', 'HA 调用审计（服务/命令/接口都存在）', r.returncode == 0,
            (last[-1].strip() if last else '审计未通过'))
    except Exception as err:  # noqa
        rec('Q50', 'HA 调用审计（服务/命令/接口都存在）', False, str(err)[:60])

def q51():
    """出声去重（04 §4「同设备同原因 1 小时内只出一次声」）必须有机械保证。

    2026-10-17 实测抓到：安全类事件每 30 分钟重复播报同一条摘要（安全分支在合并检查之前就返回）。
    现在两层保证：① notify 的同因合并（安全事件也走，但仍是"必达"语义）
                  ② outbox 投递层的"原话不重复投"（内容精确匹配）
    """
    n = txt(os.path.join(APP, 'notify.py'))
    o = txt(os.path.join(APP, 'outbox.py'))
    if not n or not o:
        rec('Q51', '出声去重（同因 1 小时一次）', False, 'notify.py / outbox.py 缺'); return
    checks = {
        '安全事件也走去重（可切换）': 'SAFETY_REPEAT' in n and '_spoken_recent' in n,
        '合并原因说清"必达"': '必达，但同设备同原因' in n,
        '投递层第二道网': '_same_text_recent' in o,
        '第二道网按内容精确匹配': "rec.get('text') == text" in o,
        '可以强制再投': 'force' in o and 'force=True' in o,
        '没话可说不算失败': "'skipped': True" in o,
        '有测试': os.path.exists(os.path.join(TOOLS, 'test_outbox.py')),
    }
    bad = [k for k, v in checks.items() if not v]
    rec('Q51', '出声去重（同因 1 小时一次）', not bad,
        f'缺 {bad}' if bad else '两层去重 + 原因说清"必达" + 可强制再投 + 没话可说不算失败')

def q52():
    """投递回执不得冒充"已送达"（桌面通道只能证明"已发出"）。

    为什么：系统不允许读通知中心数据库，`osascript` 成功 ≠ 人看到了。
    把"已发出"说成"已送达"就是编造结论（宪章第三条：不许把没验证的事说成事实）。
    """
    o = txt(os.path.join(APP, 'outbox.py'))
    if not o:
        rec('Q52', '投递回执不冒充"已送达"', False, 'app/outbox.py 缺'); return
    checks = {
        '桌面通道标 dispatched': "'dispatched':" in o,
        '写明无法机械核验': '无法机械核验' in o,
        '微信通道如实未接通': 'not_connected' in o,
        '有测试': os.path.exists(os.path.join(TOOLS, 'test_outbox.py')),
    }
    bad = [k for k, v in checks.items() if not v]
    rec('Q52', '投递回执不冒充"已送达"', not bad,
        f'缺 {bad}' if bad else '已发出≠已展示；未接通通道如实标注')

def q53():
    """冻结快照 + 漂移检测（迁移前后"代码/规范没被悄悄改"要有机械证据）。"""
    t = txt(os.path.join(TOOLS, 'freeze_snapshot.py'))
    if not t:
        rec('Q53', '冻结快照与漂移检测', False, 'tools/freeze_snapshot.py 缺'); return
    checks = {
        '对文件算指纹': 'sha256' in t,
        '记录规范版本': 'spec_versions' in t,
        '支持 --verify': '--verify' in t,
        '分别报改动/删除/新增': all(k in t for k in ("'changed'", "'removed'", "'added'")),
        '有测试': os.path.exists(os.path.join(TOOLS, 'test_freeze_snapshot.py')),
        '验收里已接': 'freeze_snapshot' in txt(os.path.join(TOOLS, 'post_migration.py')),
    }
    bad = [k for k, v in checks.items() if not v]
    rec('Q53', '冻结快照与漂移检测', not bad,
        f'缺 {bad}' if bad else '指纹 + 规范版本 + 漂移三分类 + 迁移后自动比对')

def q54():
    """备份必须**原子写**（先临时文件+校验+改名），演练遇坏包要给人话。

    2026-10-17 实测：备份与演练同时跑 → 演练读到半个包 → `EOFError` 堆栈，
    还容易被误判成"备份坏了"。备份是回滚的底牌，这类静默/误导必须杜绝。
    """
    sh = txt(os.path.join(TOOLS, 'backup.sh'))
    rd = txt(os.path.join(TOOLS, 'restore_drill.py'))
    if not sh or not rd:
        rec('Q54', '备份原子性 + 演练坏包说人话', False, 'backup.sh / restore_drill.py 缺'); return
    checks = {
        '备份写临时文件': '.partial' in sh and 'TMP=' in sh,
        '改名先校验': 'tar -tzf "$TMP"' in sh,
        '原子改名': 'mv -f "$TMP" "$OUT"' in sh,
        '排除可再下载大件': './installers' in sh,
        '演练先验完整性': "'-tzf'" in rd or 'tar -tzf' in rd,
        '坏包提示人话': '备份包不完整' in rd and '不要删旧备份' in rd,
        '有测试': os.path.exists(os.path.join(TOOLS, 'test_backup_atomic.py')),
    }
    bad = [k for k, v in checks.items() if not v]
    rec('Q54', '备份原子性 + 演练坏包说人话', not bad,
        f'缺 {bad}' if bad else '临时文件+校验+原子改名；演练先验完整性并给人话')

def q55():
    """DSH 插件入口（P6 多端）：装了**且激活**，只装桌面端，iframe 指向本机工作台。

    容易出的问题：依赖装了但 bundle 名单里没有 → 侧边栏不出现，**而且不报错**。
    """
    d = txt(os.path.join(APP, 'dsh-plugin', 'package.json'))
    if not d:
        rec('Q55', 'DSH 插件入口（装了且激活）', False, 'app/dsh-plugin/package.json 缺'); return
    c = txt(os.path.join(APP, 'dsh-plugin', 'client', 'client.js'))
    checks = {
        'manifest 有 bundle 补丁': '"bundle"' in d and 'cordis.patch.yml' in d,
        '客户端指向本机工作台': '127.0.0.1:8300' in c,
        '只用 iframe（不耦合构建链）': 'iframe' in c,
        '不暴露局域网/tailnet 地址': '192.168.' not in c and 'ts.net' not in c,
        '有测试': os.path.exists(os.path.join(TOOLS, 'test_dsh_plugin.py')),
    }
    bad = [k for k, v in checks.items() if not v]
    if bad:
        rec('Q55', 'DSH 插件入口（装了且激活）', False, f'缺 {bad}'); return
    try:
        r = subprocess.run([sys.executable, os.path.join(TOOLS, 'test_dsh_plugin.py')],
                           capture_output=True, text=True, timeout=200)
        out = [l for l in (r.stdout or '').strip().splitlines() if l.strip()]
        rec('Q55', 'DSH 插件入口（装了且激活）', r.returncode == 0,
            (out[-1].strip() if out else '测试未通过'))
    except Exception as err:  # noqa
        rec('Q55', 'DSH 插件入口（装了且激活）', False, str(err)[:60])

def q56():
    """简报必须说明数据新鲜度（迁移/故障期间不许把旧读数当现在的说）。"""
    t = txt(os.path.join(APP, 'briefing.py'))
    if not t:
        rec('Q56', '简报说明数据新鲜度', False, 'app/briefing.py 缺'); return
    checks = {
        '看 generated_at 算时长': 'generated_at' in t and '_age' in t,
        '偏旧时明说"不是现在"': '不是现在' in t,
        '阈值 10 分钟': '10' in t and '_age >= 10' in t,
        '有测试': os.path.exists(os.path.join(TOOLS, 'test_criterion1.py')),
    }
    bad = [k for k, v in checks.items() if not v]
    rec('Q56', '简报说明数据新鲜度', not bad,
        f'缺 {bad}' if bad else '偏旧就明说"最后一次可用读数，不是现在"；新鲜时不出告警')
