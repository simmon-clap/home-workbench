#!/usr/bin/env node
/* 空间视图 · 全屋 Hero 生成器（离线生成静态产物，11 v1.2 §13「已声明生成物」）
 *
 * 输入：DATA/house.json（10 房间几何 + 家具零件；来源可追溯，可替换重生成）
 * 输出：app/web/space/house.html（静态 SVG + 内联运行时；零第三方）
 *
 * 用法：node app/prototype/spatial/build_house.mjs
 * 开发：SMART_HOME_ROOT=<dir> node build_house.mjs   （<dir> 下需有 data/ 与 app/web/）
 *
 * 运行时只读 /api/state：设备点、异常数、安全域形状都在浏览器里按真实状态画，
 * 几何是离线烘好的——页面不是唯一真相源。
 */
import fs from 'node:fs';
import path from 'node:path';

const ROOT = process.env.SMART_HOME_ROOT ||
  path.resolve(path.dirname(new URL(import.meta.url).pathname), '../../..');
const SRC = path.join(ROOT, 'data', 'house.json');
const OUT = path.join(ROOT, 'app', 'web', 'space', 'house.html');
const H = JSON.parse(fs.readFileSync(SRC, 'utf8'));

const S = 98, COS = Math.cos(Math.PI / 6), SIN = 0.5;
const WALL = (H.wall && H.wall.height) || 0.40;
const T = (H.wall && H.wall.thickness) || 0.10;
const P = (x, y, z = 0) => [(x - y) * COS * S, (x + y) * SIN * S - z * S];
const pts = a => a.map(p => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ');
const attrs = o => Object.entries(o).map(([k, v]) => `${k}="${v}"`).join(' ');
const C = { line: '#DDC8AC', floor: '#FFFDF9', wall: '#F1E5D4' };
const MAT = {
  wood:   { t: '#EFDCC0', a: '#DCC29B', b: '#D2B58C' },
  fabric: { t: '#F8F1E6', a: '#E8D7BF', b: '#DFCBAD' },
  linen:  { t: '#FFFDF9', a: '#F5ECDE', b: '#EFE2D0' },
  white:  { t: '#FFFFFF', a: '#F8F2E8', b: '#F3EBDE' },
  stone:  { t: '#F3EEE5', a: '#E3DACB', b: '#DAD0BF' },
  metal:  { t: '#E7E0D3', a: '#D3CABA', b: '#C9BFAC' },
  dark:   { t: '#8A8175', a: '#7A7164', b: '#6E6659' },
  glass:  { t: '#EAF1EE', a: '#DCE8E3', b: '#D3E1DB' },
  warm:   { t: '#DE9C6A', a: '#C0713F', b: '#B4643A' },
  leaf:   { t: '#D2DCC0', a: '#B7C4A0', b: '#A9B894' },
  rug:    { t: '#F3E3CC', a: '#EAD6BB', b: '#E5CEAF' },
  wall:   { t: '#F8EFDF', a: '#EAD9BE', b: '#E2CFB1' },
  base:   { t: '#FBF5EA', a: '#F0E4D1', b: '#EADCC7' },
  trim:   { t: '#F0E1C9', a: '#E0CDB0', b: '#D8C3A2' },
  book1:  { t: '#E3BFA8', a: '#D2A88E', b: '#C89C80' },
  book2:  { t: '#D6CFB0', a: '#C4BC97', b: '#B9B088' },
  book3:  { t: '#D4BBAD', a: '#C3A595', b: '#B89887' },
};

/* 等距立体：三个可见面（顶 + 右 + 前），画家顺序 */
function box(x, y, z, w, d, h, m) {
  const M = MAT[m] || MAT.wood;
  const top = [P(x, y, z + h), P(x + w, y, z + h), P(x + w, y + d, z + h), P(x, y + d, z + h)];
  const right = [P(x + w, y, z + h), P(x + w, y + d, z + h), P(x + w, y + d, z), P(x + w, y, z)];
  const front = [P(x, y + d, z + h), P(x + w, y + d, z + h), P(x + w, y + d, z), P(x, y + d, z)];
  return poly(top, M.t) + poly(right, M.a) + poly(front, M.b);
}
function poly(p, fill, extra = '') {
  return `<polygon points="${pts(p)}" fill="${fill}" stroke="${C.line}" stroke-width="0.9" ${extra}/>`;
}
/* 圆柱：八边形顶 + 面向观察者的侧面（近似，够用且零依赖） */
function cyl(x, y, z, r, h, m) {
  const M = MAT[m] || MAT.metal, n = 8, ring = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2 + Math.PI / n;
    ring.push([x + Math.cos(a) * r, y + Math.sin(a) * r]);
  }
  const top = ring.map(p => P(p[0], p[1], z + h));
  const side = [];
  for (const p of ring) if (p[0] > x - r * 0.02 && p[1] > y - r * 0.02) side.push(p);
  let out = poly(top, M.t);
  if (side.length >= 2) {
    const a = side.map(p => P(p[0], p[1], z + h));
    const b = side.slice().reverse().map(p => P(p[0], p[1], z));
    out += poly([...a, ...b], M.b);
  }
  return out;
}
const part = p => p.s === 'cyl' ? cyl(p.x, p.y, p.z, p.r, p.h, p.m) : box(p.x, p.y, p.z, p.w, p.d, p.h, p.m);
const shadow = p => `<polygon points="${pts([P(p.x + 0.05, p.y + 0.06, 0.004), P(p.x + p.w + 0.05, p.y + 0.06, 0.004), P(p.x + p.w + 0.05, p.y + p.d + 0.06, 0.004), P(p.x + 0.05, p.y + p.d + 0.06, 0.004)])}" fill="#B9A488" opacity="0.10"/>`;
/* 墙：按门洞切段；窗画成墙面浅色窗片 */
function wallSegments(room, side) {
  const [x, y, w, d] = room.rect;
  const len = side === 'x' ? d : w;
  const doors = (room.doors || []).filter(o => o.side === side).sort((a, b) => a.at - b.at);
  const cuts = [];
  for (const o of doors) cuts.push([o.at - o.w / 2, o.at + o.w / 2]);
  let segs = [], cur = 0.04;
  for (const [a, b] of cuts) { if (a > cur) segs.push([cur, a]); cur = Math.max(cur, b); }
  if (cur < len - 0.04) segs.push([cur, len - 0.04]);
  return { segs, doors };
}
function renderWalls(room) {
  const [x, y, w, d] = room.rect;
  let out = '';
  for (const side of ['x', 'y']) {
    const { segs, doors } = wallSegments(room, side);
    if ((room.rail || []).includes(side)) { out += rail(x, y, w, d, side); continue; }
    for (const [a, b] of segs) {
      if (b - a <= 0.001) continue;
      out += side === 'x'
        ? box(x + w - T, y + a, 0, T, b - a, WALL, 'wall') + baseboard(x + w - T - 0.012, y + a, 0, 0.012, b - a, 'x')
        : box(x + a, y + d - T, 0, b - a, T, WALL, 'wall') + baseboard(x + a, y + d - T - 0.012, 0, b - a, 0.012, 'y');
    }
    for (const o of doors) out += doorFrame(x, y, w, d, side, o.at, o.w);
    for (const win of (room.windows || []).filter(o => o.side === side)) out += windowPane(x, y, w, d, side, win.at, win.w);
  }
  return out;
}
function baseboard(bx, by, z, bw, bd, side) {
  const h = 0.055;
  return side === 'x'
    ? poly([P(bx, by, h), P(bx, by + bd, h), P(bx, by + bd, 0), P(bx, by, 0)], MAT.trim.b)
    : poly([P(bx, by, h), P(bx + bw, by, h), P(bx + bw, by, 0), P(bx, by, 0)], MAT.trim.b);
}
/* 阳台栏杆：立柱 + 上下横杆（取代该侧墙） */
function rail(x, y, w, d, side) {
  let out = '';
  const RZ = 0.62;
  if (side === 'y') {
    const by = y + d - 0.06;
    out += box(x + 0.02, by, 0, w - 0.04, 0.06, 0.04, 'trim');
    out += box(x + 0.02, by, RZ - 0.05, w - 0.04, 0.06, 0.05, 'trim');
    const n = Math.max(2, Math.round(w / 0.45));
    for (let i = 0; i <= n; i++) out += box(x + 0.02 + (w - 0.08) * (i / n), by + 0.01, 0.04, 0.035, 0.045, RZ - 0.09, 'trim');
  } else {
    const bx = x + w - 0.06;
    out += box(bx, y + 0.02, 0, 0.06, d - 0.04, 0.04, 'trim');
    out += box(bx, y + 0.02, RZ - 0.05, 0.06, d - 0.04, 0.05, 'trim');
    const n = Math.max(2, Math.round(d / 0.45));
    for (let i = 0; i <= n; i++) out += box(bx + 0.01, y + 0.02 + (d - 0.08) * (i / n), 0.04, 0.045, 0.035, RZ - 0.09, 'trim');
  }
  return out;
}
/* 瓷砖地面：细网格（样式化，不是照片纹理） */
function floorGrid(x, y, w, d) {
  let out = '';
  const step = 0.55, t = 0.012;
  for (let gx = step; gx < w - 0.02; gx += step)
    out += poly([P(x + gx, y + 0.02, 0.006), P(x + gx + t, y + 0.02, 0.006), P(x + gx + t, y + d - 0.02, 0.006), P(x + gx, y + d - 0.02, 0.006)], '#EFE6D6');
  for (let gy = step; gy < d - 0.02; gy += step)
    out += poly([P(x + 0.02, y + gy, 0.006), P(x + w - 0.02, y + gy, 0.006), P(x + w - 0.02, y + gy + t, 0.006), P(x + 0.02, y + gy + t, 0.006)], '#EFE6D6');
  return out;
}
function doorFrame(x, y, w, d, side, at, dw) {
  let out = '';
  const z0 = 0.02, z1 = WALL * 0.94;
  if (side === 'x') {
    const bx = x + w - T;
    out += box(bx, y + at - dw / 2 - 0.035, 0, T, 0.035, WALL, 'trim');
    out += box(bx, y + at + dw / 2, 0, T, 0.035, WALL, 'trim');
    out += box(bx + T * 0.15, y + at - dw / 2, z0, 0.035, dw, z1, 'trim'); // 门扇（半开）
  } else {
    const by = y + d - T;
    out += box(x + at - dw / 2 - 0.035, by, 0, 0.035, T, WALL, 'trim');
    out += box(x + at + dw / 2, by, 0, 0.035, T, WALL, 'trim');
    out += box(x + at - dw / 2, by + T * 0.15, z0, dw, 0.035, z1, 'trim');
  }
  return out;
}
function windowPane(x, y, w, d, side, at, ww) {
  const z0 = WALL * 0.34, z1 = WALL * 0.86;
  if (side === 'x') {
    const bx = x + w + 0.004;
    return poly([P(bx, y + at - ww / 2, z0), P(bx, y + at + ww / 2, z0), P(bx, y + at + ww / 2, z1), P(bx, y + at - ww / 2, z1)], MAT.glass.t, 'opacity="0.9"');
  }
  const by = y + d + 0.004;
  return poly([P(x + at - ww / 2, by, z0), P(x + at + ww / 2, by, z0), P(x + at + ww / 2, by, z1), P(x + at - ww / 2, by, z1)], MAT.glass.t, 'opacity="0.9"');
}

/* 组装：房间按 (x+y) 由远及近；每间先地板 → 家具 → 墙（墙在近侧，能正确遮挡） */
const rooms = H.rooms.slice().sort((a, b) => (a.rect[0] + a.rect[1]) - (b.rect[0] + b.rect[1]));
const hx0 = Math.min(...H.rooms.map(r => r.rect[0])), hy0 = Math.min(...H.rooms.map(r => r.rect[1]));
const hx1 = Math.max(...H.rooms.map(r => r.rect[0] + r.rect[2])), hy1 = Math.max(...H.rooms.map(r => r.rect[1] + r.rect[3]));
const BH = 0.075, BP = 0.13;   // 基座厚度 / 外扩
let body = '', labels = '', i = 0;
body += box(hx0 - BP, hy0 - BP, -BH, (hx1 - hx0) + BP * 2, (hy1 - hy0) + BP * 2, BH, 'base');
body += poly([P(hx0 - BP, hy0 - BP, 0.001), P(hx1 + BP, hy0 - BP, 0.001), P(hx1 + BP, hy1 + BP, 0.001), P(hx0 - BP, hy1 + BP, 0.001)], 'none', `stroke="${C.line}" stroke-width="0"`);
let minX = 1e9, maxX = -1e9, minY = 1e9, maxY = -1e9;
for (const r of rooms) {
  const [x, y, w, d] = r.rect;
  for (const p of [[x, y], [x + w, y], [x + w, y + d], [x, y + d]]) {
    const q = P(p[0], p[1], 0); const t = P(p[0], p[1], WALL);
    for (const v of [q, t]) { minX = Math.min(minX, v[0]); maxX = Math.max(maxX, v[0]); minY = Math.min(minY, v[1]); maxY = Math.max(maxY, v[1]); }
  }
  const all = H.parts.filter(p => p.room === r.name);
  const shades = all.filter(p => p.s === 'shadow');
  const parts = all.filter(p => p.s !== 'shadow')
    .sort((a, b) => ((a.x + a.y) || 0) - ((b.x + b.y) || 0));
  body += `<g class="room${i % 2 ? ' alt' : ''}" id="r${i++}" data-room="${r.name}" data-rect="${x},${y},${w},${d}">`;
  body += poly([P(x, y), P(x + w, y), P(x + w, y + d), P(x, y + d)], C.floor, `class="floor"`);
  if (r.tile) body += floorGrid(x, y, w, d);
  body += shades.map(shadow).join('');
  body += parts.map(part).join('');
  body += renderWalls(r);
  const c = P(x + w / 2, y + d / 2, WALL + 0.14);
  const bw = Math.max(58, r.name.length * 16 + 20);
  labels += `<g class="rlg" data-room="${r.name}"><rect class="rbg" x="${(c[0] - bw / 2).toFixed(0)}" y="${(c[1] - 16).toFixed(0)}" width="${bw}" height="36" rx="9"/>` +
    `<text class="rl" x="${c[0].toFixed(0)}" y="${c[1].toFixed(0)}" text-anchor="middle">` +
    `<tspan class="rn">${r.name}</tspan><tspan class="rc" dy="15" x="${c[0].toFixed(0)}">—</tspan></text></g>`;
  body += '</g>';
}
const pad = 90;
const vb = `${(minX - pad).toFixed(0)} ${(minY - pad).toFixed(0)} ${(maxX - minX + pad * 2).toFixed(0)} ${(maxY - minY + pad * 2).toFixed(0)}`;

const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="generated-by" content="app/prototype/spatial/build_house.mjs">
<meta name="generated-src" content="data/house.json">
<meta name="generated-at" content="${new Date().toISOString()}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>空间视图 · 家庭工作台</title>
<style>
:root{--page:#FDFBF7;--face:#FFFDF9;--top:#F6EFE4;--shade1:#EADCC7;--shade2:#E2D5C2;
      --line:#E2D5C2;--text:#4E463C;--muted:#9C9184;--warm:#C0713F;--alert:#B4453C;--warn:#8A6A1F}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--text);
  font:14px/1.5 -apple-system,"PingFang SC",sans-serif;padding:20px}
h1{font-size:15px;font-weight:600;margin:0 0 4px}p.sub{margin:0 0 10px;color:var(--muted);font-size:12px}
#stage{position:relative;background:#FBF8F1;border:1px solid var(--line);border-radius:14px;overflow:hidden}
svg.house{display:block;width:100%;height:auto;touch-action:manipulation}
svg.house .floor{transition:fill .25s}
svg.house .room.alt .floor{fill:#FDF8F0}
svg.house .rlg{pointer-events:none}
svg.house .rbg{fill:#FFFDF9;opacity:.82;stroke:#E9DCC9;stroke-width:.8}
svg.house .room{cursor:pointer}
svg.house .room.zoom .floor{fill:#FFFDF9}
svg.house .rl .rn{fill:var(--text);font-size:14px;font-weight:600}
svg.house .rl .rc{fill:var(--muted);font-size:11.5px}
svg.house .room.warn .floor{fill:#FCF6EA}
svg.house .room.sec .floor{fill:#FDF0EC}
svg.house .room.warn .rl .rc{fill:var(--warn)}
svg.house .room.sec .rl .rc{fill:var(--alert)}
svg.house .room.sel .rl .rn{fill:var(--warm)}
#world{transition:transform .32s cubic-bezier(.22,.61,.36,1);transform-origin:center}
.dot{stroke-width:0;opacity:.95}
.dot.on{fill:var(--warm)}.dot.off{fill:#C9C1B4}.dot.stale{fill:var(--warn)}
.dot.sec{fill:var(--alert)}
.hint{margin:8px 2px 0;color:var(--muted);font-size:12px}
.hint b{color:var(--text);font-weight:600}
.legend{display:flex;gap:14px;margin:10px 2px 0;color:var(--muted);font-size:12px;flex-wrap:wrap}
.legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:1px}
.legend i.on{background:var(--warm)}
.legend i.off{background:#C9C1B4}
.legend i.d{background:var(--alert);border-radius:1px;transform:rotate(45deg)}
@media (max-width:520px){
  body{padding:10px}h1{font-size:14px}p.sub{font-size:11px;margin-bottom:8px}.hint{font-size:11px}
  #stage{border-radius:12px}
  svg.house .rl .rn{font-size:24px}svg.house .rl .rc{font-size:19px}
  svg.house .rbg{display:none}
  svg.house .rl .rn,svg.house .rl .rc{paint-order:stroke;stroke:#FFFDF9;stroke-width:5px;stroke-linejoin:round}
  svg.house .dot{r:7.5}svg.house .dot[width]{width:16;height:16}
}
</style></head><body>
<h1>空间视图</h1>
<p class="sub">10 个房间 · 家具与几何来自 <b>data/house.json</b>（可替换后重新生成）· 状态实时来自 /api/state</p>
<div id="stage"><svg class="house" viewBox="${vb}" xmlns="http://www.w3.org/2000/svg">
<g id="world">${body}${labels}</g></svg></div>
<div class="legend"><span><i class="on"></i>在线</span><span><i class="off"></i>离线 / 无读数</span><span><i class="d"></i>安全域（形状可辨）</span></div>
<p class="hint" id="hint">点击房间放大 · 按 Esc 或再点一次回到全屋。设备点按真实状态实时更新。</p>
<script>
(() => {
  const svg = document.querySelector('svg.house'), world = document.getElementById('world');
  const VB0 = (() => { const b = svg.viewBox.baseVal; return { x: b.x, y: b.y, w: b.width, h: b.height }; })();
  const hint = document.getElementById('hint');
  const POS = [[0.16,0.18],[0.46,0.12],[0.80,0.20],[0.24,0.52],[0.62,0.56],[0.86,0.78],[0.14,0.84],[0.52,0.86]];
  let sel = null;
  const esc = s => String(s).replace(/[^\\w\\u4e00-\\u9fa5-]/g, '');
  function anchor(room, name){
    let h = 0; for (const ch of room + '|' + name) h = (h * 31 + ch.codePointAt(0)) >>> 0;
    return POS[h % POS.length];
  }
  function placeDots(roomEl, roomName, devs){
    roomEl.querySelectorAll('.dots').forEach(n => n.remove());
    const g = document.createElementNS('http://www.w3.org/2000/svg','g');
    g.setAttribute('class','dots');
    const r = roomEl; const rect = RECT[roomName]; if (!rect) return;
    devs.slice(0, 8).forEach((d, i) => {
      const [fx, fy] = anchor(roomName, d.name);
      const x = rect[0] + rect[2] * fx + (i % 2 ? 0.04 : 0), y = rect[1] + rect[3] * fy;
      const p = PROJ(x, y, 0.03);
      const el = document.createElementNS('http://www.w3.org/2000/svg', d.security_domain ? 'rect' : 'circle');
      el.setAttribute('class','dot ' + (d.confidence === 'online' ? 'on' : d.confidence === 'stale' ? 'stale' : 'off') + (d.security_domain ? ' sec' : ''));
      if (d.security_domain) { el.setAttribute('x', (p[0]-5).toFixed(1)); el.setAttribute('y', (p[1]-5).toFixed(1)); el.setAttribute('width','10'); el.setAttribute('height','10'); el.setAttribute('transform','rotate(45 ' + p[0].toFixed(1) + ' ' + p[1].toFixed(1) + ')'); }
      else { el.setAttribute('cx', p[0].toFixed(1)); el.setAttribute('cy', p[1].toFixed(1)); el.setAttribute('r','4.6'); }
      g.appendChild(el);
    });
    roomEl.appendChild(g);
  }
  const RECT = {}, PROJ = (x, y, z) => { const c = Math.cos(Math.PI/6); return [(x-y)*c*98, (x+y)*0.5*98 - (z||0)*98]; };
  document.querySelectorAll('.room').forEach(el => { RECT[el.dataset.room] = el.dataset.rect.split(',').map(Number); });
  fetch('/api/state').then(r => r.json()).then(st => {
    const byRoom = new Map((st.rooms || []).map(r => [r.name, r]));
    const devs = st.devices || [];
    for (const el of document.querySelectorAll('.room')) {
      const name = el.dataset.room, r = byRoom.get(name);
      const lw = document.querySelector('.rlg[data-room="' + name + '"] .rc');
      const total = r ? r.total : 0, off = r ? r.offline : 0;
      if (!r) { if (lw) lw.textContent = '未接入设备'; continue; }
      if (lw) lw.textContent = off ? off + ' 台异常 / 共 ' + total + ' 台' : total + ' 台 · 正常';
      if (off) el.classList.add((st.attention || []).some(a => a.room === name && a.level === 'sec') ? 'sec' : 'warn');
      const rank = d => d.security_domain ? 0 : d.confidence === 'offline' ? 1 : d.confidence === 'stale' ? 2 : 3;
      const list = devs.filter(d => d.room === name).sort((a, b) => rank(a) - rank(b) || (a.name < b.name ? -1 : 1));
      placeDots(el, name, list);
    }
    hint.textContent = '状态已接上（' + byRoom.size + ' 个房间）· 设备点最多 8 个、异常/安全域优先 · 点击房间放大，Esc 回全屋。';
  }).catch(() => { hint.textContent = '实时状态暂时读不到：图上只显示几何与家具，不显示设备状态。'; });

  const want = new URLSearchParams(location.search).get('room');
  if (want) { const hit = [...document.querySelectorAll('.room')].find(n => n.dataset.room === want);
    if (hit) select(hit); }
  svg.addEventListener('click', ev => {
    const g = ev.target.closest('.room'); if (!g) { reset(); return; }
    if (sel === g.id) { reset(); return; }
    select(g);
  });
  function select(g) {
    document.querySelectorAll('.room.sel').forEach(n => n.classList.remove('sel'));
    sel = g.id; g.classList.add('sel');
    const r = RECT[g.dataset.room]; if (!r) return;
    const c = PROJ(r[0] + r[2] / 2, r[1] + r[3] / 2, 0), k = 2.1;
    svg.setAttribute('viewBox', (c[0] - VB0.w / (2 * k)).toFixed(1) + ' ' + (c[1] - VB0.h / (2 * k)).toFixed(1) + ' ' + (VB0.w / k).toFixed(1) + ' ' + (VB0.h / k).toFixed(1));
    hint.textContent = g.dataset.room + ' · 再点一次或按 Esc 回到全屋';
  }
  function reset() {
    if (sel) document.querySelectorAll('.room.sel').forEach(n => n.classList.remove('sel'));
    sel = null; svg.setAttribute('viewBox', VB0.x + ' ' + VB0.y + ' ' + VB0.w + ' ' + VB0.h);
    hint.textContent = '点击房间放大 · 按 Esc 或再点一次回到全屋。';
  }
  document.addEventListener('keydown', e => { if (e.key === 'Escape') reset(); });
})();
</script>
</body></html>
`;

fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, html);
console.log(`已生成 ${path.relative(ROOT, OUT)}（${rooms.length} 房间 · ${H.parts.length} 零件 · ${(html.length / 1024).toFixed(1)} KB）`);
