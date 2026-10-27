# -*- coding: utf-8 -*-
"""把指定的路由函数从 novel_manager.py 搬到某个蓝图模块。

用法：
    python tests/move_routes.py --to app/library/routes.py --bp library_bp \
        --endpoints get_all_authors get_all_tags ... \
        [--rename CONFIG=TAG_IMPLICATIONS]

做的事：
  1. 按 ast 定位函数（含装饰器）的精确行区间
  2. `@app.route(` → `@{bp}.route(`
  3. 从主模块删除这些区间（从后往前删，不破坏行号）
  4. 按原顺序追加到目标文件末尾
  5. `--rename` 给的每个名字做「独立标识符」级别的替换（加 nm. 前缀），
     带前后边界保护，不会误伤 CONFIG_FILE / SENSITIVE_CONFIG_KEYS 这类
  6. 搬完做一次语法检查

⚠️ 只做机械搬运，不改任何逻辑。改完必须跑 url_map + 行为快照。
"""

import ast
import io
import os
import re
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(APP_DIR, 'novel_manager.py')


def parse_args():
    args = sys.argv[1:]
    opts = {'to': None, 'bp': None, 'endpoints': [], 'rename': []}
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == '--to':
            opts['to'] = args[index + 1]
            index += 2
        elif arg == '--bp':
            opts['bp'] = args[index + 1]
            index += 2
        elif arg == '--endpoints':
            index += 1
            while index < len(args) and not args[index].startswith('--'):
                opts['endpoints'].append(args[index])
                index += 1
        elif arg == '--rename':
            index += 1
            while index < len(args) and not args[index].startswith('--'):
                opts['rename'].append(args[index])
                index += 1
        else:
            raise SystemExit(f'未知参数: {arg}')
    if not opts['to'] or not opts['bp'] or not opts['endpoints']:
        raise SystemExit(__doc__)
    return opts


def strip_globals(block, names):
    """删掉 `global X` 里被改名的名字。

    改成 `nm.X = ...` 之后就不再是模块全局赋值了，`global X` 必须一起去掉，
    否则 `global nm.X` 是语法错误。整行名字都被去光时原地留一条注释说明。
    """
    out = []
    for line in block.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped.startswith('global '):
            out.append(line)
            continue
        indent = line[:len(line) - len(line.lstrip())]
        parts = [p.strip() for p in stripped[len('global '):].split(',') if p.strip()]
        kept = [p for p in parts if p not in names]
        removed = [p for p in parts if p in names]
        if not kept:
            out.append(f"{indent}# 原本是 global {', '.join(removed)}，改用 nm.X 赋值后不再需要\n")
        else:
            out.append(f"{indent}global {', '.join(kept)}\n")
    return ''.join(out)


def apply_renames(block, names):
    """把独立的裸标识符加上 nm. 前缀（CONFIG -> nm.CONFIG）。

    整行注释跳过：注释里提到名字是为了给人看，加上 nm. 反而误导。
    """
    out = []
    for line in block.splitlines(keepends=True):
        if line.lstrip().startswith('#'):
            out.append(line)
            continue
        for name in names:
            pattern = re.compile(r'(?<![\w.])' + re.escape(name) + r'(?![\w])')
            line = pattern.sub('nm.' + name, line)
        out.append(line)
    return ''.join(out)


def main():
    opts = parse_args()
    target_path = os.path.join(APP_DIR, opts['to']) if not os.path.isabs(opts['to']) else opts['to']
    if not os.path.exists(target_path):
        raise SystemExit(f'目标文件不存在（先建好含 import 头的骨架）: {target_path}')

    source = io.open(SOURCE, encoding='utf-8').read()
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)

    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}

    blocks = []
    missing = []
    for endpoint in opts['endpoints']:
        node = functions.get(endpoint)
        if node is None:
            missing.append(endpoint)
            continue
        start = min(d.lineno for d in node.decorator_list) if node.decorator_list else node.lineno
        blocks.append((start, node.end_lineno, endpoint, node))
    if missing:
        raise SystemExit(f'找不到这些函数: {missing}')

    blocks.sort()

    # ---- 提取片段并改写装饰器 ----
    pieces = []
    for start, end, endpoint, node in blocks:
        segment = ''.join(lines[start - 1:end])
        before = segment.count('@app.')
        segment = segment.replace('@app.route(', f'@{opts["bp"]}.route(')
        segment = segment.replace('@app.get(', f'@{opts["bp"]}.get(')
        segment = segment.replace('@app.post(', f'@{opts["bp"]}.post(')
        if before and f'@{opts["bp"]}.' not in segment:
            raise SystemExit(f'{endpoint}: 装饰器改写失败')
        segment = strip_globals(segment, opts['rename'])
        segment = apply_renames(segment, opts['rename'])
        pieces.append((start, end, endpoint, segment))

    # ---- 备份并写目标文件 ----
    with io.open(target_path, encoding='utf-8') as handle:
        existing = handle.read()
    addition = '\n\n'.join(piece[3].rstrip('\n') for piece in pieces)
    if not existing.endswith('\n'):
        existing += '\n'
    new_target = existing + '\n\n' + addition + '\n'
    ast.parse(new_target)  # 语法自检
    io.open(target_path, 'w', encoding='utf-8', newline='\n').write(new_target)

    # ---- 从主模块删除（从后往前）----
    for start, end, endpoint, _ in reversed(pieces):
        del lines[start - 1:end]

    new_source = ''.join(lines)
    ast.parse(new_source)
    io.open(SOURCE, 'w', encoding='utf-8', newline='\n').write(new_source)

    print(f'搬走 {len(pieces)} 个路由 -> {opts["to"]}')
    for start, end, endpoint, _ in pieces:
        print(f'  {endpoint:28s} 原行 {start}-{end}（{end - start + 1} 行）')
    print(f'novel_manager.py 行数: {source.count(chr(10))} -> {new_source.count(chr(10))}')
    if opts['rename']:
        print(f'标识符改写: {", ".join("nm." + n for n in opts["rename"])}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
