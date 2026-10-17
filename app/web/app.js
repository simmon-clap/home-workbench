/* 家庭工作台 · 前端（数据来自 /api/state，即 L2 状态模型；不做任何猜测） */
const LAYOUT = {
  '客厅':  {x:0, y:0,   w:6, d:4.5}, '主卧': {x:6, y:0,   w:4, d:4.5},
  '厨房':  {x:0, y:4.5, w:3, d:3.5}, '餐厅': {x:3, y:4.5, w:3, d:3.5},
  '次卧':  {x:6, y:4.5, w:4, d:3.5}, '客卫': {x:0, y:8,   w:2, d:2},
  '主卫':  {x:2, y:8,   w:2, d:2},   '书房': {x:4, y:8,   w:2, d:2},
  '阳台':  {x:6, y:8,   w:2, d:2},   '办公室': {x:8, y:8, w:2, d:2}
};
const GLYPH = {
  light:'<path d="M9.2 18h5.6M10.4 21h3.2M12 3a6 6 0 0 1 3.4 10.9c-.4.3-.6.8-.6 1.3v.8H9.2v-.8c0-.5-.2-1-.6-1.3A6 6 0 0 1 12 3z"/>',
  curtain:'<path d="M3.5 4h17M6.5 4v15M17.5 4v15M6.5 8.5c2 1 3.7 1 5.5 0s3.5-1 5.5 0"/>',
  ac:'<rect x="3" y="6" width="18" height="7.5" rx="2"/><path d="M7 17c1 1.2 2 1.2 3 0M14 17c1 1.2 2 1.2 3 0"/>',
  cam:'<path d="M4 8.5h3l1.4-2h7.2l1.4 2h3v9H4z"/><circle cx="12" cy="13" r="2.8"/>',
  lock:'<rect x="5" y="10.5" width="14" height="9.5" rx="2.5"/><path d="M8.5 10.5V7.5a3.5 3.5 0 0 1 7 0v3"/>',
  sensor:'<rect x="4.5" y="6" width="15" height="12" rx="3"/><path d="M8.5 12h7"/>',
  plug:'<rect x="5" y="9" width="14" height="10" rx="2.5"/><path d="M9.5 9V5.5M14.5 9V5.5"/>',
  tv:'<rect x="3" y="5" width="18" height="11.5" rx="2"/><path d="M9 19.5h6"/>',
  vacuum:'<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="2.4"/><path d="M12 4v3"/>',
  speaker:'<rect x="6.5" y="3" width="11" height="18" rx="3.2"/><circle cx="12" cy="9" r="1.9"/><circle cx="12" cy="15.8" r="2.8"/>',
  other:'<rect x="4" y="4" width="16" height="16" rx="3.5"/><path d="M8 12h8"/>'
};
const TYPE2GLYPH = {cover:'curtain', ac:'ac', light:'light', lock:'lock', camera:'cam', cam:'cam',
  sensor:'sensor', plug:'plug', tv:'tv', vacuum:'vacuum', speaker:'speaker', curtain:'curtain', other:'other'};
const ico = (t, s, c, sw) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="${c}" stroke-width="${sw || 1.5}" stroke-linecap="round" stroke-linejoin="round">${GLYPH[TYPE2GLYPH[t] || t] || GLYPH.other}</svg>`;
const KCOLOR = {online:'#C0713F', offline:'#CFC7BB', stale:'#B98A3E', unknown:'#9C9184'};
const S = 98, WALL = 0.30;
const proj = (x, y, z) => [(x - y) * 0.866 * S, (x + y) * 0.5 * S - (z || 0) * S];
const pts = a => a.map(p => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
const $ = s => document.querySelector(s);
let STATE = null, SEL = {room:null, device:null};
let CAPS = {devices:{}, readonly_types:[], not_connected:[]};
let SCENES = [], PENDING_SCENE = null;

function devState(d){
  if (d.confidence === 'online') return '在线';
  if (d.confidence === 'offline') return '离线';
  if (d.confidence === 'stale') return '超时未上报';
  return '无有效读数';
}
function devColor(d){ return d.confidence === 'online' ? (d.security_domain ? '#B4453C' : '#C0713F') : KCOLOR[d.confidence]; }
function roomLevel(room){
  const att = STATE.attention.filter(a => a.room === room);
  if (att.some(a => a.level === 'sec')) return 'sec';
  if (att.length) return 'warn';
  return 'ok';
}
function sortedRoomDevices(room){
  const rank = d => (d.confidence !== 'online' && d.security_domain) ? 0
    : d.confidence !== 'online' ? 1
    : (d.type === 'camera' || d.type === 'lock') ? 2
    : d.type === 'light' ? 3 : 4;
  return STATE.devices.filter(d => d.room === room).slice().sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
}

/* ---------------- 2.5D 全屋 ---------------- */
function drawHouseSafe(){
  /* 规范 03 §8：3D 不是唯一视图 —— 渲染失败或低配设备时必须能用等价的列表。
     兜底：出错/没布局就把空间图藏起来，显示房间列表（.mlist）。 */
  try {
    drawHouse();
    document.body.classList.remove('no-3d');
  } catch (err) {
    document.body.classList.add('no-3d');
    console.warn('空间视图渲染失败，已退回房间列表', err);
  }
}

function drawHouse(){
  const svg = $('#house');
  const rooms = STATE.rooms.filter(r => LAYOUT[r.name]);
  if (!rooms.length){ svg.innerHTML = ''; document.body.classList.add('no-3d'); return; }
  svg.innerHTML = `<defs><radialGradient id="lamp"><stop offset="0%" stop-color="#F3C877" stop-opacity="0.9"/><stop offset="62%" stop-color="#F3C877" stop-opacity="0.3"/><stop offset="100%" stop-color="#F3C877" stop-opacity="0"/></radialGradient>
    <radialGradient id="floorG"><stop offset="0%" stop-color="#FBEDE1" stop-opacity="0.95"/><stop offset="100%" stop-color="#FBEDE1" stop-opacity="0"/></radialGradient></defs>`;
  const base = rooms.flatMap(r => { const L = LAYOUT[r.name];
    return [proj(L.x, L.y, 0), proj(L.x + L.w, L.y, 0), proj(L.x + L.w, L.y + L.d, 0), proj(L.x, L.y + L.d, 0)]; });
  const bx = base.map(p => p[0]), by = base.map(p => p[1]);
  const minX = Math.min(...bx) - 80, maxX = Math.max(...bx) + 80;
  const minY = Math.min(...by) - 90, maxY = Math.max(...by) + 70;
  svg.setAttribute('viewBox', `${minX} ${minY} ${maxX - minX} ${maxY - minY}`);
  svg.insertAdjacentHTML('beforeend', `<ellipse cx="${(minX + maxX) / 2}" cy="${(minY + maxY) / 2 + 20}" rx="${(maxX - minX) / 2}" ry="${(maxY - minY) / 2.4}" fill="url(#floorG)"/>`);

  const order = rooms.slice().sort((a, b) => (LAYOUT[a.name].x + LAYOUT[a.name].y) - (LAYOUT[b.name].x + LAYOUT[b.name].y));
  for (const r of order){
    const L = LAYOUT[r.name], z = WALL, lv = roomLevel(r.name), sel = SEL.room === r.name;
    const stroke = lv === 'sec' ? '#D9887E' : lv === 'warn' ? '#DDBE8A' : '#E2D5C2';
    const top = sel ? '#FFEEDA' : lv === 'sec' ? '#FDF0EC' : lv === 'warn' ? '#FCF6EA' : '#FFFDF9';
    const wx = sel ? '#F7ECD9' : lv === 'sec' ? '#F6E0DA' : lv === 'warn' ? '#F7ECD9' : '#F1E5D4';
    const wy = sel ? '#F3E5CE' : lv === 'sec' ? '#F2D8D2' : lv === 'warn' ? '#F3E5CE' : '#EADCC7';
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.setAttribute('class', 'room' + (sel ? ' sel' : ''));
    g.setAttribute('opacity', SEL.room && !sel ? '0.88' : '1');
    g.dataset.room = r.name;
    g.innerHTML = `
      <polygon class="walls" points="${pts([proj(L.x + L.w, L.y, z), proj(L.x + L.w, L.y + L.d, z), proj(L.x + L.w, L.y + L.d, 0), proj(L.x + L.w, L.y, 0)])}" fill="${wx}" stroke="${stroke}" stroke-width="1"/>
      <polygon class="walls" points="${pts([proj(L.x, L.y + L.d, z), proj(L.x + L.w, L.y + L.d, z), proj(L.x + L.w, L.y + L.d, 0), proj(L.x, L.y + L.d, 0)])}" fill="${wy}" stroke="${stroke}" stroke-width="1"/>
      <polygon class="top" points="${pts([proj(L.x, L.y, z), proj(L.x + L.w, L.y, z), proj(L.x + L.w, L.y + L.d, z), proj(L.x, L.y + L.d, z)])}"
        fill="${top}" stroke="${sel ? '#B4643A' : stroke}" stroke-width="${sel ? 2.8 : (lv === 'ok' ? 1.2 : 1.7)}"/>`;
    const big = L.w * L.d >= 12;
    // 标签统一画到房子外侧并带引线（规范 03 §1：标签引线放在外侧），见 drawOuterLabels
    /* 关键设备令牌：异常优先 */
    const mk = sortedRoomDevices(r.name).slice(0, big ? 3 : 1);
    const POS = [[0.30, 0.28], [0.68, 0.34], [0.48, 0.66], [0.80, 0.62]];
    mk.forEach((d, i) => {
      const [px, py] = proj(L.x + L.w * POS[i % 4][0], L.y + L.d * POS[i % 4][1], z);
      const on = SEL.device === d.name, col = devColor(d), R = on ? 20 : 15, cy = py - (on ? 12 : 9);
      if (d.confidence === 'online' && d.type !== 'camera') svg.ownerSVGElement;
      g.insertAdjacentHTML('beforeend', `<g opacity="${SEL.device && !on ? '0.45' : '1'}">
        ${on ? `<circle cx="${px}" cy="${cy}" r="${R + 10}" fill="#FBE7D2" stroke="#C0713F" stroke-opacity="0.8" stroke-width="2.6"/>` : ''}
        <circle cx="${px}" cy="${cy}" r="${R}" fill="#FFFFFF" stroke="${on ? '#C0713F' : col}" stroke-opacity="${on ? 1 : 0.5}" stroke-width="${on ? 2.4 : 1}"/>
        <g transform="translate(${px - (on ? 15 : 10)},${cy - (on ? 15 : 10)})">${ico(d.type, on ? 30 : 20, on ? '#9E4F20' : col, on ? 2.4 : 1.5)}</g>
        ${on ? `<rect x="${px - (d.name.length * 6 + 11)}" y="${cy - 56}" width="${d.name.length * 12 + 22}" height="26" rx="13" fill="#FFF3E2" stroke="#C0713F" stroke-opacity="0.55"/><text x="${px}" y="${cy - 38}" text-anchor="middle" font-size="12" fill="#B4643A" font-weight="700">${d.name}</text>` : ''}
      </g>`);
    });
    g.addEventListener('click', () => selectRoom(r.name));
    svg.appendChild(g);
  }
  drawOuterLabels(svg, order, minX, maxX, minY, maxY);
}

/* 外侧标签 + 引线（规范 03 §1「标签引线放在外侧」）。
   房间密、标签放里面会压住设备点，所以放到房子外侧、按左右两列纵向排开。 */
function drawOuterLabels(svg, rooms, minX, maxX, minY, maxY){
  const midX = (minX + maxX) / 2;
  /* 字号/线宽按视框宽度换算：SVG 被缩放到容器宽度，写死 13px 会小到看不清（实测截图如此）。 */
  const vbW = maxX - minX;
  const fName = Math.max(18, vbW / 46), fSub = Math.max(13, vbW / 62);
  const lw = Math.max(1, vbW / 900);
  const sides = { left: [], right: [] };
  for (const r of rooms){
    const L = LAYOUT[r.name];
    const c = proj(L.x + L.w / 2, L.y + L.d / 2, WALL);
    (c[0] < midX ? sides.left : sides.right).push({ r, c });
  }
  const rows = Math.max(sides.left.length, sides.right.length, 1);
  for (const side of ['left', 'right']){
    sides[side].sort((a, b) => a.c[1] - b.c[1]);
    sides[side].forEach((it, i) => {
      const y = minY + (maxY - minY) * ((i + 0.5) / rows);
      const anchorX = side === 'left' ? minX - 12 : maxX + 12;
      const sel = SEL.room === it.r.name, lv = roomLevel(it.r.name);
      const col = sel ? '#C0713F' : lv === 'sec' ? '#B4453C' : lv === 'warn' ? '#B98A3E' : '#8A8078';
      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.setAttribute('class', 'outer-label' + (sel ? ' sel' : ''));
      g.dataset.room = it.r.name;
      g.innerHTML =
        `<line x1="${anchorX + (side === 'left' ? 3 : -3)}" y1="${y}" x2="${it.c[0]}" y2="${it.c[1]}"
               stroke="${col}" stroke-opacity="0.5" stroke-width="${lw}" stroke-dasharray="${lw * 5} ${lw * 8}"/>` +
        `<text x="${anchorX}" y="${y - 2}" text-anchor="${side === 'left' ? 'end' : 'start'}"
               font-size="${fName}" font-weight="${sel ? 700 : 600}" fill="${col}">${it.r.name}</text>` +
        `<text x="${anchorX}" y="${y + fSub * 1.9}" text-anchor="${side === 'left' ? 'end' : 'start'}"
               font-size="${fSub}" fill="${it.r.offline ? '#B4453C' : '#9C9184'}">${it.r.offline ? it.r.offline + ' 台异常' : it.r.total + ' 台'}</text>`;
      g.addEventListener('click', () => selectRoom(it.r.name));
      svg.appendChild(g);
    });
  }
  /* 视框按**实际内容**（含外侧标签）自适应 —— 否则面板占位让画布变窄时，标签会被裁掉。
     2026-10-17 实测：选中房间后右侧面板展开，外侧标签整个消失（被 viewBox 裁了）。 */
  try {
    const bb = svg.getBBox();
    const m = Math.max(10, (maxX - minX) * 0.02);
    if (bb.width > 0 && bb.height > 0) {
      svg.setAttribute('viewBox', `${bb.x - m} ${bb.y - m} ${bb.width + 2 * m} ${bb.height + 2 * m}`);
    }
  } catch (e) { /* 拿不到包围盒就保持原视框 */ }
}

/* ---------------- 右侧上下文面板 ---------------- */
function renderPanel(){
  const p = $('#roomPanel');
  if (!SEL.room){ p.classList.add('hidden'); p.innerHTML = ''; return; }
  p.classList.remove('hidden');
  const list = sortedRoomDevices(SEL.room);
  if (!SEL.device){
    p.innerHTML = `<div class="ph"><span class="tt">${SEL.room}</span><span class="ct">${list.length} 台设备</span></div>
      ${SEL.room === '客厅' ? `<div class="real3d"><div class="r3h"><span>真实 3D · 客餐厅（扫描）</span><a href="/space/scan-room-model.html" target="_blank">打开可编辑</a></div><a class="r3thumb" href="/space/scan-room-model.html" title="点开可编辑 3D"><div class="r3box" role="img" aria-label="客厅真实 3D 扫描模型"></div></a></div>` : ''}
      <div class="pb">${list.map(d => `
        <div class="di ${d.confidence !== 'online' ? 'off' : ''}" data-dev="${d.name}">
          <span class="ic">${ico(d.type, 20, devColor(d))}</span>
          <span class="nm">${d.name}</span>
          <span class="st"><b>${devState(d)}</b><br>${d.security_domain ? '安全域' : (d.manufacturer || '')}</span>
        </div>`).join('')}</div>
      ${SCENES.length ? `<div class="sceneRow"><span class="ct">场景</span>${SCENES.map(x =>
        `<button class="chip" data-scene="${x.id}" title="影响 ${x.executable} 步">${x.name}</button>`).join('')}</div>
        <div class="tip" id="sceneTip">场景会动多台设备：第一次点给预告，再点一次才执行</div>` : ''}
      <div class="tip">点设备看它的状态与数据 · 点其他房间可切换 · <a href="/space/house.html">全屋空间视图</a> · <a href="/space/scan-room-model.html">扫描实景 3D（可编辑）</a> · <a href="/space/">扫描几何快照</a> · <a href="/settings.html">功能设置</a><br>未接通：${(CAPS.not_connected || []).join(' · ') || '无'}</div>`;
  } else {
    const d = list.find(x => x.name === SEL.device) || STATE.devices.find(x => x.name === SEL.device);
    const rows = (d.readings || []).map(r => `<div class="drow"><span class="k">${r.label}${r.note ? `<small class="rn">${r.note}</small>` : ''}</span><span class="v num">${r.value}${r.unit ? ' ' + r.unit : ''}</span></div>`).join('');
    p.innerHTML = `<div class="ph"><span class="bk" id="pBack">← ${SEL.room}</span><span class="ct">${(d.status_at || '').slice(11, 16)}</span></div>
      <div class="dhead"><span class="big">${ico(d.type, 30, devColor(d))}</span><span class="nm">${d.name}</span>
        <span class="st">${devState(d)}${d.security_domain ? ' · 安全域' : ''}</span></div>
      <div class="pb">
        ${rows || `<div class="drow"><span class="k">读数</span><span class="v">暂无</span></div>`}
        <div class="drow"><span class="k">来源</span><span class="v">${d.source}</span></div>
        <div class="drow"><span class="k">读数时间</span><span class="v num">${d.observed_at ? d.observed_at.replace('T', ' ').slice(5, 16) : '—'}</span></div>
        <div class="tip" id="chgBox" hidden></div>
        ${d.observed_note ? `<div class="tip">${d.observed_note}${d.status_at ? ' · 状态生效于 ' + d.status_at.replace('T', ' ').slice(5, 16) : ''}</div>` : ''}
        <div class="tip">未接通：${(CAPS.not_connected || []).join(' · ') || '无'}</div>
        <div class="spark" id="spark"></div>
      </div>
      <div class="acts"><button id="pMore">更多</button>${actButton(d)}</div>`;
    /* 最近变化（含来源）：渲染后再取，避免把同步渲染函数改成 async。
       没有记录就不显示 —— 不编（宪章：状态被推翻要留痕；外部改动不许冒充成我们做的）。 */
    const chgBox = p.querySelector('#chgBox');
    if (chgBox) {
      api('/api/changes?device=' + encodeURIComponent(d.name)).then((c) => {
        const last = (c.changes || [])[0];
        if (!last) return;
        const tag = last.source === 'external' ? '外部改动（墙面开关/米家/家庭 App）' : '我方执行';
        chgBox.textContent = `最近变化：${tag} · ${last.from} → ${last.to}（${(last.at || '').slice(5, 16)}）`;
        chgBox.hidden = false;
      }).catch(() => {});
    }
    $('#pBack').onclick = () => { SEL.device = null; renderPanel(); drawHouse(); };
    p.querySelectorAll('[data-scene]').forEach(btn => btn.onclick = async () => {
      const id = btn.dataset.scene, tip = () => document.getElementById('sceneTip');
      if (PENDING_SCENE !== id) {                       /* 第一次：只说将要发生什么，不执行 */
        let j = {};
        try {
          j = await (await fetch('/api/scene', {method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({scene_id: id, dry: true})})).json();
        } catch (e) { j = {reason:'预告请求失败：' + e}; }
        PENDING_SCENE = id;
        if (tip()) tip().innerHTML = (j.preview || j.reason || '') + ` —— <b>再点一次「${btn.textContent}」执行</b>`;
        return;
      }
      PENDING_SCENE = null;                              /* 第二次：真执行 + 回读 + 可撤销 */
      btn.disabled = true; btn.textContent = '执行中…';
      let out = {};
      try {
        out = await (await fetch('/api/scene', {method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({scene_id: id})})).json();
      } catch (e) { out = {reason:'执行请求失败：' + e}; }
      const html = (out.receipt || out.reason || '没有回执') +
        (out.action_id ? ` · <a href="#" id="undoScene">撤销</a>` : '');
      if (tip()) tip().innerHTML = html;
      const u = document.getElementById('undoScene');
      if (u) u.onclick = async (ev) => {
        ev.preventDefault();
        const j = await (await fetch('/api/undo', {method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({action_id: out.action_id})})).json();
        if (tip()) tip().textContent = j.ok ? '已撤销（读回确认）' : ('撤销失败：' + (j.error || '未知'));
      };
      await reload();                                   /* 状态真相以回读后的数据为准，不复用旧渲染 */
    });
    $('#pMore').onclick = () => showAudit(d);
    p.querySelectorAll('[data-act]').forEach(btn => btn.onclick = async () => {
      btn.disabled = true; btn.textContent = '执行中…';
      let out = {};
      try {
        const r = await fetch('/api/device-action', {method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({name: d.name, action: btn.dataset.act})});
        out = await r.json();
      } catch (e) { out = {receipt: '执行请求失败：' + e}; }
      const box = document.getElementById('lastReceipt') || document.createElement('div');
      box.className = 'tip'; box.id = 'lastReceipt';
      box.innerHTML = (out.receipt || '没有回执') +
        (out.action_id ? ` · <a href="#" id="undoNow">撤销</a>` : '') +
        `<br>未接通：${(CAPS.not_connected || []).join(' · ') || '无'}`;
      const host = document.getElementById('spark');
      if (host && !document.getElementById('lastReceipt')) host.insertAdjacentElement('afterend', box);
      renderPanel();
      const u = document.getElementById('undoNow');
      if (u) u.onclick = async (ev) => {
        ev.preventDefault();
        const rr = await fetch('/api/undo', {method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({action_id: out.action_id})});
        const j = await rr.json();
        alert(j.ok ? '已撤销（读回确认）' : ('撤销失败：' + (j.error || '未知')));
      };
    });
    drawSpark(d);
  }
  p.querySelectorAll('[data-dev]').forEach(el => el.onclick = () => {
    SEL.device = el.dataset.dev; renderPanel(); drawHouse();
  });
}
function actsOf(d){
  /* 动作表来自服务端逐设备解析（app/panel_action.py 按真实实体解析），前端不另立规则 */
  if (d.security_domain) return {};
  if ((CAPS.readonly_types || []).includes(d.type)) return {};
  return (CAPS.devices || {})[d.name] || {};
}
function actButton(d){
  if (d.security_domain) return '<button class="pri" disabled>需本机确认（去米家手动）</button>';
  const acts = actsOf(d);
  const ids = Object.keys(acts);
  if (!ids.length) return '';
  return ids.map(a => `<button class="pri" data-act="${a}"` +
    (acts[a].verifiable ? '' : ' title="这台设备不回传状态，点了只能确认指令已发出">') +
    `>${acts[a].label || a}${acts[a].verifiable ? '' : '（不回传状态）'}</button>`).join('');
}
function toast(text){
  const el = document.getElementById('spark') || document.getElementById('pBody');
  if (el) el.insertAdjacentHTML('afterend', `<div class="tip" id="lastReceipt">${text}</div>`);
}
function sparkSvg(points, unit){
  const w = 280, h = 54;
  const vs = points.map(p => p[1]);
  const mn = Math.min.apply(null, vs), mx = Math.max.apply(null, vs), rg = (mx - mn) || 1;
  const t0 = points[0][0], t1 = points[points.length - 1][0] || t0 + 1;
  const d = points.map(p => `${((p[0] - t0) / (t1 - t0) * w).toFixed(1)},${(h - (p[1] - mn) / rg * h).toFixed(1)}`).join(' ');
  /* 标签写真实跨度：不足 24 小时就说不足，不假装 */
  const spanMin = Math.round((t1 - t0) / 60000);
  const left = spanMin >= 1200 ? '24 小时前' : spanMin >= 60 ? Math.round(spanMin / 60) + ' 小时前' : spanMin + ' 分钟前';
  return `<svg width="${w}" height="${h + 10}" viewBox="0 0 ${w} ${h + 10}">
    <polyline points="${d}" fill="none" stroke="#C0713F" stroke-width="1.6" stroke-linejoin="round"/>
    <text x="0" y="${h + 8}" font-size="10" fill="#8A8078">${left}</text>
    <text x="${w}" y="${h + 8}" font-size="10" fill="#8A8078" text-anchor="end">现在${unit ? '（' + unit + '）' : ''}</text>
    ${spanMin < 1200 ? `<text x="${w / 2}" y="10" text-anchor="middle" font-size="10" fill="#9C9184">接入后 ${spanMin >= 60 ? Math.round(spanMin / 60) + ' 小时' : spanMin + ' 分钟'}的数据</text>` : ''}</svg>`;
}
async function drawSpark(dev){
  const el = document.getElementById('spark');
  if (!el) return;
  const cand = (dev.readings || []).find(r => /^-?[0-9.]+$/.test(String(r.value)) && r.unit);
  if (!cand) return;
  try {
    const r = await fetch(`/api/history?entity_id=${encodeURIComponent(cand.entity_id)}&hours=24`);
    const h = await r.json();
    if (h.points && h.points.length >= 2) el.innerHTML = sparkSvg(h.points, h.unit || cand.unit);
  } catch (e) { /* 没有历史就不画，不编数据 */ }
}
async function showAudit(d){
  const p = $('#roomPanel');
  let rows = [], sum = {};
  try {
    const r = await fetch('/api/audit?limit=20&target=' + encodeURIComponent(d.entity_id || ''));
    const j = await r.json();
    rows = j.rows || []; sum = j.summary || {};
  } catch (e) { /* 取不到就说取不到，不编 */ }
  p.innerHTML = `<div class="ph"><span class="bk" id="pBack2">← ${d.name}</span><span class="ct">${sum.total || 0} 条</span></div>
    <div class="dhead"><span class="big">${ico(d.type, 30, devColor(d))}</span><span class="nm">动作历史</span>
      <span class="st">只在有记录时显示 · 审计只追加</span></div>
    <div class="pb">${rows.length ? rows.slice().reverse().map(r => `
      <div class="drow"><span class="k">${(r.at || '').slice(11, 19)}</span>
        <span class="v">${r.action} · ${r.result}${r.readback ? ' · 回读 ' + r.readback : ''}</span></div>`).join('')
      : '<div class="drow"><span class="k">这台设备</span><span class="v">暂无动作记录</span></div>'}</div>
    <div class="tip">来源：data/audit.jsonl（只追加，无删除接口）。被规范拦下的动作也会留痕。</div>`;
  $('#pBack2').onclick = () => renderPanel();
}
function selectRoom(name){ SEL = {room:name, device:null}; renderPanel(); drawHouseSafe(); }
function goHome(){ SEL = {room:null, device:null}; renderPanel(); drawHouse(); }

/* ---------------- 页头 / 提醒 / 页脚 / 窄屏列表 ---------------- */
function renderChrome(){
  const s = STATE.summary, now = new Date();
  const h = now.getHours();
  const greet = h < 6 ? '夜里好' : h < 11 ? '早上好' : h < 14 ? '中午好' : h < 18 ? '下午好' : '晚上好';
  $('#greet').innerHTML = `${greet}<small>${s.headline}</small>`;
  $('#remindTx').innerHTML = s.attention_count ? `<b>${STATE.attention[0].device}</b> ${STATE.attention[0].issue} · ${STATE.attention[0].detail}` : '';
  $('#remind').classList.toggle('on', s.attention_count > 0);
  $('#tTotal').textContent = s.total + ' 台设备';
  $('#tOff').textContent = (s.offline + s.stale) + ' 台异常';
  $('#tUnknown').textContent = s.unknown + ' 台无读数';
  $('#tSec').textContent = s.security_domain + ' 台安全域';
  $('#goHome').textContent = '回全屋';
  $('#env').textContent = '数据来自 HA';
  $('#fTime').textContent = (STATE.generated_at || '').replace('T', ' ').slice(11, 16);
  /* 数据偏旧时**明说**（03 §12：HA 不通要明说"中枢连不上"，并给出最后可用读数的时间）。
     数据新鲜时绝不出现这条 —— 不许假告警（测试守着）。 */
  const ageMin = STATE.generated_at ? Math.round((now - new Date(STATE.generated_at)) / 60000) : null;
  const stale = ageMin !== null && ageMin >= 10;
  const bar = $('#staleBar');
  if (bar) {
    if (stale) {
      bar.textContent = `中枢可能连不上：数据最后更新于 ${ageMin} 分钟前（${(STATE.generated_at || '').replace('T', ' ').slice(5, 16)}）。`
        + '下面显示的是**最后一次可用读数**，不是现在。';
      bar.hidden = false;
    } else {
      bar.hidden = true;                       // 新鲜时保持隐藏，不吓人
    }
  }
  const ml = $('#mlist');
  if (ml){
    const rank = r => roomLevel(r.name) === 'sec' ? 0 : roomLevel(r.name) === 'warn' ? 1 : 2;
    ml.innerHTML = STATE.rooms.slice().sort((a, b) => rank(a) - rank(b)).map(r => {
      const lv = roomLevel(r.name);
      return `<div class="mi ${lv === 'sec' ? 'flag' : lv === 'warn' ? 'warnd' : ''}" data-room="${r.name}">
        <div><div class="nm">${r.name}</div><div class="sub">${r.total} 台设备</div></div>
        <div class="st">${r.offline ? r.offline + ' 台异常' : '正常'}</div></div>`;
    }).join('');
    ml.querySelectorAll('.mi').forEach(el => el.onclick = () => selectRoom(el.dataset.room));
  }
}

async function reload(){
  try { STATE = await (await fetch('/api/state')).json(); } catch (e) { return; }
  renderChrome(); drawHouseSafe(); renderPanel();
}
async function boot(){
  const r = await fetch('/api/state');
  if (!r.ok){ document.querySelector('#greet').innerHTML = '状态尚未生成<small>请先运行 app/state.py</small>'; return; }
  STATE = await r.json();
  /* 打开时若数据偏旧（≥5 分钟），先让服务端刷新一次再渲染 —— 状态真相不能是几小时前的。
     刷新是同步子进程（几秒），失败也不影响把最后可用读数画出来。 */
  try {
    const ageMin = STATE.generated_at ? (Date.now() - new Date(STATE.generated_at)) / 60000 : 999;
    if (ageMin >= 5) {
      const rr = await fetch('/api/refresh', { method: 'POST' });
      if (rr.ok) { const r2 = await fetch('/api/state'); if (r2.ok) STATE = await r2.json(); }
    }
  } catch (e) { /* 刷新失败就用现有的：不编、不卡 */ }
  try { CAPS = await (await fetch('/api/capabilities')).json(); } catch (e) { /* 拉不到就用空表：不显示按钮，不猜 */ }
  try { SCENES = (await (await fetch('/api/scenes')).json()).scenes || []; } catch (e) { SCENES = []; }
  renderChrome(); drawHouse(); renderPanel();
  $('#remindGo').onclick = () => { const a = STATE.attention[0]; if (a) selectRoom(a.room); };
  $('#goHome').onclick = goHome;
  /* 深链接（也用于截图预设）：?room=厨房&device=小米天然气卫士 */
  const q = new URLSearchParams(location.search);
  if (q.get('room')){ selectRoom(q.get('room')); if (q.get('device')){ SEL.device = q.get('device'); renderPanel(); drawHouseSafe(); } }
}
boot();
