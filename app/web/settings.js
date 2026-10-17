/**
 * 功能设置页（03 §1D）
 *
 * 规范要求这里必须能：改设备↔房间绑定 · 改展示短名 · 改标签 · 改离线阈值 ·
 * 手动录入设备 · 看到变更历史并回滚。**不依赖 agent 在线**——这一页纯前端 + 本地接口。
 *
 * 入口：?view=settings（房间面板底部有链接）
 */
(function () {
  const $ = (s) => document.querySelector(s);
  const api = async (path, body) => {
    const r = await fetch(path, body === undefined ? {} :
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    return r.json();
  };
  const esc = (t) => String(t == null ? '' : t)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  const THRESHOLDS = [[300, '摄像头 300 秒'], [600, '市电/Wi-Fi 600 秒'], [43200, '电池 12 小时']];

  function row(d, rooms) {
    const opts = rooms.map((r) => `<option value="${esc(r)}"${r === d.room ? ' selected' : ''}>${esc(r)}</option>`).join('');
    const src = d.room_source === 'override' ? '本地改过' : (d.room_source === 'manual' ? '手动录入' : '米家');
    const th = THRESHOLDS.map(([v, l]) =>
      `<option value="${v}"${v === d.offline_threshold_s ? ' selected' : ''}>${l}</option>`).join('');
    const has = (t) => (d.tags || []).includes(t);
    return `<div class="srow wrap" data-name="${esc(d.name)}">
      <span class="sname click" data-open="${esc(d.name)}">${esc(d.name)}${d.security_domain ? '<b class="secmark">安全域</b>' : ''}</span>
      <span class="ssrc">${src}</span>
      <select class="sroom" data-name="${esc(d.name)}">${opts}</select>
      <div class="smore" hidden>
        <label class="slab">短名
          <input class="sshort" data-name="${esc(d.name)}" value="${esc(d.short_name || '')}" placeholder="（留空用全名）" />
        </label>
        <label class="slab">标签
          <span class="stags">
            <label><input type="checkbox" class="stag" data-name="${esc(d.name)}" data-tag="type" ${has('type') ? 'checked' : ''}/>type</label>
            <label><input type="checkbox" class="stag" data-name="${esc(d.name)}" data-tag="sec" ${has('sec') ? 'checked' : ''}/>sec</label>
          </span>
        </label>
        <label class="slab">离线阈值
          <select class="sth" data-name="${esc(d.name)}">${th}</select>
        </label>
      </div>
    </div>`;
  }

  function histRow(h) {
    const done = h.reverted ? '<b class="ssrc">已回滚</b>' : '';
    const btn = (h.reverted || h.id == null) ? ''
      : `<button class="chip" data-entry="${h.id}">回滚</button>`;
    return `<div class="srow"><span class="sname">${esc(h.device)} · ${esc(h.field)}${done ? ' ' + done : ''}</span>
      <span class="ssrc">${esc((h.at || '').slice(5, 16))} 由${h.by === 'agent' ? '助手' : '你'}改</span>
      <span class="sval">${esc(h.from == null ? '—' : h.from)} → ${esc(h.to)}</span>${btn}</div>`;
  }

  async function renderSettings() {
    /* 独立页面用 #settingsBox；从主页面进来时退回 #roomPanel（两种情况都能用） */
    const box = document.querySelector('#settingsBox') || $('#roomPanel');
    if (!document.querySelector('#settingsBox')) {
      box.classList.remove('hidden');
      const stage = document.querySelector('.stage'); if (stage) stage.style.display = 'none';
      const remind = document.querySelector('#remind'); if (remind) remind.style.display = 'none';
    }
    const d = await api('/api/settings');
    const rooms = d.rooms || [];
    const byRoom = {};
    for (const dev of d.devices || []) (byRoom[dev.room] ||= []).push(dev);

    const hl = await api('/api/health');
    const age = hl.state_age_s;
    const freshTxt = age == null ? '未知' : (age < 60 ? `${age} 秒前` : `${Math.round(age / 60)} 分钟前`);
    const health = `<div class="ssec">系统状态</div>
      <div class="tip">数据${hl.state_fresh ? '新鲜' : '<b class="swarn">偏旧</b>'}：状态生成于 ${freshTxt}
        · ${hl.devices} 台设备 · ${hl.attention} 项待注意</div>
      <div class="tip">HA：${hl.ha_via_api ? '可达（数据取自官方 API）'
        : hl.ha_data_fresh ? '可达（数据是新鲜的，快照在离线时生成过）'
        : '这次取数没成功（显示的是最后一次可用数据）'} · 令牌：${hl.ha_configured ? '已配置' : '未配置'}
        ${hl.ha_token_problem ? '（' + esc(hl.ha_token_problem) + '）' : ''}
        · 审计：${hl.audit.total} 条（被拒 ${hl.audit.blocked}）</div>
      <div class="tip">离线阈值校准：观测 ${hl.calibration ? hl.calibration.hours : '—'} 小时
        · 可校准 ${hl.calibration ? hl.calibration.calibrated : '—'}/${hl.calibration ? hl.calibration.devices : '—'}
        ${hl.calibration && hl.calibration.enough_24h ? '（已满足 24 小时）' : '（<b class="swarn">未满 24 小时，阈值判定未启用</b>）'}</div>
      <div class="tip">最近说过：${hl.outbox && hl.outbox.total ? (hl.outbox.total + ' 条 · 最后 ' + esc((hl.outbox.last_at || '').slice(5, 16))) : '还没有（没话就不说）'}</div>
      <div class="tip">出声额度：${hl.quota.level}（${hl.quota.score}/10）
        · 仍需米家：${hl.mijia_need == null ? '—' : hl.mijia_need + ' 台'}
        · 待你决定：${hl.open_decisions == null ? '—' : hl.open_decisions + ' 项'}</div>`;
    box.innerHTML = `
      <div class="ph"><span class="bk" id="sBack">← 回全屋</span><span class="ct">功能设置</span></div>
      ${health}
      <div class="tip">改的是<b>映射</b>，不改设备本身、不改米家原名。改动立即生效，并记进历史可回滚。</div>
      <div class="ssec">规则（说一句话 → 我复述一遍 → 你确认才生效）</div>
      <div class="tip">例：每天22:30如果主卫没人就把主卫的灯关了。条件需要人体传感器；没有的话我会直说做不了并给替代方案。</div>
      <div class="sadd">
        <input id="ruleText" placeholder="说一句规则，例如：每天23:00把客厅的灯关了" />
        <button class="chip" id="ruleParse">解析</button>
      </div>
      <div class="tip" id="ruleMsg"></div>
      ${(d.rules || []).map((r) => `<div class="srow">
        <span class="sname">${esc(r.recap || '')}<span class="ssrc"> · ${esc(r.status || '')}${
          r.ha_entity ? ' · ' + esc(r.ha_entity) : ''}${r.readback_ok === false ? ' · <b class="swarn">未回读</b>' : ''}</span></span>
        ${r.status === 'active' && r.ha_entity ? `<button class="chip" data-rule-off="${esc(r.id)}" data-on="1">停用</button>` : ''}
      </div>`).join('') || '<div class="tip">还没有规则</div>'}
      <div class="ssec">场景（可见 · 可编辑 · 可停用 · 可回滚）</div>
      <div class="tip">每个场景都用一句人话复述出来；安全域动作自动标成"只提醒"。</div>
      ${(d.scenes || []).map((sc) => `<div class="scard">
        <div class="srow">
          <span class="sname">${esc(sc.name)}${sc.enabled ? '' : ' <b class="ssrc">（已停用）</b>'}</span>
          <button class="chip" data-scene-toggle="${esc(sc.id)}" data-on="${sc.enabled ? '1' : '0'}">${sc.enabled ? '停用' : '启用'}</button>
          <button class="chip" data-scene-undo="${esc(sc.id)}">回滚</button>
        </div>
        <div class="tip">${esc(sc.describe)}</div>
        <div class="sceneRow">
          ${(sc.step_list || []).filter((st) => st.action).map((st) =>
            `<span class="chip">${esc(st.describe.replace('（共 1 步）', ''))}
               <b class="xdel" data-scene-del="${esc(sc.id)}" data-idx="${st.index}">×</b></span>`).join('') || '<span class="ssrc">还没有步骤</span>'}
        </div>
        <div class="sadd">
          <select class="snewtype" data-scene="${esc(sc.id)}">
            ${[['light', '灯'], ['cover', '窗帘'], ['ac', '空调'], ['plug', '插座'], ['lock', '门锁（只提醒）']]
              .map(([k, l]) => `<option value="${k}">${l}</option>`).join('')}
          </select>
          <select class="snewact" data-scene="${esc(sc.id)}">
            ${[['turn_on', '打开'], ['turn_off', '关掉'], ['open', '拉开'], ['close', '合上']]
              .map(([k, l]) => `<option value="${k}">${l}</option>`).join('')}
          </select>
          <select class="snewroom" data-scene="${esc(sc.id)}"><option value="">全部房间</option>
            ${rooms.map((r) => `<option>${esc(r)}</option>`).join('')}</select>
          <button class="chip" data-scene-add="${esc(sc.id)}">加一步</button>
        </div>
      </div>`).join('') || '<div class="tip">没有场景</div>'}
      <div class="ssec">分区映射（扫地机地图 → 我们的房间名）</div>
      <div class="tip">扫地机扫出来的分区叫「房间1/房间8」，和我们的房间名不一定一致；这里对齐后，空间视图就能把它们当成真的房间用。</div>
      ${(d.zones || []).map((z) => `<div class="srow">
        <span class="sname">${esc(z.zone)}<span class="ssrc"> · 占 ${Math.round((z.share || 0) * 100)}% 面积</span></span>
        <input class="szname" data-zone="${esc(z.zone)}" value="${esc(z.label || z.zone)}"
               title="改分区名（如 房间1 → 儿童房）；重新扫描地图也不会丢" />
        <select class="szone" data-zone="${esc(z.zone)}">
          <option value="">（未映射）</option>
          ${rooms.map((r) => `<option value="${esc(r)}"${r === z.room ? ' selected' : ''}>${esc(r)}</option>`).join('')}
        </select></div>`).join('') || '<div class="tip">没有分区数据（先跑 tools/floorplan_from_shot.py）</div>'}
      <div class="ssec">米家依赖补录（判据 1）</div>
      <div class="tip">为了清单外的事打开了米家？记一笔 —— 这些才是"一整天不用打开米家"的真实缺口。</div>
      <div class="sadd">
        <input id="depReason" placeholder="为什么开了米家（一句话）" />
        <button class="chip" id="depAdd">记一笔</button>
      </div>
      ${(d.extra_deps || []).map((x) => `<div class="srow">
        <span class="sname">${esc(x.reason)}</span>
        <span class="ssrc">${esc((x.at || '').slice(5, 16))} · ${esc(x.where || '米家')}</span>
        <button class="chip" data-depdel="${esc(x.reason)}">移除</button></div>`).join('') ||
        '<div class="tip">还没有补录</div>'}
      <div class="ssec">房间绑定（${(d.devices || []).length} 台）</div>
      ${Object.keys(byRoom).sort().map((r) => `<div class="sgroup">${esc(r)}</div>` +
          byRoom[r].map((x) => row(x, rooms)).join('')).join('')}
      <div class="ssec">手动录入设备（未接入 HA 也能登记位置）</div>
      <div class="sadd">
        <input id="sNewName" placeholder="设备名称（用米家的名字）" />
        <select id="sNewRoom">${rooms.map((r) => `<option>${esc(r)}</option>`).join('')}</select>
        <button class="chip" id="sAdd">录入</button>
      </div>
      <div class="tip" id="sMsg"></div>
      <div class="ssec">变更历史（最近 40 条，可回滚）</div>
      ${(d.history || []).length ? d.history.map(histRow).join('') : '<div class="tip">还没有改动过</div>'}
      <div class="tip">阈值可选：摄像头 300 秒 · 市电/Wi-Fi 600 秒 · 电池 43200 秒（06 §3 参考值）</div>`;

    const back = $('#sBack'); if (back) back.onclick = () => { location.href = '/'; };
    box.querySelectorAll('.sroom').forEach((sel) => {
      sel.onchange = async () => {
        const out = await api('/api/settings/set',
          { device: sel.dataset.name, field: 'room', value: sel.value });
        $('#sMsg').textContent = out.message || '';
        if (out.ok) renderSettings();
      };
    });
    /* 展开一行：短名 / 标签 / 离线阈值（03 §1D 的可编辑对象要全部能改） */
    box.querySelectorAll('[data-open]').forEach((el) => {
      el.onclick = () => { const more = el.parentElement.querySelector('.smore'); more.hidden = !more.hidden; };
    });
    box.querySelectorAll('.sshort').forEach((inp) => {
      inp.onchange = async () => {
        const out = await api('/api/settings/set',
          { device: inp.dataset.name, field: 'short_name', value: inp.value.trim() });
        $('#sMsg').textContent = out.message || '';
        if (out.ok) renderSettings();
      };
    });
    box.querySelectorAll('.sth').forEach((sel) => {
      sel.onchange = async () => {
        const out = await api('/api/settings/set',
          { device: sel.dataset.name, field: 'offline_threshold_s', value: parseInt(sel.value, 10) });
        $('#sMsg').textContent = out.message || '';
        if (out.ok) renderSettings();
      };
    });
    box.querySelectorAll('.stag').forEach((cb) => {
      cb.onchange = async () => {
        const name = cb.dataset.name;
        const tags = [...box.querySelectorAll('.stag')]
          .filter((x) => x.dataset.name === name && x.checked).map((x) => x.dataset.tag);
        let out = await api('/api/settings/set', { device: name, field: 'tags', value: tags });
        if (!out.ok && (out.message || '').indexOf('确认') >= 0) {          /* 安全域越权保护：显式确认 */
          if (window.confirm((out.message || '') + '\n\n确认要这样做吗？')) {
            out = await api('/api/settings/set', { device: name, field: 'tags', value: tags, confirm: true });
          }
        }
        $('#sMsg').textContent = out.message || '';
        if (out.ok) renderSettings(); else renderSettings();
      };
    });
    /* 场景编辑（03 §7）：停用/启用 · 回滚 · 删一步 · 加一步 */
    const rParse = $('#ruleParse');
    if (rParse) rParse.onclick = async () => {
      const out = await api('/api/rule/propose', { text: $('#ruleText').value.trim() });
      let html = esc(out.recap || '没听懂');
      if (out.needs) html += `<br><b class="swarn">${esc(out.needs)}</b>`;
      if (out.rule_id) {
        html += `<br><button class="chip" id="ruleConfirm">确认创建（会写进 HA 并回读）</button>
                 <button class="chip" id="ruleCancel">先不建</button>`;
      }
      $('#ruleMsg').innerHTML = html;
      const cf = $('#ruleConfirm');
      if (cf) cf.onclick = async () => {
        const r2 = await api('/api/rule/commit', { rule_id: out.rule_id, confirm: true });
        $('#ruleMsg').textContent = r2.ok
          ? `已创建并回读确认（${r2.readback}）`
          : ('创建失败：' + (r2.error || '未知'));
        renderSettings();
      };
      const cc = $('#ruleCancel');
      if (cc) cc.onclick = () => { $('#ruleMsg').textContent = '没有创建任何东西'; };
    };
    box.querySelectorAll('[data-rule-off]').forEach((b) => {
      b.onclick = async () => {
        const r2 = await api('/api/rule/enable', { rule_id: b.dataset.ruleOff, enabled: false });
        $('#sMsg').textContent = r2.ok ? '已停用并回读确认' : ('停用失败：' + (r2.error || ''));
        renderSettings();
      };
    });
    box.querySelectorAll('[data-scene-toggle]').forEach((b) => {
      b.onclick = async () => {
        const out = await api('/api/scenes/edit',
          { do: 'toggle', scene_id: b.dataset.sceneToggle, enabled: b.dataset.on !== '1' });
        $('#sMsg').textContent = out.message || '';
        renderSettings();
      };
    });
    box.querySelectorAll('[data-scene-undo]').forEach((b) => {
      b.onclick = async () => {
        const out = await api('/api/scenes/edit', { do: 'undo', scene_id: b.dataset.sceneUndo });
        $('#sMsg').textContent = out.message || '';
        renderSettings();
      };
    });
    box.querySelectorAll('[data-scene-del]').forEach((b) => {
      b.onclick = async () => {
        const out = await api('/api/scenes/edit',
          { do: 'remove', scene_id: b.dataset.sceneDel, index: parseInt(b.dataset.idx, 10) });
        $('#sMsg').textContent = out.message || '';
        renderSettings();
      };
    });
    box.querySelectorAll('[data-scene-add]').forEach((b) => {
      b.onclick = async () => {
        const card = b.closest('.scard');
        const out = await api('/api/scenes/edit', {
          do: 'add', scene_id: b.dataset.sceneAdd,
          type: card.querySelector('.snewtype').value,
          action: card.querySelector('.snewact').value,
          room: card.querySelector('.snewroom').value || null });
        $('#sMsg').textContent = out.message || '';
        renderSettings();
      };
    });
    const depAdd = $('#depAdd');
    if (depAdd) depAdd.onclick = async () => {
      const out = await api('/api/settings/dep', { reason: $('#depReason').value.trim() });
      $('#sMsg').textContent = out.message || '';
      if (out.ok) renderSettings();
    };
    box.querySelectorAll('[data-depdel]').forEach((b) => {
      b.onclick = async () => {
        const out = await api('/api/settings/dep', { reason: b.dataset.depdel, remove: true });
        $('#sMsg').textContent = out.message || '';
        if (out.ok) renderSettings();
      };
    });
    box.querySelectorAll('.szname').forEach((inp) => {
      inp.onchange = async () => {
        const out = await api('/api/settings/zone-name',
          { zone: inp.dataset.zone, label: inp.value.trim() });
        $('#sMsg').textContent = out.message || '';
        if (out.ok) renderSettings();
      };
    });
    box.querySelectorAll('.szone').forEach((sel) => {
      sel.onchange = async () => {
        const out = await api('/api/settings/set-zone', { zone: sel.dataset.zone, room: sel.value });
        $('#sMsg').textContent = out.message || '';
        if (out.ok) renderSettings();
      };
    });
    box.querySelectorAll('[data-entry]').forEach((b) => {
      b.onclick = async () => {
        const out = await api('/api/settings/undo', { entry_id: parseInt(b.dataset.entry, 10) });
        $('#sMsg').textContent = out.message || '';
        if (out.ok) renderSettings();
      };
    });
    $('#sAdd').onclick = async () => {
      const out = await api('/api/settings/add-device',
        { name: $('#sNewName').value.trim(), room: $('#sNewRoom').value });
      $('#sMsg').textContent = out.message || '';
      if (out.ok) renderSettings();
    };
  }

  window.renderSettings = renderSettings;
  /* 只有设置页（有 #settingsBox）才自动渲染。
     否则在主页面也会被 DOMContentLoaded 触发、把房间面板覆盖成设置内容（实测踩过）。 */
  if (document.querySelector('#settingsBox')) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', renderSettings);
    else renderSettings();
  }
})();
