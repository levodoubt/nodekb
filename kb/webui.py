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
.mbtn{font-size:12px;border:1px solid var(--border);background:#1a2029;color:var(--muted);
  border-radius:5px;padding:2px 10px;cursor:pointer}
.mbtn:hover{border-color:var(--accent);color:var(--fg)}
canvas#graph{position:fixed;top:47px;left:268px;z-index:1;cursor:grab;touch-action:none;
  width:calc(100vw - 268px);height:calc(100vh - 47px)}
.hint{position:fixed;left:278px;bottom:12px;z-index:5;color:var(--muted);font-size:12px}
@media (max-width:900px){
  #leftbar{width:200px}
  canvas#graph{left:200px;width:calc(100vw - 200px)}
  .hint{left:210px}
}
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
      <label>横向间距 <input id="sl-hgap" type="range" min="40" max="300" value="100"><span id="hgap-val">100%</span></label>
      <label>纵向间距 <input id="sl-vgap" type="range" min="40" max="300" value="100"><span id="vgap-val">100%</span></label>
      <label>线明度 <input id="sl-edge" type="range" min="0" max="300" value="100"><span id="edge-val">100%</span></label>
      <label style="gap:6px">
        <button id="btn-fit" class="mbtn">重新适配</button>
        <button id="btn-fitall" class="mbtn">全部适配</button>
      </label>
    </div>
  </div>
</aside>
<canvas id="graph"></canvas>
<div class="hint">滚轮缩放 · 拖空白平移 · 点击节点/树项查看详情 · 点节点右侧 ＋N 展开/折叠 · Esc 关闭</div>
<aside id="panel"></aside>
<script>
'use strict';
const $ = s => document.querySelector(s);
let KB = '', GRAPH = null, byId = new Map(), TYPES = new Set(), COUNTS = {};
let HIDDEN = new Set(), SEL = null, HOVER = null;
const SETTINGS = {hgap: 1, vgap: 1, edge: 1};              /* 视图调节：横向/纵向间距、线明度倍数 */
const VW = () => cv.clientWidth || Math.max(180, window.innerWidth - 268);
const VH = () => cv.clientHeight || Math.max(180, window.innerHeight - 47);

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
    const w = Math.max(24, Math.ceil(ctx.measureText(label).width) + 16 + (n._nkids ? 26 : 0));
    n._box = {w, h: 26};
  }
  return n._box;
}
function resize(){
  const dpr = window.devicePixelRatio || 1;
  /* 显式写 px 尺寸：canvas 是替换元素，仅靠 top/right/bottom 会退回属性尺寸（曾导致高度只有 298px） */
  const lb = document.querySelector('#leftbar');
  const left = lb ? Math.round(lb.getBoundingClientRect().width) : 268;
  const top = 47;
  const w = Math.max(180, window.innerWidth - left);
  const h = Math.max(180, window.innerHeight - top);
  cv.style.left = left + 'px';
  cv.style.top = top + 'px';
  cv.style.width = w + 'px';
  cv.style.height = h + 'px';
  cv.width = Math.round(w * dpr);
  cv.height = Math.round(h * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const hint = document.querySelector('.hint');
  if (hint){ hint.style.left = (left + 10) + 'px'; hint.style.bottom = '12px'; }
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
  /* 边：父→子 为曲线（左出右入）；ref 引用线仅悬停/选中时显示，避免树形视图被交叉线淹没 */
  const isRefFocus = t => HOVER === t || SEL === t;
  for (const e of GRAPH.edges){
    const a = byId.get(e.s), b = byId.get(e.t);
    if (!a || !b || a.hidden || b.hidden) continue;
    if (e.r === 'p'){
      if (hoverSet && !hoverSet.has(e.s) && !hoverSet.has(e.t)) continue;
      const x1 = a.x + nodeBox(a).w / 2, x2 = b.x - nodeBox(b).w / 2;
      const mx = (x1 + x2) / 2;
      ctx.beginPath();
      ctx.moveTo(sx(x1), sy(a.y));
      ctx.bezierCurveTo(sx(mx), sy(a.y), sx(mx), sy(b.y), sx(x2), sy(b.y));
      ctx.strokeStyle = 'rgba(255,255,255,' + (0.16 * eA).toFixed(3) + ')';
      ctx.lineWidth = 1; ctx.stroke();
    } else if (isRefFocus(e.s) || isRefFocus(e.t)){
      ctx.beginPath(); ctx.moveTo(sx(a.x), sy(a.y)); ctx.lineTo(sx(b.x), sy(b.y));
      ctx.strokeStyle = 'rgba(91,155,255,' + (0.55 * eA).toFixed(3) + ')';
      ctx.setLineDash([4, 3]); ctx.lineWidth = 1; ctx.stroke(); ctx.setLineDash([]);
    }
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
      if (n._nkids){                             /* 折叠徽标：点击展开/收起子节点 */
        ctx.textAlign = 'right';
        ctx.font = Math.max(8, fs - 1) + 'px sans-serif';
        ctx.fillStyle = typeColor(n.type);
        ctx.globalAlpha = 0.95;
        ctx.fillText((n.collapsed ? '＋' : '－') + n._nkids, x + hw - 6, y);
        ctx.globalAlpha = 1;
      }
    }
  }
}

/* 树状布局：父左子右（确定性，同步计算，不依赖动画回调）
   默认只展开前两层（文件夹 + 文件），深层节点折叠为 +N 徽标，点击展开；
   适配时若整棵树大到不可读，则以可读缩放（0.3）左上对齐，而不是缩成一小团。 */
function buildTreeIndex(){
  const parentOf = new Map(), kidsAll = new Map(), roots = [];
  for (const e of GRAPH.edges) if (e.r === 'p') parentOf.set(e.t, e.s);
  for (const n of GRAPH.nodes){
    const p = parentOf.get(n.tid);
    if (p && p !== n.tid && byId.has(p)){
      if (!kidsAll.has(p)) kidsAll.set(p, []);
      kidsAll.get(p).push(n);
    } else roots.push(n);
  }
  /* 基础深度（全量，用于默认折叠策略） */
  const depthAll = new Map(), guard = new Set();
  const walkAll = (n, d) => {
    if (guard.has(n.tid)) return;
    guard.add(n.tid); depthAll.set(n.tid, d);
    for (const c of kidsAll.get(n.tid) || []) walkAll(c, d + 1);
  };
  roots.forEach(r => walkAll(r, 0));
  GRAPH.nodes.forEach(n => { if (!guard.has(n.tid)) walkAll(n, 0); });
  for (const n of GRAPH.nodes){
    /* 初始全部折叠（只显示顶层），避免 500+ 节点一次性纵向铺开上万像素 */
    if (n.collapsed === undefined) n.collapsed = (kidsAll.get(n.tid) || []).length > 0;
    n._nkids = (kidsAll.get(n.tid) || []).length;
  }
  return {parentOf, kidsAll, roots, depthAll};
}

function layoutTree(){
  if (!GRAPH || !GRAPH.nodes.length) return;
  const {parentOf, kidsAll, roots} = buildTreeIndex();

  /* 可见集合：类型过滤优先，折叠节点的子树不展开 */
  const visible = new Set();
  const visit = n => {
    if (HIDDEN.has(n.type)) return;
    visible.add(n.tid);
    if (n.collapsed) return;
    for (const c of kidsAll.get(n.tid) || []) visit(c);
  };
  roots.forEach(visit);

  /* 只兜底「从根不可达」的节点（环/孤立）；被折叠的子节点本身可达，不能再加回来 */
  const reach = new Set();
  const mark = n => {
    if (reach.has(n.tid)) return;
    reach.add(n.tid);
    for (const c of kidsAll.get(n.tid) || []) mark(c);
  };
  roots.forEach(mark);
  const visitOrphan = n => {
    if (visible.has(n.tid) || HIDDEN.has(n.type)) return;
    visible.add(n.tid);
    if (!n.collapsed) for (const c of kidsAll.get(n.tid) || []) visitOrphan(c);
  };
  GRAPH.nodes.forEach(n => { if (!reach.has(n.tid)) visitOrphan(n); });
  for (const n of GRAPH.nodes) n.hidden = !visible.has(n.tid);

  const vis = GRAPH.nodes.filter(n => visible.has(n.tid));
  /* 有效父：最近可见祖先（父被折叠/过滤时上溯） */
  const kids = new Map(), tops = [];
  for (const n of vis){
    let p = parentOf.get(n.tid);
    const gp = new Set();
    while (p && !visible.has(p) && !gp.has(p)){ gp.add(p); p = parentOf.get(p); }
    if (p && p !== n.tid && visible.has(p)){
      if (!kids.has(p)) kids.set(p, []);
      kids.get(p).push(n);
    } else tops.push(n);
  }

  const order = new Map(GRAPH.nodes.map((n, i) => [n.tid, i]));
  const sortKids = arr => arr.sort((a, b) => (order.get(a.tid) || 0) - (order.get(b.tid) || 0));
  const depth = new Map(), seen = new Set();
  const walk = (n, d) => {
    if (seen.has(n.tid)) return;
    seen.add(n.tid); depth.set(n.tid, d);
    for (const c of sortKids(kids.get(n.tid) || [])) walk(c, d + 1);
  };
  tops.forEach(r => walk(r, 0));
  vis.forEach(n => { if (!seen.has(n.tid)) walk(n, 0); });

  const maxDepth = Math.max(0, ...Array.from(depth.values()));
  const colW = new Array(maxDepth + 1).fill(0);
  for (const n of vis){
    const d = depth.get(n.tid) || 0;
    colW[d] = Math.max(colW[d], nodeBox(n).w);
  }
  const HGAP = 70 * SETTINGS.hgap;
  const colX = []; let acc = 0;
  for (let d = 0; d <= maxDepth; d++){
    colX[d] = acc + colW[d] / 2;
    acc += colW[d] + HGAP;
  }

  const ROW = 26 + 16 * SETTINGS.vgap;
  let slot = 0;
  const placed = new Set();
  const assignY = n => {
    if (placed.has(n.tid)) return n.y;
    placed.add(n.tid);
    const ks = (kids.get(n.tid) || []).filter(c => !placed.has(c.tid));
    let y;
    if (!ks.length){ y = slot * ROW; slot++; }
    else {
      const ys = ks.map(assignY);
      y = (Math.min(...ys) + Math.max(...ys)) / 2;
    }
    n.y = y;
    return y;
  };
  tops.forEach(assignY);
  vis.forEach(n => { if (!placed.has(n.tid)) assignY(n); });

  for (const n of vis) n.x = colX[depth.get(n.tid) || 0];
  fitView();
}

function fitView(readable = true){
  if (!GRAPH) return;
  const ns = GRAPH.nodes.filter(n => !n.hidden && n.x != null);
  if (!ns.length) return;
  let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
  for (const n of ns){
    const b = nodeBox(n), hw = b.w / 2, hh = b.h / 2;
    minX = Math.min(minX, n.x - hw); maxX = Math.max(maxX, n.x + hw);
    minY = Math.min(minY, n.y - hh); maxY = Math.max(maxY, n.y + hh);
  }
  const W = VW(), H = VH(), pad = 28;
  const bw = Math.max(1, maxX - minX), bh = Math.max(1, maxY - minY);
  const sBoth = Math.min((W - pad * 2) / bw, (H - pad * 2) / bh);
  if (!readable || sBoth >= 0.3){
    VIEW.s = Math.max(0.03, Math.min(sBoth, 1.25));   /* 全部适配：保证全貌可见 */
    VIEW.x = W / 2 - (minX + maxX) / 2 * VIEW.s;
    VIEW.y = H / 2 - (minY + maxY) / 2 * VIEW.s;
  } else {
    /* 可读优先：0.3 左上对齐，用平移/折叠浏览 */
    VIEW.s = 0.3;
    VIEW.x = pad - minX * VIEW.s;
    VIEW.y = pad - minY * VIEW.s;
  }
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
  if (n && n._nkids){                            /* 点右侧徽标 → 折叠/展开 */
    const right = (n.x + nodeBox(n).w / 2) * VIEW.s + VIEW.x;
    if (p.x > right - 28){
      n.collapsed = !n.collapsed;
      n._box = null;                             /* 徽标宽度变化，重算框宽 */
      layoutTree();
      return;
    }
  }
  drag = {px: p.x, py: p.y, ox: VIEW.x, oy: VIEW.y, tid: n ? n.tid : null, moved: false};
});
cv.addEventListener('pointermove', e => {
  const p = pos(e);
  if (drag){
    const dx = p.x - drag.px, dy = p.y - drag.py;
    if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
    VIEW.x = drag.ox + dx;
    VIEW.y = drag.oy + dy;
    draw();
    return;
  }
  const n = nodeAt(p.x, p.y);
  HOVER = n ? n.tid : null;
  cv.style.cursor = n ? 'pointer' : 'grab';
  draw();
});
cv.addEventListener('pointerup', () => {
  const was = drag;
  drag = null;
  if (was && !was.moved && was.tid) openNode(was.tid);
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
  layoutTree();
}

/* ---------------- 视图调节滑杆 ---------------- */
function wireControls(){
  const wire = (id, key, valId) => {
    $('#' + id).addEventListener('input', e => {
      SETTINGS[key] = e.target.value / 100;
      $('#' + valId).textContent = e.target.value + '%';
      if (key === 'edge') draw(); else layoutTree();
    });
  };
  wire('sl-hgap', 'hgap', 'hgap-val');
  wire('sl-vgap', 'vgap', 'vgap-val');
  wire('sl-edge', 'edge', 'edge-val');
  $('#btn-fit').addEventListener('click', () => fitView(true));
  $('#btn-fitall').addEventListener('click', () => fitView(false));
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
  const host = $('#tree');
  host.innerHTML = '<div class="empty">加载中…</div>';
  const d = await api('/api/tree', {kb: KB});
  host.innerHTML = '';                       /* 切库时必须清空，否则旧树残留、追加成重复项 */
  renderTree(d.tree, host);
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
