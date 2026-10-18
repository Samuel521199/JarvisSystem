"""Host-owned contracts and independent oracles, outside candidate write access."""
import csv
import io
import json
import random

from ..policy import CoreError, canonical_json, digest

SKILL = 'inventory-export'
CONTRACT = 'inventory-export/1'
MAX_INPUT = 65536


def validate_input(value, revision):
    if not isinstance(value, dict) or set(value) != {'format', 'entries'}:
        raise CoreError('evolution_input_invalid', '输入需要 format 和 entries。')
    formats = ('csv', 'markdown') if revision == 1 else ('csv', 'markdown', 'tsv')
    if value['format'] not in formats or not isinstance(value['entries'], list) or len(value['entries']) > 100:
        raise CoreError('evolution_input_invalid', '格式不支持，或记录超过 100 条。')
    for row in value['entries']:
        if (not isinstance(row, dict) or set(row) != {'path', 'size'} or
                not isinstance(row['path'], str) or not 1 <= len(row['path']) <= 256 or
                '\0' in row['path'] or type(row['size']) is not int or not 0 <= row['size'] <= 10**12):
            raise CoreError('evolution_input_invalid', '每条记录需要文本 path 和非负整数 size。')
    if len(canonical_json(value).encode()) > MAX_INPUT:
        raise CoreError('evolution_input_invalid', '输入超过字节限额。')
    return value


def expected(value):
    rows = sorted(value['entries'], key=lambda row: row['path'])
    if value['format'] in ('csv', 'tsv'):
        stream = io.StringIO(newline='')
        writer = csv.writer(stream, delimiter=',' if value['format'] == 'csv' else '\t', lineterminator='\n')
        writer.writerow(['path', 'size'])
        writer.writerows([row['path'], row['size']] for row in rows)
        return stream.getvalue()
    def escape(path):
        for old, new in (('&', '&amp;'), ('<', '&lt;'), ('>', '&gt;'),
                         ('\\', '&#92;'), ('|', '&#124;'), ('\r', '&#13;'), ('\n', '&#10;'), ('\t', '&#9;')):
            path = path.replace(old, new)
        return path
    return '| path | size |\n| --- | ---: |\n' + ''.join(
        f"| {escape(row['path'])} | {row['size']} |\n" for row in rows)


def cases(revision, *, heldout=False):
    entries = [[], [{'path': 'b.txt', 'size': 20}, {'path': 'a.txt', 'size': 0}]]
    if heldout:
        entries += [[{'path': name, 'size': i * 13} for i, name in enumerate(
            ['中文.txt', 'quote"a,b', 'line\r\nbreak', 'a|b\\c', '<img>&', 'tab\tfile', '=SUM(1)', 'same', 'same'])]]
        rng = random.Random(41427)
        entries += [[{'path': ''.join(rng.choices('ab你|&<>\\\n\t,\"', k=12)),
                      'size': rng.randrange(10**12)} for _ in range(100)]]
    formats = ['csv', 'markdown'] + (['tsv'] if revision == 2 else [])
    return [{'format': fmt, 'entries': rows} for rows in entries for fmt in formats]


def specification(revision):
    if type(revision) is not int or revision not in (1, 2):
        raise CoreError('evolution_revision_invalid', '当前支持报告工具 v1、v2。')
    return {
        'skill_id': SKILL, 'revision': revision, 'contract': CONTRACT,
        'goal': 'Implement a pure Python transform(data) -> str that exports bounded file metadata.',
        'input': 'Object with format and entries; entries are {path:str,size:int}, up to 100. Host validates input.',
        'formats': ['csv', 'markdown'] + (['tsv'] if revision == 2 else []),
        'rules': [
            'Sort entries by path using Python Unicode order, stably; retain duplicate paths.',
            'CSV uses Python csv.writer, delimiter comma, lineterminator LF, header path,size; include final newline.',
            'TSV when supported uses csv.writer with tab delimiter and LF, header path and size.',
            'Markdown starts exactly "| path | size |\\n| --- | ---: |\\n". Each row is "| ESCAPED_PATH | SIZE |\\n".',
            'For Markdown escape sequentially &: &amp;, <: &lt;, >: &gt;, backslash: &#92;, pipe: &#124;, CR: &#13;, LF: &#10;, tab: &#9;.',
            'Return plain text. Do not read files, contact networks, execute commands or modify input.',
            'Only imports csv and io are permitted. No private/dunder attribute access, reflection, dynamic imports, decorators or top-level effects.',
            'Use functions, ordinary data structures and loops. No external dependencies.',
        ],
        'examples': [{'input': value, 'expected': expected(value)} for value in cases(revision)],
    }


def binding(revision):
    return digest(canonical_json({'spec': specification(revision),
                                 'heldout': [(v, expected(v)) for v in cases(revision, heldout=True)]}).encode())


def metadata(revision):
    return {'id': SKILL, 'revision': revision, 'name': '文件清单导出',
            'contract': CONTRACT, 'execution': 'python-pure-transform-lpac',
            'dependencies': ['python-stdlib:csv', 'python-stdlib:io'],
            'permissions': ['provided-json:read', 'result-text:return'],
            'mode': 'explicit', 'scope': 'provided_metadata_only',
            'positive_examples': ['把已提供的文件清单转为 CSV', '把这些路径和大小整理成 Markdown 表格'],
            'negative_examples': ['扫描我的硬盘', '打开导出的 CSV 并运行公式'],
            'formats': specification(revision)['formats'], 'acceptance_digest': binding(revision)}


def reference_skill(revision):
    return ('# 文件清单导出\n\n版本：' + str(revision) + '\n\n'
            '适用：把已提供的路径和大小转换成 ' + '、'.join(specification(revision)['formats']) + ' 文本。\n'
            '不适用：扫描磁盘、读取源文件、执行 CSV 公式、运行命令或调用网络。\n'
            '输入：format 与 entries（每条含 path、size）；输出：文本。\n'
            '只能显式调用；文件名按原文保留，输出不会自动交给电子表格程序执行。\n')
