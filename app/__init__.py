# -*- coding: utf-8 -*-
"""Flask 应用工厂。

拆分路线见 `docs/blueprint-roadmap.md`（77 条路由 → auth/library/reader/media/core）。

当前进度
--------
- 阶段 1（已完成）：`create_app()` 只接管「Flask 实例创建」。路由仍由主模块
  `novel_manager.py` 用 `@app.route` 注册 —— 这一步的目的只是把「造 app」的
  职责从主模块挪出来，为后面注册蓝图留出位置。
- 阶段 2 起：把路由按域搬进 `app/<domain>/routes.py`，在 `create_app()` 里注册蓝图。

刻意保持不变的东西
------------------
- `import_name` 仍是 `'novel_manager'`：它决定 `app.name`、Jinja 的 root、
  `url_for('static')` 的解析基础，换掉会引起难以察觉的行为差异。
- `root_path` 显式指向项目根目录（不是 `app/`），否则 `templates/` 和 `static/`
  会解析到 `app/` 下面去 —— 模板找不到，所有页面 500。
- 不给蓝图单独配 `static_folder` / `template_folder`：全局只有一套。
"""

import os

from flask import Flask

# 项目根目录 = novel_manager.py 所在目录（app/ 的上一级）
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 已迁入蓝图的域：(模块名, 蓝图变量名, url_prefix)。加新域时补一行。
# 顺序 = 注册顺序；url_prefix 为 None 表示路由里自带完整路径前缀。
BLUEPRINT_MODULES = [
    ('app.auth', 'auth_bp', None),
    ('app.library', 'library_bp', None),
    ('app.reader', 'reader_bp', None),
]


def create_app(import_name='novel_manager', root_path=None, template_folder='templates'):
    """建 Flask 实例。

    只做「造实例」这一件事。配置（secret_key / session / 缓存头 / 压缩）仍留在
    novel_manager.py，因为它们依赖那边的 CONFIG 与工具函数。
    """
    app = Flask(
        import_name,
        root_path=root_path or APP_DIR,
        template_folder=template_folder,
    )
    return app


def load_blueprints():
    """import 各域路由模块，返回 [(blueprint, url_prefix), ...]。

    ⚠️ 必须在主模块（novel_manager）初始化完成之后才调用。
    蓝图模块反向 import 主模块的共享状态（CONFIG / is_admin / save_json_file…），
    提前 import 会拿到半初始化的模块，报 ImportError。

    所以这里用「函数内 import」而不是模块顶层 import。
    """
    import importlib

    loaded = []
    for module_name, bp_attr, url_prefix in BLUEPRINT_MODULES:
        package = importlib.import_module(module_name)
        # 触发 routes 子模块的装饰器执行，路由才会挂到 blueprint 上
        importlib.import_module(f'{module_name}.routes')
        loaded.append((getattr(package, bp_attr), url_prefix))
    return loaded


def register_blueprints(app):
    """把已迁出的域挂到 app 上。"""
    for blueprint, url_prefix in load_blueprints():
        if url_prefix:
            app.register_blueprint(blueprint, url_prefix=url_prefix)
        else:
            app.register_blueprint(blueprint)
    return app
