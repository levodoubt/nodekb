"""render —— 基于内存节点模型的渲染层（md 即库，无持久化状态）。

- render_node / render_subtree：read 模式，[[TID]] 就地填充（transclusion 展开）。
- toc_lines：目录视图（tid · 标题 · 字符数，不渲染正文）。
- node_info：节点元信息（含 source 行号）。
- 环检测：展开路径重复出现同一 TID 抛 TransclusionError；悬空引用保留 [[TID]] 原文（diag 报告）。
"""

from __future__ import annotations

from typing import Optional

from . import parse


class TransclusionError(Exception):
    pass


def _children(nodes: dict[str, dict], tid: str) -> list[dict]:
    return sorted(
        (n for n in nodes.values() if n["parent_tid"] == tid),
        key=lambda n: (n["sort"], n["tid"]),
    )


def _has_children(nodes: dict[str, dict], tid: str) -> bool:
    return any(n["parent_tid"] == tid for n in nodes.values())


def _cycle_msg(seen: list[str], target: str, nodes: dict[str, dict]) -> str:
    msg = "循环引用: " + " -> ".join(seen + [target])
    node = nodes.get(target)
    if node and node.get("source"):
        msg += f"（重复节点源: {node['source']}）"
    return msg


def _project_container(nodes: dict[str, dict], tid: str, seen: list[str]) -> str:
    """容器节点（文件夹/文件）转译：整支子树投影（`## 标题` + 内容 + 子节递归）。

    seen 已含本 tid（由调用方标记访问），环检测在 _expand 层完成。
    """
    node = nodes[tid]
    parts = []
    title = node["title"] or tid
    if title != tid:  # 显式节点（title==tid）内联时不输出 `## tid` 标题，避免列表内噪音
        parts.append("## " + title)
    parts.append(_expand(node["content"], nodes, seen))
    for child in _children(nodes, tid):
        parts.append(_project_container(nodes, child["tid"], seen + [child["tid"]]))
    return "\n\n".join(parts)


def _expand(text: str, nodes: dict[str, dict], seen: list[str]) -> str:
    out: list[str] = []
    pos = 0
    for m in parse.REF_RE.finditer(text):
        out.append(text[pos : m.start()])
        target = m.group(1)
        if target in seen:
            raise TransclusionError(_cycle_msg(seen, target, nodes))
        nxt = seen + [target]
        if target in nodes:
            if _has_children(nodes, target):
                out.append(_project_container(nodes, target, nxt))
            else:
                out.append(_expand(nodes[target]["content"], nodes, nxt))
        else:
            out.append(m.group(0))  # 悬空：保留原文，diag 报告
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def render_node(nodes: dict[str, dict], tid: str) -> str:
    """渲染单节点内容（不含标题行）。"""
    node = nodes.get(tid)
    if node is None:
        raise KeyError(f"节点不存在: {tid}")
    return _expand(node["content"], nodes, [tid])


def render_subtree(nodes: dict[str, dict], tid: str, level: int = 1) -> str:
    """渲染整支：递归子树为带标题层级的 md。"""
    node = nodes.get(tid)
    if node is None:
        raise KeyError(f"节点不存在: {tid}")
    title = node["title"] or tid
    head = "#" * level + " " + title
    body = _expand(node["content"], nodes, [tid])
    parts = [head, body]
    for child in _children(nodes, tid):
        parts.append(render_subtree(nodes, child["tid"], level + 1))
    return "\n\n".join(parts)


def toc_lines(nodes: dict[str, dict], tid: str, level: int = 0) -> list[str]:
    """目录视图：每节点一行（tid · 标题 · 字符数）。"""
    node = nodes.get(tid)
    if node is None:
        return [f"未找到节点: {tid}"]
    lines = [f"{'  ' * level}- {node['tid']} · {node['title'] or '(无标题)'} · {len(node['content'])} 字符"]
    for child in _children(nodes, tid):
        lines.extend(toc_lines(nodes, child["tid"], level + 1))
    return lines


def node_info(nodes: dict[str, dict], tid: str) -> dict:
    node = nodes.get(tid)
    if node is None:
        raise KeyError(f"节点不存在: {tid}")
    return {
        "tid": node["tid"], "type": node["type"], "title": node["title"],
        "parent_tid": node["parent_tid"], "sort": node["sort"],
        "source": node["source"], "content": node["content"],
    }


def resolve_path(nodes: dict[str, dict], path: str) -> Optional[str]:
    """路径解析：精确 TID 优先；否则 TID 前缀唯一匹配。"""
    if path in nodes:
        return path
    hits = sorted(t for t in nodes if t == path or t.startswith(path + ":"))
    if len(hits) == 1:
        return hits[0]
    return None
