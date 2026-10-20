# NodeKB —— 节点化项目知识库 接口设计（SPEC v0.3，.nodekb 递归）

## 1. 目标与定位

**md 文件即资料库，节点是 md 中以标记标定的文本块**；NodeKB 是纯解析/渲染层（零持久化状态），提供 read / search / diag 供 Agent（MCP）与人类（dump/WebUI）使用。

设计基线：

- **库根 = 技能文件夹下 `.nodekb/`**，递归解析其内全部 md——任意目录结构、任意嵌套、自定义类型天然支持。
- **写 = 直接写 `.nodekb` 下的 md**；无 edit 命令；版本/回滚由编辑工具链的文件追踪承担。
- **所有文本皆节点**：显式 `<node>` 段 + 隐式 `##` H2 段统一成节点。
- 单一真源天然成立：无第二存储、无同步、无单点故障。

## 2. 节点模型（.nodekb 递归）

```
.nodekb/                     ← 库根（tid=root）
├── doc/                     ← 文件夹节点（type=doc，parent=root）
│   ├── 01.md                ← 文件节点（tid=doc:01，parent=doc）
│   │   ├── <node name="a">  ← 第一个 <node> = 文件根（parent=文件节点）
│   │   │   └── <node name="b">   ← b.parent 缺省 = a（文件根）
│   │   └── ## 概述           ← 隐式段（parent 缺省 = 文件根）
├── ModelInfo/               ← 自定义文件夹（type=modelinfo）
│   └── readme.md
```

### 层级与缺省规则

| 元素 | 节点 | type | parent 缺省 |
|---|---|---|---|
| 文件夹（递归） | 文件夹节点 | **文件夹名** | 父文件夹 |
| md 文件 | 文件节点 | 文件夹名 | 所在文件夹 |
| `<node name="X">` 第一个 | 显式节点 | 文件夹名 | 文件节点 |
| `<node name="X">` 其余 | 显式节点 | 文件夹名 | **文件内第一个 `<node>` 段的 name** |
| `## 标题`（非节点文本） | 隐式节点 | 文件夹名 | 文件内第一个 `<node>` name，否则文件节点 |

### 显式 `<node>` 语法

```html
<node name="a" parent="b" type="c">
  文本
</node>
```

- `name` = 完整 TID（必需）；`parent` / `type` 可选（缺省规则如上）。
- 允许单行：`<node name="fact:ver">20261003.0.0</node>`；允许嵌套（内层须单行闭合）。

### 引用（transclusion）

- `[[TID]]` 引用任意节点，read 时展开；环检测报错（含重复节点源行号）；悬空引用保留原文 + diag 报告。
- 引用**文件/文件夹**节点时展开其整支子树（`##` 小节与子节全部内联，`[[文件TID]]` 不再丢小节）；引用**显式 `<node>`** 只展开该原子节点自身（同文件兄弟不连带展开——节点的 `kind` = folder/file/section/node 决定）。
- 物理唯一、逻辑多态：文本只存在于 `.nodekb` 的 md 一处，投影出现在所有引用处。

## 3. TID 规范

- 文件夹/文件/段节点由程序派生：`{文件夹tid}:{文件名slug}`、`{文件tid}:{章节号}`。
- 显式 `<node name>` 即完整 TID（全局唯一，重复解析报错）。
- 命名字符集：`a-z0-9 中文 . _ - :`；段级优先章节号（`## 3.1` → `:3.1`），否则序号。

## 4. 命令接口（CLI 与 MCP 同签名）

```
read <tid> [--node] [--toc] [--raw] [--json] [--kb N | --lib 技能目录或.nodekb]
search <query> [--type T] [--limit N] [--json] [--kb N | --lib …]
diag [--json] [--kb N | --lib …]
dump --out <dir> [--kb N | --lib …]
register <name> <技能目录>      # 自动创建 .nodekb 库根 + 初始化内嵌 git
list [--json]
vcs init|status|commit [--msg …] [--kb N | --lib …]   # 版本控制
webui [--host 127.0.0.1] [--port 8666]   # 只读本地 WebUI
```

- read：默认整支渲染投影（[[TID]] 展开，文件/文件夹引用展开整支子树）；`--toc` 目录视图；`--raw` 元信息（含 source 行号）；`--maxlen` 整支字符上限（默认 50000，`0`=不限；超限报错并建议 `--node`/小节）。
- search：自建 2-gram 倒排（实时），中文自然语言可用，多词加权，LIKE 兜底；`offset` 分页续读、`snippet` 片段窗口；命中 `tid` 为稳定句柄（位置型段落上溯到文件/显式节点）、`ref` 为实际命中节点、`positional` 标记；片段保留换行/缩进。
- diag：悬空/循环引用（循环含源行号）、孤儿节点、树环、重复 TID、位置型 TID 引用（`文件:序号`）、内容漂移（≥40 字符跨节点物理重复块，最多报 20 条）、节点内重复行（≥40 字符正文/命令行同节点 2+ 次，跳过围栏/表格/纯符号行，最多报 20 条）。
- 解析健壮性：` ``` ` 围栏内不切分（`##`/`<node>` 按原文）、BOM 剥除、重复 TID 可在传入 problems 时降级「跳过冲突项 + 其余照读」。
- 错误语义：未找到/前缀歧义时列出候选；`--lib` 路径不存在时报错同时给出原参数。

## 5. MCP 通用化

- 只配置一个 nodekb 本体 MCP（stdio），目标库通过 `kb`（注册名）选择。
- 六工具：`kb_list` / `kb_read` / `kb_search` / `kb_diag` / `kb_vcs_init` / `kb_vcs_status`（无 edit——写文档 = 原生 write/edit）。
- 注册表：`nodekb/kb_registry.json`（name → 技能目录），`kb register` 维护。
- Agent 典型流程：`kb_list` → `kb_search(kb=库名, query)` → `kb_read(kb=库名, target=tid)`；**写 = 改 `.nodekb` 下 md**，下次读取自动快照（见 §7）。

## 6. WebUI（人类只读界面 · 星图）

`python -m kb webui`：纯只读本地 HTTP server（stdlib http.server，零依赖；单 HTML 内联 CSS/JS 零 CDN）。仅绑 127.0.0.1，默认端口 8666。

- **关系星图**（暗色）：节点 = 方形文本框（深色底 + 类型色描边，显示 `name` 上限 50 字符），边 = parent 层级 + `[[TID]]` ref 引用；力导向布局（网格斥力 + 弹簧，力/速度/坐标钳制防 500+ 节点发散）。
- **左侧栏**：类型 chip 筛选 + 层级树（点击定位居中）+ 视图调节滑杆（排斥力/线明度实时生效）。
- **点击节点 → 右侧详情面板**（markdown 渲染，引用展开；整支/仅节点/元信息）；滚轮缩放、平移、拖节点、悬停高亮、Esc 关闭。
- 无任何编辑入口；改文档 = 直接改 `.nodekb` 下的 md。

只读接口（JSON，错误统一 `{"error": …}`）：

| 路由 | 参数 | 返回 |
|---|---|---|
| `/api/list` | – | `{"libraries": {name: 技能目录}}` |
| `/api/graph` | `kb` | `{"nodes": [{tid,title,name,type,kind,nchar}], "edges": [{s,t,r: p|r}]}`（r=p 父链 / r=ref 转译引用） |
| `/api/tree` | `kb` | `{"tree": 递归树, "total": N}`（每节点 tid/title/type/source/children） |
| `/api/toc` | `kb, tid` | `{"tid", "lines": [目录行]}`（tid 缺省 root） |
| `/api/read` | `kb, tid, node` | `{"tid", "title", "type", "source", "text"}`（渲染文本，node=1 仅单节点） |
| `/api/raw` | `kb, tid` | `{"tid", "type", "title", "parent_tid", "sort", "source", "content"}` |
| `/api/search` | `kb, q, type, limit, offset` | `{"total", "count", "offset", "hits"}`（hit: tid 稳定句柄/ref/positional/type/title/source/snippet） |

## 7. 版本控制（内嵌 git，自动快照）

- 仓库根 = `.nodekb/` 自身（只版本化知识库，不碰技能目录其它文件）；`.git` 等点目录解析时跳过。
- 初始化：`register` 自动；既有库 `kb vcs init` / MCP `kb_vcs_init` 一次即可。
- 自动快照：每次解析库后若仓库有变更即 `commit`（`autosnap: N 处变更`），零手动操作；线程锁防并发（WebUI）。
- 手动：`vcs status`（repo/last_commit/dirty/kinds）、`vcs commit --msg`。
- git 缺失或非仓库：全部静默跳过，只读功能不受影响。

## 8. 存储位置

- 库 = 技能文件夹下 `.nodekb/`，md 递归组织（任意目录结构）。
- 技能目录原 doc/ 等保留为备份（迁移时复制，不删除）。
- 版本历史由 `.nodekb` 内嵌 git 仓库承担（自动快照，见 §7）。

## 9. 验证清单（回归门禁）

- [x] `.nodekb` 递归解析：文件夹/文件/隐式段/显式 `<node>` 四级。
- [x] 缺省规则：type=文件夹名；parent=文件内第一个 `<node>` name，否则文件节点。
- [x] 自定义文件夹类型（ModelInfo → modelinfo）与嵌套子目录。
- [x] `<node>` 单行/多行/嵌套（内层单行闭合）。
- [x] `[[TID]]` 展开；循环报错；悬空 diag 检出。
- [x] 引用文件/文件夹展开整支子树（`[[文件TID]]` 不再丢 `##` 小节）；显式 `<node>` 原子引用只展开自身（kind 规则，不连带同文件兄弟）。
- [x] read 整支 / --toc / --raw / --maxlen（超限报错、0=不限）；search 中文多词；dump 导出。
- [x] 围栏内 `##` 不切分、BOM 剥除；重复 TID 降级（problems 收集）实测。
- [x] diag 结构 + 内容级实测（comfyui 508 / minecraft 342 / filmmeasure 154 节点）：minecraft 0 错误；漂移/节点内重复实测检出模板类与整段拷贝。
- [x] 显式节点转译不连带兄弟 / 节点内重复行 lint 回归测试通过；minecraft `index:entry` 渲染 13.2k→8.9k 字符（-33%），§4 gradlew 4→1、Copy-Item 3→1。
- [x] 位置型 TID 引用 / 内容漂移 / 循环源行号 / 前缀歧义候选 回归测试通过。
- [x] search 稳定句柄实测：`kb_search reconcile` 首条 tid=`index:entry`（非位置型），ref=`index:entry:6`，positional 标记，片段保留换行；`kb_read fact:mod` 列候选 fact:mod-dir/modid/modid-places/modid-trap。
- [x] MCP 六工具交互正常；重复 TID 报错。
- [x] vcs：register 自动 init；改动后读取自动快照（`autosnap: N 处变更`）实测；`.git` 点目录不污染节点树；三库（minecraft/comfyui/filmmeasure）已初始化并含初始快照。
- [x] WebUI：/api/list·graph·tree·toc·read·raw·search 全接口实测通过；星图（暗色/力导向/类型着色/chip 筛选/点击详情/缩放平移）浏览器实测 5 项全过（comfyui 583 节点坐标有界 ≤410）。
