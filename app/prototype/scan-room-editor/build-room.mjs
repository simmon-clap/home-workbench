#!/usr/bin/env node
/* 扫描房间 · 可编辑 3D 模型（Anatomy 风格，真实尺寸）
 *
 * 数据：data/3d/rooms/客厅餐厅-20261017.json（RoomPlan 扫描归一化，单位 m）
 *      + 同名 .edited.json（编辑器保存的覆盖版本，存在则优先）
 * 产物：app/web/space/scan-room-model.html（生成物：静态 SVG + 内联交互脚本）
 *
 * 交互：
 *   悬停 → 该构件轮廓高亮 + 名称/尺寸浮标
 *   点击 → 选中（右侧面板可改语义类型/名称/尺寸/位置/旋转，可删除）
 *   保存 → POST /api/3d/edit → 服务端写 .edited.json 并重建本页
 *
 * 用法：node app/prototype/scan-room-editor/build.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as k from './kit/iso-kit.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../../..');
const DATA = path.join(ROOT, 'data', '3d', 'rooms');
const NAME = process.env.SCAN_ROOM_NAME || '客厅餐厅-20261017';
const OUT = path.join(ROOT, 'app', 'web', 'space', 'scan-room-model.html');
const BASE = JSON.parse(fs.readFileSync(path.join(DATA, NAME + '.json'), 'utf8'));
const EDITED = path.join(DATA, NAME + '.edited.json');
const model = fs.existsSync(EDITED) ? JSON.parse(fs.readFileSync(EDITED, 'utf8')) : BASE;

const M = (v) => v * 100;              // m → cm（工作单位 cm）
const CUT = 72;                        // 墙/门/窗的剖切高度（cm）
const WIDTH = 940, HEIGHT = 700;

/* ---------- 世界坐标：扫描坐标（x 右、y 下）→ 模型坐标 ---------- */
const walls = model.walls.map((w) => ({
  ...w, x1: M(w.x1), y1: M(w.y1), x2: M(w.x2), y2: M(w.y2),
  length: M(w.length), t: M(w.t), h: M(w.h),
  openings: (w.openings || []).map((o) => ({
    ...o, start: M(o.start), end: M(o.end), width: M(o.width),
    height: M(o.height), sill: M(o.sill),
  })),
}));
const furn = (model.furniture || []).map((f, i) => ({
  ...f, idx: i, x: M(f.x), y: M(f.y), w: M(f.w), d: M(f.d), h: M(f.h),
}));
const labels = (model.room_labels || []).map((l) => ({ ...l, x: M(l.x), y: M(l.y) }));

const allPts = [
  ...walls.flatMap((w) => [[w.x1, w.y1, 0], [w.x2, w.y2, 0], [w.x1, w.y1, CUT], [w.x2, w.y2, CUT]]),
  ...furn.flatMap((f) => [[f.x, f.y, 0], [f.x, f.y, Math.min(f.h, 130)]]),
];
const P = k.fitProjection(allPts, WIDTH, HEIGHT, { pad: 34, headroom: 26, azimuth: 45, elevation: 30 });
const iso = (pt) => k.iso(pt, P);
const S = (paths, style) => k.solidSvg(paths, style || {});

const ringRect = (cx, cy, w, d, rot = 0) => {
  const a = (rot * Math.PI) / 180, ca = Math.cos(a), sa = Math.sin(a);
  return [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([sx, sy]) => {
    const lx = (sx * w) / 2, ly = (sy * d) / 2;
    return [cx + lx * ca - ly * sa, cy + lx * sa + ly * ca];
  });
};

/* ---------- 构件构造 ---------- */
const pieces = [];
const add = (id, kind, label, center, depthPoint, svg) =>
  pieces.push({ id, kind, label, center, depth: k.depthOf([depthPoint[0], depthPoint[1], 0], P), svg });

/* 地板 + 基座 */
function basePlate() {
  const xs = walls.flatMap((w) => [w.x1, w.x2]);
  const ys = walls.flatMap((w) => [w.y1, w.y2]);
  const pad = 18;
  const plan = { x: Math.min(...xs) - pad, y: Math.min(...ys) - pad, w: Math.max(...xs) - Math.min(...xs) + pad * 2, d: Math.max(...ys) - Math.min(...ys) + pad * 2, r: 14 };
  let out = `<path class="iso-halo" d="${k.haloOf(plan, -16, 16, P)}"/>`;
  out += S(k.slabOf(plan, -16, 16, P, 6, 2), { tone: 'mid' });
  out += S(k.slabOf({ ...plan, x: plan.x + 10, y: plan.y + 10, w: plan.w - 20, d: plan.d - 20 }, 0, 1, P, 4), { tone: 'lo', crease: 'none' });
  return out;
}

/* 墙：按门窗洞切段；窗留窗台，门留洞 */
function wallPiece(w, wi) {
  const L = w.length || 1;
  const ux = (w.x2 - w.x1) / L, uy = (w.y2 - w.y1) / L;
  const nx = -uy, ny = ux;
  const ops = [...w.openings].sort((a, b) => a.start - b.start);
  const segs = [];
  let pos = 0;
  for (const o of ops) { if (o.start > pos) segs.push([pos, o.start, 'wall', null]); segs.push([o.start, o.end, o.kind, o]); pos = Math.max(pos, o.end); }
  if (pos < L) segs.push([pos, L, 'wall', null]);

  const ringOf = (a, b) => [
    [w.x1 + ux * a + nx * w.t / 2, w.y1 + uy * a + ny * w.t / 2],
    [w.x1 + ux * b + nx * w.t / 2, w.y1 + uy * b + ny * w.t / 2],
    [w.x1 + ux * b - nx * w.t / 2, w.y1 + uy * b - ny * w.t / 2],
    [w.x1 + ux * a - nx * w.t / 2, w.y1 + uy * a - ny * w.t / 2],
  ];
  let out = '';
  for (const [a, b, kind, op] of segs) {
    if (kind === 'wall') {
      out += S(k.extrude(ringOf(a, b), 0, CUT, P, { convex: true, bevel: 1.2 }), { tone: 'mid' });
    } else if (kind === 'window') {
      const sill = Math.min(op.sill, CUT);
      out += S(k.extrude(ringOf(a, b), 0, sill, P, { convex: true, bevel: 1 }), { tone: 'mid' });
      const top = Math.min(CUT, sill + Math.max(12, Math.min(op.height, CUT - sill)));
      // 玻璃面：贴在墙中心线上的一条带
      const z0 = sill + 2, z1 = top - 2;
      if (z1 > z0) {
        const p1 = [w.x1 + ux * a, w.y1 + uy * a];
        const p2 = [w.x1 + ux * b, w.y1 + uy * b];
        const quad = [iso([p1[0], p1[1], z0]), iso([p2[0], p2[1], z0]), iso([p2[0], p2[1], z1]), iso([p1[0], p1[1], z1])];
        out += `<polygon class="glass" points="${quad.map((q) => q.map((v) => v.toFixed(1)).join(',')).join(' ')}"/>`;
        out += k.lineSvg(k.pathOf([iso([p1[0], p1[1], z1]), iso([p2[0], p2[1], z1])]), { tone: 'mid' });
        out += k.lineSvg(k.pathOf([iso([p1[0], p1[1], z0]), iso([p2[0], p2[1], z0])]), { tone: 'lo' });
        // 竖框（两端 + 中分）
        for (const t of [0.02, 0.5, 0.98]) {
          const p = [w.x1 + ux * (a + (b - a) * t), w.y1 + uy * (a + (b - a) * t)];
          out += k.lineSvg(k.pathOf([iso([p[0], p[1], z0]), iso([p[0], p[1], z1])]), { tone: 'lo' });
        }
      }
    } else if (kind === 'door') {
      const hS = CUT; // 剖切高度内全空
      out += S(k.extrude(ringOf(a, a + 5), 0, hS, P, { convex: true, bevel: 0.8 }), { tone: 'mid' });
      out += S(k.extrude(ringOf(b - 5, b), 0, hS, P, { convex: true, bevel: 0.8 }), { tone: 'mid' });
      // 门扇：以 a 端为轴，开 72°
      const leafW = Math.max(20, b - a - 8);
      const hinge = [w.x1 + ux * (a + 4), w.y1 + uy * (a + 4)];
      const ang = Math.atan2(uy, ux) + (Math.PI * 72) / 180;
      const tip = [hinge[0] + Math.cos(ang) * leafW, hinge[1] + Math.sin(ang) * leafW];
      const th = 3.6;
      const pn = [-Math.sin(ang), Math.cos(ang)];
      const leafRing = [
        [hinge[0] + pn[0] * th / 2, hinge[1] + pn[1] * th / 2],
        [tip[0] + pn[0] * th / 2, tip[1] + pn[1] * th / 2],
        [tip[0] - pn[0] * th / 2, tip[1] - pn[1] * th / 2],
        [hinge[0] - pn[0] * th / 2, hinge[1] - pn[1] * th / 2],
      ];
      out += S(k.extrude(leafRing, 0, Math.min(200, CUT), P, { convex: true, bevel: 0.6 }), { tone: 'hi' });
      // 开门弧线（地面）
      const arcPts = [];
      for (let s = 0; s <= 12; s++) {
        const aa = Math.atan2(uy, ux) + (Math.PI * 72 * s) / 12 / 180;
        arcPts.push(iso([hinge[0] + Math.cos(aa) * leafW, hinge[1] + Math.sin(aa) * leafW, 0.6]));
      }
      out += k.lineSvg(k.pathOf(arcPts), { tone: 'faint', dashed: true });
    }
  }
  const mid = [(w.x1 + w.x2) / 2, (w.y1 + w.y2) / 2];
  add(`wall-${wi}`, 'wall', `墙体 ${Math.round(w.length)} cm`, mid, mid, out);
  // 门窗独立可选中
  w.openings.forEach((o, oi) => {
    const c = [w.x1 + ux * ((o.start + o.end) / 2), w.y1 + uy * ((o.start + o.end) / 2)];
    const kind = o.kind === 'window' ? 'window' : 'door';
    const label = kind === 'window' ? `窗 ${Math.round(o.width)} cm` : (o.type === 'opening' ? `洞口 ${Math.round(o.width)} cm` : `门 ${Math.round(o.width)} cm`);
    add(`${kind}-${wi}-${oi}`, kind, label, c, c, '');
  });
}

/* 家具 */
const MAT = {
  sofa: { tone: 'mid' }, table: { tone: 'mid' }, chair: { tone: 'mid' },
  cabinet: { tone: 'mid' }, tv: { tone: 'hi' }, other: { tone: 'lo' },
};

function furnitureSvg(f) {
  const ring = (dz, dw = 0, dd = 0, dy = 0) => ringRect(f.x, f.y + dy, f.w - dw, f.d - dd, f.rot);
  const out = [];
  const foot = 6;
  switch (f.kind) {
    case 'sofa': {
      out.push(S(k.extrude(ringRect(f.x, f.y + 6, f.w - 8, f.d - 16, f.rot), foot, 32, P, { convex: true, bevel: 2 }), MAT.sofa));
      out.push(S(k.extrude(ringRect(f.x, f.y - f.d / 2 + 10, f.w - 16, 16, f.rot), foot, 78, P, { convex: true, bevel: 2 }), { tone: 'mid' }));
      for (const sx of [-1, 1])
        out.push(S(k.extrude(ringRect(f.x + sx * (f.w / 2 - 9), f.y + 2, 18, f.d - 30, f.rot), foot, 54, P, { convex: true, bevel: 2 }), { tone: 'mid' }));
      for (const sx of [-1, 1])
        out.push(S(k.extrude(ringRect(f.x + sx * f.w / 4.3, f.y + 6, f.w / 2 - 22, f.d - 34, f.rot), 32, 8, P, { convex: true, bevel: 3 }), { tone: 'hi' }));
      // 靠垫两块（斜靠）
      for (const sx of [-1, 1]) {
        const c = ringRect(f.x + sx * f.w / 3.4, f.y - f.d / 2 + 18, f.w / 3.6, 12, f.rot);
        out.push(S(k.extrude(c, 40, 34, P, { convex: true, bevel: 3 }), { tone: 'lo' }));
      }
      break;
    }
    case 'table': {
      out.push(S(k.extrude(ring(0, 6, 6), Math.min(72, f.h * 100 - 4), 5, P, { convex: true, bevel: 1.2 }), { tone: 'mid' }));
      for (const sx of [-1, 1]) for (const sy of [-1, 1]) {
        const cx = f.x + sx * (f.w / 2 - 10), cy = f.y + sy * (f.d / 2 - 10);
        out.push(S(k.cylinder(cx, cy, 3, 0, Math.min(72, f.h * 100 - 4), P, 18), { tone: 'lo', crease: 'none' }));
        out.push(k.dotsSvg([iso([cx, cy, 74])], { size: 0.7, tone: 'lo' }));
      }
      break;
    }
    case 'chair': {
      const seatH = 44;
      out.push(S(k.extrude(ringRect(f.x, f.y, f.w - 4, f.d - 4, f.rot), seatH, 5, P, { convex: true, bevel: 1.5 }), { tone: 'mid' }));
      out.push(S(k.extrude(ringRect(f.x, f.y - f.d / 2 + 4, f.w - 8, 6, f.rot), seatH + 5, Math.min(40, f.h * 100 - seatH), P, { convex: true, bevel: 1 }), { tone: 'mid' }));
      for (const sx of [-1, 1]) for (const sy of [-1, 1]) {
        out.push(S(k.cylinder(f.x + sx * (f.w / 2 - 6), f.y + sy * (f.d / 2 - 6), 2.2, 0, seatH, P, 12), { tone: 'lo', crease: 'none' }));
      }
      break;
    }
    case 'cabinet': {
      const h = Math.min(f.h * 100, 110);
      out.push(S(k.extrude(ring(0, 4, 4), 0, h, P, { convex: true, bevel: 1.2 }), { tone: 'mid' }));
      const front = ringRect(f.x, f.y + f.d / 2 - 5, f.w - 12, 2, f.rot);
      out.push(k.lineSvg(k.pathOf(front.map(([x, y]) => iso([x, y, h * 0.55]))), { tone: 'lo' }));
      out.push(k.dotsSvg([iso([f.x - f.w / 4, f.y + f.d / 2 - 4, h * 0.55]), iso([f.x + f.w / 4, f.y + f.d / 2 - 4, h * 0.55])], { size: 1, tone: 'hi' }));
      break;
    }
    case 'tv': {
      const h = Math.min(f.h * 100, 130);
      out.push(S(k.extrude(ringRect(f.x, f.y, f.w - 8, 5, f.rot), 18, h - 18, P, { convex: true, bevel: 0.8 }), { tone: 'hi' }));
      out.push(S(k.extrude(ringRect(f.x, f.y + 8, 40, 18, f.rot), 0, 18, P, { convex: true, bevel: 1 }), { tone: 'lo' }));
      break;
    }
    default: {
      out.push(S(k.extrude(ring(0, 4, 4), 0, Math.min(f.h * 100, 110), P, { convex: true, bevel: 1 }), MAT.other));
    }
  }
  return out.join('');
}

/* 组装 */
let body = '';
body += basePlate();
for (let wi = 0; wi < walls.length; wi++) wallPiece(walls[wi], wi);
for (const f of furn) {
  const svg = furnitureSvg(f);
  if (!svg) continue;
  add(`furn-${f.idx}`, f.kind, `${f.label}${f.name ? ' · ' + f.name : ''}`, [f.x, f.y], [f.x, f.y], svg);
}
for (const l of labels) {
  const p = iso([l.x, l.y, 6]);
  add(`label-${l.label}`, 'zone', `区域 · ${l.label}`, [l.x, l.y], [l.x, l.y],
    `<g class="zone-label" data-zone-room="${l.label}"><circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="3"/><text class="zone-text" x="${(p[0] + 8).toFixed(1)}" y="${(p[1] + 4).toFixed(1)}">${l.label}</text></g>`);
}
pieces.sort((a, b) => a.depth - b.depth);
for (const p of pieces) {
  body += `<g class="piece" data-id="${p.id}" data-kind="${p.kind}" data-label="${escape(p.label)}" data-cx="${p.center[0].toFixed(1)}" data-cy="${p.center[1].toFixed(1)}">${p.svg}</g>`;
}

const SIZE = walls.length ? {
  w: Math.max(...walls.flatMap((w) => [w.x1, w.x2])) - Math.min(...walls.flatMap((w) => [w.x1, w.x2])),
  d: Math.max(...walls.flatMap((w) => [w.y1, w.y2])) - Math.min(...walls.flatMap((w) => [w.y1, w.y2])),
} : { w: 0, d: 0 };

const svg = `<svg class="iso-svg" viewBox="0 0 ${WIDTH} ${HEIGHT}" width="${WIDTH}" height="${HEIGHT}" role="img" aria-label="扫描房间 3D 模型">${body}</svg>`;

const editable = {
  name: NAME,
  rooms: labels.map((l) => l.label),
  size: { w: +(SIZE.w / 100).toFixed(2), d: +(SIZE.d / 100).toFixed(2) },
  walls: walls.map((w) => ({ x1: w.x1 / 100, y1: w.y1 / 100, x2: w.x2 / 100, y2: w.y2 / 100, openings: w.openings.length })),
  furniture: furn.map((f) => ({
    id: f.id, idx: f.idx, kind: f.kind, label: f.label, name: f.name || '',
    x: +(f.x / 100).toFixed(2), y: +(f.y / 100).toFixed(2),
    w: +(f.w / 100).toFixed(2), d: +(f.d / 100).toFixed(2), h: +(f.h / 100).toFixed(2), rot: f.rot,
  })),
};


/* ---------- 缩略 SVG：房间面板里 <img> 直接用（自带样式，不依赖宿主 CSS） ---------- */
const thumbCss = `${k.ISO_CSS}
svg .iso[data-theme="light"]{--anatomy-page:#FDFBF7;--anatomy-card:#FFFDF9;--anatomy-text:#6B6156;--anatomy-strong:#4E463C;--anatomy-muted:#9C9184;
  --anatomy-paper:#FFFDF9;--anatomy-face:#FBF4E9;--anatomy-top:#FFFDF9;
  --anatomy-shade-0:#D9C3A3;--anatomy-shade-1:#E2CEB0;--anatomy-shade-2:#EADCC8;--anatomy-shade-3:#F3E9DC;
  --anatomy-hi:#4E463C;--anatomy-mid:#8A8078;--anatomy-lo:#B9A488;--anatomy-faint:#DDC8AC;--anatomy-lit:#C0713F;
  --anatomy-halo:#B9A488;--anatomy-halo-opacity:.22;--anatomy-dot:#C0713F}
svg .glass{fill:#EAF1EE;fill-opacity:.85;stroke:#D3E1DB;stroke-width:.8}
svg .zone-label circle{fill:#C0713F;opacity:.7}
svg .zone-label text{fill:#C0713F;font-size:13px;font-weight:700}
svg .piece[data-kind="tv"] .iso-fill{fill:#7A7164}
svg .piece[data-kind="tv"] .iso-top{fill:#8A8175}
svg .piece[data-kind="tv"] .iso-shade{fill:#6E6659}
svg .piece[data-kind="cabinet"] .iso-top{fill:#F3E6D2}`;
const thumb = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${WIDTH} ${HEIGHT}" width="${WIDTH}" height="${HEIGHT}"><style>${thumbCss}</style><rect width="${WIDTH}" height="${HEIGHT}" fill="#FBF4E9"/><g class="iso" data-theme="light">${body}</g></svg>`;
fs.writeFileSync(path.join(ROOT, 'app', 'web', 'space', 'scan-room-thumb.svg'), thumb);

const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="generated-by" content="app/prototype/scan-room-editor/build.mjs">
<meta name="generated-src" content="data/3d/rooms/${NAME}.json">
<meta name="generated-at" content="${new Date().toISOString()}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>扫描模型 · ${NAME}</title>
<style>
${k.ISO_CSS}
html,body{margin:0;background:#FDFBF7}
.wrap{display:grid;grid-template-columns:1fr 330px;gap:0;min-height:100vh}
@media(max-width:820px){.wrap{grid-template-columns:1fr}.panel{border-left:0;border-top:1px solid #E9DCC9}}
.left{padding:26px 20px 20px;display:flex;flex-direction:column;gap:10px}
.hd{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.hd .back{font-size:12.5px;color:#C0713F;text-decoration:none;border:1px solid #EADCC8;border-radius:7px;padding:3px 8px}
.hd .back:hover{background:#FBF4E9}
.hd h1{font-size:16px;margin:0;color:#4E463C;font-weight:700}
.hd .m{font-size:12px;color:#9C9184}
.stage{flex:1;min-height:0;background:#FBF4E9;border:1px solid #E2D5C2;border-radius:16px;padding:10px;position:relative;overflow:hidden}
.stage .iso-svg{width:100%;height:auto;display:block}
.chip{position:absolute;pointer-events:none;background:#4E463C;color:#FFFDF9;font-size:12px;padding:4px 9px;border-radius:7px;transform:translate(12px,-28px);opacity:0;transition:opacity .12s;z-index:5;white-space:nowrap}
.chip.on{opacity:1}
.panel{border-left:1px solid #E9DCC9;background:#FFFDF9;padding:20px 18px;overflow:auto}
.panel h2{font-size:13px;margin:0 0 10px;color:#4E463C}
.kv{display:flex;justify-content:space-between;font-size:12.5px;padding:6px 0;border-bottom:1px solid #F3E8D7;color:#6B6156}
.kv b{color:#4E463C}
.list{list-style:none;padding:0;margin:10px 0 0;display:flex;flex-direction:column;gap:4px}
.list li{font-size:12.5px;color:#6B6156;padding:5px 8px;border-radius:7px;cursor:pointer;display:flex;justify-content:space-between;border:1px solid transparent}
.list li:hover{background:#FBF4E9;border-color:#EADCC8}
.list li[data-sel]{background:#FBEADF;border-color:#E2B48C;color:#9E4F20}
.field{display:flex;flex-direction:column;gap:4px;margin-bottom:9px}
.field label{font-size:11.5px;color:#9C9184}
.field input,.field select{font:13px/1.4 -apple-system,"PingFang SC",sans-serif;padding:6px 8px;border:1px solid #E2D5C2;border-radius:8px;background:#FDFBF7;color:#4E463C}
.row{display:flex;gap:8px}.row>*{flex:1}
button{font:13px/1 -apple-system,"PingFang SC",sans-serif;padding:9px 10px;border-radius:9px;border:1px solid #E2D5C2;background:#FBF4E9;color:#6B6156;cursor:pointer}
button.primary{background:#C0713F;border-color:#B4643A;color:#FFFDF9;font-weight:600}
button.danger{color:#B4453C;border-color:#E7C8C2}
.hint{font-size:11.5px;color:#9C9184;margin-top:12px;line-height:1.6}
.saved{font-size:12px;color:#3E7A4E;margin-top:8px;min-height:18px}
.iso[data-theme="light"]{--anatomy-page:#FDFBF7;--anatomy-card:#FFFDF9;--anatomy-text:#6B6156;--anatomy-strong:#4E463C;--anatomy-muted:#9C9184;
  --anatomy-paper:#FFFDF9;--anatomy-face:#FBF4E9;--anatomy-top:#FFFDF9;
  --anatomy-shade-0:#D9C3A3;--anatomy-shade-1:#E2CEB0;--anatomy-shade-2:#EADCC8;--anatomy-shade-3:#F3E9DC;
  --anatomy-hi:#4E463C;--anatomy-mid:#8A8078;--anatomy-lo:#B9A488;--anatomy-faint:#DDC8AC;--anatomy-lit:#C0713F;
  --anatomy-halo:#B9A488;--anatomy-halo-opacity:.22;--anatomy-dot:#C0713F}
.piece{cursor:pointer}
.piece .iso-edge{transition:stroke .12s,stroke-width .12s}
.piece[data-hover] .iso-edge{stroke:#C0713F;stroke-width:1.7}
.piece[data-selected] .iso-edge{stroke:#B4453C;stroke-width:2.1}
.piece[data-selected] .iso-top{fill:#FFF3E2}
.piece[data-kind="tv"] .iso-fill{fill:#7A7164}
.piece[data-kind="tv"] .iso-top{fill:#8A8175}
.piece[data-kind="tv"] .iso-shade{fill:#6E6659}
.piece[data-kind="cabinet"] .iso-top{fill:#F3E6D2}
.zone-label circle{fill:#C0713F;opacity:.7}
.zone-label text{fill:#C0713F;font-size:13px;font-weight:700}
.glass{fill:#EAF1EE;fill-opacity:.85;stroke:#D3E1DB;stroke-width:.8}
body.embed .panel{display:none}
body.embed .wrap{grid-template-columns:1fr}
body.embed .hd .back,body.embed .hd .m,body.embed .hint{display:none}
body.embed .left{padding:10px}
body.embed .stage{border-radius:10px;border-color:#EADCC8}
.dim text{fill:#9C9184;font-family:var(--anatomy-mono);font-size:11px}
</style></head><body class="iso" data-theme="light">
<div class="wrap"><div class="left">
  <div class="hd"><a class="back" href="/">← 工作台</a><a class="back" href="/space/house.html">全屋视图</a><h1>扫描模型 · 客餐厅</h1><span class="m">真实尺寸 ${(SIZE.w / 100).toFixed(2)} m × ${(SIZE.d / 100).toFixed(2)} m · 墙高 ${(model.wall_height).toFixed(2)} m · 悬停看轮廓 / 点击可编辑</span></div>
  <div class="stage" id="stage"><div class="chip" id="chip"></div>${svg}</div>
  <div class="hint">数据来源：iPhone RoomPlan 扫描（OpenPlan3D 导出）。剖切高度 ${CUT} cm；尺寸单位 cm（面板里可改）。</div>
</div>
<div class="panel" id="panel"></div></div>
<script>
const MODEL = ${JSON.stringify(editable)};
const $ = (s) => document.querySelector(s);
const stage = $('#stage'), chip = $('#chip'), panel = $('#panel');
const svg = stage.querySelector('svg');
let sel = null, hover = null;

const KIND_OPTIONS = [['sofa','沙发'],['table','桌子'],['chair','椅子'],['cabinet','柜子'],['tv','电视'],['door','门'],['window','窗'],['wall','墙'],['zone','区域'],['other','其他']];
const kindName = (k) => (KIND_OPTIONS.find(([v]) => v === k) || [k, k])[1];

function select(id, pieceEl) {
  svg.querySelectorAll('.piece[data-selected]').forEach((el) => el.removeAttribute('data-selected'));
  sel = id || null;
  if (id && pieceEl) pieceEl.setAttribute('data-selected', '');
  renderPanel();
}
function renderPanel() {
  if (!sel) {
    panel.innerHTML = '<h2>房间</h2>' +
      '<div class="kv"><span>外轮廓</span><b>' + MODEL.size.w + ' × ' + MODEL.size.d + ' m</b></div>' +
      '<div class="kv"><span>墙</span><b>' + MODEL.walls.length + ' 面</b></div>' +
      '<div class="kv"><span>家具</span><b>' + MODEL.furniture.length + ' 件</b></div>' +
      '<h2 style="margin-top:18px">构件清单</h2><ul class="list" id="plist">' +
      [...svg.querySelectorAll('.piece')].map((el) =>
        '<li data-pid="' + el.dataset.id + '"><span>' + el.dataset.label + '</span><span style="color:#B9A488">' + el.dataset.kind + '</span></li>').join('') +
      '</ul><div class="hint">点模型上的构件，或点这里选。</div>';
    panel.querySelectorAll('#plist li').forEach((li) => li.onclick = () => {
      const el = svg.querySelector('.piece[data-id="' + CSS.escape(li.dataset.pid) + '"]');
      if (el) select(el.dataset.id, el);
    });
    return;
  }
  const fidx = sel.startsWith('furn-') ? Number(sel.slice(5)) : -1;
  const f = MODEL.furniture.find((x) => x.idx === fidx);
  const isFurn = !!f;
  const pieceEl = svg.querySelector('.piece[data-id="' + CSS.escape(sel) + '"]');
  const kind = pieceEl ? pieceEl.dataset.kind : 'other';
  const label = pieceEl ? pieceEl.dataset.label : '';
  let html = '<h2>编辑构件</h2>';
  html += '<div class="kv"><span>ID</span><b style="font-size:11px">' + sel + '</b></div>';
  html += field('语义类型', '<select id="f-kind">' + KIND_OPTIONS.map(([v, n]) => '<option value="' + v + '"' + (v === kind ? ' selected' : '') + '>' + n + '</option>').join('') + '</select>');
  html += field('名称', '<input id="f-name" value="' + escapeAttr(f ? (f.name || '') : label) + '" placeholder="例如：电视 / 沙发 / 主灯规则">');
  if (isFurn) {
    html += '<div class="row">' + field('宽 w (cm)', '<input id="f-w" type="number" value="' + Math.round(f.w * 100) + '">') + field('深 d (cm)', '<input id="f-d" type="number" value="' + Math.round(f.d * 100) + '">') + '</div>';
    html += '<div class="row">' + field('高 h (cm)', '<input id="f-h" type="number" value="' + Math.round(f.h * 100) + '">') + field('旋转', '<input id="f-rot" type="number" value="' + Math.round(f.rot) + '">') + '</div>';
    html += '<div class="row">' + field('x (cm)', '<input id="f-x" type="number" value="' + Math.round(f.x * 100) + '">') + field('y (cm)', '<input id="f-y" type="number" value="' + Math.round(f.y * 100) + '">') + '</div>';
  }
  html += '<div class="row" style="margin-top:10px"><button class="primary" id="b-save">保存并重建</button><button id="b-cancel">取消</button></div>';
  if (isFurn) html += '<button class="danger" id="b-del" style="margin-top:8px;width:100%">删除这个构件</button>';
  html += '<div class="saved" id="saved"></div>';
  html += '<div class="hint">改「语义类型 / 名称 / 尺寸 / 位置」后保存：服务端写入 .edited.json 并重建本页（约 1 秒）。</div>';
  panel.innerHTML = html;
  panel.querySelector('#b-cancel').onclick = () => select(null);
  panel.querySelector('#b-save').onclick = () => save(fidx, kind);
  if (isFurn) panel.querySelector('#b-del').onclick = () => {
    MODEL.furniture = MODEL.furniture.filter((x) => x.idx !== fidx);
    save(-1, null, true);
  };
}
function field(label, inner) { return '<div class="field"><label>' + label + '</label>' + inner + '</div>'; }
function escapeAttr(s) { return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;'); }

async function save(fidx, kind, deleted) {
  const out = { name: MODEL.name, furniture: MODEL.furniture.map((x, i) => ({ ...x })) };
  if (!deleted && fidx >= 0) {
    const f = out.furniture.find((x) => x.idx === fidx);
    if (f) {
      f.kind = panel.querySelector('#f-kind').value;
      f.label = kindName(f.kind);
      f.name = panel.querySelector('#f-name').value.trim();
      const num = (id) => Number((panel.querySelector(id) || {}).value || 0);
      f.w = +(num('#f-w') / 100).toFixed(3);
      f.d = +(num('#f-d') / 100).toFixed(3);
      f.h = +(num('#f-h') / 100).toFixed(3);
      f.rot = num('#f-rot');
      f.x = +(num('#f-x') / 100).toFixed(3);
      f.y = +(num('#f-y') / 100).toFixed(3);
    }
  }
  const s = panel.querySelector('#saved');
  if (s) s.textContent = '保存中…';
  try {
    const r = await fetch('/api/3d/edit', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(out) });
    const j = await r.json();
    if (!j.ok) throw new Error(j.error || '保存失败');
    if (s) s.textContent = '已保存并重建，正在刷新…';
    setTimeout(() => location.reload(), 650);
  } catch (e) {
    if (s) s.textContent = '保存失败：' + e.message;
  }
}

svg.addEventListener('mousemove', (e) => {
  const el = e.target.closest && e.target.closest('.piece');
  if (!el) { chip.classList.remove('on'); if (hover) { hover.removeAttribute('data-hover'); hover = null; } return; }
  if (hover !== el) { if (hover) hover.removeAttribute('data-hover'); hover = el; el.setAttribute('data-hover', ''); }
  chip.textContent = el.dataset.label;
  chip.style.left = e.offsetX + 'px';
  chip.style.top = e.offsetY + 'px';
  chip.classList.add('on');
});
svg.addEventListener('mouseleave', () => { chip.classList.remove('on'); if (hover) hover.removeAttribute('data-hover'); hover = null; });
svg.addEventListener('click', (e) => {
  const el = e.target.closest && e.target.closest('.piece');
  if (!el) { select(null); return; }
  select(el.dataset.id, el);
});
renderPanel();
// 接工作台实时数据：区域标签显示 台数/异常
fetch('/api/state').then((r) => r.json()).then((st) => {
  for (const room of (st.rooms || [])) {
    const g = svg.querySelector('.zone-label[data-zone-room="' + room.name + '"]');
    if (!g) continue;
    const t = g.querySelector('.zone-text');
    const bad = room.offline || 0;
    t.textContent = room.name + ' · ' + room.total + ' 台' + (bad ? ' · ' + bad + ' 异常' : '');
    if (bad) t.style.fill = '#B4453C';
  }
}).catch(() => {});
// 深链：?select=furn-0 选中某构件；?hover=furn-0 显示悬停高亮（用于截图/分享）
const q = new URLSearchParams(location.search);
if (q.get('embed') === '1') document.body.classList.add('embed');
const pick = q.get('select') || q.get('hover');
if (pick) {
  const el = svg.querySelector('.piece[data-id="' + CSS.escape(pick) + '"]');
  if (el) {
    if (q.get('hover')) el.setAttribute('data-hover', '');
    else select(el.dataset.id, el);
  }
}
</script></body></html>`;

fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, html);
console.log(`已生成缩略图 app/web/space/scan-room-thumb.svg（${(thumb.length / 1024).toFixed(1)} KB）`);
console.log(`已生成 ${path.relative(ROOT, OUT)}（${(html.length / 1024).toFixed(1)} KB · ${pieces.length} 个可选中构件）`);

function escape(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
