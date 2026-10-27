# -*- coding: utf-8 -*-
"""分析 novel_manager.py 里的路由：代码块边界、函数体内的 global 写操作、行数。

拆蓝图前用它排期 —— 关键是找出「函数里对模块全局赋值」的地方，
这些搬家时必须改写成 `nm.X = ...`，否则会写到新模块的全局里，主模块纹丝不动。

    python tests/analyze_routes.py                # 全部路由
    python tests/analyze_routes.py library        # 只看某个域（读 docs 映射表不行，用内置表）
    python tests/analyze_routes.py --endpoint index
"""

import ast
import io
import os
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(APP_DIR, 'novel_manager.py')


def collect():
    source = io.open(TARGET, encoding='utf-8').read()
    lines = source.splitlines()
    tree = ast.parse(source)

    routes = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        decorators = []
        for deco in node.decorator_list:
            text = ast.unparse(deco)
            if text.startswith('app.route') or text.startswith('app.get') or text.startswith('app.post'):
                decorators.append(text)
        if not decorators:
            continue
        globals_assigned = []
        for sub in ast.walk(node):
            if isinstance(sub, ast.Global):
                globals_assigned.extend(sub.names)
        routes.append({
            'endpoint': node.name,
            'start': node.lineno,
            'end': node.end_lineno,
            'size': node.end_lineno - node.lineno + 1,
            'decoration': decorators[0],
            'globals': sorted(set(globals_assigned)),
        })
    routes.sort(key=lambda r: r['start'])
    return routes, lines


def main():
    routes, lines = collect()
    only = None
    endpoint = None
    args = sys.argv[1:]
    for index, arg in enumerate(args):
        if arg == '--endpoint':
            endpoint = args[index + 1]

    if endpoint:
        routes = [r for r in routes if r['endpoint'] == endpoint]

    print(f'# 路由 {len(routes)} 条（文件共 {len(lines)} 行）')
    print()
    print('| 行号区间 | 行数 | 端点 | 全局写操作 |')
    print('|---|---|---|---|')
    total = 0
    with_global = 0
    for route in routes:
        total += route['size']
        glob = ', '.join(route['globals']) or '—'
        if route['globals']:
            with_global += 1
            glob = f'⚠️ {glob}'
        print(f"| {route['start']}-{route['end']} | {route['size']} | {route['endpoint']} | {glob} |")

    print()
    print(f'合计 {total} 行，其中 {with_global} 个函数有 global 写操作')
    return 0


if __name__ == '__main__':
    sys.exit(main())
