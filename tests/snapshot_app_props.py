# -*- coding: utf-8 -*-
"""Flask 实例属性快照：证明模块化前后「实例配置」一字不差。

只比配置与钩子清单，不比业务结果 —— 业务结果由 snapshot_behavior.py 管。

    python tests/snapshot_app_props.py > /tmp/props_after.txt
    diff /tmp/props_before.txt /tmp/props_after.txt
"""

import os
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

_REAL_STDOUT = sys.stdout


def load_app():
    sys.stdout = sys.stderr  # 启动日志别混进快照
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


def _pretty(value):
    if isinstance(value, bool) or value is None:
        return repr(value)
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if os.path.isabs(text):
        return text.replace(APP_DIR, '<APP>')
    return text


def main():
    app, module = load_app()

    print('# ==== app 基础属性 ====')
    for name in ('name', 'root_path', 'instance_path', 'template_folder',
                 'static_folder', 'static_url_path'):
        raw = getattr(app, name, None)
        if name in ('root_path', 'instance_path', 'static_folder') and raw:
            raw = str(raw).replace(APP_DIR, '<APP>')
        print(f'{name:22s} = {_pretty(raw)}')

    loader = getattr(app.jinja_loader, 'searchpath', None)
    if loader:
        print('jinja_searchpath      = ' + ', '.join(
            str(p).replace(APP_DIR, '<APP>') for p in loader))

    print()
    print('# ==== 关键 config ====')
    keys = [
        'SESSION_COOKIE_HTTPONLY', 'SESSION_COOKIE_SAMESITE', 'SESSION_COOKIE_SECURE',
        'SESSION_COOKIE_NAME', 'PERMANENT_SESSION_LIFETIME', 'SEND_FILE_MAX_AGE_DEFAULT',
        'MAX_CONTENT_LENGTH', 'JSON_AS_ASCII', 'JSON_SORT_KEYS', 'PROPAGATE_EXCEPTIONS',
        'TESTING', 'DEBUG', 'TRAP_HTTP_EXCEPTIONS', 'TRAP_BAD_REQUEST_ERRORS',
        'EXPLAIN_TEMPLATE_LOADING', 'PREFERRED_URL_SCHEME', 'APPLICATION_ROOT',
    ]
    for key in keys:
        if key in app.config:
            print(f'{key:26s} = {_pretty(app.config[key])}')
    print(f'{"SECRET_KEY(len)":26s} = {len(app.config.get("SECRET_KEY") or "")}')
    print(f'{"config.keys()":26s} = {len(app.config)} 项')

    print()
    print('# ==== 钩子清单（数量与顺序都必须一致）====')
    def _names(funcs, label):
        print(f'{label} ({len(funcs)}):')
        for func in funcs:
            target = func
            while hasattr(target, '__wrapped__'):
                target = target.__wrapped__
            module_name = getattr(target, '__module__', '?')
            qual = getattr(target, '__qualname__', getattr(target, '__name__', '?'))
            print(f'    {module_name}.{qual}')

    _names(app.before_request_funcs.get(None, []), 'before_request')
    _names(app.after_request_funcs.get(None, []), 'after_request')
    _names(app.teardown_request_funcs.get(None, []), 'teardown_request')
    _names(app.context_processors.get(None, []) if hasattr(app, 'context_processors')
           else app.template_context_processors.get(None, []), 'context_processor')
    _names(sorted(app.error_handler_spec.get(None, {}).get(None, {}).values(),
                  key=lambda f: getattr(f, '__name__', '')),
           'error_handler')

    print()
    print('# ==== 视图与蓝图 ====')
    print(f'view_functions   = {len(app.view_functions)} 个')
    print(f'blueprints       = {sorted(app.blueprints)}')
    print(f'url_map rules    = {len(list(app.url_map.iter_rules()))} 条')
    print(f'wsgi_app 中间件  = {type(app.wsgi_app).__name__}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
