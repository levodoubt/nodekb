"""NodeKB MCP 独立启动入口（不依赖 PYTHONPATH 与 cwd）。

供 Trae 等 MCP 客户端以绝对路径方式启动：python run_mcp.py
启动失败时错误写 stderr（多数客户端会显示）。
"""

import os
import sys

_NODEKB_ROOT = os.path.dirname(os.path.abspath(__file__))
if _NODEKB_ROOT not in sys.path:
    sys.path.insert(0, _NODEKB_ROOT)

try:
    from kb.mcp_server import serve
except Exception as e:
    print(f"nodekb MCP 启动失败: {e}", file=sys.stderr)
    sys.exit(1)

if __name__ == "__main__":
    sys.exit(serve())
