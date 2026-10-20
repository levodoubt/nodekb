# NodeKB — Markdown-native, node-based knowledge base

**Your Markdown files are the database.** NodeKB turns a directory of Markdown into an addressable node graph: no database, no sync step, no duplicated state. It exposes a small `read / search / diag` surface for agents (MCP) and humans (CLI + a zero-dependency local WebUI).

[中文说明](README_CN.md)

---

## Why

When project memory grows past a single file, agents end up reading whole documents to find one value — and values get copy-pasted until they drift apart. NodeKB keeps the text in Markdown only, gives every block a stable address (`TID`), and renders references on demand:

- **Bounded reads** — read one node, one subtree, or one section instead of a 200 KB document.
- **Single source of truth** — a fact lives in exactly one node; other pages *transclude* it with `[[TID]]`.
- **Verifiable structure** — `diag` reports dangling references, cycles, duplicate IDs and content drift before they bite.

## Design baseline

- **Library root = `.nodekb/` inside a skill folder**; every Markdown file below it is parsed recursively — arbitrary directory layouts and custom types work out of the box.
- **Writing = editing Markdown**; there is no `edit` command. History is handled by an embedded git repo.
- **Every piece of text is a node**: explicit `<node>` blocks and implicit `##` sections are first-class.
- **Zero third-party dependencies** (`http.server`, `subprocess`, `re`, `json` only).

## Requirements

- Python **3.10+**
- `git` on `PATH` (optional — version control silently degrades to read-only if missing)

## Quick start

```bash
# Register a library (creates <skill-dir>/.nodekb and initializes embedded git)
python -m kb register mykb /path/to/skill-dir

# Read a node, a subtree, a table of contents, or raw metadata
python -m kb read root            --kb mykb
python -m kb read index:entry     --kb mykb --node
python -m kb read doc             --kb mykb --toc
python -m kb read fact:modid      --kb mykb --raw

# Search (natural language works; CJK is indexed with 2-grams)
python -m kb search "proxy port"  --kb mykb --json

# Self-check
python -m kb diag                 --kb mykb
```

`--lib <skill-dir | .nodekb>` works anywhere `--kb <name>` does, for one-off libraries.

## Node model

```
.nodekb/                     ← library root (tid = root)
├── doc/                     ← folder node   (type=doc, parent=root)
│   ├── 01.md                ← file node     (tid=doc:01, parent=doc)
│   │   ├── <node name="a">  ← first <node> = file root (parent = file node)
│   │   │   └── <node name="b">  ← b.parent defaults to a
│   │   └── ## Overview      ← implicit section (parent defaults to file root)
└── ModelInfo/               ← custom folder → type=modelinfo
```

**Defaults**: `type` falls back to the folder name; `parent` falls back to the first `<node>` in the file, otherwise the file node. Section IDs prefer an explicit number (`## 3.1` → `:3.1`) and otherwise use an ordinal.

**Transclusion**: `[[TID]]` inlines any node when rendering. Referencing a **file/folder** expands its whole subtree; referencing an explicit `<node>` inlines only that atom. Cycles raise an error with the source location; dangling references are kept verbatim and reported by `diag`.

## CLI

```
read   <tid> [--node] [--toc] [--raw] [--json] [--maxlen N] [--kb NAME | --lib PATH]
search <query> [--type T] [--limit N] [--offset N] [--snippet N] [--json] [--kb …]
diag   [--strict] [--kb …]
dump   --out <dir> [--kb …]
register <name> <skill-dir>
list   [--json]
vcs    init|status|commit [--msg TEXT] [--kb …]
webui  [--host 127.0.0.1] [--port 8666]
```

- **read** — renders the subtree with references expanded. `--maxlen` (default 50000) guards against blowing up an agent's context; `0` disables the guard.
- **search** — live 2-gram inverted index with multi-term weighting and a LIKE fallback. Hits return a **stable `tid`** (positional section IDs are lifted to their file/anchor node), the actual `ref`, a `positional` flag, and a snippet that preserves newlines and indentation.
- **diag** — structural errors (dangling / positional references, cycles, orphans, duplicate IDs) fail with exit code 2; drift warnings (cross-node duplicate blocks, duplicated lines within a node) are reported separately and only fail under `--strict`. Boilerplate such as navigation lines, link-only blocks and parameter lists is ignored; per-library exemptions go in `.nodekb/diag_ignore.json`.

## MCP (agent integration)

Run one stdio MCP server for all libraries; pick a target library with `kb`:

```json
{
  "mcpServers": {
    "nodekb": {
      "command": "python",
      "args": ["/absolute/path/to/nodekb/run_mcp.py"],
      "env": { "PYTHONIOENCODING": "utf-8" }
    }
  }
}
```

Tools: `kb_list`, `kb_read`, `kb_search`, `kb_diag`, `kb_vcs_init`, `kb_vcs_status`. There is no write tool — edits are made with the agent's native file tools and picked up on the next read.

Typical flow: `kb_list` → `kb_search(kb=…, query=…)` → `kb_read(kb=…, target=…)`.

## Embedded version control

- The repository root is the `.nodekb/` directory itself — only knowledge is versioned, never the surrounding skill folder.
- `kb register` initializes it automatically; existing libraries need one `kb vcs init`.
- **Auto-snapshot**: after every parse (read/search/diag/WebUI), pending changes are committed as `autosnap: N change(s)`. No manual git required.
- `kb vcs status` shows the last commit and pending changes; `kb vcs commit --msg …` records a meaningful message.
- Missing `git`, or a directory that is not a repository, is a silent no-op.

## WebUI

```bash
python -m kb webui          # http://127.0.0.1:8666/
```

A read-only, single-page UI with inline CSS/JS (no CDN, works offline):

- **Left-to-right tree** (parents left, children right) computed deterministically — no animation callbacks involved.
- Boxed nodes: dark fill, type-colored outline, node `name` inside (up to 50 characters).
- Outside each box, top-left: a small label with `type · child count` (or `type ＋N` when collapsed).
- **Sidebar**: type chips to filter, a collapsible hierarchy tree for navigation, and view controls (horizontal gap, vertical gap, edge brightness, *Fit readable* / *Fit all*).
- **Click** a node for a right-side panel with rendered Markdown (references expanded; whole-subtree / node-only / raw metadata). Clicking never moves the canvas; double-click collapses or expands a branch.
- Wheel to zoom (labels scale too), drag empty space to pan, `Esc` closes the panel.

JSON endpoints: `/api/list`, `/api/graph`, `/api/tree`, `/api/toc`, `/api/read`, `/api/raw`, `/api/search`.

## Layout

```
nodekb/
├── README.md / README_CN.md / SPEC.md
├── kb/
│   ├── __main__.py     CLI entry point
│   ├── mdlib.py        parser (.nodekb recursion → node tree)
│   ├── render.py       rendering (transclusion / toc / raw)
│   ├── commands.py     read / search / diag / register / list / dump
│   ├── mcp_server.py   MCP server (stdio, zero dependencies)
│   ├── webui.py        read-only WebUI (http.server, zero dependencies)
│   └── vcs.py          embedded git auto-snapshots
├── run_mcp.py          standalone MCP entry point (no PYTHONPATH/cwd needed)
└── tests/test_core.py  36 regression tests
```

## Tests

```bash
python -m unittest discover -s tests
```

## License

[MIT](LICENSE) © 2026 levodoubt
