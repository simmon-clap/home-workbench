#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
24h 在线就绪检查测试（tools/uptime_check.py）

这个检查的价值在于：条件被打破时**必须报警**，否则就是"看着绿、其实已经不具备 24h 前提"。
所以正反两面都测：
  ① 全部满足 → 就绪
  ② 每一项单独被打破 → 必须判为阻塞，且说明"为什么"与"谁来改"
  ③ 风险项（自动更新、Wi-Fi）只提示、不阻塞（否则会天天红，人就麻木了）

全部用注入参数，不依赖本机真实设置。

用法：python3 tools/test_uptime.py      退出码 0 = 全过
"""
import importlib.util
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('uc', os.path.join(ROOT, 'tools', 'uptime_check.py'))
uc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uc)

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


GOOD_MANIFEST = {'jobs': [], 'services': []}


def main():
    # ① 全绿
    ok, res = uc.check(sleep='0', autorestart='1', womp='1', login_user=os.environ.get('USER', 'user'),
                       autoupdate=False, manifest=GOOD_MANIFEST,
                       net={'interface': 'en0', 'is_wifi': False})
    check('全部满足 → 就绪', ok and not res['blockers'], str(res['blockers']))
    check('没有风险提示时也如实为空', not res['warnings'])

    # ② 逐项打破
    cases = [
        ('睡眠没关', dict(sleep='1'), '系统睡眠已禁用'),
        ('断电不会自动开机', dict(autorestart='0'), '断电恢复后自动开机'),
        ('没配自动登录', dict(login_user=None), '重启后自动登录（用户级自启的前提）'),
    ]
    for label, over, expect_item in cases:
        kw = dict(sleep='0', autorestart='1', womp='1', login_user=os.environ.get('USER', 'user'),
                  autoupdate=False, manifest=GOOD_MANIFEST, net={'interface': 'en0', 'is_wifi': False})
        kw.update(over)
        ok2, res2 = uc.check(**kw)
        check(f'{label} → 判为阻塞', (not ok2) and expect_item in res2['blockers'],
              str(res2['blockers']))
        item = next((i for i in res2['items'] if i['item'] == expect_item), {})
        check(f'{label} → 说明"谁来改"和"怎么改"', bool(item.get('who')) and bool(item.get('fix')),
              f"{item.get('who')} / {item.get('fix')}")

    # ③ 自动登录那条必须解释"为什么重要"
    _, res3 = uc.check(sleep='0', autorestart='1', womp='1', login_user=None,
                       autoupdate=False, manifest=GOOD_MANIFEST, net={'is_wifi': False})
    item = next(i for i in res3['items'] if i['item'].startswith('重启后自动登录'))
    check('自动登录项写清"用户级自启的前提"', '自启' in item['item'])

    # ④ 风险项只提示不阻塞
    ok4, res4 = uc.check(sleep='0', autorestart='1', womp='1', login_user=os.environ.get('USER', 'user'),
                         autoupdate=True, manifest=GOOD_MANIFEST,
                         net={'interface': 'en1', 'is_wifi': True})
    check('自动更新开着 + Wi-Fi → 仍判就绪（只提示）', ok4, str(res4['blockers']))
    check('两条风险都提示到', len(res4['warnings']) == 2,
          str([w['item'] for w in res4['warnings']]))

    # ⑤ 自启缺口要能被发现
    tmpd = tempfile.mkdtemp(prefix='uptime-test-')
    uc.AGENTS = tmpd
    ok5, res5 = uc.check(sleep='0', autorestart='1', womp='1', login_user=os.environ.get('USER', 'user'),
                         autoupdate=False,
                         manifest={'jobs': [{'id': 'x', 'agent': 'com.nope'}], 'services': []},
                         net={'is_wifi': False})
    check('清单里缺驱动 → 判为阻塞', (not ok5) and '自启覆盖（清单里的服务与任务）' in res5['blockers'],
          str(res5['blockers']))

    # ⑥ pmset 解析（行首有空格，曾因此漏读）
    parsed = uc.pmset_value('sleep', ' sleep                0\ndisplaysleep         180\n')
    check('能解析 pmset 的行（行首空格不算）', parsed == '0', str(parsed))

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
