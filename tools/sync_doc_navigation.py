"""Build/check the book navigation from manifest grouping and explicit headings.

Only marked navigation blocks are generated. Bodies, anchors and diagrams remain
authored sources. Run with --check to validate without writing.
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
from pathlib import Path

NAV_START = "<!-- book-nav:start -->"
NAV_END = "<!-- book-nav:end -->"
TREE_START = "<!-- book-tree:start -->"
TREE_END = "<!-- book-tree:end -->"
FOOT_START = "<!-- book-footer:start -->"
FOOT_END = "<!-- book-footer:end -->"
ANCHOR = re.compile(r'^<a id="([a-zA-Z0-9_-]+)"></a>$')


def replace_block(text: str, start: str, end: str, content: str) -> str:
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError(f"Expected exactly one {start} / {end}")
    first, last = text.index(start), text.index(end)
    if last < first:
        raise ValueError(f"Reversed block {start}")
    return text[:first] + start + "\n" + content.strip() + "\n" + end + text[last + len(end):]


def headings(text: str) -> list[tuple[int, str, str]]:
    """Read only body ATX headings; exclude code fences and generated blocks."""
    result = []
    fence = None
    generated = False
    anchor = None
    previous_level = 1
    title_count = 0
    for line in text.splitlines():
        if line in (NAV_START, FOOT_START):
            generated = True
            continue
        if line in (NAV_END, FOOT_END):
            generated = False
            continue
        if generated:
            continue
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            continue
        if marker:
            fence = marker[1]
            anchor = None
            continue
        if re.match(r'^# ', line):
            title_count += 1
        explicit = ANCHOR.fullmatch(line.strip())
        if explicit:
            anchor = explicit[1]
            continue
        heading = re.match(r'^(#{2,6}) (.+)$', line)
        if heading:
            level = len(heading[1])
            if level > 4:
                raise ValueError("Use H2/H3/H4 body headings; split an oversized section instead")
            if level > previous_level + 1:
                raise ValueError(f"Skipped heading level: {line}")
            if anchor is None:
                raise ValueError(f"Heading needs an explicit stable anchor: {line}")
            result.append((level, heading[2], anchor))
            previous_level = level
        if line.strip():
            anchor = None
    if fence:
        raise ValueError("Unclosed code fence")
    if title_count != 1:
        raise ValueError("Chapter needs exactly one H1 title")
    if not result:
        raise ValueError("Chapter has no body sections")
    return result


def build(root: Path) -> dict[Path, str]:
    root = root.resolve()
    manifest = json.loads((root / "docs/manifest.json").read_text(encoding="utf-8"))
    documents = {d["id"]: d for d in manifest["documents"]}
    parts = manifest["book"]["parts"]
    if not parts:
        raise ValueError("Book must contain parts")
    chapter_ids = [doc for part in parts for doc in part["chapters"]]
    expected_ids = {d["id"] for d in documents.values() if d["path"].startswith("docs/") and d["path"] != "docs/README.md"}
    if len(chapter_ids) != len(set(chapter_ids)) or set(chapter_ids) != expected_ids:
        raise ValueError("Each registered docs chapter must belong to exactly one book part")
    part_ids = [p["id"] for p in parts]
    if len(part_ids) != len(set(part_ids)) or any(not re.fullmatch(r'part-[a-z0-9-]+', p) for p in part_ids):
        raise ValueError("Book part IDs must be unique stable part-* identifiers")
    entries, bodies, sections = [], {}, {}
    for part in parts:
        if not part["title"].strip() or not part["chapters"]:
            raise ValueError("Empty book part")
        for doc_id in part["chapters"]:
            doc = documents[doc_id]
            if not isinstance(doc.get("reader_summary"), str) or not doc["reader_summary"].strip():
                raise ValueError(f"Chapter needs a reader_summary: {doc['path']}")
            path = (root / doc["path"]).resolve()
            if not path.is_relative_to(root / "docs"):
                raise ValueError("Chapter escapes docs directory")
            text = path.read_text(encoding="utf-8")
            title = re.search(r'^# (.+)$', text, re.M)
            if not title or title[1] != doc["title"]:
                raise ValueError(f"H1 and manifest title disagree: {doc['path']}")
            bodies[doc_id] = text
            sections[doc_id] = headings(text)
            entries.append((part, doc, path))
    output = {}
    tree = ["<a id=\"book-tree\"></a>", "## 按主题查阅完整文档", "",
            "点击章节名打开正文，正文顶部可跳转到具体小节。下面的编号是阅读顺序；开发顺序以核心章中的 K0—K6 为准。", ""]
    position = 0
    for part in parts:
        tree += [f'<a id="{part["id"]}"></a>', f'### {part["title"]}', "",
                 "| 章 | 文档 | 这章回答什么 |", "|---|---|---|"]
        for doc_id in part["chapters"]:
            position += 1
            _, doc, path = entries[position - 1]
            local = path.relative_to(root / "docs").as_posix()
            directory = posixpath.dirname(local) or "."
            index_link = posixpath.relpath("README.md", directory)
            title = f"第 {position:02d} 章 · {doc['title']}"
            summary = doc["reader_summary"].replace("|", "\\|").replace("\n", " ")
            tree.append(f"| {position:02d} | [{doc['title']}]({local}) | {summary} |")
            toc, counters = [], [0, 0, 0]
            for level, label, anchor in sections[doc_id]:
                index = level - 2
                counters[index] += 1
                counters[index + 1:] = [0] * (2 - index)
                number = ".".join(map(str, [position] + counters[:index + 1]))
                # Existing printed section numbers are not new identities.
                display = re.sub(r'^\d+\.\s+', '', label)
                toc.append("  " * index + f"- [{number} {display}](#{anchor})")
            crumb = f"[全书目录]({index_link}#book-tree) › [{part['title']}]({index_link}#{part['id']}) › {title}"
            navigation = crumb + "\n\n## 本章导航\n\n" + "\n".join(toc)
            previous = entries[position - 2][1] if position > 1 else None
            following = entries[position][1] if position < len(entries) else None
            footer = [f"[返回全书目录]({index_link}#book-tree)"]
            for label, other in (("上一章", previous), ("下一章", following)):
                if other:
                    relative = posixpath.relpath((root / other['path']).relative_to(root / 'docs').as_posix(), directory)
                    footer.append(f"[{label}：{other['title']}]({relative})")
            text = replace_block(bodies[doc_id], NAV_START, NAV_END, navigation)
            output[path] = replace_block(text, FOOT_START, FOOT_END, " · ".join(footer))
        tree.append("")
    index_path = root / "docs/README.md"
    output[index_path] = replace_block(index_path.read_text(encoding="utf-8"), TREE_START, TREE_END, "\n".join(tree))
    return output


def validate(root: Path) -> list[str]:
    try:
        expected = build(root)
        return [f"Stale book navigation: {path.relative_to(root.resolve()).as_posix()}" for path, text in expected.items() if path.read_text(encoding="utf-8") != text]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return ["Book navigation: " + str(exc)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        errors = validate(args.root)
        print("\n".join(errors) if errors else "OK book navigation")
        return int(bool(errors))
    try:
        expected = build(args.root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("ERROR " + str(exc))
        return 1
    count = 0
    for path, text in expected.items():
        if path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
            count += 1
    print(f"Updated navigation in {count} files; chapter bodies unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
