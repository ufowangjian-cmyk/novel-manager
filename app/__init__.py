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

# 已注册的蓝图。阶段 2 起往里加 (blueprint, url_prefix) —— 集中在这里，
# 便于一眼看出「哪个 URL 前缀归哪个模块」。
BLUEPRINTS = []


def create_app(import_name='novel_manager', root_path=None, template_folder='templates'):
    """建 Flask 实例。

    只做「造实例」这一件事。配置（secret_key / session / 缓存头 / 压缩）仍留在
    novel_manager.py，因为它们依赖那边的 CONFIG 与工具函数；等阶段 2 拆 auth 时
    再逐步判断哪些可以搬过来。
    """
    app = Flask(
        import_name,
        root_path=root_path or APP_DIR,
        template_folder=template_folder,
    )
    return app


def register_blueprints(app):
    """把 BLUEPRINTS 里的蓝图挂到 app 上（阶段 2 起才会真正有内容）。"""
    for entry in BLUEPRINTS:
        blueprint, url_prefix = entry
        if url_prefix:
            app.register_blueprint(blueprint, url_prefix=url_prefix)
        else:
            app.register_blueprint(blueprint)
    return app
