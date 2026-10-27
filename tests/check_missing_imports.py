# -*- coding: utf-8 -*-
"""检查某个模块里「用了但没定义也没 import」的名字（NameError 预警）。

拆文件时最容易漏的就是这类：函数体里 `threading.Thread(...)`，
主模块顶层有 `import threading`，搬到新文件后忘了带 —— 启动不报错，
一到那个路由就 500。

    python tests/check_missing_imports.py app/library/routes.py
    python tests/check_missing_imports.py app/auth/routes.py app/library/routes.py
"""

import ast
import builtins
import io
import sys


def module_level_names(tree):
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name):
                        names.add(sub.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, (ast.For, ast.While, ast.If, ast.Try, ast.With)):
            # 兼容顶层条件 import / 循环赋值
            for sub in ast.walk(node):
                if isinstance(sub, ast.Import):
                    for alias in sub.names:
                        names.add(alias.asname or alias.name.split('.')[0])
                elif isinstance(sub, ast.ImportFrom):
                    for alias in sub.names:
                        names.add(alias.asname or alias.name)
    return names


def local_names(func):
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
            if node.args.vararg:
                names.add(node.args.vararg.arg)
            if node.args.kwarg:
                names.add(node.args.kwarg.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.Lambda):
            lam = node.args
            for group in (lam.posonlyargs, lam.args, lam.kwonlyargs):
                for arg in group:
                    names.add(arg.arg)
            if lam.vararg:
                names.add(lam.vararg.arg)
            if lam.kwarg:
                names.add(lam.kwarg.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split('.')[0])
    return names


def check_file(path):
    source = io.open(path, encoding='utf-8').read()
    tree = ast.parse(source)
    module_names = module_level_names(tree) | set(dir(builtins))
    missing = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        free = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                free.add(sub.id)
        unknown = free - local_names(node) - module_names
        if unknown:
            missing[node.name] = sorted(unknown)
    return missing


def main():
    paths = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not paths:
        raise SystemExit(__doc__)
    bad = False
    for path in paths:
        missing = check_file(path)
        if not missing:
            print(f'✅ {path}: 没有未定义的名字')
            continue
        bad = True
        print(f'❌ {path}: {len(missing)} 个函数存在未定义名字')
        for func, names in missing.items():
            print(f'   {func}: {", ".join(names)}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
