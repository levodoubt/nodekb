# NodeKB —— 节点化项目知识库（md 即库）

**md 文件即资料库，节点是 md 中以标记标定的文本块。** NodeKB 是纯解析/渲染层（零持久化状态），为 Agent（MCP）与人类（dump/WebUI）提供 `read / search / diag` 检索接口。

## 设计基线

- **库根 = 技能文件夹下 `.nodekb/`**，递归解析其内全部 md——任意目录结构、任意嵌套、自定义类型天然支持。
- **写 = 直接写 `.nodekb` 下的 md**；无 edit 命令；版本/回滚由编辑工具链的文件追踪承担。
- **所有文本皆节点**：显式 `<node>` 段 + 隐式 `##` H2 段统一成节点。
- **单一真源天然成立**：无第二存储、无同步、无单点故障。

## 节点模型

```
.nodekb/                     ← 库根（tid=root）
├── doc/                     ← 文件夹节点（type=doc，parent=root）
│   ├── 01.md                ← 文件节点（tid=doc:01，parent=doc）
│   │   ├── <node name="a">  ← 第一个 <node> = 文件根（parent=文件节点）
│   │   │   └── <node name="b">   ← b.parent 缺省 = a（文件根）
│   │   └── ## 概述           ← 隐式段（parent 缺省 = 文件根）
├── ModelInfo/               ← 自定义文件夹（type=modelinfo）
```

**缺省规则**：`type` 缺省 = 所在文件夹名；`parent` 缺省 = 文件内第一个 `<node>` 段的 name，否则文件节点。

**引用（transclusion）**：`[[TID]]` 引用任意节点，read 时展开；环检测报错；悬空引用保留原文 + diag 报告。物理唯一、逻辑多态——文本只存一处，投影出现在所有引用处。

## 命令

```
python -m kb read <tid> [--node] [--toc] [--raw] [--json] [--kb N | --lib 技能目录]
python -m kb search <query> [--type T] [--limit N] [--json] [--kb N | --lib …]
python -m kb diag [--kb N | --lib …]
python -m kb dump --out <dir> [--kb N | --lib …]
python -m kb register <name> <技能目录>    # 自动创建 .nodekb 库根 + 初始化内嵌 git
python -m kb list
python -m kb vcs init|status|commit [--msg …] [--kb N | --lib …]   # 版本控制
python -m kb webui [--host 127.0.0.1] [--port 8666]   # 只读本地 WebUI
```

- `read`：默认整支渲染投影（引用展开）；`--toc` 目录视图；`--raw` 元信息（含 source 行号）；`--maxlen` 整支字符上限（默认 50000，超限报错提示缩小范围，`0`=不限）。引用**文件/文件夹**节点时展开整支子树（`##` 小节不再丢失）；引用**显式 `<node>`** 只展开该原子节点自身（同文件兄弟不连带展开）。
- `search`：自建 2-gram 倒排（实时），中文自然语言可用，多词加权，LIKE 兜底。`--offset` 分页续读、`--snippet` 片段窗口；命中 `tid` 为**稳定句柄**（位置型段落上溯到文件/显式节点），`ref` 为实际命中节点、`positional` 标记；片段保留换行/缩进（代码块不压平）。
- `diag`：悬空/循环引用（带源行号）、孤儿节点、树环、重复 TID、位置型 TID 引用、内容漂移（跨节点物理重复块）、节点内重复行（正文/命令行整段拷贝）。

## MCP（Agent 接入）

只配置一个本体 MCP（stdio），目标库通过 `kb` 注册名选择：

```json
{
  "mcpServers": {
    "nodekb": {
      "command": "D:\\software\\Python\\3.13.14\\python.exe",
      "args": ["D:\\desktop\\1\\1\\nodekb\\run_mcp.py"],
      "env": { "PYTHONIOENCODING": "utf-8" }
    }
  }
}
```

六工具：`kb_list` / `kb_read` / `kb_search` / `kb_diag` / `kb_vcs_init` / `kb_vcs_status`（无 edit——写文档 = 原生 write/edit）。Agent 典型流程：`kb_list` → `kb_search(kb=库名, query)` → `kb_read(kb=库名, target=tid)`；改动自动快照见下。

## 版本控制（内嵌 git，自动快照）

- **仓库根 = `.nodekb/` 自身**：只版本化知识库，不碰技能目录其它文件；`.git` 目录解析时自动跳过。
- **初始化**：`kb register` 自动完成；既有库执行一次 `kb vcs init`（或 MCP `kb_vcs_init`）即可。
- **自动快照**：每次读取/检索/自检后，若仓库有变更则自动 `commit`（消息 `autosnap: N 处变更`）——Agent 改完 md，下一次读取即落盘，无需手动 git。
- **手动**：`kb vcs status`（最近提交/待提交变更）、`kb vcs commit --msg …`（有意义的提交信息）。
- git 缺失时全部静默跳过，只读功能不受影响。既有库（minecraft/comfyui/filmmeasure）已初始化。

## WebUI（人类只读界面）

`python -m kb webui` 启动纯只读本地 server（stdlib http.server，零依赖，单 HTML 内联 CSS/JS 零 CDN）。浏览器打开 http://127.0.0.1:8666/：

- **库选择**：顶部下拉（读 `kb_registry.json`，仅列出存在 `.nodekb` 的库）
- **左栏项目树**：全库导航（文件夹/文件/显式节点递归，懒展开），类型过滤可只看 doc/todo/git/… 
- **全文检索**：复用 search（中文 2-gram），结果点击直达节点
- **阅读视图**：`[[TID]]` 引用已展开；「仅此节点 / 元信息」按钮；来源行号展示；markdown 渲染（标题/表格/任务清单/嵌套列表/引用/代码块/图片/删除线）
- **只读**：无任何编辑入口——改文档 = 直接改 `.nodekb` 下的 md

只读接口（JSON）：`/api/list` `/api/tree?kb=` `/api/toc?kb=&tid=` `/api/read?kb=&tid=&node=` `/api/raw?kb=&tid=` `/api/search?kb=&q=&type=&limit=`。

## 文档

- [SPEC.md](SPEC.md)：完整接口设计（v0.3，.nodekb 递归）
- [tests/test_core.py](tests/test_core.py)：14 项回归测试，`python -m unittest discover -s tests`

## 布局

```
nodekb/
├── README.md / SPEC.md
├── kb/
│   ├── __main__.py     CLI（read/search/diag/…/webui）
│   ├── mdlib.py        解析层（.nodekb 递归 → 节点树）
│   ├── render.py       渲染（引用展开 / toc / raw）
│   ├── commands.py     read / search / diag / register / list / dump
│   ├── mcp_server.py   MCP server（stdio，零依赖）
│   ├── webui.py        只读本地 WebUI（http.server 零依赖）
│   ├── vcs.py          .nodekb 内嵌 git（自动快照，零依赖）
│   └── run_mcp.py      独立启动入口（不依赖 PYTHONPATH/cwd）
└── tests/test_core.py
```
