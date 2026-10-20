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
        self.assertEqual(hits[0]["tid"], "doc:01:1.1")  # 双词命中排前

    def test_register_creates_nodekb(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        commands.register_db("t", str(tmp))
        self.assertTrue((tmp / ".nodekb").is_dir())
        reg = commands.load_registry()
        self.assertEqual(reg["t"]["path"], str(tmp.resolve()))


if __name__ == "__main__":
    unittest.main()
