"""mdlib —— md 即库的解析层（零持久化状态）。

库根 = 技能文件夹下 `.nodekb/`，递归解析其内全部 md。模型统一：
- 文件夹 → 节点（type=文件夹名，parent=父文件夹）
- md 文件 → 文件节点（tid=`{文件夹tid}:{文件名}`，parent=所在文件夹）
- `<node name="X" parent="Y" type="Z">文本</node>` 显式节点：
  parent 缺省 = 文件内第一个 `<node>` 段的 name（文件根），否则文件节点
  type 缺省 = 所在文件夹名
- 非节点文本按最近 `##` H2 拆分为隐式节点：title=H2 标题，tid=`{文件tid}:{章节号}`，
  parent 缺省规则同显式节点

所有文本皆节点；content 为原文（含 `[[TID]]` 引用），渲染层展开。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from . import parse

H1_RE = re.compile(r"^#\s+(.*)$")
H2_RE = re.compile(r"^##\s+(.*)$")
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
NUM_HEAD = re.compile(r"^\d+(\.\d+)*$")

ROOT_TID = "root"


def section_tid(file_tid: str, title: str, idx: int) -> str:
    """段级 TID：标题首 token 为数字编号时用编号，否则用序号。"""
    first = title.split(None, 1)[0].rstrip("。：:") if title else ""
    if NUM_HEAD.match(first):
        return f"{file_tid}:{first}"
    return f"{file_tid}:{idx}"


def _new_node(tid, title, type_, parent, sort, source, content=None) -> dict:
    return {
        "tid": tid, "title": title, "type": type_, "parent_tid": parent,
        "sort": sort, "content": [] if content is None else content, "source": source,
    }


def parse_file(path: Path, file_tid: str, folder_type: str, parent_tid: str) -> list[dict]:
    """解析单个 md 文件为节点列表（文件节点 + 隐式 H2 段 + 显式 <node>，按物理行序）。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    rel = path.as_posix()

    h1: Optional[str] = None
    h1_line = 0
    for lineno, line in enumerate(lines, start=1):
        m = H1_RE.match(line)
        if m:
            h1 = m.group(1).strip()
            h1_line = lineno
            break

    nodes: list[dict] = []
    file_node = _new_node(file_tid, h1 or path.stem, folder_type, parent_tid, 0.0,
                          f"{rel}#L1-L{len(lines)}")
    nodes.append(file_node)

    first_node_tid: Optional[str] = None  # 文件根（第一个 <node> 的 name）
    sec_node: Optional[dict] = None
    sec_index = 0
    stack: list[dict] = []  # 显式 <node> 嵌套栈

    def default_parent() -> str:
        return first_node_tid if first_node_tid else file_tid

    for lineno, line in enumerate(lines, start=1):
        if lineno == h1_line:
            continue
        if stack:
            if line.strip() == "</node>":
                stack.pop()
                continue
            if "<node" in line:  # 内层 <node>（须单行闭合）
                attrs = dict(ATTR_RE.findall(line))
                name = attrs.get("name", "").strip()
                if name:
                    n = _new_node(name, name, attrs.get("type", "").strip() or folder_type,
                                  attrs.get("parent", "").strip() or default_parent(),
                                  float(lineno), f"{rel}#L{lineno}")
                    nodes.append(n)
                    gt = line.find(">")
                    rest = line[gt + 1 :] if gt >= 0 else ""
                    if "</node>" in rest:
                        n["content"].append(rest.split("</node>")[0])
                        after = rest.split("</node>", 1)[1]
                        if after:
                            stack[-1]["content"].append(after)
                continue
            stack[-1]["content"].append(line)
            continue
        if line.lstrip().startswith("<node"):
            attrs = dict(ATTR_RE.findall(line))
            name = attrs.get("name", "").strip()
            if name:
                parent = attrs.get("parent", "").strip() or default_parent()
                ptype = attrs.get("type", "").strip() or folder_type
                n = _new_node(name, name, ptype, parent, float(lineno),
                              f"{rel}#L{lineno}")
                nodes.append(n)
                if first_node_tid is None:
                    first_node_tid = name
                gt = line.find(">")
                rest = line[gt + 1 :] if gt >= 0 else ""
                if "</node>" in rest:  # 单行 <node>…文本…</node>
                    n["content"].append(rest.split("</node>")[0])
                else:
                    stack.append(n)
            continue
        m2 = H2_RE.match(line)
        if m2:
            sec_index += 1
            title = m2.group(1).strip() or "(unnamed)"
            tid = section_tid(file_tid, title, sec_index)
            sec_node = _new_node(tid, title, folder_type, default_parent(), float(lineno),
                                 f"{rel}#L{lineno}")
            nodes.append(sec_node)
            continue
        (sec_node or file_node)["content"].append(line)

    for n in nodes:
        n["content"] = "\n".join(n["content"]).strip()
    return nodes


def _folder_tid(rel_parts: tuple[str, ...]) -> str:
    if not rel_parts:
        return ROOT_TID
    return ":".join(parse.slugify(p) for p in rel_parts)


def parse_library(lib_dir: str) -> dict[str, dict]:
    """解析 `.nodekb/` 库为节点映射。递归：文件夹 → 节点，md → 文件节点 + 内容节点。"""
    root = Path(lib_dir)
    if not root.is_dir():
        raise ValueError(f"库目录不存在: {lib_dir}")
    nodes: dict[str, dict] = {
        ROOT_TID: _new_node(ROOT_TID, ".nodekb", "root", None, 0.0, "", content=""),
    }

    for dirpath, dirnames, filenames in os.walk(root):
        d = Path(dirpath)
        rel = d.relative_to(root).parts
        folder_tid = _folder_tid(rel)
        folder_type = parse.slugify(rel[-1]) if rel else "root"
        parent_tid = _folder_tid(rel[:-1])
        if folder_tid != ROOT_TID:
            if folder_tid in nodes:
                raise ValueError(f"重复 TID: {folder_tid}（文件夹冲突）")
            nodes[folder_tid] = _new_node(folder_tid, rel[-1], folder_type, parent_tid,
                                          float(len(rel)), "", content="")
        for name in sorted(filenames):
            if not name.endswith(".md"):
                continue
            md = d / name
            file_tid = f"{folder_tid}:{parse.slugify(Path(name).stem)}" if folder_tid != ROOT_TID \
                else parse.slugify(Path(name).stem)
            for node in parse_file(md, file_tid, folder_type, folder_tid):
                if node["tid"] in nodes:
                    raise ValueError(f"重复 TID: {node['tid']}（{md.name} 与现有节点冲突）")
                nodes[node["tid"]] = node
    return nodes


def lib_root_tids(nodes: dict[str, dict]) -> list[str]:
    """一级节点列表（parent 为 None）。"""
    return [n["tid"] for n in sorted(
        (n for n in nodes.values() if n["parent_tid"] is None),
        key=lambda n: n["sort"],
    )]
