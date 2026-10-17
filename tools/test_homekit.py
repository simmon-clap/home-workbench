#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
苹果侧曝露面测试（05 v1.1 §9-2 · 08 v1.2 §7）

这是**红线所在**：一旦清单里混进安全域/门锁/摄像头/在家状态，判据 4 当场失效。
所以重点测：
  ① 安全域设备（门锁/摄像头）绝不出现在清单里
  ② 名字命中安全/行为类的设备（在家/离家、人体、门窗）绝不出现
  ③ 安全类**读数**可以进（为了苹果通知），但**只能是只读实体**（sensor/binary_sensor），
     出现 switch/valve/button 即判违规
  ④ 红线自检函数能抓出被人为塞进去的违规项（测试它真的会红）

用法：python3 tools/test_homekit.py      退出码 0 = 全过
"""
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'app'))
spec = importlib.util.spec_from_file_location('hk', os.path.join(ROOT, 'tools', 'homekit_plan.py'))
hk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hk)

OK, FAIL = [], []


def check(name, cond, detail=''):
    (OK if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f'  —— {detail}' if detail else ''))


def main():
    doc = hk.build()
    inc = doc['include']

    sec_names = [x['device'] for x in inc if '门锁' in x['device'] or '摄像' in x['device']]
    check('门锁与摄像头绝不出现在曝露面里', not sec_names, str(sec_names))

    bad_dom = [x['entity_id'] for x in inc if x['entity_id'].split('.')[0] in hk.NEVER_DOMAINS]
    check('永不暴露的域（lock/camera/vacuum…）不出现', not bad_dom, str(bad_dom))

    behavior = [x['device'] for x in inc if hk.NEVER_NAME.search(x['device'])]
    check('名字命中安全/行为类（在家/人体/门窗）不出现', not behavior, str(behavior))

    ro = [x for x in inc if x['class'] == 'A-readonly']
    check('安全类读数可以进（苹果通知做"必须送达"）', len(ro) >= 1, f'{len(ro)} 台')
    check('安全类读数**只暴露只读实体**（sensor/binary_sensor）',
          all(x['entity_id'].split('.')[0] in ('sensor', 'binary_sensor') for x in ro),
          str([x['entity_id'] for x in ro]))
    check('安全类读数标记 readonly', all(x.get('readonly') for x in ro))

    check('清单里都是 A 类（含只读）', all(x['class'] in ('A', 'A-readonly') for x in inc),
          str(sorted({x['class'] for x in inc})))
    check('红线索检函数对正常清单不报错', not hk.violations(doc))

    # ④ 故意塞违规项 → 必须红
    fake = json.loads(json.dumps(doc))
    fake['include'].append({'device': '小米全自动智能门锁 Pro', 'room': '主卧',
                            'entity_id': 'lock.loock_cn_x_s_2', 'domain': 'lock', 'name': '门锁',
                            'class': 'A', 'readonly': False})
    check('被人为塞进门锁时红线会红', bool(hk.violations(fake)), str(hk.violations(fake))[:60])
    fake2 = json.loads(json.dumps(doc))
    fake2['include'].append({'device': '小米天然气卫士', 'room': '厨房',
                             'entity_id': 'switch.lumi_cn_591368370_mcn02_valve_p_3_1', 'domain': 'switch',
                             'name': '燃气阀', 'class': 'A-readonly', 'readonly': True})
    check('安全类若暴露可执行实体（燃气阀）也会红', bool(hk.violations(fake2)),
          str(hk.violations(fake2))[:70])

    y = hk.to_yaml(doc)
    check('生成的 HA 配置用白名单（include_entities）', 'include_entities' in y and 'filter' in y)
    check('配置里不含任何 lock./camera. 实体', 'lock.' not in y and 'camera.' not in y)

    print(f'\n测试结果：通过 {len(OK)} · 失败 {len(FAIL)}' + (f'　失败项 {FAIL}' if FAIL else '　全过'))
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
