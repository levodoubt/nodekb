"""kb.webui —— 纯只读本地 WebUI（人类可读界面，零第三方依赖）。

md 即库：只读；改文档 = 直接改 `.nodekb` 下的 md，本界面无任何编辑入口。
只读 HTTP 接口（JSON）：
  /api/list                    注册库列表（仅保留存在 .nodekb 的条目）
  /api/graph?kb=               星图数据：节点（name/type/kind/字符数）+ 边（parent 层级 / ref 转译引用）
  /api/tree?kb=                全库导航树（递归 JSON）
  /api/toc?kb=&tid=            目录视图行（render.toc_lines，tid 可省略=root）
  /api/read?kb=&tid=&node=1    渲染阅读视图（[[TID]] 已展开；node=1 仅单节点）
  /api/raw?kb=&tid=            节点元信息（含 source 行号）
  /api/search?kb=&q=&type=&limit=&offset=  全文检索（中文 2-gram）
页面：单 HTML 内联 CSS/JS（暗色星图 + 力导向布局，零 CDN），可离线使用。

运行：python -m kb webui [--host 127.0.0.1] [--port 8666]  （或 python -m kb.webui）
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from . import commands, parse, render


# ------------------------------------------------------------------ HTML 页面

HTML_PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NodeKB · 星图</title>
<style>
:root{
  --bg:#0f1115; --panel:#161a22; --border:#262c38; --fg:#d7dde6;
  --muted:#7b8494; --accent:#5b9bff;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;height:100%;overflow:hidden}
body{background:var(--bg);color:var(--fg);font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
header{position:fixed;top:0;left:0;right:0;z-index:20;display:flex;gap:10px;align-items:center;
  padding:8px 14px;background:rgba(15,17,21,.88);backdrop-filter:blur(6px);
  border-bottom:1px solid var(--border)}
.brand{font-weight:600;white-space:nowrap}
select,input{height:30px;padding:0 8px;border:1px solid var(--border);border-radius:6px;
  background:#1a2029;color:var(--fg);font:inherit;outline:none}
select:focus,input:focus{border-color:var(--accent)}
#search{flex:1;min-width:120px;max-width:380px}
#count{color:var(--muted);font-size:12px;white-space:nowrap}
#filters{display:flex;gap:6px;flex-wrap:wrap;padding:8px 12px;overflow:auto;max-height:40%}
.chip{display:inline-flex;align-items:center;gap:5px;height:24px;padding:0 8px;border-radius:12px;
  border:1px solid var(--border);background:#1a2029;color:var(--muted);font-size:12px;cursor:pointer}
.chip .dot{width:8px;height:8px;border-radius:50%}
.chip b{font-weight:500;opacity:.7}
.chip.on{color:var(--fg);border-width:1px;background:#1d2531}
#leftbar{position:fixed;top:47px;left:0;bottom:0;width:268px;z-index:14;
  background:rgba(15,17,21,.92);border-right:1px solid var(--border);
  display:flex;flex-direction:column;overflow:hidden}
.lsec{display:flex;flex-direction:column;border-bottom:1px solid var(--border)}
.lsec.grow{flex:1;min-height:0}
.lsec-h{font-size:12px;color:var(--muted);padding:6px 12px 2px;letter-spacing:.5px}
#tree{flex:1;overflow:auto;padding:4px 8px 12px;user-select:none}
.trow{display:flex;align-items:center;gap:4px;padding:2px 5px;border-radius:5px;cursor:pointer;font-size:12px}
.trow:hover{background:#1d2531}
.trow.active{background:#1d2531;box-shadow:inset 2px 0 0 var(--accent)}
.tcaret{width:12px;color:var(--muted);flex:none;text-align:center;font-size:10px}
.tlabel{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tchildren{margin-left:10px}
.tchildren.hidden{display:none}
.ctl{padding:4px 12px 10px;display:flex;flex-direction:column;gap:7px}
.ctl label{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--muted)}
.ctl span{width:38px;text-align:right;color:var(--fg);font-variant-numeric:tabular-nums}
.ctl input[type=range]{flex:1;accent-color:var(--accent);height:4px}
canvas#graph{position:fixed;top:0;left:268px;right:0;bottom:0;z-index:1;cursor:grab;touch-action:none}
.hint{position:fixed;left:278px;bottom:12px;z-index:5;color:var(--muted);font-size:12px}
#panel{position:fixed;top:0;right:0;bottom:0;z-index:15;width:min(560px,84vw);
  background:var(--panel);border-left:1px solid var(--border);
  transform:translateX(100%);transition:transform .18s ease;overflow:auto;padding:16px 22px 60px}
#panel.open{transform:none}
.doc h1{font-size:20px;margin:2px 0 10px}
.doc h2{font-size:17px;border-bottom:1px solid var(--border);padding-bottom:4px;margin:20px 0 8px}
.doc h3{font-size:15px;margin:16px 0 6px}
.doc h4{font-size:14px;margin:12px 0 4px}
.doc h5,.doc h6{font-size:13px;margin:10px 0 4px}
.doc pre{background:#10131a;border:1px solid var(--border);border-radius:6px;padding:10px;overflow:auto}
.doc code{font:12px/1.5 Consolas,Menlo,monospace;background:#1b212b;border-radius:3px;padding:1px 4px}
.doc pre code{background:none;padding:0}
.doc blockquote{margin:8px 0;padding:2px 12px;border-left:3px solid #3a4354;color:#9aa4b4}
.doc ul,.doc ol{padding-left:22px;margin:6px 0}
.doc li{margin:2px 0}
.doc hr{border:none;border-top:1px solid var(--border);margin:16px 0}
.doc a{color:var(--accent)}
.doc table{border-collapse:collapse;margin:8px 0;font-size:13px;display:block;max-width:100%;overflow-x:auto}
.doc th,.doc td{border:1px solid var(--border);padding:4px 10px;text-align:left;vertical-align:top}
.doc th{background:#1b212b;font-weight:600}
.doc del{color:var(--muted)}
.doc img{max-width:100%;border-radius:6px;margin:4px 0}
.doc input[type=checkbox]{vertical-align:-2px;margin-right:6px}
.meta{color:var(--muted);font-size:12px;margin-bottom:12px}
.btns{display:inline-flex;gap:6px;margin-left:8px;vertical-align:middle}
.btns button{font-size:12px;border:1px solid var(--border);background:#1a2029;border-radius:5px;
  padding:1px 8px;cursor:pointer;color:var(--muted)}
.btns button:hover{border-color:var(--accent);color:var(--fg)}
#rawjson{white-space:pre-wrap;font:12px/1.6 Consolas,Menlo,monospace;background:#10131a;
  border:1px solid var(--border);border-radius:6px;padding:10px}
.result{border:1px solid var(--border);border-radius:8px;background:#1a2029;
  padding:8px 12px;margin-bottom:8px;cursor:pointer}
.result:hover{border-color:var(--accent)}
.result h3{margin:0 0 4px;font-size:15px}
.result .snippet{color:#9aa4b4;white-space:pre-wrap;font-size:12px}
.empty{color:var(--muted);text-align:center;padding:40px 0}
.badge{font-size:11px;color:var(--muted);background:#1b212b;border-radius:4px;padding:0 6px}
</style>
</head>
<body>
<header>
  <span class="brand">NodeKB</span>
  <select id="lib-select" title="库"></select>
  <input id="search" placeholder="全文检索…（Enter 搜索）">
  <span id="count"></span>
</header>
<aside id="leftbar">
  <div class="lsec">
    <div class="lsec-h">类型筛选</div>
    <div id="filters"></div>
  </div>
  <div class="lsec grow">
    <div class="lsec-h">层级</div>
    <div id="tree"><div class="empty">加载中…</div></div>
  </div>
  <div class="lsec">
    <div class="lsec-h">视图调节</div>
    <div class="ctl">
      <label>排斥力 <input id="sl-rep" type="range" min="30" max="300" value="100"><span id="rep-val">100%</span></label>
      <label>线明度 <input id="sl-edge" type="range" min="0" max="300" value="100"><span id="edge-val">100%</span></label>
    </div>
  </div>
</aside>
<canvas id="graph"></canvas>
<div class="hint">滚轮缩放 · 拖空白平移 · 拖节点调整 · 点击节点/树项查看详情 · Esc 关闭</div>
<aside id="panel"></aside>
<script>
'use strict';
const $ = s => document.querySelector(s);
let KB = '', GRAPH = null, byId = new Map(), TYPES = new Set(), COUNTS = {};
let HIDDEN = new Set(), SEL = null, HOVER = null;
const SETTINGS = {rep: 1, edge: 1};                       /* 视图调节：斥力倍数 / 线明度倍数 */
const VW = () => cv.clientWidth || window.innerWidth;
const VH = () => cv.clientHeight || window.innerHeight;

async function api(path, params){
  const u = new URL(path, location.origin);
  for (const k in params)
    if (params[k] !== undefined && params[k] !== '') u.searchParams.set(k, params[k]);
  const r = await fetch(u);
  const data = await r.json().catch(() => ({error: '响应解析失败'}));
  if (!r.ok || data.error) throw new Error(data.error || ('HTTP ' + r.status));
  return data;
}
function esc(s){
  return String(s).replace(/[&<>"']/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function trunc(s, n){ s = String(s); return s.length > n ? s.slice(0, n) + '…' : s; }

/* ---------------- markdown 渲染（零依赖） ---------------- */
function inline(s){
  s = esc(s);
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
  s = s.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (m, alt, u) =>
    /^https?:\/\//i.test(u) ? '<img src="' + u + '" alt="' + alt + '" loading="lazy">' : m);
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (m, t, u) =>
    /^https?:\/\//i.test(u) ? '<a href="' + u + '" target="_blank" rel="noopener">' + t + '</a>' : t);
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/~~([^~]+)~~/g, '<del>$1</del>');
  s = s.replace(/\*([^*\s][^*]*?)\*/g, '<em>$1</em>');
  s = s.replace(/(^|\s)(https?:\/\/[^\s<]+)/g,
    '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
  return s;
}
function listHtml(items){
  const roots = [], stack = [];
  for (const it of items){
    while (stack.length && stack[stack.length - 1].it.depth >= it.depth) stack.pop();
    const node = {it, children: []};
    if (!stack.length) roots.push(node); else stack[stack.length - 1].children.push(node);
    stack.push(node);
  }
  return renderList(roots);
}
function renderList(nodes){
  let h = '';
  for (const n of nodes){
    const tm = n.it.text.match(/^\[([ xX])\]\s*(.*)$/);
    const body = tm
      ? '<input type="checkbox" disabled' + (tm[1] !== ' ' ? ' checked' : '') + '> ' + inline(tm[2])
      : inline(n.it.text);
    h += '<li>' + body + (n.children.length ? renderList(n.children) : '') + '</li>';
  }
  const tag = nodes[0].it.ol ? 'ol' : 'ul';
  return '<' + tag + '>' + h + '</' + tag + '>';
}
function isItemLine(l){ return /^(\s*)([-*+]|\d+[.)])\s+/.test(l); }
function indentOf(s){ return s.replace(/\t/g, '    ').length; }
function splitRow(l){
  l = l.trim();
  if (l.charAt(0) === '|') l = l.slice(1);
  if (l.charAt(l.length - 1) === '|') l = l.slice(0, -1);
  return l.split('|').map(c => c.trim());
}
function mdToHtml(md){
  const lines = String(md || '').split('\n');
  const out = [];
  let i = 0;
  while (i < lines.length){
    const line = lines[i], t = line.trim();
    if (!t){ i++; continue; }
    if (t.startsWith('```')){                    /* 代码块 */
      const buf = []; i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')){ buf.push(lines[i]); i++; }
      i++;
      out.push('<pre><code>' + esc(buf.join('\n')) + '</code></pre>');
      continue;
    }
    const h = t.match(/^(#{1,6})\s+(.*)$/);       /* 标题 */
    if (h){
      out.push('<h' + h[1].length + '>' + inline(h[2]) + '</h' + h[1].length + '>');
      i++; continue;
    }
    if (/^(-{3,}|\*{3,})\s*$/.test(t)){ out.push('<hr>'); i++; continue; }  /* 分隔线 */
    if (t.includes('|') && i + 1 < lines.length &&                       /* 表格 */
        /^\|?[\s:-]+\|[\s:|:-]*\|?$/.test(lines[i + 1].trim())){
      const rows = [];
      while (i < lines.length && lines[i].trim() !== '' && lines[i].includes('|')){
        rows.push(splitRow(lines[i])); i++;
      }
      const head = rows[0], body = rows.slice(2);
      out.push('<table><thead><tr>' + head.map(c => '<th>' + inline(c) + '</th>').join('') +
               '</tr></thead><tbody>' +
               body.map(r => '<tr>' + r.map(c => '<td>' + inline(c) + '</td>').join('') + '</tr>').join('') +
               '</tbody></table>');
      continue;
    }
    if (/^>\s?/.test(line)){                     /* 引用（内部递归渲染） */
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])){ buf.push(lines[i].replace(/^>\s?/, '')); i++; }
      out.push('<blockquote>' + mdToHtml(buf.join('\n')) + '</blockquote>');
      continue;
    }
    if (isItemLine(line)){                       /* 列表（嵌套 + 续行 + 任务清单） */
      const items = [];
      let rootIndent = -1;
      while (i < lines.length){
        const l = lines[i];
        if (!l.trim() || !isItemLine(l)) break;
        const m = l.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/);
        const ind = indentOf(m[1]);
        if (rootIndent < 0) rootIndent = ind;
        if (ind < rootIndent) break;
        items.push({depth: Math.floor((ind - rootIndent) / 2), ol: /^\d/.test(m[2]), text: m[3]});
        i++;
        while (i < lines.length){                /* 续行：缩进且非列表行的内容并入上一条 */
          const c = lines[i];
          if (!c.trim() || isItemLine(c) || !/^\s/.test(c)) break;
          items[items.length - 1].text += ' ' + c.trim();
          i++;
        }
      }
      out.push(listHtml(items));
      continue;
    }
    const para = [];                             /* 段落 */
    while (i < lines.length && lines[i].trim() &&
           !/^(#{1,6}\s|```|>)/.test(lines[i]) && !isItemLine(lines[i]) &&
           !/^(-{3,}|\*{3,})\s*$/.test(lines[i].trim()) &&
           !(lines[i].includes('|') && i + 1 < lines.length &&
             /^\|?[\s:-]+\|[\s:|:-]*\|?$/.test(lines[i + 1].trim()))){
      para.push(lines[i]); i++;
    }
    out.push('<p>' + para.map(inline).join('<br>') + '</p>');
  }
  return out.join('\n');
}

/* ---------------- 星图：力导向布局（零依赖） ---------------- */
const cv = $('#graph'), ctx = cv.getContext('2d');
const VIEW = {x: 0, y: 0, s: 1};
const TYPE_COLOR = {
  doc: '#4e9fff', facts: '#4fc98f', git: '#b98cff', handover: '#ff9f4e',
  index: '#55d4e8', lessons: '#ffd166', todo: '#ff6b6b', root: '#8a8f98',
};
function typeColor(t){
  if (TYPE_COLOR[t]) return TYPE_COLOR[t];
  let h = 0;
  for (const c of String(t)) h = (h * 31 + c.charCodeAt(0)) % 360;
  return 'hsl(' + h + ', 60%, 62%)';
}
function nodeBox(n){  /* 方形文本框：尺寸由 name 文本决定（缓存，上限 50 字符） */
  if (!n._box){
    ctx.font = '12px sans-serif';
    const label = trunc(n.name || n.tid, 50);
    const w = Math.max(24, Math.ceil(ctx.measureText(label).width) + 16);
    n._box = {w, h: 26};
  }
  return n._box;
}
function nodeRadius(n){ return Math.max(nodeBox(n).w, nodeBox(n).h) / 2; }
function resize(){
  const dpr = window.devicePixelRatio || 1;
  const w = VW(), h = VH();
  cv.width = w * dpr; cv.height = h * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
window.addEventListener('resize', () => { resize(); if (GRAPH) fitView(); });

function draw(){
  const W = VW(), H = VH();
  ctx.clearRect(0, 0, W, H);
  const sx = x => x * VIEW.s + VIEW.x, sy = y => y * VIEW.s + VIEW.y;
  const hoverSet = HOVER ? new Set([HOVER]) : null;
  if (HOVER){
    const hn = byId.get(HOVER);
    for (const e of GRAPH.edges)
      if (e.s === HOVER) hoverSet.add(e.t); else if (e.t === HOVER) hoverSet.add(e.s);
  }
  const eA = SETTINGS.edge;                    /* 线明度倍数 */
  /* 边：ref 高亮，parent 弱化；悬停时只画相邻边 */
  for (const e of GRAPH.edges){
    const a = byId.get(e.s), b = byId.get(e.t);
    if (!a || !b || a.hidden || b.hidden) continue;
    if (hoverSet && !hoverSet.has(e.s) && !hoverSet.has(e.t)) continue;
    ctx.beginPath(); ctx.moveTo(sx(a.x), sy(a.y)); ctx.lineTo(sx(b.x), sy(b.y));
    ctx.strokeStyle = e.r === 'p'
      ? 'rgba(255,255,255,' + (0.06 * eA).toFixed(3) + ')'
      : 'rgba(91,155,255,' + (0.26 * eA).toFixed(3) + ')';
    ctx.lineWidth = 1; ctx.stroke();
  }
  /* 节点：方形文本框，深色底 + 类型色描边，名称在框内 */
  for (const n of GRAPH.nodes){
    if (n.hidden) continue;
    const box = nodeBox(n);
    const x = sx(n.x), y = sy(n.y);
    const hw = box.w * VIEW.s / 2, hh = box.h * VIEW.s / 2;
    if (x + hw < 0 || x - hw > W || y + hh < 0 || y - hh > H) continue;
    ctx.globalAlpha = HOVER ? (hoverSet.has(n.tid) ? 1 : 0.25) : 1;
    const rad = Math.min(4, hw, hh);
    ctx.beginPath();
    ctx.moveTo(x - hw + rad, y - hh);
    ctx.arcTo(x + hw, y - hh, x + hw, y + hh, rad);
    ctx.arcTo(x + hw, y + hh, x - hw, y + hh, rad);
    ctx.arcTo(x - hw, y + hh, x - hw, y - hh, rad);
    ctx.arcTo(x - hw, y - hh, x + hw, y - hh, rad);
    ctx.closePath();
    ctx.fillStyle = 'rgba(22,26,34,0.85)';
    ctx.fill();
    ctx.strokeStyle = n.tid === SEL ? '#ffffff' : (HOVER === n.tid ? '#ffd166' : typeColor(n.type));
    ctx.lineWidth = n.tid === SEL ? 2.5 : 1.4;
    ctx.stroke();
    ctx.globalAlpha = 1;
    const fs = 12 * VIEW.s;                      /* 文本字号随缩放同步变化 */
    if (fs >= 6){                                /* 框内显示 name（上限 50 字符） */
      ctx.fillStyle = n.tid === SEL ? '#fff' : '#d7dde6';
      ctx.font = fs + 'px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(trunc(n.name || n.tid, 50), x, y);
    }
  }
}

/* 力导向模拟：网格近似斥力 + 弹簧 + 弱向心，冷却后静止。
   力/速度/坐标全程钳制，防止密集图（500+ 节点）下弹簧力导致坐标发散飞出画布。 */
function runSim(){
  const ns = GRAPH.nodes.filter(n => !n.hidden);
  if (!ns.length){ draw(); return; }
  const byId2 = new Map(ns.map(n => [n.tid, n]));
  for (const n of ns) if (n.x == null){ n.x = (Math.random() - 0.5) * 900; n.y = (Math.random() - 0.5) * 600; }
  const edges = GRAPH.edges.filter(e => byId2.has(e.s) && byId2.has(e.t));
  const CELL = 180, REP = 4200 * SETTINGS.rep, K = 0.9, GRAV = 0.02;
  const SPR_P = 120, SPR_R = 200, FMAX = 90, VMAX = 30, BOUND = 8000;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  let alpha = 1;
  const done = () => { cancelAnimationFrame(runSim._ra); fitView(); };
  function tick(){
    try{
    const grid = new Map();
    for (const n of ns){
      const key = Math.floor(n.x / CELL) + ',' + Math.floor(n.y / CELL);
      if (!grid.has(key)) grid.set(key, []);
      grid.get(key).push(n);
    }
    for (const n of ns){                        /* 斥力 + 盒子碰撞推出 */
      let fx = 0, fy = 0;
      const bx = Math.floor(n.x / CELL), by = Math.floor(n.y / CELL);
      for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++){
        const cells = grid.get((bx + dx) + ',' + (by + dy));
        if (!cells) continue;
        for (const m of cells){
          if (m === n) continue;
          let ddx = n.x - m.x, ddy = n.y - m.y;
          let d2 = ddx * ddx + ddy * ddy;
          if (d2 < 1) d2 = 1;
          if (d2 > CELL * CELL * 2.5) continue;
          const d = Math.sqrt(d2);
          const rsum = nodeRadius(n) + nodeRadius(m);
          const f = d < rsum ? 500 / d : REP / d2;   /* 重叠时强推，否则常规斥力 */
          fx += ddx / d * f; fy += ddy / d * f;
        }
      }
      n.fx = clamp(fx, -FMAX, FMAX); n.fy = clamp(fy, -FMAX, FMAX);
    }
    for (const e of edges){                      /* 弹簧（力同样钳制） */
      const a = byId2.get(e.s), b = byId2.get(e.t);
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.max(1, Math.hypot(dx, dy));
      const target = e.r === 'p' ? SPR_P : SPR_R;
      const f = clamp((d - target) * K, -FMAX, FMAX) * alpha;
      const ux = dx / d, uy = dy / d;
      a.fx += ux * f; a.fy += uy * f;
      b.fx -= ux * f; b.fy -= uy * f;
    }
    for (const n of ns){                         /* 积分 + 弱向心 + 位置界 */
      n.fx = clamp(n.fx - n.x * GRAV, -FMAX, FMAX);
      n.fy = clamp(n.fy - n.y * GRAV, -FMAX, FMAX);
      const vx = n.vx || 0, vy = n.vy || 0;
      n.vx = clamp((vx + n.fx * alpha) * 0.8, -VMAX, VMAX);
      n.vy = clamp((vy + n.fy * alpha) * 0.8, -VMAX, VMAX);
      n.x = clamp(n.x + n.vx, -BOUND, BOUND);
      n.y = clamp(n.y + n.vy, -BOUND, BOUND);
    }
    alpha *= 0.99;
    draw();
    if (alpha > 0.02) requestAnimationFrame(tick);
    else done();
    }catch(err){ done(); }                        /* 异常不中断：至少完成一次 fitView */
  }
  cancelAnimationFrame(runSim._ra);
  runSim._ra = requestAnimationFrame(tick);
}
function fitView(){
  const ns = GRAPH.nodes.filter(n => !n.hidden && n.x != null);
  if (!ns.length) return;
  let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
  for (const n of ns){
    const r = nodeRadius(n);
    if (n.x - r < minX) minX = n.x - r; if (n.x + r > maxX) maxX = n.x + r;
    if (n.y - r < minY) minY = n.y - r; if (n.y + r > maxY) maxY = n.y + r;
  }
  const W = VW(), H = VH(), pad = 60;
  const bw = Math.max(1, maxX - minX), bh = Math.max(1, maxY - minY);
  const s = Math.min((W - pad * 2) / bw, (H - pad * 2) / bh, 1.6);
  VIEW.s = Math.max(0.25, s);
  VIEW.x = W / 2 - (minX + maxX) / 2 * VIEW.s;
  VIEW.y = H / 2 - (minY + maxY) / 2 * VIEW.s;
  draw();
}
function centerView(tid){
  const n = byId.get(tid);
  if (n && n.x != null){
    VIEW.x = VW() / 2 - n.x * VIEW.s;
    VIEW.y = VH() / 2 - n.y * VIEW.s;
    draw();
  }
}
function nodeAt(px, py){
  for (const n of GRAPH.nodes){
    if (n.hidden || n.x == null) continue;
    const box = nodeBox(n);
    const x = n.x * VIEW.s + VIEW.x, y = n.y * VIEW.s + VIEW.y;
    const hw = box.w * VIEW.s / 2 + 2, hh = box.h * VIEW.s / 2 + 2;
    if (Math.abs(px - x) <= hw && Math.abs(py - y) <= hh) return n;
  }
  return null;
}
function pos(e){
  const r = cv.getBoundingClientRect();
  return {x: e.clientX - r.left, y: e.clientY - r.top};
}
let drag = null;
cv.addEventListener('pointerdown', e => {
  cv.setPointerCapture(e.pointerId);
  const p = pos(e), n = nodeAt(p.x, p.y);
  drag = n
    ? {type: 'node', tid: n.tid, px: p.x, py: p.y, nx: n.x, ny: n.y}
    : {type: 'pan', px: p.x, py: p.y, ox: VIEW.x, oy: VIEW.y};
});
cv.addEventListener('pointermove', e => {
  const p = pos(e);
  if (drag){
    if (drag.type === 'node'){
      const n = byId.get(drag.tid);
      n.x = drag.nx + (p.x - drag.px) / VIEW.s;
      n.y = drag.ny + (p.y - drag.py) / VIEW.s;
      draw();
    } else {
      VIEW.x = drag.ox + (p.x - drag.px);
      VIEW.y = drag.oy + (p.y - drag.py);
      draw();
    }
    return;
  }
  const n = nodeAt(p.x, p.y);
  HOVER = n ? n.tid : null;
  cv.style.cursor = n ? 'pointer' : 'grab';
  draw();
});
cv.addEventListener('pointerup', e => {
  const p = pos(e), was = drag;
  drag = null;
  if (was && was.type === 'node'){
    const n = byId.get(was.tid);
    const moved = Math.hypot((p.x - was.px) / VIEW.s, (p.y - was.py) / VIEW.s) > 3;
    if (!moved) openNode(n.tid);
  }
});
cv.addEventListener('wheel', e => {
  e.preventDefault();
  const p = pos(e);
  const ns = VIEW.s * Math.exp(-e.deltaY * 0.0012);
  const k = ns / VIEW.s;
  VIEW.x = p.x - (p.x - VIEW.x) * k;
  VIEW.y = p.y - (p.y - VIEW.y) * k;
  VIEW.s = Math.min(2.5, Math.max(0.2, ns));
  draw();
}, {passive: false});
document.addEventListener('keydown', e => { if (e.key === 'Escape') closePanel(); });

/* ---------------- 类型快捷筛选 ---------------- */
function buildFilters(){
  const types = Array.from(TYPES).sort();
  $('#filters').innerHTML = '';
  for (const t of types){
    const btn = document.createElement('button');
    btn.className = 'chip' + (HIDDEN.has(t) ? '' : ' on');
    btn.style.borderColor = typeColor(t);
    btn.innerHTML = '<span class="dot" style="background:' + typeColor(t) + '"></span>'
      + esc(t) + ' <b>' + COUNTS[t] + '</b>';
    btn.onclick = () => {
      HIDDEN.has(t) ? HIDDEN.delete(t) : HIDDEN.add(t);
      btn.classList.toggle('on');
      applyVis();
    };
    $('#filters').appendChild(btn);
  }
}
function applyVis(){
  for (const n of GRAPH.nodes) n.hidden = HIDDEN.has(n.type);
  if (SEL){ const n = byId.get(SEL); if (n && n.hidden) closePanel(); }
  runSim();
}

/* ---------------- 视图调节滑杆 ---------------- */
function wireControls(){
  $('#sl-rep').addEventListener('input', e => {
    SETTINGS.rep = e.target.value / 100;
    $('#rep-val').textContent = e.target.value + '%';
    runSim();
  });
  $('#sl-edge').addEventListener('input', e => {
    SETTINGS.edge = e.target.value / 100;
    $('#edge-val').textContent = e.target.value + '%';
    draw();
  });
}

/* ---------------- 层级树（左侧定位） ---------------- */
function renderTree(node, parent){
  for (const k of (node.children || [])){
    const isDir = (k.children || []).length > 0;
    const row = document.createElement('div');
    row.className = 'trow';
    const caret = document.createElement('span');
    caret.className = 'tcaret';
    caret.textContent = isDir ? '▸' : '';
    const label = document.createElement('span');
    label.className = 'tlabel';
    label.textContent = k.title || k.tid;
    label.title = k.tid;
    row.append(caret, label);
    const go = () => { treeActive(row); openNode(k.tid); centerView(k.tid); };
    if (isDir){
      const wrap = document.createElement('div');
      wrap.className = 'tchildren hidden';
      let opened = false;
      caret.addEventListener('click', e => {
        e.stopPropagation();
        opened = !opened;
        caret.textContent = opened ? '▾' : '▸';
        wrap.classList.toggle('hidden', !opened);
        if (opened && !wrap.dataset.loaded){ wrap.dataset.loaded = '1'; renderTree(k, wrap); }
      });
      row.addEventListener('click', go);
      parent.append(row, wrap);
    } else {
      row.addEventListener('click', go);
      parent.append(row);
    }
  }
}
function treeActive(row){
  document.querySelectorAll('#tree .trow').forEach(r => r.classList.remove('active'));
  row.classList.add('active');
}
async function loadTree(){
  const d = await api('/api/tree', {kb: KB});
  renderTree(d.tree, $('#tree'));
}

/* ---------------- 详情面板 / 检索 ---------------- */
function openPanel(html){
  $('#panel').innerHTML = html;
  $('#panel').classList.add('open');
}
function closePanel(){
  $('#panel').classList.remove('open');
  SEL = null;
  draw();
}
async function openNode(tid, mode){
  SEL = tid;
  centerView(tid);
  try{
    const data = await api('/api/read', {kb: KB, tid, node: mode === 'node' ? 1 : 0});
    let text = data.text || '', cut = '';
    if (text.length > 40000){ cut = '<div class="meta">… 内容过长，仅显示前 40000 字符</div>'; text = text.slice(0, 40000); }
    openPanel(
      '<div class="doc"><h1>' + esc(data.title || tid) + '</h1>' +
      '<div class="meta"><span class="badge">' + esc(data.type || '') + '</span> ' +
      esc(data.tid) + ' · 来源 ' + esc(data.source || '') +
      '<span class="btns">' +
      '<button onclick="openNode(\'' + data.tid + '\',\'' + (mode === 'node' ? '' : 'node') + '\')">' +
      (mode === 'node' ? '整支' : '仅此节点') + '</button>' +
      '<button onclick="rawNode(\'' + data.tid + '\')">元信息</button>' +
      '<button onclick="closePanel()">✕</button>' +
      '</span></div>' + cut + mdToHtml(text) + '</div>');
  }catch(err){
    openPanel('<div class="empty">' + esc(err.message) + '</div>');
  }
}
async function rawNode(tid){
  try{
    const data = await api('/api/raw', {kb: KB, tid});
    openPanel('<div class="doc"><h1>' + esc(tid) + ' · 元信息</h1>' +
      '<pre id="rawjson">' + esc(JSON.stringify(data, null, 2)) + '</pre></div>');
  }catch(err){
    openPanel('<div class="empty">' + esc(err.message) + '</div>');
  }
}
let searchTimer = null;
$('#search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(doSearch, 250); });
$('#search').addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
async function doSearch(){
  const q = $('#search').value.trim();
  if (!q) return;
  try{
    const data = await api('/api/search', {kb: KB, q, limit: 30});
    if (!data.count){
      openPanel('<div class="empty">无匹配：' + esc(q) + '</div>');
      return;
    }
    openPanel(
      '<h2 style="margin:2px 0 12px">' + data.count + ' 条匹配「' + esc(q) + '」（共 ' + data.total + '）</h2>' +
      data.hits.map(h =>
        '<div class="result" onclick="openNode(\'' + (h.ref || h.tid) + '\')">' +
        '<h3>' + esc(h.title || h.tid) + ' <span class="badge">' + esc(h.type || '') + '</span></h3>' +
        '<div class="snippet">' + esc(h.snippet) + '</div>' +
        '<div class="meta">' + esc(h.tid) + ' · ' + esc(h.source || '') + '</div></div>'
      ).join(''));
  }catch(err){
    openPanel('<div class="empty">' + esc(err.message) + '</div>');
  }
}

/* ---------------- 初始化 ---------------- */
async function loadLib(){
  const g = await api('/api/graph', {kb: KB});
  GRAPH = g;
  byId = new Map(g.nodes.map(n => [n.tid, n]));
  TYPES = new Set(); COUNTS = {};
  for (const n of g.nodes){
    TYPES.add(n.type);
    COUNTS[n.type] = (COUNTS[n.type] || 0) + 1;
  }
  $('#count').textContent = g.nodes.length + ' 节点 · ' + g.edges.length + ' 边';
  HIDDEN = new Set(); SEL = null;
  buildFilters();
  loadTree();
  applyVis();
  setTimeout(() => { if (GRAPH) fitView(); }, 1500);   /* 兜底：模拟未冷却也先适配一次视口 */
}
async function init(){
  const libs = await api('/api/list');
  const names = Object.keys(libs.libraries || {});
  if (!names.length){
    document.body.innerHTML = '<div class="empty" style="padding:80px">暂无已注册库（kb register &lt;名称&gt; &lt;技能目录&gt;）</div>';
    return;
  }
  const sel = $('#lib-select');
  sel.innerHTML = names.map(n => '<option value="' + esc(n) + '">' + esc(n) + '</option>').join('');
  sel.addEventListener('change', () => { KB = sel.value; loadLib(); });
  wireControls();
  KB = names[0];
  resize();
  loadLib();
}
init().catch(e => { document.body.innerHTML = '<div class="empty" style="padding:80px">加载失败：' + esc(e.message) + '</div>'; });
</script>
</body>
</html>
"""


# ------------------------------------------------------------------ 只读接口

def _list_libs() -> dict:
    """注册库列表：仅保留 .nodekb 实际存在的条目。"""
    out = {}
    for name, info in sorted(commands.load_registry().items()):
        nodekb = os.path.join(info.get("path", ""), ".nodekb")
        if os.path.isdir(nodekb):
            out[name] = info["path"]
    return out


def _children(nodes: dict, tid: str) -> list[dict]:
    return sorted(
        (n for n in nodes.values() if n["parent_tid"] == tid),
        key=lambda n: (n["sort"], n["tid"]),
    )


def _tree(nodes: dict, tid: str = "root") -> dict:
    node = nodes[tid]
    return {
        "tid": node["tid"], "title": node["title"] or tid, "type": node["type"],
        "source": node["source"],
        "children": [_tree(nodes, c["tid"]) for c in _children(nodes, tid)],
    }


def _graph(nodes: dict) -> dict:
    """星图数据：节点（不含 root）+ 边。边两类：parent=层级（s=父 t=子）；ref=转译引用（s=引用方 t=被引用方）。"""
    g_nodes = []
    for tid, n in nodes.items():
        if tid == "root":
            continue
        g_nodes.append({"tid": tid, "title": n["title"] or tid, "name": n["title"] or tid,
                        "type": n["type"], "kind": n.get("kind", "node"), "nchar": len(n["content"])})
    edges: list[dict] = []
    seen: set = set()
    for tid, n in nodes.items():
        if tid == "root":
            continue
        p = n["parent_tid"]
        if p and p in nodes and p != "root":
            key = (p, tid, "p")
            if key not in seen:
                seen.add(key)
                edges.append({"s": p, "t": tid, "r": "p"})
        for ref in parse.extract_refs(n["content"]):
            if ref in nodes and ref != tid:
                key = (tid, ref, "r")
                if key not in seen:
                    seen.add(key)
                    edges.append({"s": tid, "t": ref, "r": "r"})
    return {"nodes": g_nodes, "edges": edges}


def _q(params: dict, key: str, default=None) -> Optional[str]:
    vals = params.get(key)
    return vals[0] if vals else default


class _Handler(BaseHTTPRequestHandler):
    server_version = "NodeKBWebUI/0.1"

    def log_message(self, fmt, *args):  # 安静日志：仅记录错误
        code = str(args[0]) if args else ""
        if code.startswith(("4", "5")):
            sys.stderr.write("[webui] " + fmt % args + "\n")

    def _send(self, data: bytes, ctype: str, status: int = 200) -> None:
        self.send_response(status)
        if status != 204:
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if status != 204:
            self.wfile.write(data)

    def _json(self, obj, status: int = 200) -> None:
        self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", status)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        q = parse_qs(parsed.query)
        try:
            if path == "/":
                return self._send(HTML_PAGE.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/favicon.ico":
                return self._send(b"", "image/x-icon", 204)
            if path == "/api/list":
                return self._json({"libraries": _list_libs()})
            if path not in ("/api/graph", "/api/tree", "/api/toc", "/api/read", "/api/raw", "/api/search"):
                return self._json({"error": f"未知路径: {path}"}, 404)
            kb = _q(q, "kb")
            if not kb:
                return self._json({"error": "缺少 kb 参数（库注册名，/api/list 查看）"}, 400)
            nodes = commands.load_library(kb, None)
            if path == "/api/graph":
                return self._json(_graph(nodes))
            if path == "/api/tree":
                return self._json({"tree": _tree(nodes), "total": len(nodes)})
            tid = _q(q, "tid") or "root"
            resolved = render.resolve_path(nodes, tid)
            if resolved is None:
                return self._json({"error": f"未找到节点: {tid}"}, 404)
            if path == "/api/toc":
                return self._json({"tid": resolved, "lines": render.toc_lines(nodes, resolved)})
            if path == "/api/read":
                node_only = _q(q, "node", "0") in ("1", "true", "yes")
                text = render.render_node(nodes, resolved) if node_only \
                    else render.render_subtree(nodes, resolved)
                info = render.node_info(nodes, resolved)
                return self._json({"tid": resolved, "title": info["title"], "type": info["type"],
                                   "source": info["source"], "text": text})
            if path == "/api/raw":
                return self._json(render.node_info(nodes, resolved))
            if path == "/api/search":
                query = _q(q, "q", "")
                if not query.strip():
                    return self._json({"count": 0, "hits": []})
                type_ = _q(q, "type") or None
                limit = min(int(_q(q, "limit", "30") or 30), 200)
                offset = min(int(_q(q, "offset", "0") or 0), 500)
                text, _code = commands.cmd_search(nodes, query, type_=type_, limit=limit,
                                                  as_json=True, offset=offset)
                return self._send(text.encode("utf-8"), "application/json; charset=utf-8")
        except Exception as e:  # 兜底：不崩 server，回 JSON 错误
            return self._json({"error": str(e)}, 500)


def main(host: str = "127.0.0.1", port: int = 8666) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"NodeKB WebUI（只读星图，md 即库无编辑）→ http://{host}:{port}/  Ctrl+C 退出", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
