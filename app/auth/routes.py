# -*- coding: utf-8 -*-
"""auth 蓝图：登录、登出、用户管理、个人阅读偏好。

划分依据见 `docs/blueprint-roadmap.md`（auth = 9 条路由）。

为什么这里要反向 import 主模块
------------------------------
本项目的共享状态（CONFIG、novel_data、各类缓存）和被十几处路由复用的工具函数
（is_admin、save_json_file、normalize_user_info…）目前都还住在 `novel_manager.py`。
把它们整体下沉到 `app/core/` 会牵动 200+ 个引用点，风险远大于收益，所以本次
重构采取「路由搬走、共享物原地不动」的方式：蓝图反向 import 主模块取用。

这样做的前提是**注册时机**：`register_blueprints()` 由 `novel_manager.py` 在文件
末尾调用，那时主模块的全局名字已经全部就绪，反向 import 才不会拿到半成品。
见 `app/__init__.py` 的 `load_blueprints()`。

为什么 CONFIG 要用 `novel_manager.CONFIG` 而不是 `from ... import CONFIG`
--------------------------------------------------------------------------
`save_config_api` / `reload_config_api` 里有 `global CONFIG; CONFIG = 新dict`，
也就是**整个对象会被替换**。如果用 from-import，本模块会绑死在旧 dict 上，
表现为「在配置页保存一次之后，用户管理读到的还是旧用户表」，直到重启才恢复。
所以凡是可能被重新赋值的全局量，一律通过模块属性访问。
"""

import os
import random

from flask import jsonify, redirect, render_template, request, session, url_for

from . import auth_bp

import novel_manager as nm
from novel_manager import (
    AVATAR_COLORS,
    AVATAR_ICONS,
    CONFIG_FILE,
    avatar_look,
    ensure_avatar_seed,
    find_user_by_password,
    get_current_user_info,
    get_user_record_file,
    hash_password,
    is_admin,
    is_authenticated,
    logger,
    migrate_record_file,
    new_user_key,
    normalize_user_info,
    password_used_by_others,
    resolve_reader_prefs,
    save_json_file,
)

#==================== 登录 =====================
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    users = nm.CONFIG.get('users', {}) or {}
    has_users = bool(users)

    # 没有用户时不再自动创建硬编码后门账号，只允许通过环境变量初始化
    if not has_users:
        default_admin_password = (os.environ.get('DEFAULT_ADMIN_PASSWORD') or '').strip()
        if default_admin_password:
            key = new_user_key()
            users = {key: {'role': 'admin', 'user_id': 'admin',
                           'password_hash': hash_password(default_admin_password)}}
            nm.CONFIG['users'] = users
            save_json_file(CONFIG_FILE, nm.CONFIG)
            has_users = True
            logger.warning("⚠️ 用户表为空，已用 DEFAULT_ADMIN_PASSWORD 初始化管理员账号")
        else:
            logger.error("❌ 用户表为空：请设置 DEFAULT_ADMIN_PASSWORD 环境变量或恢复 config.json 中的 users")
            return render_template('login.html', error='系统未配置任何用户，请设置 DEFAULT_ADMIN_PASSWORD 环境变量后重启', has_users=False)

    if request.method == 'POST':
        password = request.form.get('password', '')
        user_key, user_info = find_user_by_password(password)

        # 兼容手工写进 config.json 的明文密码条目：首次登录时自动升级
        if user_key is None and password and password in users:
            legacy_info = normalize_user_info(users[password], password)
            new_key = new_user_key()
            legacy_info['password_hash'] = hash_password(password)
            users.pop(password, None)
            users[new_key] = legacy_info
            nm.CONFIG['users'] = users
            save_json_file(CONFIG_FILE, nm.CONFIG)
            migrate_record_file(password, new_key)
            user_key, user_info = new_key, legacy_info
            logger.info("🔐 检测到明文密码用户，已自动升级为哈希存储")

        if user_key:
            role = user_info.get('role', 'user')
            user_id = user_info.get('user_id', user_key)

            session.clear()
            session.permanent = True
            session['authenticated'] = True
            session['user_key'] = user_key          # 只保存不可猜的用户标识，不保存密码
            session['user_role'] = role
            session['user_id'] = user_id
            session['user_name'] = f"{user_id}（{'管理员' if role == 'admin' else '普通用户'}）"

            logger.info(f"✅ 用户登录: {role} ({user_id})")

            record_file = get_user_record_file(user_key)
            if not os.path.exists(record_file):
                save_json_file(record_file, {})

            next_url = request.args.get('next', '')
            if next_url.startswith('/') and not next_url.startswith('//'):
                return redirect(next_url)
            return redirect(url_for('index'))
        else:
            logger.warning(f"⚠️ 登录失败，密码错误（长度 {len(password)}）")
            return render_template('login.html', error='密码错误', has_users=has_users)

    return render_template('login.html', has_users=has_users)

#==================== 登出 =====================
@auth_bp.route('/logout')
def logout():
    user_name = session.get('user_name', '未知用户')
    print(f"👋 用户登出: {user_name}")
    session.clear()
    return redirect(url_for('auth.login'))

# ==================== 用户管理 API ====================

@auth_bp.route('/api/users/list')
def api_users_list():
    """获取所有用户列表（只返回不可猜的 user key，绝不返回密码或哈希）"""
    if not is_admin():
        return jsonify({'error': '权限不足'}), 403

    users = nm.CONFIG.get('users', {}) or {}
    user_list = []
    for key, user_info in users.items():
        info = normalize_user_info(user_info, key)
        # 老用户首次进这个页面时补一个 seed（写盘一次，之后直接读）
        avatar_seed = ensure_avatar_seed(key)
        avatar_icon, avatar_color = avatar_look(avatar_seed)
        user_list.append({
            'key': key,
            'role': info.get('role', 'user'),
            'user_id': info.get('user_id', key),
            'preferences': info.get('preferences', {}) or {},
            'avatar_seed': avatar_seed,
            'avatar_icon': avatar_icon,
            'avatar_color': avatar_color,
        })
    return jsonify(user_list)


@auth_bp.route('/api/avatar/options')
def api_avatar_options():
    """可选头像（Lucide 图标名 + 描边色）。配置页编辑用户时用来渲染选择器。"""
    if not is_admin():
        return jsonify({'error': '权限不足'}), 403
    return jsonify({'icons': list(AVATAR_ICONS), 'colors': list(AVATAR_COLORS)})

#=================== 添加用户 API ====================
@auth_bp.route('/api/users/add', methods=['POST'])
def api_users_add():
    """添加用户"""
    if not is_admin():
        return jsonify({'success': False, 'message': '权限不足'}), 403

    data = request.get_json(silent=True) or {}
    password = (data.get('password') or '').strip()
    role = data.get('role', 'user')
    user_id = (data.get('user_id') or '').strip()

    if not password:
        return jsonify({'success': False, 'message': '密码不能为空'})
    if len(password) < 4:
        return jsonify({'success': False, 'message': '密码长度至少4位'})
    if not user_id:
        return jsonify({'success': False, 'message': '显示名称不能为空'})
    if role not in ['admin', 'user']:
        return jsonify({'success': False, 'message': '角色无效'})

    users = nm.CONFIG.get('users', {}) or {}

    if password_used_by_others(password):
        return jsonify({'success': False, 'message': '该密码已被其它用户使用，请更换'})

    for existing in users.values():
        info = normalize_user_info(existing, '')
        if info.get('user_id') == user_id:
            return jsonify({'success': False, 'message': f'显示名称 "{user_id}" 已存在'})

    key = new_user_key()
    users[key] = {
        'role': role,
        'user_id': user_id,
        'password_hash': hash_password(password),
        # 新用户直接分配头像 seed，省得第一次打开首页才懒生成
        'avatar': {'seed': random.randint(1, 999999)},
    }
    nm.CONFIG['users'] = users
    save_json_file(CONFIG_FILE, nm.CONFIG)
    save_json_file(get_user_record_file(key), {})

    logger.info(f"✅ 用户已添加: {user_id} -> {role} (key={key})")
    return jsonify({'success': True, 'key': key})

#=================== 编辑用户 API ====================
@auth_bp.route('/api/users/edit', methods=['POST'])
def api_users_edit():
    """编辑用户（user_key 标识用户；新密码只存哈希）"""
    if not is_admin():
        return jsonify({'success': False, 'message': '权限不足'}), 403

    data = request.get_json(silent=True) or {}
    user_key = (data.get('user_key') or data.get('old_password') or '').strip()
    new_password = (data.get('new_password') or '').strip()
    role = data.get('role', 'user')
    user_id = (data.get('user_id') or '').strip()
    keep_preferences = data.get('keep_preferences', True)

    # 头像：传了 avatar_seed 就换，没传保留原来的
    # （下面 new_info 是重建的 dict，不显式带上就会把 avatar 丢掉）
    avatar_seed = None
    if data.get('avatar_seed') is not None:
        try:
            avatar_seed = int(data.get('avatar_seed'))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': '头像参数无效'})
        if avatar_seed < 0 or avatar_seed > 9999999:
            return jsonify({'success': False, 'message': '头像参数超出范围'})

    if not user_id:
        return jsonify({'success': False, 'message': '显示名称不能为空'})

    if new_password and len(new_password) < 4:
        return jsonify({'success': False, 'message': '密码长度至少4位'})

    if role not in ['admin', 'user']:
        return jsonify({'success': False, 'message': '角色无效'})

    users = nm.CONFIG.get('users', {}) or {}

    if user_key not in users:
        return jsonify({'success': False, 'message': '用户不存在'})

    # 不允许把最后一个管理员降级（否则会把自己锁在门外）
    if role != 'admin':
        admin_keys = [k for k, v in users.items() if normalize_user_info(v, k).get('role') == 'admin']
        if user_key in admin_keys and len(admin_keys) <= 1:
            return jsonify({'success': False, 'message': '不能取消最后一个管理员的管理员身份'})

    if new_password and password_used_by_others(new_password, exclude_key=user_key):
        return jsonify({'success': False, 'message': '该密码已被其它用户使用，请更换'})

    old_info = normalize_user_info(users[user_key], user_key)
    new_info = {
        'role': role,
        'user_id': user_id,
    }
    if keep_preferences and old_info.get('preferences'):
        new_info['preferences'] = old_info['preferences']
    # 头像：优先用新选中的，否则沿用旧的（老用户可能还没有，交给懒生成）
    if avatar_seed is not None:
        new_info['avatar'] = {'seed': avatar_seed}
    elif isinstance(old_info.get('avatar'), dict):
        new_info['avatar'] = old_info['avatar']
    new_info['password_hash'] = old_info.get('password_hash')
    if new_password:
        new_info['password_hash'] = hash_password(new_password)

    users[user_key] = new_info
    nm.CONFIG['users'] = users
    save_json_file(CONFIG_FILE, nm.CONFIG)

    if user_key == nm.current_user_key():
        session['user_role'] = role
        session['user_id'] = user_id
        session['user_name'] = f"{user_id}（{'管理员' if role == 'admin' else '普通用户'}）"

    return jsonify({'success': True})

#=================== 删除用户 API ====================
@auth_bp.route('/api/users/delete', methods=['POST'])
def api_users_delete():
    """删除用户"""
    if not is_admin():
        return jsonify({'success': False, 'message': '权限不足'}), 403

    data = request.get_json(silent=True) or {}
    user_key = (data.get('user_key') or data.get('password') or '').strip()

    users = nm.CONFIG.get('users', {}) or {}

    if user_key not in users:
        return jsonify({'success': False, 'message': '用户不存在'})

    info = normalize_user_info(users[user_key], user_key)
    user_role = info.get('role', 'user')

    # 检查管理员数量
    admin_count = sum(1 for k, u in users.items() if normalize_user_info(u, k).get('role') == 'admin')
    if user_role == 'admin' and admin_count <= 1:
        return jsonify({'success': False, 'message': '不能删除最后一个管理员'})

    # 删除记录文件（含锁文件）
    record_file = get_user_record_file(user_key)
    try:
        if os.path.exists(record_file):
            os.remove(record_file)
        if os.path.exists(record_file + '.lock'):
            os.remove(record_file + '.lock')
    except OSError as e:
        logger.warning(f"删除记录文件失败: {e}")

    display_name = info.get('user_id', user_key)
    del users[user_key]
    nm.CONFIG['users'] = users
    save_json_file(CONFIG_FILE, nm.CONFIG)

    logger.info(f"✅ 用户已删除: {display_name}")
    return jsonify({'success': True})

#=================== 获取当前用户偏好 API ====================
@auth_bp.route('/api/get_preferences')
def api_get_preferences():
    """获取当前登录用户的阅读偏好

    overrides: 该用户自己设置过的项（空 = 跟随全局默认）
    effective: 全局默认 + 个人覆盖后真正生效的值，供前端显示占位提示
    """
    if not is_authenticated():
        return jsonify({'error': '未登录'}), 401

    _, user_info = get_current_user_info()
    if not user_info:
        return jsonify({'error': '未登录'}), 401

    overrides = user_info.get('preferences', {}) or {}
    payload = dict(overrides)          # 兼容旧调用方：顶层直接是偏好键
    payload['overrides'] = overrides
    payload['effective'] = resolve_reader_prefs(user_info)
    return jsonify(payload)

#=================== 保存当前用户偏好 API ====================
@auth_bp.route('/api/save_preferences', methods=['POST'])
def api_save_preferences():
    """保存当前登录用户的阅读偏好（增量合并）"""
    if not is_authenticated():
        return jsonify({'success': False, 'message': '未登录'}), 401

    user_key, user_info = get_current_user_info()
    if not user_key or not user_info:
        return jsonify({'success': False, 'message': '未登录'}), 401

    data = request.get_json(silent=True) or {}

    # 只允许白名单字段，避免前端乱塞
    ALLOWED_KEYS = {
        'font_size', 'font_family', 'line_height', 'theme',
        'speech_rate', 'speech_pitch',
        'auto_save_progress', 'show_word_count',
        'indent_paragraph', 'paragraph_spacing',
        'reader_theme',
        'drag_scroll', 'text_select',
        # 列表与显示（列表排序 / 分页 / 日期格式等，2026-10-19 开放给普通用户）
        'default_sort_by', 'default_sort_order',
        'per_page', 'words_per_page', 'max_tags_display', 'date_format',
        # 分元素字体扩展（标题 + reader-core 全部高亮类型）
        'title_font_family', 'double_quote_font_family', 'single_quote_font_family', 'bracket_font_family',
        'square_bracket_font_family', 'square_bracket_1_font_family', 'hollow_bracket_font_family', 'book_font_family',
        # 分元素 加粗/斜体（正文 + 标题 + reader-core 全部高亮类型）
        'body_bold', 'body_italic', 'title_bold', 'title_italic',
        'double_quote_bold', 'double_quote_italic', 'single_quote_bold', 'single_quote_italic',
        'bracket_bold', 'bracket_italic', 'square_bracket_bold', 'square_bracket_italic',
        'square_bracket_1_bold', 'square_bracket_1_italic', 'hollow_bracket_bold', 'hollow_bracket_italic',
        'book_bold', 'book_italic',
    }

    prefs_to_save = {k: v for k, v in data.items() if k in ALLOWED_KEYS}

    if not prefs_to_save:
        return jsonify({'success': False, 'message': '没有可保存的偏好字段'})

    users = nm.CONFIG.get('users', {}) or {}
    if user_key not in users:
        return jsonify({'success': False, 'message': '用户不存在'}), 404

    prefs = user_info.get('preferences', {}) or {}

    # 传空字符串 = 「恢复为跟随全局默认」，把该键从个人覆盖里删掉，
    # 而不是存一个空值（否则 resolve_reader_prefs 会拿到无意义的字符串）
    cleared_keys = []
    for k, v in prefs_to_save.items():
        if isinstance(v, str) and v.strip() == '':
            cleared_keys.append(k)
            prefs.pop(k, None)

    effective = {k: v for k, v in prefs_to_save.items() if k not in cleared_keys}
    prefs.update(effective)
    user_info['preferences'] = prefs
    users[user_key] = user_info

    nm.CONFIG['users'] = users
    save_json_file(CONFIG_FILE, nm.CONFIG)

    logger.debug(
        f"💾 用户偏好已更新: 设置 {list(effective.keys())} / 清除 {cleared_keys} -> {user_key}"
    )
    return jsonify({'success': True, 'preferences': prefs})
