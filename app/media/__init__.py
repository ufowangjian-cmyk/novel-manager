# -*- coding: utf-8 -*-
"""media 蓝图：配图检测 / 音视频 / 映射表 / 头图。

路由在 `routes.py`，由 `app.load_blueprints()` 在主模块初始化完成后才 import。
"""

from flask import Blueprint

media_bp = Blueprint('media', __name__)
