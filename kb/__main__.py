"""NodeKB CLI 入口：python -m kb <命令>。

命令：read / search / diag / register / list / dump（edit 已删——修改 = 直接改 md）。
库 = 技能目录下的 type 目录，实时解析，无持久化状态。
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from . import commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kb", description="节点化项目知识库（md 即库）")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("read", help="读取：默认整支 / --node 单节点 / --toc 目录 / --raw 元信息")
    p.add_argument("target")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--node", action="store_true", help="仅该节点内容")
    g.add_argument("--toc", action="store_true", help="目录视图（tid·标题·字符数）")
    p.add_argument("--raw", action="store_true", help="节点元信息（含 source 行号）")
    p.add_argument("--json", action="store_true")
    p.add_argument("--maxlen", type=int, default=commands.DEFAULT_MAXLEN,
                   help="整支渲染字符上限（0=不限；超限报错并提示缩小范围）")
    p.add_argument("--kb", default=None, help="库注册名（kb list 查看）")
    p.add_argument("--lib", default=None, help="技能目录或 .nodekb 路径")

    p = sub.add_parser("search", help="全文 / TID / 标题检索（中文自然语言可用）")
    p.add_argument("query")
    p.add_argument("--type")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--offset", type=int, default=0, help="跳过前 N 条命中（配合 limit 分页续读）")
    p.add_argument("--snippet", type=int, default=240, help="片段窗口字符数（保留换行/缩进）")
    p.add_argument("--json", action="store_true")
    p.add_argument("--kb", default=None)
    p.add_argument("--lib", default=None)

    p = sub.add_parser("diag", help="自检：悬空/循环引用、树完整性、类型清单")
    p.add_argument("--kb", default=None)
    p.add_argument("--lib", default=None)

    p = sub.add_parser("register", help="注册一个库（name → 技能目录；自动创建 .nodekb 库根）")
    p.add_argument("name")
    p.add_argument("lib_dir", help="技能目录，如 F:\\ComfyUI\\.dsh\\skills\\about-comfyui")

    p = sub.add_parser("list", help="列出已注册的库")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("dump", help="导出整库为渲染 md 树")
    p.add_argument("--out", required=True)
    p.add_argument("--kb", default=None)
    p.add_argument("--lib", default=None)

    p = sub.add_parser("webui", help="启动只读本地 WebUI（人类可读界面，浏览器打开）")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8666)

    return parser


def _load(args, problems: Optional[list] = None) -> dict:
    return commands.load_library(getattr(args, "kb", None), getattr(args, "lib", None), problems)


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 CP936，中文会乱码：强制 UTF-8 输出
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        if args.command == "register":
            entry = commands.register_db(args.name, args.lib_dir)
            print(f"已注册: {args.name} -> {entry['path']}")
            print(f"库根: {entry['path']}\\.nodekb")
            return 0
        if args.command == "list":
            reg = commands.load_registry()
            if args.json:
                print(json_dumps(reg))
                return 0
            if not reg:
                print("（无已注册的库）")
                return 0
            for name, info in sorted(reg.items()):
                print(f"{name}\t{info.get('path')}\t库根={info.get('path')}\\.nodekb")
            return 0
        if args.command == "webui":
            from . import webui

            return webui.main(host=args.host, port=args.port)
        problems: list = []
        nodes = _load(args, problems)
        if args.command == "read":
            text, code = commands.cmd_read(nodes, args.target, node=args.node,
                                           raw=args.raw, as_json=args.json, toc=args.toc,
                                           maxlen=args.maxlen)
        elif args.command == "search":
            text, code = commands.cmd_search(nodes, args.query, type_=args.type,
                                             limit=args.limit, as_json=args.json,
                                             offset=args.offset, snippet=args.snippet)
        elif args.command == "diag":
            text, code = commands.cmd_diag(nodes, problems)
        elif args.command == "dump":
            text, code = commands.cmd_dump(nodes, args.out)
        else:
            text, code = f"未知命令: {args.command}", 2
    except (KeyError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 2
    print(text)
    return code


def json_dumps(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    sys.exit(main())
