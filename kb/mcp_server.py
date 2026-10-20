"""NodeKB MCP Server（stdio，JSON-RPC 2.0，零依赖手写）。

md 即库：无持久化状态，每次调用实时解析技能目录。四个工具：
  kb_list    列出已注册的库
  kb_read   读取（整支 / --node / --toc / --raw）
  kb_search 检索（中文自然语言）
  kb_diag   自检
edit 已删——修改文档 = 直接写 md（Agent 原生 write/edit 工具承担）。

运行：python -m kb.mcp_server（或 run_mcp.py，无依赖）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from . import commands


def _tools() -> list[dict]:
    return [
        {
            "name": "kb_list",
            "description": "列出已注册的库（名称 + 技能目录 + type 目录映射）。调用其他工具前先看有哪些库。",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "kb_read",
            "description": "读取节点（md 即库，实时解析）。默认整支渲染投影（[[TID]] 已展开，等价 md 整篇）；node=true 仅单节点；toc=true 目录视图；raw=true 元信息（含 source 行号）。目标库：kb（注册名）或 srcs（type 目录映射）。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "节点 TID，如 doc:03-工程经验与已知坑:3.1 或 todo:01"},
                    "node": {"type": "boolean"},
                    "toc": {"type": "boolean", "description": "目录视图（tid·标题·字符数，列子树用）"},
                    "raw": {"type": "boolean", "description": "节点元信息（含 source 行号）"},
                    "maxlen": {"type": "integer", "default": 50000,
                               "description": "整支渲染字符上限（0=不限；超限报错并提示缩小范围，防止打爆上下文）"},
                    "kb": {"type": "string", "description": "库注册名（kb_list 可查看，如 mykb）"},
                },
                "required": ["target"],
            },
        },
        {
            "name": "kb_search",
            "description": "全文 / TID / 标题检索（中文自然语言可用，2-gram 拆分 + 命中加权）。返回渲染上下文片段。命中 tid=稳定句柄（位置型段落已上溯到文件/显式节点，可直接用于 kb_read），ref=实际命中节点（可能是位置型 TID，仅用于定位）。目标库：kb 或 srcs。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "type": {"type": "string", "description": "节点类型过滤，如 doc/todo/git/handover"},
                    "limit": {"type": "integer", "default": 10},
                    "offset": {"type": "integer", "default": 0,
                               "description": "跳过前 N 条命中（配合 limit 分页续读）"},
                    "snippet": {"type": "integer", "default": 240,
                                "description": "片段窗口字符数（保留换行/缩进，不再压平）"},
                    "kb": {"type": "string"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "kb_diag",
            "description": "自检：悬空/位置型引用、循环引用、树完整性、类型清单。errors 是真损坏（退出非零）；warnings 是疑似内容漂移（共用样板块已自动忽略，库根 diag_ignore.json 可再加本地豁免），默认不影响退出码，strict=true 时才算失败。目标库：kb 或 srcs。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "kb": {"type": "string"},
                    "strict": {"type": "boolean", "description": "严格模式：把漂移 warning 也视为失败（默认 false）"},
                },
            },
        },
        {
            "name": "kb_vcs_init",
            "description": "初始化 .nodekb 内嵌 git 仓库（register 已自动做；既有库手动补一次即可，之后自动快照）。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "kb": {"type": "string"},
                },
            },
        },
        {
            "name": "kb_vcs_status",
            "description": "版本控制状态：仓库是否初始化、最近提交、待提交变更数。变更会在任意读取后自动提交（autosnap）。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "kb": {"type": "string"},
                },
            },
        },
    ]


def _handle_request(msg: dict) -> Optional[dict]:
    method = msg.get("method")
    if method == "initialize":
        return {
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "nodekb", "version": "0.2.0"},
            }
        }
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "tools/list":
        return {"result": {"tools": _tools()}}
    if method == "tools/call":
        return _call_tool(msg.get("params") or {})
    return {"error": {"code": -32601, "message": f"未知方法: {method}"}, "id": msg.get("id")}


def _call_tool(params: dict) -> dict:
    name = params.get("name")
    args = params.get("arguments") or {}
    try:
        if name == "kb_list":
            reg = commands.load_registry()
            text = json.dumps(reg, ensure_ascii=False, indent=2) if reg else "（无已注册的库，用 kb register 添加）"
            return {"result": {"content": [{"type": "text", "text": text}], "isError": False}}
        nodes = commands.load_library(args.get("kb"), None)
        if name == "kb_read":
            text, code = commands.cmd_read(
                nodes, args["target"], node=args.get("node", False),
                raw=args.get("raw", False), toc=args.get("toc", False),
                maxlen=args.get("maxlen", commands.DEFAULT_MAXLEN),
            )
        elif name == "kb_search":
            text, code = commands.cmd_search(
                nodes, args["query"], type_=args.get("type"), limit=args.get("limit", 10),
                as_json=True, offset=args.get("offset", 0), snippet=args.get("snippet", 240),
            )
        elif name == "kb_diag":
            problems: list = []
            nodes = commands.load_library(args.get("kb"), None, problems)
            try:
                lib_root = commands.lib_dir_of(args.get("kb"), None)
            except (KeyError, ValueError):
                lib_root = None
            text, code = commands.cmd_diag(
                nodes, problems, strict=bool(args.get("strict", False)),
                lib_root=Path(lib_root) if lib_root else None,
            )
        elif name == "kb_vcs_init":
            text, code = commands.cmd_vcs(args.get("kb"), None, "init")
        elif name == "kb_vcs_status":
            text, code = commands.cmd_vcs(args.get("kb"), None, "status")
        else:
            return {"result": {"content": [{"type": "text", "text": f"未知工具: {name}"}], "isError": True}}
        return {"result": {"content": [{"type": "text", "text": text}], "isError": code != 0}}
    except Exception as e:  # 兜底：不让 server 崩溃
        return {"result": {"content": [{"type": "text", "text": f"错误: {e}"}], "isError": True}}


def serve() -> int:
    # Windows 下强制 UTF-8：客户端以 UTF-8 收发，Python 默认 locale 编码会乱码
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = _handle_request(msg)
        if resp is not None:
            resp.setdefault("jsonrpc", "2.0")
            resp.setdefault("id", msg.get("id"))
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    return serve()


if __name__ == "__main__":
    sys.exit(main())
