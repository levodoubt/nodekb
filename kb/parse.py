"""tscl 语法解析：<tscl id="TID"> 定义 与 [[TID]] 引用。

语法规范（SPEC §4）：
- 定义：<tscl id="TID">任意文本</tscl>（ID 单点声明，闭合标签无参；允许跨行与嵌套）
- 引用：[[TID]]
"""

from __future__ import annotations

import re
from typing import Iterator

TSCL_RE = re.compile(r'<tscl id="([^"]+)">(.*?)</tscl>', re.S)
REF_RE = re.compile(r"\[\[([a-zA-Z0-9\u4e00-\u9fff:._-]+)\]\]")

# 允许 CJK：中文文件名/标题可进入 TID（可读性优先）
CJK = r"\u4e00-\u9fff"
TID_PATTERN = rf"[a-z0-9{CJK}][a-z0-9{CJK}:._-]*"
TID_RE = re.compile(f"^{TID_PATTERN}$")

# 节点类型名：小写字母/数字/CJK 开头，仅 a-z0-9 CJK _ -；不含冒号（避免与 TID 前缀分隔符混淆）
TYPE_RE = re.compile(rf"^[a-z0-9{CJK}][a-z0-9{CJK}_-]*$")


def is_valid_tid(tid: str) -> bool:
    """TID 合法性：小写字母/数字/CJK 开头，仅含 a-z0-9 CJK : . _ -。"""
    return bool(TID_RE.match(tid))


def is_valid_type(type_: str) -> bool:
    """节点类型名（可自定义）：小写字母/数字/CJK 开头，仅 a-z0-9 CJK _ -，不含冒号。"""
    return bool(TYPE_RE.match(type_))


def slugify(name: str) -> str:
    """文件名/标题 → TID 段：保留 CJK/数字/字母/._-，空白与标点转 '-', 压缩连续 '-'。"""
    s = name.lower()
    s = re.sub(r"[^\w\u4e00-\u9fff._-]", "-", s, flags=re.UNICODE)
    s = re.sub(r"-+", "-", s)
    return s.strip("-_")


def extract_defs(content: str) -> list[tuple[str, str]]:
    """提取全部 <tscl> 定义，返回 [(tid, 文本)]（保序）。"""
    return [(m.group(1), m.group(2)) for m in TSCL_RE.finditer(content)]


def extract_refs(content: str) -> list[str]:
    """提取全部 [[TID]] 引用，返回 [tid]（保序）。"""
    return [m.group(1) for m in REF_RE.finditer(content)]


def iter_defs(content: str) -> Iterator[tuple[str, str]]:
    for m in TSCL_RE.finditer(content):
        yield m.group(1), m.group(2)


def strip_tags(content: str) -> str:
    """剥离 <tscl> 标签本身，保留内部文本（渲染投影的基础变换）。"""
    return TSCL_RE.sub(r"\2", content)


def find_duplicate_defs(content: str) -> list[str]:
    """同一节点内重复定义的 tid。"""
    seen: dict[str, int] = {}
    for tid, _ in extract_defs(content):
        seen[tid] = seen.get(tid, 0) + 1
    return [tid for tid, n in seen.items() if n > 1]
