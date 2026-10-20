"""kb.webui —— 纯只读本地 WebUI（人类可读界面，零第三方依赖）。

md 即库：只读；改文档 = 直接改 `.nodekb` 下的 md，本界面无任何编辑入口。
只读 HTTP 接口（JSON）：
  /api/list                    注册库列表（仅保留存在 .nodekb 的条目）
  /api/tree?kb=                全库导航树（递归 JSON，左栏项目树）
  /api/toc?kb=&tid=            目录视图行（render.toc_lines，tid 可省略=root）
  /api/read?kb=&tid=&node=1    渲染阅读视图（[[TID]] 已展开；node=1 仅单节点）
  /api/raw?kb=&tid=            节点元信息（含 source 行号）
  /api/search?kb=&q=&type=&limit=  全文检索（中文 2-gram）
页面：单 HTML 内联 CSS/JS，零 CDN，可离线使用。

运行：python -m kb webui [--host 127.0.0.1] [--port 8666]  （或 python -m kb.webui）
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from . import commands, render


# ------------------------------------------------------------------ HTML 页面

HTML_PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NodeKB · 知识库</title>
<style>
:root{
  --bg:#fafafa; --panel:#fff; --border:#e6e6e6; --fg:#1f2328;
  --muted:#8a8f98; --accent:#1a73e8; --accent-soft:#e8f0fe; --badge:#f1f3f4;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{background:var(--bg);color:var(--fg);font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
header{position:sticky;top:0;z-index:10;display:flex;gap:10px;align-items:center;
  padding:8px 14px;background:var(--panel);border-bottom:1px solid var(--border)}
header .brand{font-weight:600;white-space:nowrap}
select,input{height:30px;padding:0 8px;border:1px solid var(--border);border-radius:6px;
  background:#fff;font:inherit;color:inherit;outline:none}
select:focus,input:focus{border-color:var(--accent)}
#search{flex:1;min-width:140px;max-width:420px}
#count{color:var(--muted);font-size:12px;white-space:nowrap}
.layout{display:flex;min-height:calc(100vh - 47px)}
aside{width:320px;max-width:36vw;border-right:1px solid var(--border);background:var(--panel);
  overflow:auto;padding:10px;display:flex;flex-direction:column;gap:8px}
#tree{user-select:none;flex:1}
.row{display:flex;align-items:center;gap:4px;padding:2px 6px;border-radius:5px;cursor:pointer}
.row:hover{background:var(--accent-soft)}
.row.active{background:var(--accent-soft);box-shadow:inset 2px 0 0 var(--accent)}
.caret{width:14px;color:var(--muted);flex:none;text-align:center;font-size:10px}
.label{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.badge{flex:none;font-size:10px;color:var(--muted);background:var(--badge);border-radius:4px;padding:0 5px}
.children{margin-left:12px}
.children.hidden{display:none}
main{flex:1;overflow:auto;padding:18px 26px 60px}
.doc{max-width:860px}
.doc h1{font-size:22px;margin:4px 0 12px}
.doc h2{font-size:18px;border-bottom:1px solid var(--border);padding-bottom:4px;margin:22px 0 8px}
.doc h3{font-size:16px;margin:18px 0 6px}
.doc h4{font-size:14px;margin:14px 0 4px}
.doc h5,.doc h6{font-size:13px;margin:12px 0 4px}
.doc pre{background:#f6f8fa;border:1px solid var(--border);border-radius:6px;padding:10px;overflow:auto}
.doc code{font:12px/1.5 Consolas,Menlo,monospace;background:#f1f3f4;border-radius:3px;padding:1px 4px}
.doc pre code{background:none;padding:0}
.doc blockquote{margin:8px 0;padding:2px 12px;border-left:3px solid #d0d7de;color:#57606a}
.doc ul,.doc ol{padding-left:22px;margin:6px 0}
.doc li{margin:2px 0}
.doc li li{margin:0}
.doc hr{border:none;border-top:1px solid var(--border);margin:16px 0}
.doc a{color:var(--accent)}
.meta{color:var(--muted);font-size:12px;margin-bottom:14px}
.btns{display:inline-flex;gap:6px;margin-left:8px}
.btns button{font-size:12px;border:1px solid var(--border);background:#fff;border-radius:5px;
  padding:1px 8px;cursor:pointer;color:inherit}
.btns button:hover{border-color:var(--accent);color:var(--accent)}
#rawjson{white-space:pre-wrap;font:12px/1.6 Consolas,Menlo,monospace;background:#f6f8fa;
  border:1px solid var(--border);border-radius:6px;padding:10px}
.result{border:1px solid var(--border);border-radius:8px;background:var(--panel);
  padding:8px 12px;margin-bottom:8px;cursor:pointer}
.result:hover{border-color:var(--accent)}
.result h3{margin:0 0 4px;font-size:15px}
.result .snippet{color:#57606a}
.empty{color:var(--muted);text-align:center;padding:40px 0}
@media (max-width:760px){
  .layout{flex-direction:column}
  aside{width:100%;max-width:none;border-right:none;border-bottom:1px solid var(--border);max-height:38vh}
}
</style>
</head>
<body>
<header>
  <span class="brand">NodeKB</span>
  <select id="lib-select" title="库"></select>
  <input id="search" placeholder="全文检索…（Enter 搜索）">
  <span id="count"></span>
</header>
<div class="layout">
  <aside>
    <select id="type-filter" title="类型过滤"></select>
    <div id="tree"></div>
  </aside>
  <main id="content"><div class="empty">加载中…</div></main>
</div>
<script>
'use strict';
const $ = s => document.querySelector(s);
let KB = '', CACHE = null, TYPES = new Set();

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

/* ---------------- markdown 渲染 ---------------- */
function inline(s){
  s = esc(s);
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/\*([^*\s][^*]*?)\*/g, '<em>$1</em>');
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (m, t, u) =>
    /^[a-z]+:/i.test(u) ? '<a href="' + u + '" target="_blank" rel="noopener">' + t + '</a>' : t);
  return s;
}
function listHtml(items){
  const roots = [], stack = [];
  for (const it of items){
    while (stack.length && stack[stack.length - 1].depth >= it.depth) stack.pop();
    const node = {it, children: []};
    if (!stack.length) roots.push(node); else stack[stack.length - 1].children.push(node);
    stack.push(node);
  }
  return renderList(roots);
}
function renderList(nodes){
  let h = '';
  for (const n of nodes) h += '<li>' + inline(n.it.text) + (n.children.length ? renderList(n.children) : '') + '</li>';
  const tag = nodes[0].it.ol ? 'ol' : 'ul';
  return '<' + tag + '>' + h + '</' + tag + '>';
}
function mdToHtml(md){
  const lines = String(md || '').split('\n');
  const out = [];
  let i = 0;
  while (i < lines.length){
    const t = lines[i].trim();
    if (!t){ i++; continue; }
    if (t.startsWith('```')){                 /* 代码块 */
      const buf = []; i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')){ buf.push(lines[i]); i++; }
      i++;
      out.push('<pre><code>' + esc(buf.join('\n')) + '</code></pre>');
      continue;
    }
    if (/^#{1,6}\s/.test(lines[i])){          /* 标题 */
      const lvl = lines[i].match(/^#+/)[0].length;
      out.push('<h' + lvl + '>' + inline(lines[i].replace(/^#+\s*/, '')) + '</h' + lvl + '>');
      i++; continue;
    }
    if (/^\s*([-*]|\d+[.)])\s+/.test(lines[i])){  /* 列表 */
      const items = [];
      while (i < lines.length){
        const m = lines[i].match(/^(\s*)([-*]|\d+[.)])\s+(.*)$/);
        if (!m) break;
        items.push({depth: Math.floor(m[1].length / 2), ol: /^\d/.test(m[2]), text: m[3]});
        i++;
      }
      out.push(listHtml(items));
      continue;
    }
    if (/^>\s?/.test(lines[i])){              /* 引用 */
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])){ buf.push(lines[i].replace(/^>\s?/, '')); i++; }
      out.push('<blockquote>' + inline(buf.join('\n')) + '</blockquote>');
      continue;
    }
    if (/^-{3,}$/.test(t)){ out.push('<hr>'); i++; continue; }
    const para = [];                          /* 段落 */
    while (i < lines.length && lines[i].trim() &&
           !/^(#{1,6}\s|```|[-*]\s+|\d+[.)]\s+|>)/.test(lines[i])){
      para.push(lines[i]); i++;
    }
    out.push('<p>' + para.map(inline).join('<br>') + '</p>');
  }
  return out.join('\n');
}

/* ---------------- 导航树 ---------------- */
function countNodes(n){ return 1 + (n.children || []).reduce((a, c) => a + countNodes(c), 0); }
function collectTypes(n){
  if (n.type && n.type !== 'root') TYPES.add(n.type);
  (n.children || []).forEach(collectTypes);
}
function fillTypeFilter(){
  const sel = $('#type-filter'), cur = sel.value;
  sel.innerHTML = '<option value="">全部类型</option>' +
    Array.from(TYPES).sort().map(t => '<option value="' + esc(t) + '">' + esc(t) + '</option>').join('');
  if (cur) sel.value = cur;
}
function visible(n){
  const f = $('#type-filter').value;
  if (!f || n.type === f) return true;
  return (n.children || []).some(visible);
}
function markActive(row){
  document.querySelectorAll('#tree .row').forEach(r => r.classList.remove('active'));
  row.classList.add('active');
}
function renderTree(node, parent){
  parent.innerHTML = '';
  for (const k of (node.children || []).filter(visible)){
    const isDir = (k.children || []).length > 0;
    const row = document.createElement('div');
    row.className = 'row';
    const caret = document.createElement('span');
    caret.className = 'caret';
    caret.textContent = isDir ? '▸' : '';
    const label = document.createElement('span');
    label.className = 'label';
    label.textContent = k.title || k.tid;
    label.title = k.tid;
    const badge = document.createElement('span');
    badge.className = 'badge';
    badge.textContent = k.type;
    row.append(caret, label, badge);
    const go = () => { readNode(k.tid); markActive(row); };
    if (isDir){
      const wrap = document.createElement('div');
      wrap.className = 'children hidden';
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
async function loadLib(){
  const data = await api('/api/tree', {kb: KB});
  CACHE = data.tree;
  $('#count').textContent = data.total + ' 节点';
  TYPES.clear(); collectTypes(CACHE); fillTypeFilter();
  renderTree(CACHE, $('#tree'));
  readNode('root');
}

/* ---------------- 阅读 / 元信息 / 检索 ---------------- */
async function readNode(tid, mode){
  try{
    const data = await api('/api/read', {kb: KB, tid, node: mode === 'node' ? 1 : 0});
    $('#content').innerHTML =
      '<div class="doc"><h1>' + esc(data.title || tid) + '</h1>' +
      '<div class="meta"><span class="badge">' + esc(data.type || '') + '</span> ' +
      '<span>' + esc(data.tid) + '</span> · <span class="src">来源 ' + esc(data.source || '') + '</span>' +
      '<span class="btns">' +
      '<button onclick="readNode(\'' + data.tid + '\',\'node\')">仅此节点</button>' +
      '<button onclick="rawNode(\'' + data.tid + '\')">元信息</button>' +
      '</span></div>' + mdToHtml(data.text) + '</div>';
  }catch(e){ $('#content').innerHTML = '<div class="empty">' + esc(e.message) + '</div>'; }
}
async function rawNode(tid){
  try{
    const data = await api('/api/raw', {kb: KB, tid});
    $('#content').innerHTML = '<div class="doc"><h1>' + esc(tid) + ' · 元信息</h1>' +
      '<pre id="rawjson">' + esc(JSON.stringify(data, null, 2)) + '</pre></div>';
  }catch(e){ $('#content').innerHTML = '<div class="empty">' + esc(e.message) + '</div>'; }
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
      $('#content').innerHTML = '<div class="empty">无匹配：' + esc(q) + '</div>';
      return;
    }
    $('#content').innerHTML =
      '<h2 style="margin:4px 0 12px">' + data.count + ' 条匹配「' + esc(q) + '」</h2>' +
      data.hits.map(h =>
        '<div class="result" onclick="readNode(\'' + h.tid + '\')">' +
        '<h3>' + esc(h.title || h.tid) + ' <span class="badge">' + esc(h.type || '') + '</span></h3>' +
        '<div class="snippet">' + esc(h.snippet) + '</div>' +
        '<div class="meta">' + esc(h.tid) + ' · ' + esc(h.source || '') + '</div></div>'
      ).join('');
  }catch(e){ $('#content').innerHTML = '<div class="empty">' + esc(e.message) + '</div>'; }
}

/* ---------------- 初始化 ---------------- */
async function init(){
  const libs = await api('/api/list');
  const names = Object.keys(libs.libraries || {});
  if (!names.length){
    $('#content').innerHTML = '<div class="empty">暂无已注册库（kb register &lt;名称&gt; &lt;技能目录&gt;）</div>';
    return;
  }
  const sel = $('#lib-select');
  sel.innerHTML = names.map(n => '<option value="' + esc(n) + '">' + esc(n) + '</option>').join('');
  sel.addEventListener('change', () => { KB = sel.value; loadLib(); });
  $('#type-filter').addEventListener('change', () => { if (CACHE) renderTree(CACHE, $('#tree')); });
  KB = names[0];
  loadLib();
}
init().catch(e => { $('#content').innerHTML = '<div class="empty">加载失败：' + esc(e.message) + '</div>'; });
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
            if path not in ("/api/tree", "/api/toc", "/api/read", "/api/raw", "/api/search"):
                return self._json({"error": f"未知路径: {path}"}, 404)
            kb = _q(q, "kb")
            if not kb:
                return self._json({"error": "缺少 kb 参数（库注册名，/api/list 查看）"}, 400)
            nodes = commands.load_library(kb, None)
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
                text, _code = commands.cmd_search(nodes, query, type_=type_, limit=limit, as_json=True)
                return self._send(text.encode("utf-8"), "application/json; charset=utf-8")
        except Exception as e:  # 兜底：不崩 server，回 JSON 错误
            return self._json({"error": str(e)}, 500)


def main(host: str = "127.0.0.1", port: int = 8666) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"NodeKB WebUI（只读，md 即库无编辑）→ http://{host}:{port}/  Ctrl+C 退出", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
