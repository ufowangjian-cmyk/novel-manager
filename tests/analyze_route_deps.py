# -*- coding: utf-8 -*-
"""提取指定路由函数对外部模块级名字的依赖（自动生成 import 清单）。

原理：用 ast 扫函数体里所有 Name 引用，减去 局部赋值、函数参数、内建名、
已 import 进来的名字，剩下的就是「必须从主模块拿」的自由变量。

    python tests/analyze_route_deps.py api_tag_add api_tag_edit ...
    python tests/analyze_route_deps.py --file tmp_endpoints.txt
"""

import ast
import builtins
import io
import os
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(APP_DIR, 'novel_manager.py')


def module_names(tree):
    """模块级定义的函数名、类名、赋值目标；以及 import 进来的名字。"""
    defined = set()
    imported = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.asname or alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported.add(alias.asname or alias.name)
    return defined, imported


def local_names(func):
    """函数内会产生的局部名字：参数、赋值目标、for/with/except 目标、推导式变量。"""
    names = set()
    args = func.args
    for group in (args.posonlyargs, args.args, args.kwonlyargs):
        for arg in group:
            names.add(arg.arg)
    if args.vararg:
        names.add(args.vararg.arg)
    if args.kwarg:
        names.add(args.kwarg.arg)

    for node in ast.walk(func):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node is not func:
            names.add(node.name)
            for group in (node.args.posonlyargs, node.args.args, node.args.kwonlyargs):
                for arg in group:
                    names.add(arg.arg)
    return names


def free_names(func):
    used = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.add(node.id)
    return used - local_names(func)


def main():
    source = io.open(TARGET, encoding='utf-8').read()
    tree = ast.parse(source)

    wanted = []
    target_file = None
    args = sys.argv[1:]
    for index, arg in enumerate(args):
        if arg == '--file':
            target_file = args[index + 1]
        elif not arg.startswith('--'):
            wanted.append(arg)
    if target_file:
        with io.open(target_file, encoding='utf-8') as handle:
            wanted.extend(line.strip() for line in handle if line.strip())

    defined, imported = module_names(tree)
    builtin_names = set(dir(builtins))

    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    if not wanted:
        wanted = sorted(functions)

    union = set()
    print('| 端点 | 需要从主模块 import 的名字 |')
    print('|---|---|')
    for name in wanted:
        func = functions.get(name)
        if func is None:
            print(f'| {name} | ❌ 找不到该函数 |')
            continue
        free = free_names(func)
        external = sorted(
            n for n in free
            if n in defined and n not in imported and n not in builtin_names
        )
        union.update(external)
        print(f'| {name} | {", ".join(external) or "—"} |')

    print()
    print('## 合并后的 import 清单')
    print()
    print(', '.join(sorted(union)))
    print()
    print(f'共 {len(union)} 个名字')
    return 0


if __name__ == '__main__':
    sys.exit(main())
