# -*- coding: utf-8 -*-
"""core 蓝图：PWA / 缓存统计 / 强制清理。

路由在 `routes.py`，由 `app.load_blueprints()` 在主模块初始化完成后才 import。
"""

from flask import Blueprint

core_bp = Blueprint('core', __name__)
