# -*- coding: utf-8 -*-
"""导出 Flask 的 url_map 快照，用于模块化前后逐条 diff。

    python tests/snapshot_url_map.py                     # 打印到 stdout
    python tests/snapshot_url_map.py > docs/url_map_x.txt  # 落盘（显式重定向，别偷偷写文件）
    python tests/snapshot_url_map.py --with-line         # 附源码行号，拆分前定位用

输出格式固定为「方法 | 规则 | 端点」，按规则排序，可直接 diff。
容器内跑：docker exec novel-manager python /app/tests/snapshot_url_map.py
"""

import os
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

ONLY_STDOUT = '--stdout' in sys.argv
WITH_LINE = '--with-line' in sys.argv
_REAL_STDOUT = sys.stdout


def load_app():
    """兼容两种形态：拆分前（模块级 app）与拆分后（create_app 工厂）。"""
    sys.stdout = sys.stderr  # 启动日志别混进快照文件
    try:
        import novel_manager

        # 主模块里的模块级 app 才是真正注册了全部路由的那个实例；
        # create_app() 在阶段1只是个空壳（故意不注册路由）。
        # 所以永远优先取 novel_manager.app，取不到才退回工厂。
        instance = getattr(novel_manager, 'app', None)
        if instance is not None:
            return instance, novel_manager
        factory = getattr(novel_manager, 'create_app', None)
        if callable(factory):
            return factory(), novel_manager
        raise SystemExit('既没有 novel_manager.app 也没有 create_app')
    finally:
        sys.stdout = _REAL_STDOUT


def main():
    app, module = load_app()

    rows = []
    for rule in app.url_map.iter_rules():
        methods = ','.join(sorted(m for m in rule.methods if m not in ('HEAD', 'OPTIONS')))
        rows.append((rule.rule, methods, rule.endpoint))
    rows.sort()

    lines = []
    for rule, methods, endpoint in rows:
        lines.append(f'{methods:12s} | {rule:60s} | {endpoint}')

    output = '\n'.join(lines)
    print(f'# 共 {len(rows)} 条路由')
    print(output)

    if WITH_LINE:
        import inspect

        print('\n# ==== 每个路由的源文件与行号 ====')
        seen = {}
        for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
            func = app.view_functions.get(rule.endpoint)
            if func is None:
                continue
            target = func
            # 蓝图包装会多一层，取下划线开头之外的最内层原函数
            while hasattr(target, '__wrapped__'):
                target = target.__wrapped__
            try:
                source, lineno = inspect.getsourcelines(target)
                filename = inspect.getsourcefile(target)
            except (OSError, TypeError) as exc:
                print(f'# {rule.rule} -> 取不到源码: {exc}')
                continue
            seen.setdefault(rule.endpoint, (os.path.basename(filename or ''), lineno))

        for endpoint, (filename, lineno) in sorted(seen.items(), key=lambda kv: kv[1][1]):
            print(f'{lineno:5d}  {endpoint:38s} {filename}')

    if not ONLY_STDOUT:
        pass  # 需要落盘请自行重定向；不默认写文件，避免产生意料之外的文件
    return 0


if __name__ == '__main__':
    sys.exit(main())
