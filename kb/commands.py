"""NodeKB 命令逻辑（md 即库，零持久化状态）。

命令：read / search / diag / register / list / dump（edit 已删——修改 = 直接改 md）。
库 = 技能目录下多个 type 目录（doc/git-history/todo/handover/自定义），实时解析。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

from . import mdlib, parse, render, vcs

# ---------------------------------------------------------------- 库注册表

REGISTRY_PATH = str(Path(__file__).resolve().parent.parent / "kb_registry.json")


def load_registry() -> dict:
    if not os.path.isfile(REGISTRY_PATH):
        return {}
    try:
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("libraries", {}) if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_registry(reg: dict) -> None:
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump({"libraries": reg}, f, ensure_ascii=False, indent=2)


def register_db(name: str, lib_dir: str) -> dict:
    """注册一个库。技能目录下自动创建 .nodekb 作为库根，并自动初始化内嵌 git 仓库。"""
    base = Path(lib_dir).resolve()
    nodekb = base / ".nodekb"
    nodekb.mkdir(parents=True, exist_ok=True)
    vcs.init(str(nodekb))  # 版本控制：自动初始化（git 缺失时静默跳过）
    reg = load_registry()
    reg[name] = {"path": str(base)}
    save_registry(reg)
    return reg[name]


def unregister_db(name: str) -> None:
    reg = load_registry()
    reg.pop(name, None)
    save_registry(reg)


def lib_dir_of(kb: Optional[str], lib: Optional[str]) -> str:
    """定位库根：lib（技能目录或 .nodekb 路径）优先，否则注册表 kb 名。返回 .nodekb 目录。

    lib 传入技能目录或 .nodekb 路径均可；找不到时报错同时给出原参数，避免被拼接路径误导。
    """
    if lib:
        p = Path(lib)
        nodekb = str(p if p.name == ".nodekb" else p / ".nodekb")
        if not os.path.isdir(nodekb):
            raise ValueError(f"库目录不存在: {nodekb}（你传入: {lib}）")
        return nodekb
    if kb:
        info = load_registry().get(kb) or {}
        if not info:
            raise KeyError(f"未注册的库: {kb}（用 kb register <名称> <技能目录>）")
        nodekb = str(Path(info["path"]) / ".nodekb")
        if not os.path.isdir(nodekb):
            raise ValueError(f"库目录不存在: {nodekb}（注册表 {kb} 指向 {info.get('path')}）")
        return nodekb
    raise ValueError("未指定库：用 --kb <注册名> 或 --lib <技能目录/.nodekb>")


def load_library(
    kb: Optional[str] = None,
    lib: Optional[str] = None,
    problems: Optional[list] = None,
) -> dict[str, dict]:
    """解析 .nodekb 库为节点映射。problems 传入列表时：重复 TID 降级跳过并记录。

    解析成功后触发自动快照：若 .nodekb 已初始化内嵌 git 仓库且有变更则自动 commit。
    """
    nodekb = lib_dir_of(kb, lib)
    nodes = mdlib.parse_library(nodekb, problems)
    vcs.maybe_autosnap(nodekb)
    return nodes


# ---------------------------------------------------------------- vcs

def cmd_vcs(kb: Optional[str], lib: Optional[str], action: str, msg: Optional[str] = None) -> tuple[str, int]:
    nodekb = lib_dir_of(kb, lib)
    if action == "init":
        return vcs.init(nodekb), 0
    if action == "status":
        return json.dumps(vcs.status(nodekb), ensure_ascii=False, indent=2), 0
    if action == "commit":
        return vcs.commit(nodekb, msg or "kb commit"), 0
    return f"未知 vcs 动作: {action}", 2


# ---------------------------------------------------------------- read

# 整支渲染字符上限（0 = 不限）。防止一次调用打爆上下文（root ≈ 23.5 万字符）。
DEFAULT_MAXLEN = 50000


def cmd_read(
    nodes: dict[str, dict],
    target: str,
    node: bool = False,
    raw: bool = False,
    as_json: bool = False,
    toc: bool = False,
    maxlen: int = 0,
) -> tuple[str, int]:
    try:
        tid = render.resolve_path(nodes, target)
        if tid is None:
            cands = sorted({t for t in nodes if t.startswith(target) or t.startswith(target + ":")})[:10]
            msg = f"未找到节点: {target}"
            if cands:
                msg += "；候选: " + "、".join(cands)
            return msg, 2
        if toc:
            out = "\n".join(render.toc_lines(nodes, tid))
        elif raw:
            out = json.dumps(render.node_info(nodes, tid), ensure_ascii=False, indent=2)
        elif node:
            out = render.render_node(nodes, tid)
            kids = [c for c in nodes.values() if c["parent_tid"] == tid]
            if kids:  # 反直觉提示：带 ## 子节的页面 --node 只回前言
                out += f"\n\n（本节点含 {len(kids)} 个子节：正文在子节里；看结构用 --toc，看整支不传 --node）"
        else:
            out = render.render_subtree(nodes, tid)
            if maxlen and len(out) > maxlen:  # 大小护栏：只对整支渲染生效
                return (f"渲染超上限: {len(out)} 字符 > {maxlen}。"
                        f"建议 --node 单节点或指定小节 tid；如确实需要整支，用 --maxlen 0 强制全量。"), 2
        if as_json and not raw and not toc:
            out = json.dumps({"tid": tid, "text": out}, ensure_ascii=False, indent=2)
        return out, 0
    except render.TransclusionError as e:
        return f"错误: {e}", 2
    except KeyError as e:
        return str(e), 2


# ---------------------------------------------------------------- search

# 中文虚词 2-gram（检索分词时过滤）
_STOP_GRAMS = {
    "怎么", "如何", "是否", "什么", "为什么", "一个", "这种", "那个", "这个",
    "他们", "我们", "你们", "进行", "以及", "还是", "就是", "不是", "没有",
    "可以", "需要", "问题", "情况", "时候", "地方", "东西", "因为", "所以",
    "但是", "然后", "接着", "开始", "最后", "主要", "目前", "已经", "现在",
    "等等", "如果", "那么", "就是", "不能", "不会", "应该", "可能",
}


def _search_terms(query: str) -> list[str]:
    """query → 检索 term：非中文 token 原样；连续中文按 2-gram 拆分并过滤虚词。"""
    terms: list[str] = []
    for tok in re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9_.-]+", query):
        if re.fullmatch(r"[\u4e00-\u9fff]+", tok):
            if len(tok) <= 2:
                if tok not in _STOP_GRAMS:
                    terms.append(tok)
                continue
            seen: set[str] = set()
            for i in range(len(tok) - 1):
                g = tok[i : i + 2]
                if g not in seen and g not in _STOP_GRAMS:
                    seen.add(g)
                    terms.append(g)
                if len(terms) >= 10:
                    break
        else:
            terms.append(tok)
    return list(dict.fromkeys(terms))


def _stable_tid(nodes: dict[str, dict], tid: str) -> str:
    """位置型段落 TID 提升为稳定句柄：沿 parent 上溯到文件/显式节点/文件夹。"""
    cur = nodes[tid]
    while cur.get("positional") and cur["parent_tid"] in nodes:
        cur = nodes[cur["parent_tid"]]
    return cur["tid"]


def cmd_search(
    nodes: dict[str, dict],
    query: str,
    type_: Optional[str] = None,
    limit: int = 10,
    as_json: bool = False,
    offset: int = 0,
    snippet: int = 240,
) -> tuple[str, int]:
    terms = _search_terms(query)
    idx: dict[str, set[str]] = {}
    for node in nodes.values():
        text = f"{node['title']}\n{node['content']}\n{node['tid']}".lower()
        grams: set[str] = set()
        for tok in re.findall(r"[\u4e00-\u9fff]+|[a-z0-9_]+", text):
            if tok.isascii():
                grams.add(tok)
            else:
                for i in range(len(tok) - 1):
                    grams.add(tok[i : i + 2])
        for g in grams:
            idx.setdefault(g, set()).add(node["tid"])

    scores: dict[str, int] = {}
    for g in terms:
        for tid in idx.get(g, ()):
            scores[tid] = scores.get(tid, 0) + 1
    rows: list = []
    if scores:
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], len(nodes[kv[0]]["content"])))
        for tid, _score in ranked:
            node = nodes[tid]
            if type_ and node["type"] != type_:
                continue
            rows.append(node)
    if not rows:  # LIKE 兜底
        for node in nodes.values():
            if type_ and node["type"] != type_:
                continue
            if query not in node["title"] and query not in node["content"] and query not in node["tid"]:
                continue
            rows.append(node)
    total = len(rows)
    hits = []
    for node in rows[offset : offset + limit]:
        try:
            text = render.render_node(nodes, node["tid"])
        except render.TransclusionError:
            text = node["content"]
        idx0 = text.find(terms[0]) if terms else -1
        if idx0 < 0:
            idx0 = 0
        stable = _stable_tid(nodes, node["tid"])
        half = max(40, snippet // 2)
        hits.append({
            # tid=稳定句柄（位置型段落上溯到文件/显式节点），ref=实际命中节点，positional 标记
            "tid": stable, "ref": node["tid"], "positional": bool(node.get("positional")),
            "type": node["type"], "title": node["title"],
            "source": node["source"],
            "snippet": text[max(0, idx0 - half) : idx0 + half + 1],  # 保留换行/缩进，不再压平
        })
    if as_json:
        return json.dumps({"total": total, "count": len(hits), "offset": offset, "hits": hits},
                          ensure_ascii=False, indent=2), 0
    lines = [f"{h['tid']}  [{h['type']}] {h['title']}\n    …{h['snippet']}…" for h in hits]
    return "\n".join(lines) if lines else f"无匹配: {query}", 1 if not hits else 0


# ---------------------------------------------------------------- diag

_POSITIONAL_SEG = re.compile(r"^\d+(\.\d+)*$")
_DUP_MIN_LEN = 40  # 视为漂移候选的文本块最短长度
_DUP_NAV_ALNUM = 24  # 去掉链接/URL 后实义字符少于此值 → 导航/出处样板
_IGNORE_FILE = "diag_ignore.json"  # 库根的本地豁免（不进代码）：{"blocks": ["正则"], "lines": ["正则"]}
_URL_RE = re.compile(r"https?://\S+")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_REF_RE = re.compile(r"\[\[[^\]]*\]\]")
_ALNUM_RE = re.compile(r"[\w\u4e00-\u9fff]")
_BULLET_RE = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)")


def _lib_root_of(nodes: dict[str, dict]) -> Optional[Path]:
    """从节点 source 反查库根（.nodekb 目录），用于读本地豁免文件。"""
    for n in nodes.values():
        src = (n.get("source") or "").split("#")[0]
        if not src:
            continue
        for parent in Path(src).parents:
            if parent.name == ".nodekb":
                return parent
    return None


def _compile_rules(items) -> list:
    out = []
    for item in items or []:
        try:
            out.append(re.compile(str(item)))
        except re.error:
            continue
    return out


def _load_ignore(lib_root: Optional[Path]) -> tuple[list, list]:
    """读库根的 diag_ignore.json：{"blocks": [...], "lines": [...]}，两项都是正则列表。"""
    if lib_root is None:
        return [], []
    path = lib_root / _IGNORE_FILE
    if not path.is_file():
        return [], []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], []
    if not isinstance(data, dict):
        return [], []
    return _compile_rules(data.get("blocks")), _compile_rules(data.get("lines"))


def _norm(blk: str) -> str:
    return " ".join(blk.split())


def _is_boilerplate(blk: str) -> bool:
    """样板判定：导航/出处注记、纯链接、URL、HTML 碎片、参数块。

    这些块跨页面「重复」是设计使然（上级索引行、官方推荐参数原样搬运、模型卡同作者声明），
    一旦当成漂移上报，健康检查就长期变红、随后被无视——比不检查更糟。
    """
    s = blk.strip()
    if not s:
        return True
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    # 引用块先剥掉「>」行（导航/出处注记），再看剩下是否还有实质内容
    body = [ln for ln in lines if not ln.startswith(">")]
    if not body:
        return True  # 整块都是引用注记（上级索引 / 出处说明 / 例图指引），不是正文
    core = body
    first = core[0].lstrip("*_> ").strip()
    if first.startswith("<"):
        return True  # HTML 碎片
    if _URL_RE.fullmatch(first):
        return True  # 裸 URL 行
    joined = "\n".join(core)
    # 导航块里链接文本本身就是文件名，不能算「内容」：整段链接先剔除再计实义字符
    stripped = _REF_RE.sub("", _MD_LINK_RE.sub("", _URL_RE.sub("", joined)))
    if len(_ALNUM_RE.findall(stripped)) < _DUP_NAV_ALNUM:
        return True  # 去掉链接后几乎没内容
    if all(_BULLET_RE.match(ln) or ln.startswith("|") for ln in core) and not any(
        c in joined for c in "。，"
    ):
        return True  # 整块都是列表项/表格行且无叙述句（参数块）
    return False


def _dup_blocks(nodes: dict[str, dict], ignore: list = ()) -> list[str]:
    """内容漂移：物理重复的文本块（同一段文字出现在 2+ 节点，且不是转译引用 / 样板）。"""
    by_block: dict[str, list[str]] = {}
    for n in nodes.values():
        for blk in re.split(r"\n\s*\n", n["content"]):
            b = _norm(blk)
            if len(b) < _DUP_MIN_LEN or _is_boilerplate(blk):
                continue
            if any(rx.search(b) for rx in ignore):
                continue
            by_block.setdefault(b, []).append(n["tid"])
    out = []
    for b, tids in by_block.items():
        uniq = sorted(set(tids))
        if len(uniq) >= 2:  # 跨节点漂移；单节点内部重复不报
            out.append(f"内容重复（可能漂移）: {', '.join(uniq)} 共有块「{b[:60]}{'…' if len(b) > 60 else ''}」")
    return out[:20]


def _intra_dup_lines(nodes: dict[str, dict], ignore: list = ()) -> list[str]:
    """节点内重复行：同一节点里 ≥40 字符的正文行出现 2+ 次（整段拷贝的漂移源）。

    跳过代码围栏内行（copy-ready 块可有意重复）、表格行、纯符号行、样板行，避免误报。
    """
    out = []
    for n in nodes.values():
        counts: dict[str, int] = {}
        fenced = False
        for line in n["content"].splitlines():
            s = line.strip()
            if s.startswith("```"):
                fenced = not fenced
                continue
            if fenced or s.startswith("|") or not s:
                continue
            if len(s) >= 40 and any(c.isalnum() for c in s):
                if _is_boilerplate(s) or any(rx.search(s) for rx in ignore):
                    continue
                counts[s] = counts.get(s, 0) + 1
        for s, c in counts.items():
            if c >= 2:
                out.append(f"节点内重复行: {n['tid']} 出现 {c} 次「{s[:60]}{'…' if len(s) > 60 else ''}」")
                break  # 每节点只报 1 条，避免刷屏
    return out[:20]


def cmd_diag(
    nodes: dict[str, dict],
    problems: Optional[list] = None,
    strict: bool = False,
    lib_root: Optional[Path] = None,
) -> tuple[str, int]:
    """自检。

    errors  = 真损坏（悬空/位置型引用、循环、孤儿、重复 TID）→ 退出码 2。
    warnings = 疑似漂移（重复块 / 节点内重复行），默认不影响退出码；
               需要零容忍时用 strict=True（CLI `--strict`）把它们也升为失败。
    """
    errors = list(problems or [])
    for node in nodes.values():
        for ref_tid in parse.extract_refs(node["content"]):
            if ref_tid not in nodes:
                errors.append(f"悬空引用: {node['tid']} → [[{ref_tid}]]")
            elif len(ref_tid.split(":")) >= 3 and _POSITIONAL_SEG.match(ref_tid.split(":")[-1]):
                # 位置型段落 TID（文件:序号）：插章节就漂移，禁止作为引用目标
                errors.append(f"位置型 TID 引用（插章节会漂移）: {node['tid']} → [[{ref_tid}]]")
    for tid in nodes:
        try:
            render.render_node(nodes, tid)
        except render.TransclusionError as e:
            errors.append(f"循环引用 @{tid}: {e}")
    for node in nodes.values():
        if node["parent_tid"] is not None and node["parent_tid"] not in nodes:
            errors.append(f"孤儿节点: {node['tid']} (父 {node['parent_tid']} 不存在)")
    _detect_tree_cycles(nodes, errors)

    root = lib_root or _lib_root_of(nodes)
    ignore_blocks, ignore_lines = _load_ignore(root)
    warnings = _dup_blocks(nodes, ignore_blocks) + _intra_dup_lines(nodes, ignore_lines)

    code = 2 if errors or (strict and warnings) else 0
    report = {
        "exit_code": code,
        "errors": errors,
        "warnings": warnings,
        "node_count": len(nodes),
        "types": _type_counts(nodes),
    }
    if not errors and not warnings:
        report["status"] = "ok"
    return json.dumps(report, ensure_ascii=False, indent=2), code


def _detect_tree_cycles(nodes: dict[str, dict], problems: list) -> None:
    for tid in nodes:
        cur = tid
        seen: set[str] = set()
        while cur is not None and cur in nodes:
            if cur in seen:
                problems.append(f"树环: {' -> '.join(list(seen) + [cur])}")
                break
            seen.add(cur)
            cur = nodes[cur]["parent_tid"]


def _type_counts(nodes: dict[str, dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for n in nodes.values():
        counts[n["type"]] = counts.get(n["type"], 0) + 1
    return dict(sorted(counts.items()))


# ---------------------------------------------------------------- dump

def cmd_dump(nodes: dict[str, dict], out_dir: str) -> tuple[str, int]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for tid in mdlib.lib_root_tids(nodes):
        text = render.render_subtree(nodes, tid)
        path = out / f"{tid}.md"
        path.write_text(text, encoding="utf-8")
        written.append(str(path))
    return json.dumps({"written": written}, ensure_ascii=False, indent=2), 0
