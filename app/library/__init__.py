# -*- coding: utf-8 -*-
"""library 蓝图：列表 / 详情 / 扫描 / 标签 / 站点配置。

路由在 `routes.py`，由 `app.load_blueprints()` 在主模块初始化完成后才 import。
"""

from flask import Blueprint

library_bp = Blueprint('library', __name__)
