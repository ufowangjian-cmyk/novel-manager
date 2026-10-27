# -*- coding: utf-8 -*-
"""auth 蓝图。

只在这里建 Blueprint 对象；路由在 `routes.py`，由 `app.load_blueprints()`
在主模块初始化完成之后才 import —— 否则会撞上反向 import 的半初始化模块。
"""

from flask import Blueprint

# 不加 url_prefix：原路由都是 `/login`、`/api/users/...` 这种绝对路径，
# 蓝图只改端点命名空间（login -> auth.login），URL 规则本身不动。
auth_bp = Blueprint('auth', __name__)
