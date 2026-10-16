#!/usr/bin/env python3
"""Validate the registered documentation set. Standard library only; no network.

Usage: python tools/check_docs.py [--root REPOSITORY]
Manifest: docs/manifest.json, schema_version 1.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sys
import unicodedata
from urllib.parse import unquote, urlsplit
if __package__:
    from .sync_doc_navigation import validate as validate_book_navigation
else:
    from sync_doc_navigation import validate as validate_book_navigation

BT = chr(96)
FENCE = re.compile(r"^ {0,3}([" + BT + r"~]{3,})(.*)$")
MARKER = re.compile(r"^\s*<!--\s*diagram:\s*([A-Za-z0-9][A-Za-z0-9_.-]*)\s*-->\s*$")
REFDEF = re.compile(r"^ {0,3}\[([^\]]+)\]:\s*(.*)$")
OLD_COPY = re.compile(r"(?i)v0[._-][12](?=$|[^0-9])")
OLD_MAIN = "jarvis_system_design.md"
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def ref_key(value):
    return " ".join(value.split()).casefold()


def markdown_unescape(value):
    return re.sub(r"\\([\\!" + BT + r'*_{}\[\]()#+\-.<> ])', r"\1", value)


def without_inline_code(text):
    """Blank matched code spans without changing character positions."""
    chars = list(text)
    pos = 0
    while pos < len(text):
        if text[pos] != BT:
            pos += 1
            continue
        end = pos
        while end < len(text) and text[end] == BT:
            end += 1
        token = text[pos:end]
        close = end
        while True:
            close = text.find(token, close)
            if close < 0:
                break
            after = close + len(token)
            if (close == 0 or text[close - 1] != BT) and (
                after == len(text) or text[after] != BT
            ):
                chars[pos:after] = " " * (after - pos)
                pos = after
                break
            close += len(token)
        else:
            continue
        if close < 0:
            pos = end
    return "".join(chars)


def destination(raw):
    raw = raw.strip()
    if raw.startswith("<"):
        close = re.search(r"(?<!\\)>", raw[1:])
        return markdown_unescape(raw[1:close.start() + 1]) if close else None
    depth = 0
    index = 0
    while index < len(raw):
        char = raw[index]
        if char == "\\" and index + 1 < len(raw):
            index += 2
            continue
        if char.isspace() and depth == 0:
            break
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        index += 1
    return markdown_unescape(raw[:index])


def balanced_end(text, start, opener, closer):
    depth = 1
    pos = start + 1
    while pos < len(text):
        if text[pos] == "\\":
            pos += 2
            continue
        if text[pos] == opener:
            depth += 1
        elif text[pos] == closer:
            depth -= 1
            if depth == 0:
                return pos
        pos += 1
    return None


def extract_links(line, definitions):
    """Return (destination, missing_reference); plain brackets are not links."""
    text = without_inline_code(line)
    pos = 0
    while pos < len(text):
        if text[pos] == "\\":
            pos += 2
            continue
        if text[pos] != "[":
            pos += 1
            continue
        close = balanced_end(text, pos, "[", "]")
        if close is None:
            pos += 1
            continue
        label = text[pos + 1:close]
        after = close + 1
        if after < len(text) and text[after] == "(":
            end = balanced_end(text, after, "(", ")")
            if end is not None:
                target = destination(text[after + 1:end])
                if target is not None:
                    yield target, None
                pos = end + 1
                continue
        if after < len(text) and text[after] == "[":
            end = balanced_end(text, after, "[", "]")
            if end is not None:
                key = ref_key(text[after + 1:end] or label)
                yield definitions.get(key), None if key in definitions else key
                pos = end + 1
                continue
        key = ref_key(label)
        if key in definitions:
            yield definitions[key], None
        elif re.fullmatch(r"s\d+", key, re.IGNORECASE):
            yield None, key
        pos = close + 1
    for match in re.finditer(r"<(?:a|img)\b[^>]*\b(?:href|src)\s*=\s*['\"]([^'\"]+)['\"]", text, re.I):
        yield html.unescape(match.group(1)), None


def slug(text):
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\[[^\]]*\]", r"\1", text)
    text = re.sub(r"<[^>]*>", "", text)
    text = html.unescape(markdown_unescape(text)).lower()
    text = text.replace(BT, "").replace("*", "").replace("~", "")
    return "".join(
        "-" if char.isspace() else char
        for char in text
        if char.isspace() or char in "_-" or unicodedata.category(char)[0] in "LNM"
    )


def parse_markdown(text, report):
    lines = text.splitlines()
    visible = list(lines)
    blocks = {}
    opened = None
    for index, line in enumerate(lines):
        match = FENCE.match(line)
        if opened is not None:
            visible[index] = ""
            if match and set(match.group(1)) == {opened[1]} and (
                len(match.group(1)) >= opened[2] and not match.group(2).strip()
            ):
                start, _, _, language = opened
                blocks[start] = (language, lines[start + 1:index])
                opened = None
            continue
        if match and len(set(match.group(1))) == 1:
            token, rest = match.groups()
            if token[0] == BT and BT in rest:
                continue
            opened = (index, token[0], len(token), rest.strip().lower())
            visible[index] = ""
    if opened is not None:
        report(opened[0] + 1, "unclosed fenced code block")

    definitions = {}
    definition_lines = set()
    for index, line in enumerate(visible):
        match = REFDEF.match(line)
        if match:
            key = ref_key(match.group(1))
            target = destination(match.group(2))
            if not target:
                report(index + 1, "reference definition has no destination: " + key)
                continue
            if key in definitions and definitions[key] != target:
                report(index + 1, "conflicting reference definition: " + key)
            definitions.setdefault(key, target)
            definition_lines.add(index)

    anchors = set()
    heading_counts = {}
    headings_seen = set()
    for index, line in enumerate(visible):
        heading = re.match(r"^ {0,3}#{1,6}(?:[ \t]+(.*)|[ \t]*)$", line)
        title = None
        if heading:
            title = re.sub(r"[ \t]+#+[ \t]*$", "", heading.group(1) or "").strip()
        elif index > 0 and re.match(r"^ {0,3}(?:=+|-+)\s*$", line):
            previous = visible[index - 1].strip()
            if previous and index - 1 not in definition_lines and not re.match(r"^(?:[-*+]\s|>)", previous):
                title = previous
        if title is not None:
            base = slug(title)
            candidate = base
            number = heading_counts.get(base, 0)
            while candidate in headings_seen:
                number += 1
                candidate = base + "-" + str(number)
            heading_counts[base] = number
            headings_seen.add(candidate)
            anchors.add(candidate)
        for match in re.finditer(r"<[A-Za-z][^>]*\b(?:id|name)\s*=\s*['\"]([^'\"]+)['\"]", line):
            anchors.add(html.unescape(match.group(1)))

    links = []
    diagrams = {}
    for index, line in enumerate(visible):
        marker = MARKER.match(line)
        if marker:
            diagram_id = marker.group(1)
            block = blocks.get(index + 2)
            if index + 1 >= len(lines) or lines[index + 1].strip() or not block or block[0] != "mermaid":
                report(index + 1, "diagram marker must be followed by one blank line and a mermaid fence: " + diagram_id)
            elif diagram_id in diagrams:
                report(index + 1, "duplicate diagram marker: " + diagram_id)
            else:
                body = "\n".join(block[1]) + "\n"
                diagrams[diagram_id] = (hashlib.sha256(body.encode("utf-8")).hexdigest(), index + 1)
        elif "<!--" in line and re.search(r"\bdiagram\s*:", line):
            report(index + 1, "diagram marker must occupy its own line")
        if index not in definition_lines:
            for target, missing in extract_links(line, definitions):
                if missing:
                    report(index + 1, "undefined reference: [" + missing + "]")
                elif target is not None:
                    links.append((target, index + 1))
    # Validate even unused definitions: they are maintained source entries.
    for index in definition_lines:
        match = REFDEF.match(visible[index])
        target = definitions.get(ref_key(match.group(1)))
        if target is not None:
            links.append((target, index + 1))
    return {"anchors": anchors, "links": links, "diagrams": diagrams}


class Checker:
    def __init__(self, root):
        self.root = root.resolve()
        self.errors = []
        self.documents = {}
        self.document_ids = {}
        self.diagrams = {}
        self.ids = set()
        self.owners = set()
        self.artifacts = set()
        self.generated_count = 0
        self.diagram_sources = set()

    def error(self, context, message):
        self.errors.append(str(context) + ": " + message)

    def key(self, path):
        return path.relative_to(self.root).as_posix().casefold()

    def contained(self, path):
        try:
            path.relative_to(self.root)
            return True
        except ValueError:
            return False

    def resolve_manifest_path(self, value, context):
        if not isinstance(value, str) or not value or "\x00" in value:
            self.error(context, "path must be a nonempty string")
            return None
        normalized = value.replace("\\", "/")
        if PureWindowsPath(value).drive or PurePosixPath(normalized).is_absolute():
            self.error(context, "manifest path must be repository-relative: " + value)
            return None
        try:
            path = (self.root / normalized).resolve()
        except (OSError, ValueError) as exc:
            self.error(context, "invalid path: " + str(exc))
            return None
        if not self.contained(path):
            self.error(context, "path escapes repository: " + value)
            return None
        if not path.is_file():
            self.error(context, "file does not exist: " + value)
            return None
        return path

    def register_id(self, value, context):
        if not isinstance(value, str) or not value.strip():
            self.error(context, "id must be a nonempty string")
            return False
        if value in self.ids:
            self.error(context, "duplicate id: " + value)
            return False
        self.ids.add(value)
        return True

    def read_document(self, entry, index):
        context = "documents[" + str(index) + "]"
        if not isinstance(entry, dict):
            self.error(context, "entry must be an object")
            return
        valid_id = self.register_id(entry.get("id"), context)
        if not isinstance(entry.get("title"), str) or not entry["title"].strip():
            self.error(context, "title must be a nonempty string")
        owns = entry.get("owns")
        if not isinstance(owns, list):
            self.error(context, "owns must be an array")
            owns = []
        for topic in owns:
            if not isinstance(topic, str) or not topic.strip():
                self.error(context, "owns entries must be nonempty strings")
            elif topic in self.owners:
                self.error(context, "duplicate topic ownership: " + topic)
            else:
                self.owners.add(topic)
        path = self.resolve_manifest_path(entry.get("path"), context)
        if path is None:
            return
        if path.suffix.lower() != ".md":
            self.error(context, "document must be a Markdown file")
            return
        key = self.key(path)
        if key in self.documents:
            self.error(context, "duplicate document path: " + key)
            return
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            self.error(key, "cannot read UTF-8 document: " + str(exc))
            return
        parsed = parse_markdown(text, lambda line, message: self.error(key + ":" + str(line), message))
        parsed["path"] = path
        self.documents[key] = parsed
        if valid_id:
            self.document_ids[entry["id"]] = key
        for diagram_id, details in parsed["diagrams"].items():
            if diagram_id in self.diagrams:
                self.error(key, "diagram marker also exists in another document: " + diagram_id)
            else:
                self.diagrams[diagram_id] = (key, details[0], details[1])

    def check_link(self, source, target, line):
        context = self.key(source) + ":" + str(line)
        target = html.unescape(target)
        if re.match(r"^[A-Za-z]:[\\/]", target) or target.startswith("\\\\"):
            self.error(context, "absolute filesystem link is not portable: " + target)
            return
        try:
            parts = urlsplit(target)
        except ValueError as exc:
            self.error(context, "invalid link: " + str(exc))
            return
        if parts.scheme:
            if parts.scheme.lower() == "file":
                self.error(context, "file URI is not a repository-relative link: " + target)
            return
        if parts.netloc:
            return
        raw_path = unquote(parts.path).replace("\\", "/")
        if PurePosixPath(raw_path).name.casefold() == OLD_MAIN:
            self.error(context, "obsolete monolithic document link: " + target)
        try:
            destination_path = (
                self.root / raw_path.lstrip("/") if raw_path.startswith("/")
                else source.parent / raw_path if raw_path else source
            ).resolve()
        except (OSError, ValueError) as exc:
            self.error(context, "invalid local link path: " + str(exc))
            return
        if not self.contained(destination_path):
            self.error(context, "link escapes repository: " + target)
            return
        if not destination_path.exists():
            self.error(context, "broken local link: " + target)
            return
        fragment = unquote(parts.fragment)
        if fragment:
            if destination_path.is_dir():
                destination_path = destination_path / "README.md"
            if destination_path.suffix.lower() == ".md":
                parsed = self.documents.get(self.key(destination_path))
                if parsed is None:
                    self.error(context, "anchor target is not a registered document: " + target)
                elif fragment not in parsed["anchors"]:
                    self.error(context, "missing heading/HTML anchor: " + target)

    def check_generated(self, entries):
        if not isinstance(entries, list):
            self.error("manifest", "generated_diagrams must be an array")
            return
        registered = set()
        for index, entry in enumerate(entries):
            context = "generated_diagrams[" + str(index) + "]"
            if not isinstance(entry, dict):
                self.error(context, "entry must be an object")
                continue
            diagram_id = entry.get("id")
            valid_id = self.register_id(diagram_id, context)
            if valid_id:
                self.generated_count += 1
            if isinstance(diagram_id, str):
                registered.add(diagram_id)
            source_value = entry.get("source_document")
            source_key = self.document_ids.get(source_value) if isinstance(source_value, str) else None
            source_path = self.documents[source_key]["path"] if source_key else None
            if source_key is None:
                source_path = self.resolve_manifest_path(source_value, context + ".source_document")
                source_key = self.key(source_path) if source_path else None
            external_source = source_path is not None and source_path.suffix.lower() == ".mmd"
            if source_path is not None and source_path.suffix.lower() not in {".mmd", ".md"}:
                self.error(context, "diagram source must use .mmd or registered .md")
            actual_source_hash = None
            if external_source:
                if source_key in self.diagram_sources:
                    self.error(context, "duplicate Mermaid source path: " + source_key)
                self.diagram_sources.add(source_key)
                try:
                    source_bytes = source_path.read_bytes()
                    source_bytes.decode("utf-8-sig")
                    actual_source_hash = hashlib.sha256(source_bytes).hexdigest()
                except (OSError, UnicodeError) as exc:
                    self.error(context, "cannot read UTF-8 Mermaid source: " + str(exc))
                if isinstance(diagram_id, str) and diagram_id in self.diagrams:
                    self.error(context, "diagram has both an inline marker and an external source: " + diagram_id)
            else:
                if source_key and source_key not in self.documents:
                    self.error(context, "source_document must be a registered Markdown document or a .mmd file")
                marker = self.diagrams.get(diagram_id) if isinstance(diagram_id, str) else None
                if marker is None:
                    self.error(context, "diagram marker not found: " + str(diagram_id))
                elif source_key != marker[0]:
                    self.error(context, "diagram marker belongs to a different source_document")
                if marker:
                    actual_source_hash = marker[1]
            expected = entry.get("source_sha256")
            if not isinstance(expected, str) or not SHA256.fullmatch(expected):
                self.error(context, "source_sha256 must contain 64 hexadecimal characters")
            elif actual_source_hash is not None and expected.lower() != actual_source_hash:
                self.error(context, "source_sha256 does not match " + ("raw .mmd bytes" if external_source else "Mermaid body"))
            artifacts = entry.get("artifacts")
            if not isinstance(artifacts, list) or not artifacts:
                self.error(context, "artifacts must be a nonempty array")
                continue
            for number, artifact in enumerate(artifacts):
                item_context = context + ".artifacts[" + str(number) + "]"
                if not isinstance(artifact, dict):
                    self.error(item_context, "artifact must be an object")
                    continue
                path = self.resolve_manifest_path(artifact.get("path"), item_context)
                if path is not None and path.suffix.lower() not in {".png", ".svg"}:
                    self.error(item_context, "generated diagram artifact must use .png or .svg")
                    continue
                expected = artifact.get("sha256")
                if not isinstance(expected, str) or not SHA256.fullmatch(expected):
                    self.error(item_context, "sha256 must contain 64 hexadecimal characters")
                    continue
                if path is None:
                    continue
                key = self.key(path)
                if key in self.artifacts:
                    self.error(item_context, "duplicate generated artifact path: " + key)
                self.artifacts.add(key)
                try:
                    digest = hashlib.sha256()
                    with path.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(chunk)
                    if digest.hexdigest() != expected.lower():
                        self.error(item_context, "artifact sha256 mismatch: " + key)
                except OSError as exc:
                    self.error(item_context, "cannot read artifact: " + str(exc))
        for diagram_id, marker in self.diagrams.items():
            if diagram_id not in registered:
                self.error(marker[0] + ":" + str(marker[2]), "unregistered diagram marker: " + diagram_id)

    def check_validation_record(self, entry):
        # Optional render record is immutable evidence; never rewrite its hash here.
        if entry is None:
            return
        context = "diagram_validation"
        if not isinstance(entry, dict):
            self.error(context, "must be an object")
            return
        path = self.resolve_manifest_path(entry.get("path"), context)
        expected = entry.get("sha256")
        if not isinstance(expected, str) or not SHA256.fullmatch(expected):
            self.error(context, "sha256 must contain 64 hexadecimal characters")
            return
        if path is None:
            return
        if path.suffix.lower() != ".json":
            self.error(context, "validation record must use .json")
            return
        try:
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected.lower():
                self.error(context, "validation record sha256 mismatch")
        except OSError as exc:
            self.error(context, "cannot read validation record: " + str(exc))

    def check_tree(self):
        def walk_error(exc):
            self.error("repository", "cannot scan directory: " + str(exc))
        for current, directories, files in os.walk(self.root, followlinks=False, onerror=walk_error):
            parent = Path(current)
            keep = []
            for name in directories:
                if self.key(parent / name) == "tools/node_modules":
                    continue  # Third-party renderer dependencies, not authored documentation.
                if name in {".git", ".hg", ".svn", "__pycache__"}:
                    continue
                path = parent / name
                if name.casefold() in {"archive", "archives"}:
                    self.error(self.key(path), "archive directories are disabled")
                if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                    self.error(self.key(path), "directory links are unsupported for complete repository scanning")
                    continue
                keep.append(name)
            directories[:] = keep
            for name in files:
                path = parent / name
                suffix = path.suffix.lower()
                if self.key(path).startswith("docs/diagrams/") and suffix in {".mmd", ".png", ".svg"}:
                    resolved = path.resolve()
                    if not self.contained(resolved):
                        self.error(self.key(path), "diagram symlink escapes repository")
                    elif suffix == ".mmd" and self.key(resolved) not in self.diagram_sources:
                        self.error(self.key(path), "unregistered Mermaid source")
                    elif suffix in {".png", ".svg"} and self.key(resolved) not in self.artifacts:
                        self.error(self.key(path), "unregistered generated diagram artifact")
                if suffix != ".md":
                    continue
                if not self.contained(path.resolve()):
                    self.error(self.key(path), "Markdown symlink escapes repository")
                    continue
                key = self.key(path.resolve())
                if key not in self.documents:
                    self.error(self.key(path), "unregistered Markdown file")
                if name.casefold() == OLD_MAIN:
                    self.error(self.key(path), "obsolete monolithic document file")
                if any(OLD_COPY.search(part) for part in path.relative_to(self.root).parts):
                    self.error(self.key(path), "versioned v0.1/v0.2 document copies are disabled")

    def run(self):
        manifest_path = self.root / "docs" / "manifest.json"
        if not self.root.is_dir():
            self.error("root", "repository directory does not exist")
            return
        if not self.contained(manifest_path.resolve()):
            self.error("manifest", "manifest path escapes repository")
            return
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            self.error("manifest", "cannot read docs/manifest.json: " + str(exc))
            return
        if not isinstance(manifest, dict):
            self.error("manifest", "manifest must be an object")
            return
        if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
            self.error("manifest", "schema_version must equal 1")
        entries = manifest.get("documents")
        if not isinstance(entries, list):
            self.error("manifest", "documents must be an array")
            entries = []
        for index, entry in enumerate(entries):
            self.read_document(entry, index)
        for document in self.documents.values():
            for target, line in document["links"]:
                self.check_link(document["path"], target, line)
        self.check_generated(manifest.get("generated_diagrams"))
        self.check_validation_record(manifest.get("diagram_validation"))
        self.check_tree()
        for message in validate_book_navigation(self.root):
            self.error("book", message)

    def print_result(self):
        for message in self.errors[:40]:
            print("ERROR " + message)
        if len(self.errors) > 40:
            print("ERROR ... " + str(len(self.errors) - 40) + " further errors")
        print(
            ("FAIL" if self.errors else "OK")
            + " documents=" + str(len(self.documents))
            + " diagrams=" + str(self.generated_count)
            + " artifacts=" + str(len(self.artifacts))
            + " errors=" + str(len(self.errors))
        )
        return 1 if self.errors else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    arguments = parser.parse_args(argv)
    checker = Checker(arguments.root)
    checker.run()
    return checker.print_result()


if __name__ == "__main__":
    sys.exit(main())
