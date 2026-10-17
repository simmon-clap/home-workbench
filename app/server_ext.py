#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作台服务端的扩展处理器（场景编辑 / 规则）。

从 server.py 拆出来：11 §5 要求单文件 ≤600 行。**只挪代码、不改行为**；
这些方法通过 server.Handler 的继承混入生效。
"""
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# _health 从这里读状态与数据（与 server.py 里同名同义）
DATA = os.path.join(ROOT, 'data')
STATE = os.path.join(DATA, 'state.json')


class HandlersMixin:
    def _rule_propose(self):
        """一句话 → 结构化规则提案 + 复述（**不写入任何东西**，03 §7）。"""
        sys.path.insert(0, os.path.join(ROOT, 'app'))
        import rules as R
        b = self._body()
        p = R.parse(b.get('text', ''))
        out = {'ok': p.get('ok'), 'recap': p.get('recap'), 'needs': R.needs(p),
               'trigger': p.get('trigger'), 'condition': p.get('condition'), 'action': p.get('action'),
               'condition_feasible': p.get('condition_feasible')}
        if p.get('ok'):
            entry = R.add_proposal(p)
            out['rule_id'] = entry['id']
            out['preview'] = R.commit(entry['id'], confirm=False)
        return self._json(out)

    def _rule_commit(self):
        """用户确认后才落到底座（写 automations.yaml + check_config + reload + 回读）。"""
        sys.path.insert(0, os.path.join(ROOT, 'app'))
        import rules as R
        b = self._body()
        out = R.commit(b.get('rule_id', ''), confirm=bool(b.get('confirm')))
        return self._json(out, 200 if out.get('ok') else 400)

    def _scenes_edit(self):
        """场景编辑（03 §7）：停用/启用 · 加一步 · 删一步 · 回滚。"""
        sys.path.insert(0, os.path.join(ROOT, 'app'))
        import scenes as SC
        b = self._body()
        what = b.get('do')
        if what == 'toggle':
            ok, msg = SC.set_enabled(b.get('scene_id', ''), bool(b.get('enabled')))
        elif what == 'add':
            ok, msg = SC.add_step(b.get('scene_id', ''), b.get('action', ''), b.get('type', ''),
                                  b.get('room'), bool(b.get('remind_only')))
        elif what == 'remove':
            ok, msg = SC.remove_step(b.get('scene_id', ''), int(b.get('index', -1)))
        elif what == 'undo':
            ok, msg = SC.undo(b.get('scene_id', ''))
        else:
            ok, msg = False, f'不认识的编辑动作：{what}'
        return self._json({'ok': ok, 'message': msg, 'view': SC.view()}, 200 if ok else 400)

    def _health(self):
        """系统状态（只读）：数据新鲜度、服务、审计、校准、额度、待决事项。

        为什么要有：这套东西最怕"看起来在跑、其实数据是旧的"。把新鲜度与错误计数摆出来，
        用户一眼就能看出"它还是活的"。**所有数字都从真实文件/接口读，不写死。**
        """
        import datetime
        sys.path.insert(0, os.path.join(ROOT, 'app'))
        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
        h = {}

        st_path = STATE
        if os.path.exists(st_path):
            with open(st_path, encoding='utf-8') as f:
                st = json.load(f)
            gen = st.get('generated_at')
            h['state_generated_at'] = gen
            try:
                age = (now - datetime.datetime.fromisoformat(gen)).total_seconds()
                h['state_age_s'] = int(age)
                h['state_fresh'] = age < 600          # 10 分钟内算新鲜
            except (TypeError, ValueError):
                h['state_age_s'] = None
                h['state_fresh'] = False
            h['devices'] = len(st.get('devices') or [])
            h['attention'] = (st.get('summary') or {}).get('attention_count')
        else:
            h.update({'state_age_s': None, 'state_fresh': False, 'devices': 0})

        import audit
        h['audit'] = audit.summary()
        import ha
        h['ha_configured'] = ha.configured()
        h['ha_token_problem'] = ha.token_problem()
        # 可达性**以证据为准**：状态快照如果是走官方 API 拿到的，HA 显然是可达的
        # （比单独探测可靠 —— 2026-10-17 实测：服务进程里 socket 探测偶发 False，
        #  但同进程的 API 调用一直是通的，于是设置页谎报"不可达"）。
        # 如实呈现：分开说"HA 服务可达吗"和"这份快照是怎么来的"。
        # 2026-10-17 实测：launchd 里的 socket/HTTP 探测偶发 False（独立进程正常），
        # 与其显示一个会骗人的"不可达"，不如把**证据**摆出来。
        # **不要在这里真调 HA**：/api/health 是被前端轮询的（实测 17 小时 4.5 万次请求），
        # 每次真调一次（带 30 秒重试）会让工作台在抖动时整体变卡，也让我的验收变慢。
        # 可达性用"证据"判断：快照新鲜 = 刚取到过数据 = 可达。
        h['ha_reachable'] = None          # 由下面的证据字段推导，不再主动探测
        src = (st.get('data_source') or {}) if isinstance(st, dict) else {}
        h['ha_source'] = src.get('registries') or 'unknown'
        h['ha_via_api'] = (h['ha_source'] == 'api')
        # 还有一个**更硬的证据**：快照新不新鲜。10 分钟内的设备数据本身就说明 HA 在正常应答
        # （数据是先从 HA 取回来才写进快照的）。launchd 进程里的探测偶发失败，不能让页面说谎。
        age = h.get('state_age_s')
        h['ha_data_fresh'] = bool(h.get('state_fresh') or (age is not None and age <= 600))

        cal = os.path.join(ROOT, 'data', 'offline-calibration.json')
        if os.path.exists(cal):
            with open(cal, encoding='utf-8') as f:
                c = json.load(f)
            h['calibration'] = {'hours': c.get('observation_hours'), 'calibrated': c.get('calibrated'),
                                'devices': c.get('devices'), 'enough_24h': c.get('enough_for_24h_rule')}

        import notify
        b = notify.budget()
        h['quota'] = {'score': b['score'], 'level': b['level'], 'muted_kinds': b['muted_kinds']}
        import outbox as _ob
        h['outbox'] = _ob.summary()
        # 磁盘与维护（长期运行的两件事：磁盘满了/日志涨了，都要能看见）
        import importlib.util as _iu2
        _sp2 = _iu2.spec_from_file_location('mt', os.path.join(ROOT, 'tools', 'maintain.py'))
        _mt = _iu2.module_from_spec(_sp2); _sp2.loader.exec_module(_mt)
        h['disk'] = _mt.check_disk()
        _ms = _mt.summary() or {}
        h['maintenance'] = {'at': _ms.get('at'), 'logs_mb': _ms.get('logs_mb'),
                            'rotated': len(_ms.get('rotated') or [])}
        h['quiet_hours'] = notify.quiet_hours().get('silent_hours')

        try:
            import decisions as _dec
            h['open_decisions'] = len(_dec.open_items())
        except Exception:  # noqa
            h['open_decisions'] = None

        gap = os.path.join(ROOT, 'data', 'mijia-dependency.json')
        if os.path.exists(gap):
            with open(gap, encoding='utf-8') as f:
                h['mijia_need'] = (json.load(f).get('counts') or {}).get('need_mijia')
        h['checked_at'] = now.isoformat(timespec='seconds')
        return self._json(h)
