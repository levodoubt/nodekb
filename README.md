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
python -m kb register <name> <技能目录>    # 自动创建 .nodekb 库根
python -m kb list
```

- `read`：默认整支渲染投影（引用展开）；`--toc` 目录视图；`--raw` 元信息（含 source 行号）。
- `search`：自建 2-gram 倒排（实时），中文自然语言可用，多词加权，LIKE 兜底。
- `diag`：悬空/循环引用、孤儿节点、树环、重复 TID。

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

四工具：`kb_list` / `kb_read` / `kb_search` / `kb_diag`（无 edit——写文档 = 原生 write/edit）。Agent 典型流程：`kb_list` → `kb_search(kb=库名, query)` → `kb_read(kb=库名, target=tid)`。

## 文档

- [SPEC.md](SPEC.md)：完整接口设计（v0.3，.nodekb 递归）
- [tests/test_core.py](tests/test_core.py)：14 项回归测试，`python -m unittest discover -s tests`

## 布局

```
nodekb/
├── README.md / SPEC.md
├── kb/
│   ├── __main__.py     CLI
│   ├── mdlib.py        解析层（.nodekb 递归 → 节点树）
│   ├── render.py       渲染（引用展开 / toc / raw）
│   ├── commands.py     read / search / diag / register / list / dump
│   ├── mcp_server.py   MCP server（stdio，零依赖）
│   └── run_mcp.py      独立启动入口（不依赖 PYTHONPATH/cwd）
└── tests/test_core.py
```
