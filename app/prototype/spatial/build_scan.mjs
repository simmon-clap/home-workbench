#!/usr/bin/env node
/* 空间视图生成器（离线生成静态产物，11 v1.2 §13「已声明生成物」）
 *
 * 输入：data/floorplan.json（米家 App 分区图截图 → 规则化矩形，来源可追溯）
 * 输出：app/web/space/index.html
 *
 * 为什么是"生成物"：几何是**离线**从图里算出来的（不该在浏览器里重算），
 * 但页面里嵌一小段脚本在运行时拉 /api/state —— 于是它既不是手写页面，
 * 也不是一张冻结的图：房间的异常状态会跟着真实状态变。
 *
 * 用法：node app/prototype/spatial/build_scan.mjs
 */
import fs from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '../../..');
const SRC = path.join(ROOT, 'data', 'floorplan.json');
const OUT = path.join(ROOT, 'app', 'web', 'space', 'index.html');
const fp = JSON.parse(fs.readFileSync(SRC, 'utf8'));
const rooms = fp.rooms || [];

/* 等距投影：x' = (x - y) * cos30 · y' = (x + y) * sin30 - z */
const COS = Math.cos(Math.PI / 6), SIN = Math.sin(Math.PI / 6), H = 0.10;   // 抬起的墙高
const S = 900;                                                              // 画布尺幅
const proj = (x, y, z = 0) => [ (x - y) * COS * S, (x + y) * SIN * S - z * S ];

const plates = [];
const labels = [];
let minX = 1e9, maxX = -1e9, minY = 1e9, maxY = -1e9;
for (const r of rooms) {
  const [x0, y0, x1, y1] = r.bbox;
  const quad = [proj(x0, y0, H), proj(x1, y0, H), proj(x1, y1, H), proj(x0, y1, H)];
  const base = [proj(x0, y0, 0), proj(x1, y0, 0), proj(x1, y1, 0), proj(x0, y1, 0)];
  for (const p of [...quad, ...base]) { minX = Math.min(minX, p[0]); maxX = Math.max(maxX, p[0]); minY = Math.min(minY, p[1]); maxY = Math.max(maxY, p[1]); }
  const pts = a => a.map(p => p.map(n => n.toFixed(1)).join(',')).join(' ');
  const wallA = [quad[1], quad[2], base[2], base[1]];
  const wallB = [quad[3], quad[2], base[2], base[3]];
  const c = proj((x0 + x1) / 2, (y0 + y1) / 2, H);
  plates.push(`<g class="iso-solid" data-room="${r.name}" data-kind="${r.kind}">
  <polygon class="iso-fill" points="${pts(base)}"/>
  <polygon class="iso-shade" data-shade="1" points="${pts(wallA)}"/>
  <polygon class="iso-shade" data-shade="2" points="${pts(wallB)}"/>
  <polygon class="iso-top" points="${pts(quad)}"/>
  <circle class="iso-dot" cx="${c[0].toFixed(1)}" cy="${c[1].toFixed(1)}" r="7"/>
</g>`);
  labels.push({ name: r.name, x: c[0], cy: c[1], share: r.share ?? 0 });
}

const pad = 60;
const vb = `${(minX - pad).toFixed(0)} ${(minY - pad).toFixed(0)} ${(maxX - minX + pad * 2).toFixed(0)} ${(maxY - minY + pad * 2).toFixed(0)}`;

const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="generated-by" content="app/prototype/spatial/build_scan.mjs">
<meta name="generated-src" content="data/floorplan.json">
<meta name="generated-at" content="${new Date().toISOString()}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>空间视图 · 家庭工作台</title>
<style>
:root{--page:#FDFBF7;--face:#FFFDF9;--top:#F6EFE4;--shade1:#EADCC7;--shade2:#E2D5C2;
      --line:#E2D5C2;--text:#4E463C;--muted:#9C9184;--warm:#C0713F;--alert:#B4453C;--warn:#8A6A1F}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--text);
  font:14px/1.5 -apple-system,"PingFang SC",sans-serif;padding:20px}
h1{font-size:15px;font-weight:600;margin:0 0 4px}p.sub{margin:0 0 16px;color:var(--muted);font-size:12px}
.iso-svg{display:block;width:100%;height:auto}
.iso-top{fill:var(--top);stroke:var(--line);stroke-width:1}
.iso-shade[data-shade="1"]{fill:var(--shade1);stroke:var(--line);stroke-width:1}
.iso-shade[data-shade="2"]{fill:var(--shade2);stroke:var(--line);stroke-width:1}
.iso-fill{fill:var(--face)}
.iso-dot{fill:var(--warm);opacity:.55}
.iso-solid.warn .iso-top{fill:#FCF6EA;stroke:var(--warn);stroke-width:2}
.iso-solid.sec .iso-top{fill:#FDF0EC;stroke:var(--alert);stroke-width:2}
.lb{font-size:12px;fill:var(--muted)}
.lb b{fill:var(--text)}
ul.rooms{list-style:none;padding:0;margin:18px 0 0;display:grid;gap:8px;grid-template-columns:repeat(auto-fill,minmax(180px,1fr))}
ul.rooms li{border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:var(--face)}
ul.rooms li .nm{font-weight:600}ul.rooms li .st{font-size:12px;color:var(--muted)}
ul.rooms li.flag{border-color:var(--alert)}ul.rooms li.flag .st{color:var(--alert)}
.note{margin-top:14px;font-size:12px;color:var(--muted)}
</style></head><body>
<h1>空间视图</h1>
<p class="sub">扫描几何：${rooms.length} 个分区（来源：${fp.source || 'floorplan.json'}）· 抬起高度仅用于区分房间，不是真实结构</p>
<svg class="iso-svg" viewBox="${vb}" xmlns="http://www.w3.org/2000/svg">
${plates.join('\n')}
${labels.map(l => `<text class="lb" x="${l.x.toFixed(0)}" y="${(l.cy - 16).toFixed(0)}" text-anchor="middle"><tspan font-weight="600">${l.name}</tspan></text>`).join('\n')}
</svg>
<ul class="rooms" id="rooms">${labels.map(l => `<li data-room="${l.name}"><div class="nm">${l.name}</div><div class="st">—</div></li>`).join('')}</ul>
<p class="note" id="note">正在读取实时状态…</p>
<script>
/* 运行时只读 /api/state：房间异常整块标色 + 列表同步（页面是生成物，状态是实时的） */
(async () => {
  const note = document.getElementById('note');
  try {
    const st = await (await fetch('/api/state')).json();
    const byRoom = new Map((st.rooms || []).map(r => [r.name, r]));
    let matched = 0;
    for (const li of document.querySelectorAll('#rooms li')) {
      const r = byRoom.get(li.dataset.room);
      const g = document.querySelector('.iso-solid[data-room="' + CSS.escape(li.dataset.room) + '"]');
      if (!r) { li.querySelector('.st').textContent = '未接入设备'; continue; }
      matched++;
      const off = r.offline || 0;
      li.querySelector('.st').textContent = off ? off + ' 台异常 / 共 ' + r.total + ' 台' : r.total + ' 台 · 正常';
      if (off) { li.classList.add('flag'); if (g) g.classList.add('sec'); }
      else if (r.total && g) g.classList.add('warn');
    }
    note.textContent = '实时状态已接入（' + matched + '/' + byRoom.size + ' 个分区匹配到房间）· 数据来自 /api/state';
  } catch (e) {
    note.textContent = '实时状态暂时读不到，上面显示的是扫描几何（不是设备状态）';
  }
})();
</script>
</body></html>
`;

fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, html);
console.log(`已生成 ${path.relative(ROOT, OUT)}（${rooms.length} 个分区，${(html.length / 1024).toFixed(1)} KB）`);
