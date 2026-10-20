"""NodeKB 核心回归测试（md 即库：.nodekb 递归解析 → 节点树 → 命令）。"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from kb import commands, mdlib, render


def make_lib(files: dict[str, str], sub: str = "doc") -> str:
    """建临时技能目录（.nodekb/<sub>/…），返回技能目录路径。"""
    tmp = Path(tempfile.mkdtemp())
    nodekb = tmp / ".nodekb"
    (nodekb / sub).mkdir(parents=True)
    for name, text in files.items():
        (nodekb / sub / name).write_text(text, encoding="utf-8")
    return str(tmp)


def parse(tmp: str) -> dict:
    return mdlib.parse_library(str(Path(tmp) / ".nodekb"))


class TestParse(unittest.TestCase):
    def test_folder_and_file_nodes(self):
        tmp = make_lib({"01-概述.md": "# 概述\n\n## 1.1 目标\n\n正文A。\n"})
        nodes = parse(tmp)
        self.assertIn("root", nodes)
        self.assertIn("doc", nodes)  # 文件夹节点
        self.assertEqual(nodes["doc"]["type"], "doc")
        self.assertIn("doc:01-概述", nodes)  # 文件节点
        self.assertEqual(nodes["doc:01-概述"]["parent_tid"], "doc")
        self.assertIn("doc:01-概述:1.1", nodes)
        self.assertEqual(nodes["doc:01-概述:1.1"]["content"], "正文A。")

    def test_custom_folder_type(self):
        # ModelInfo 自定义文件夹 → type=modelinfo
        tmp = make_lib({"readme.md": "# 模型信息\n"}, sub="ModelInfo")
        nodes = parse(tmp)
        self.assertIn("modelinfo", nodes)
        self.assertEqual(nodes["modelinfo"]["type"], "modelinfo")
        self.assertIn("modelinfo:readme", nodes)
        self.assertEqual(nodes["modelinfo:readme"]["type"], "modelinfo")

    def test_first_node_is_file_root(self):
        # parent 缺省 = 文件内第一个 <node> 段 name
        tmp = make_lib({"02.md": "<node name=\"a\">根\n<node name=\"b\">子</node>\n</node>\n"})
        nodes = parse(tmp)
        self.assertEqual(nodes["a"]["parent_tid"], "doc:02")  # 第一个 node → 文件节点
        self.assertEqual(nodes["b"]["parent_tid"], "a")  # 后续 → 文件根
        self.assertEqual(nodes["b"]["content"], "子")

    def test_no_node_parent_to_file(self):
        # 无 <node> 的文件：H2 段 parent = 文件节点
        tmp = make_lib({"01.md": "## 1.1\n\n正文。\n"})
        nodes = parse(tmp)
        self.assertEqual(nodes["doc:01:1.1"]["parent_tid"], "doc:01")

    def test_explicit_node_full_attrs(self):
        tmp = make_lib({"03.md": "<node name=\"a\" parent=\"b\" type=\"fact\">值</node>\n"})
        nodes = parse(tmp)
        self.assertEqual(nodes["a"]["parent_tid"], "b")
        self.assertEqual(nodes["a"]["type"], "fact")

    def test_duplicate_tid_raises(self):
        tmp = make_lib({"01.md": "<node name=\"x\">1</node>\n", "02.md": "<node name=\"x\">2</node>\n"})
        with self.assertRaises(ValueError):
            parse(tmp)


class TestRender(unittest.TestCase):
    def test_transclusion_expand(self):
        tmp = make_lib({"02.md": "## 2.1\n\n版本是 [[fact:ver]]。\n"})
        nodekb = Path(tmp) / ".nodekb" / "doc"
        (nodekb / "00.md").write_text("<node name=\"fact:ver\">20261003.0.0</node>\n", encoding="utf-8")
        nodes = parse(tmp)
        text = render.render_node(nodes, "doc:02:2.1")
        self.assertIn("版本是 20261003.0.0。", text)
        self.assertNotIn("[[fact:ver]]", text)

    def test_cycle_detected(self):
        tmp = make_lib({"a.md": "<node name=\"a\">见 [[b]]</node>\n", "b.md": "<node name=\"b\">见 [[a]]</node>\n"})
        nodes = parse(tmp)
        with self.assertRaises(render.TransclusionError):
            render.render_node(nodes, "a")

    def test_dangling_ref_diag(self):
        tmp = make_lib({"01.md": "见 [[nope]]。\n"})
        nodes = parse(tmp)
        out, code = commands.cmd_diag(nodes)
        self.assertEqual(code, 2)
        self.assertIn("悬空引用", out)

    def test_render_subtree(self):
        tmp = make_lib({"01.md": "# 标题\n\n## 1.1\n\n正文。\n"})
        nodes = parse(tmp)
        text = render.render_subtree(nodes, "doc:01")
        self.assertIn("# 标题", text)
        self.assertIn("## 1.1", text)


class TestCommands(unittest.TestCase):
    def test_read_node_and_toc(self):
        tmp = make_lib({"01.md": "# 概述\n\n## 1.1\n\n正文A。\n"})
        nodes = parse(tmp)
        text, code = commands.cmd_read(nodes, "doc:01:1.1", node=True)
        self.assertEqual(code, 0)
        self.assertEqual(text, "正文A。")
        toc, _ = commands.cmd_read(nodes, "doc", toc=True)
        self.assertIn("doc:01", toc)

    def test_search_chinese(self):
        tmp = make_lib({"01.md": "## 1.1\n\n出图后脸崩了应该修脸。\n"})
        nodes = parse(tmp)
        out, code = commands.cmd_search(nodes, "脸崩", as_json=True)
        self.assertEqual(code, 0)
        self.assertIn("doc:01:1.1", out)

    def test_search_multiword(self):
        tmp = make_lib({
            "01.md": "## 1.1\n\n白模测试 denoise 参数。\n",
            "02.md": "## 2.1\n\n白模控制。\n",
        })
        nodes = parse(tmp)
        out, code = commands.cmd_search(nodes, "白模 denoise", as_json=True)
        hits = json.loads(out)["hits"]
        self.assertEqual(hits[0]["ref"], "doc:01:1.1")  # 命中节点
        self.assertEqual(hits[0]["tid"], "doc:01")      # 稳定句柄（位置型段落上溯到文件）
        self.assertTrue(hits[0]["positional"])

    def test_register_creates_nodekb(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        commands.register_db("t", str(tmp))
        self.assertTrue((tmp / ".nodekb").is_dir())
        reg = commands.load_registry()
        self.assertEqual(reg["t"]["path"], str(tmp.resolve()))


class TestFixes(unittest.TestCase):
    """反馈修复回归（A 组正确性 / B5 护栏 / C7 降级 / D13 候选 / E16-17 内容校验）。"""

    def test_fence_not_split(self):  # A1
        tmp = make_lib({"01.md": "# F\n\n```bash\n## not a heading\nls\n```\n\n## Real\n正文\n"})
        nodes = parse(tmp)
        self.assertNotIn("doc:01:not a heading", nodes)  # 围栏内 ## 不切分
        self.assertIn("doc:01:1", nodes)  # 真正的 H2 段（title=Real）
        self.assertEqual(nodes["doc:01:1"]["title"], "Real")
        self.assertIn("## not a heading\nls", nodes["doc:01"]["content"])  # 围栏块完整保留
        self.assertIn("```bash", nodes["doc:01"]["content"])

    def test_bom_stripped(self):  # A2
        tmp = make_lib({"01.md": "\ufeff# 真标题\n\n正文\n"})
        nodes = parse(tmp)
        self.assertEqual(nodes["doc:01"]["title"], "真标题")  # BOM 不吞 H1
        self.assertNotIn("\ufeff", nodes["doc:01"]["content"])

    def test_container_transclusion_renders_children(self):  # A3
        tmp = make_lib({"02.md": "## Alpha\n\nAAA\n\n## Beta\n\nBBB\n"})
        nodekb = Path(tmp) / ".nodekb" / "doc"
        (nodekb / "entry.md").write_text("# 入口\n\n[[doc:02]]\n", encoding="utf-8")
        nodes = parse(tmp)
        text = render.render_node(nodes, "doc:entry")
        self.assertIn("AAA", text)
        self.assertIn("BBB", text)
        self.assertNotIn("[[doc:02]]", text)

    def test_mixed_structure_transclusion(self):  # A4
        tmp = make_lib({"01.md": "# Mix\n\n<node name=\"mix:root\">根</node>\n\n## Section\n分节\n"})
        nodekb = Path(tmp) / ".nodekb" / "doc"
        (nodekb / "entry.md").write_text("# 入口\n\n[[doc:01]]\n", encoding="utf-8")
        nodes = parse(tmp)
        text = render.render_node(nodes, "doc:entry")
        self.assertIn("分节", text)  # 文件节点转译应含子节（不再因 content 为空而空白）

    def test_read_maxlen_guard(self):  # B5
        body = "\n\n".join(f"## 1.{i}\n\n{'正文' * 30}" for i in range(1, 41))
        tmp = make_lib({"01.md": "# 大\n\n" + body + "\n"})
        nodes = parse(tmp)
        text, code = commands.cmd_read(nodes, "doc:01", maxlen=1000)
        self.assertEqual(code, 2)
        self.assertIn("渲染超上限", text)
        text, code = commands.cmd_read(nodes, "doc:01", maxlen=0)
        self.assertEqual(code, 0)
        self.assertIn("## 1.1", text)

    def test_duplicate_degrade_with_problems(self):  # C7
        tmp = make_lib({"01.md": "<node name=\"x\">1</node>\n", "02.md": "<node name=\"x\">2</node>\n"})
        probs = []
        nodes = commands.load_library(lib=str(tmp), problems=probs)
        self.assertEqual(nodes["x"]["content"], "1")  # 首见者生效
        self.assertTrue(any("重复 TID: x" in p for p in probs))
        out, code = commands.cmd_diag(nodes, probs)
        self.assertEqual(code, 2)
        self.assertIn("重复 TID: x", out)

    def test_ambiguous_prefix_lists_candidates(self):  # D13
        def n(tid):
            return {"tid": tid, "title": tid, "type": "doc", "parent_tid": "root",
                    "sort": 0.0, "content": "", "source": "x.md#L1"}
        nodes = {t: n(t) for t in ("root", "a:1", "a:2", "b:1")}
        text, code = commands.cmd_read(nodes, "a", maxlen=0)  # 前缀同时命中 a:1 / a:2
        self.assertEqual(code, 2)
        self.assertIn("候选", text)
        self.assertIn("a:1", text)
        self.assertIn("a:2", text)

    def test_diag_positional_ref(self):  # E16
        tmp = make_lib({"01.md": "## 3.1\n\n见 [[doc:01:3.1]]。\n"})
        nodes = parse(tmp)
        out, code = commands.cmd_diag(nodes)
        self.assertEqual(code, 2)
        self.assertIn("位置型 TID 引用", out)

    def test_diag_duplicate_blocks(self):  # E17
        blk = "这是完全相同的长文本块用于漂移检测，必须超过四十个字符才会被记录并上报，请勿删改。"
        tmp = make_lib({"01.md": "## 1\n\n" + blk + "\n", "02.md": "## 2\n\n" + blk + "\n"})
        nodes = parse(tmp)
        out, code = commands.cmd_diag(nodes)
        self.assertEqual(code, 2)
        self.assertIn("内容重复", out)

    def test_cycle_error_has_source(self):  # C8
        tmp = make_lib({"a.md": "<node name=\"a\">见 [[b]]</node>\n", "b.md": "<node name=\"b\">见 [[a]]</node>\n"})
        nodes = parse(tmp)
        with self.assertRaises(render.TransclusionError) as ctx:
            render.render_node(nodes, "a")
        self.assertIn("循环引用", str(ctx.exception))
        self.assertIn(".md", str(ctx.exception))  # 带源文件
        out, code = commands.cmd_diag(nodes)
        self.assertEqual(code, 2)
        self.assertIn("循环引用", out)

    def test_resolve_fuzzy_lists_candidates(self):  # 裸前缀模糊
        tmp = make_lib({"01.md": "<node name=\"fact:modid\">1</node>\n",
                        "02.md": "<node name=\"fact:modid-places\">2</node>\n",
                        "03.md": "<node name=\"fact:modid-trap\">3</node>\n"})
        nodes = parse(tmp)
        text, code = commands.cmd_read(nodes, "fact:mod", maxlen=0)
        self.assertEqual(code, 2)
        self.assertIn("候选", text)
        self.assertIn("fact:modid", text)
        self.assertIn("fact:modid-places", text)
        self.assertIn("fact:modid-trap", text)

    def test_resolve_fuzzy_unique(self):
        tmp = make_lib({"01.md": "<node name=\"fact:modid\">1</node>\n"})
        nodes = parse(tmp)
        text, code = commands.cmd_read(nodes, "fact:mod", node=True, maxlen=0)
        self.assertEqual(code, 0)
        self.assertEqual(text, "1")  # 唯一模糊命中直接解析

    def test_search_offset_and_total(self):
        tmp = make_lib({"01.md": "## 1\n\nreconcile 甲。\n", "02.md": "## 2\n\nreconcile 乙。\n",
                        "03.md": "## 3\n\nreconcile 丙。\n"})
        nodes = parse(tmp)
        out, code = commands.cmd_search(nodes, "reconcile", limit=2, as_json=True)
        d = json.loads(out)
        self.assertEqual(d["total"], 3)
        self.assertEqual(d["count"], 2)
        first = d["hits"][0]["ref"]
        out2, _ = commands.cmd_search(nodes, "reconcile", limit=2, offset=2, as_json=True)
        d2 = json.loads(out2)
        self.assertEqual(d2["count"], 1)  # 偏移续读剩余 1 条
        self.assertNotEqual(d2["hits"][0]["ref"], first)

    def test_snippet_keeps_newlines(self):  # 代码块缩进不再压平
        tmp = make_lib({"01.md": "## 1\n\n```python\ndef f():\n    return 1\n```\nreconcile 出现。\n"})
        nodes = parse(tmp)
        out, _ = commands.cmd_search(nodes, "reconcile", as_json=True, snippet=80)
        snip = json.loads(out)["hits"][0]["snippet"]
        self.assertIn("\n", snip)

    def test_explicit_node_transclusion_no_sibling_dump(self):  # kind 规则：显式节点不连带展开同文件兄弟
        tmp = make_lib({"01.md": "<node name=\"fact:a\">值A</node>\n<node name=\"fact:b\">值B</node>\n"
                                  "<node name=\"fact:c\">值C</node>\n"})
        nodes = parse(tmp)
        text = render.render_node(nodes, "fact:a")  # fact:a 是同文件首节点（缺省父），但不展开兄弟
        self.assertIn("值A", text)
        self.assertNotIn("值B", text)
        self.assertNotIn("值C", text)

    def test_diag_intra_node_dup_lines(self):  # 节点内重复长行 lint
        ln = "这条命令行内容足够长，超过四十个字符，用于测试节点内部重复行的漂移检测必须达标。"
        tmp = make_lib({"01.md": "## 1\n\n" + ln + "\n" + ln + "\n"})
        nodes = parse(tmp)
        out, code = commands.cmd_diag(nodes)
        self.assertEqual(code, 2)
        self.assertIn("节点内重复行", out)


if __name__ == "__main__":
    unittest.main()
