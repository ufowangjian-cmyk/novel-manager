# -*- coding: utf-8 -*-
"""reader 蓝图：阅读页 / 进度 / 书内搜索 / 记录清理。

路由在 `routes.py`，由 `app.load_blueprints()` 在主模块初始化完成后才 import。
"""

from flask import Blueprint

reader_bp = Blueprint('reader', __name__)
