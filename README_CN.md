# NodeKB —— Markdown 即库的节点化知识库

**Markdown 文件就是资料库。** NodeKB 把一个 Markdown 目录解析成可寻址的节点图：没有数据库、没有同步步骤、没有第二份状态。它向 Agent（MCP）与人类（CLI + 零依赖本地 WebUI）提供 `read / search / diag` 三个接口。

[English](README.md)

---

## 为什么

当项目记忆超过单文件容量后，Agent 为了找一个值往往要整篇读入，而同一个值被多处拷贝后又必然漂移。NodeKB 让文本只存在于 Markdown 中，为每个文本块分配稳定地址（`TID`），并在需要时展开引用：

- **读取量有上限** —— 读一个节点、一支子树或一个小节，而不是一篇 200 KB 文档。
- **单一真源** —— 一个事实只存在于一个节点，其它页面用 `[[TID]]` 转译。
- **结构可验证** —— `diag` 在悬空引用、循环、重复 ID、内容漂移变成事故前就报出来。

## 设计基线

- **库根 = 技能目录下的 `.nodekb/`**，递归解析其内全部 Markdown——任意目录结构与自定义类型天然支持。
- **写 = 直接改 Markdown**；没有 `edit` 命令，历史交给内嵌 git。
- **所有文本皆节点**：显式 `<node>` 块与隐式 `##` 小节都是一等公民。
- **零第三方依赖**（仅用 `http.server`、`subprocess`、`re`、`json`）。

## 环境要求

- Python **3.10+**
- `PATH` 中有 `git`（可选——缺失时版本控制静默降级，只读功能不受影响）

## 快速开始

```bash
# 注册库（自动创建 <技能目录>/.nodekb 并初始化内嵌 git）
python -m kb register mykb /path/to/skill-dir

# 读整支 / 单节点 / 目录视图 / 元信息
python -m kb read root            --kb mykb
python -m kb read index:entry     --kb mykb --node
python -m kb read doc             --kb mykb --toc
python -m kb read fact:modid      --kb mykb --raw

# 检索（中文自然语言可用，2-gram 倒排）
python -m kb search "代理端口"     --kb mykb --json

# 自检
python -m kb diag                 --kb mykb
```

任何 `--kb <名称>` 的位置都可以换成 `--lib <技能目录 | .nodekb>`，用于一次性读取。

## 节点模型

```
.nodekb/                     ← 库根（tid = root）
├── doc/                     ← 文件夹节点（type=doc，parent=root）
│   ├── 01.md                ← 文件节点（tid=doc:01，parent=doc）
│   │   ├── <node name="a">  ← 第一个 <node> = 文件根（parent = 文件节点）
│   │   │   └── <node name="b">  ← b.parent 缺省 = a
│   │   └── ## 概述           ← 隐式小节（parent 缺省 = 文件根）
└── ModelInfo/               ← 自定义文件夹 → type=modelinfo
```

**缺省规则**：`type` 缺省 = 所在文件夹名；`parent` 缺省 = 文件内第一个 `<node>`，否则文件节点。小节 ID 优先取显式编号（`## 3.1` → `:3.1`），否则用序号。

**转译**：渲染时 `[[TID]]` 就地展开。引用**文件/文件夹**展开整支子树；引用显式 `<node>` 只展开该原子节点。循环引用报错并带源位置；悬空引用保留原文并由 `diag` 报告。

## 命令

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

- **read** —— 默认渲染整支并展开引用。`--maxlen`（默认 50000）防止一次读爆 Agent 上下文；`0` 表示不限。
- **search** —— 实时 2-gram 倒排 + 多词加权 + LIKE 兜底。命中返回**稳定 `tid`**（位置型小节 ID 自动上溯到文件/锚点节点）、实际命中 `ref`、`positional` 标记，以及**保留换行与缩进**的片段。
- **diag** —— 结构错误（悬空/位置型引用、循环、孤儿、重复 ID）以退出码 2 失败；漂移警告（跨节点重复块、节点内重复行）单独列出，仅 `--strict` 时失败。导航行、纯链接块、参数列表等样板内容自动忽略；单库豁免写在 `.nodekb/diag_ignore.json`。

## MCP（Agent 接入）

只需配置一个 stdio MCP 服务，用 `kb` 参数选择目标库：

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

工具：`kb_list`、`kb_read`、`kb_search`、`kb_diag`、`kb_vcs_init`、`kb_vcs_status`。没有写工具——修改文档用 Agent 原生文件工具，下一次读取即生效。

典型流程：`kb_list` → `kb_search(kb=…, query=…)` → `kb_read(kb=…, target=…)`。

## 内嵌版本控制

- 仓库根就是 `.nodekb/` 目录本身——只版本化知识，不碰外层技能目录。
- `kb register` 自动初始化；既有库执行一次 `kb vcs init`。
- **自动快照**：每次解析（read/search/diag/WebUI）后若有变更就提交为 `autosnap: N 处变更`，无需手动 git。
- `kb vcs status` 查看最近提交与待提交变更；`kb vcs commit --msg …` 记录有意义的提交信息。
- git 缺失或目录不是仓库时全部静默跳过。

## WebUI

```bash
python -m kb webui          # http://127.0.0.1:8666/
```

纯只读单页界面，内联 CSS/JS（零 CDN，可离线）：

- **左→右树状布局**（父左子右），确定性同步计算，不依赖动画回调。
- 方形节点：深色底 + 类型色描边，框内显示 `name`（上限 50 字符）。
- 框外左上角小字标注 `类型 · 子分支数`（折叠时显示 `类型 ＋N`）。
- **左侧栏**：类型 chip 筛选、可展开的层级树导航、视图调节（横向间距 / 纵向间距 / 线明度，「重新适配」可读优先、「全部适配」全貌优先）。
- **点击节点**右侧滑出面板，渲染 Markdown（引用已展开；整支/仅节点/元信息）。点击不会移动画布；双击折叠/展开分支。
- 滚轮缩放（文字同步缩放）、拖空白平移、`Esc` 关闭面板。

JSON 接口：`/api/list`、`/api/graph`、`/api/tree`、`/api/toc`、`/api/read`、`/api/raw`、`/api/search`。

## 目录结构

```
nodekb/
├── README.md / README_CN.md / SPEC.md
├── kb/
│   ├── __main__.py     CLI 入口
│   ├── mdlib.py        解析层（.nodekb 递归 → 节点树）
│   ├── render.py       渲染（转译 / toc / raw）
│   ├── commands.py     read / search / diag / register / list / dump
│   ├── mcp_server.py   MCP server（stdio，零依赖）
│   ├── webui.py        只读 WebUI（http.server，零依赖）
│   └── vcs.py          内嵌 git 自动快照
├── run_mcp.py          独立 MCP 入口（不依赖 PYTHONPATH/cwd）
└── tests/test_core.py  36 项回归测试
```

## 测试

```bash
python -m unittest discover -s tests
```

## 许可

当前未附带许可证文件；对外分发或接受贡献前请先补上。
