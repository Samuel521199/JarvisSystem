"""A small, total ranking language compiled from a verified Python AST.

Python is executed only by the LPAC evaluator. The host interprets a finite
tuple of feature names, never eval/exec/imports the candidate source.
"""
import ast
import time

FEATURES = ('coverage', 'text_coverage', 'heading_coverage', 'score')
TAIL = ('path', 'start_line')


def source_for(keys):
    expressions = [('-' if key in FEATURES else '') + f'data[i]["{key}"]' for key in keys]
    return ('def transform(data):\n'
            '    return ",".join(str(i) for i in sorted(range(len(data)), '
            'key=lambda i: (' + ', '.join(expressions) + ')))\n')


def compile_source(source):
    if not isinstance(source, str) or not 20 <= len(source.encode()) <= 4000:
        raise ValueError('ranking source size')
    tree = ast.parse(source)
    # Infer only candidate keys, then compare the ENTIRE tree to the grammar.
    lambdas = [n for n in ast.walk(tree) if isinstance(n, ast.Lambda)]
    if len(lambdas) != 1 or not isinstance(lambdas[0].body, ast.Tuple):
        raise ValueError('ranking grammar')
    keys = []
    for item in lambdas[0].body.elts:
        node = item.operand if isinstance(item, ast.UnaryOp) else item
        if not isinstance(node, ast.Subscript) or not isinstance(node.slice, ast.Constant):
            raise ValueError('ranking key')
        keys.append(node.slice.value)
    if (not 3 <= len(keys) <= 6 or tuple(keys[-2:]) != TAIL
            or any(k not in FEATURES for k in keys[:-2])
            or len(set(keys)) != len(keys) or 'score' not in keys):
        raise ValueError('ranking keys')
    if ast.dump(tree) != ast.dump(ast.parse(source_for(keys))):
        raise ValueError('unsupported ranking code')
    return tuple(keys)


def features(rows, words):
    if len(rows) > 2048 or len(words) > 128:
        raise ValueError('ranking quota')
    return [dict(score=r['score'], path=r['path'], start_line=r['start_line'],
                 coverage=sum(w in r['text'] or w in r['heading'] for w in words),
                 text_coverage=sum(w in r['text'] for w in words),
                 heading_coverage=sum(w in r['heading'] for w in words)) for r in rows]


def order_features(rows, keys):
    return sorted(range(len(rows)), key=lambda i: tuple(
        -rows[i][k] if k in FEATURES else rows[i][k] for k in keys))


class Program:
    protocol = 1

    def __init__(self, source, module_id='candidate'):
        self.keys = compile_source(source)
        self.module_id = module_id

    def order(self, rows, words):
        started = time.perf_counter()
        result = order_features(features(rows, words), self.keys)
        # A finite program cannot loop or do IO. A slow machine can still fall
        # back after work; this is not a preemptive real-time deadline.
        if time.perf_counter() - started > .25:
            raise ValueError('ranking latency budget')
        return result
