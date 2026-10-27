# -*- coding: utf-8 -*-
"""core 蓝图：PWA、静态资源辅助、缓存统计与强制清理等跨域基础设施。

这四条路由不属于任何业务域，放这里让 `novel_manager.py` 彻底不含 `@app.route`。

共享物反向 import 主模块，原因见 `app/auth/routes.py` 顶部。
⚠️ `CONFIG` 走 `nm.*`（会被 `save_config_api` 整体替换）。
"""

import gc
import os

from flask import jsonify, request, send_from_directory, session

from . import core_bp

import novel_manager as nm
from novel_manager import (
    BASE_DIR,
    _image_check_cache,
    _work_id_file_cache,
    _work_id_sets,
    aggressive_cache_cleanup,
    chapter_cache,
    image_cache,
    is_admin,
    is_authenticated,
    line_cache,
    line_cache_bytes,
    logger,
    tag_parse_cache,
    trim_memory,
    work_id_cache_kb,
)


@core_bp.route('/api/force_cleanup', methods=['POST'])
def force_cleanup():
    """强制清理缓存释放内存"""
    logger.info(
        f"force_cleanup 被调用: user_role={session.get('user_role')}, "
        f"authenticated={session.get('authenticated')}"
    )

    if not is_admin():
        logger.warning("force_cleanup 权限不足，拒绝执行")
        return jsonify({'success': False, 'message': '权限不足'}), 403

    # deep=true 时连热缓存一起丢（keep 全 0），用于「我就是要立刻把内存压下去」
    payload = request.get_json(silent=True) or {}
    deep = bool(payload.get('deep'))

    # 1) 清缓存（原地）
    if deep:
        result = aggressive_cache_cleanup(
            keep_tag=0, keep_chapter=0, keep_image=0,
            keep_work_id=0, keep_mapping=0
        )
    else:
        result = aggressive_cache_cleanup()

    # line_cache 才是真正的大头，单独统计后清空
    line_before = len(line_cache)
    line_mb_before = round(line_cache_bytes() / 1024 / 1024, 2)
    line_cache.clear()
    result['line'] = line_before
    result['line_mb'] = line_mb_before

    # 清理后各缓存「还剩多少」——前端用它来解释为什么没有归零
    result['remaining'] = {
        'tag': len(tag_parse_cache),
        'chapter': len(chapter_cache),
        'image': len(image_cache),
        'line': len(line_cache),
        'work_id_file': len(_work_id_file_cache),
        'work_id_set': len(_work_id_sets),
    }
    result['deep'] = deep

    # 2) 触发 GC，回收不可达对象
    collected = gc.collect()
    result['gc_collected'] = collected

    # 3) 关键：让 glibc 把空闲内存归还 OS
    trimmed = trim_memory()
    result['memory_trimmed'] = trimmed

    # 4) 获取当前内存信息
    try:
        import psutil
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024
        result['memory_mb'] = round(memory_mb, 1)
    except Exception:
        # 回退到 /proc
        try:
            with open('/proc/self/statm', 'r') as f:
                parts = f.read().split()
                if len(parts) >= 2:
                    result['memory_mb'] = round(int(parts[1]) * 4 / 1024, 1)
        except Exception:
            pass

    logger.info(f"force_cleanup 完成: {result}")
    return jsonify({'success': True, 'result': result})

@core_bp.route('/manifest.json')
def pwa_manifest():
    theme = request.args.get('theme')
    if theme not in ('light', 'dark'):
        theme = nm.CONFIG.get('theme', 'auto')
        if theme == 'auto':
            theme = 'dark'  # 服务端默认

    theme_color = '#ffffff' if theme == 'light' else '#131a12'

    manifest = {
        "name": "摸鱼读物",
        "short_name": "被窝阅读器",
        "description": "个人小说阅读管理器",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": theme_color,
        "theme_color": theme_color,
        "lang": "zh-CN",
        "dir": "ltr",
        "categories": ["books", "productivity"],
        "icons": [
            {"src": "/static/images/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/static/images/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/static/images/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}
        ],
        "shortcuts": [
            {
                "name": "继续阅读",
                "short_name": "继续",
                "url": "/",
                "icons": [{"src": "/static/images/icon-192.png", "sizes": "192x192"}]
            }
        ]
    }
    return jsonify(manifest)

@core_bp.route('/service-worker.js')
def pwa_service_worker():
    """Service Worker - 必须从根路径访问，才能覆盖整个网站"""
    from flask import send_from_directory
    response = send_from_directory(
        os.path.join(BASE_DIR, 'static'),
        'service-worker.js',
        mimetype='application/javascript'
    )
    # 关键：告诉浏览器不要缓存 SW 本身
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    # 允许跨域（如果以后有子域）
    response.headers['Service-Worker-Allowed'] = '/'
    return response

@core_bp.route('/api/cache/stats')
def get_cache_stats():
    """获取缓存统计信息"""
    if not is_authenticated():
        return jsonify({'error': '未登录'}), 401

    memory_mb = None

    # 优先用 psutil（最准确）
    try:
        import psutil
        process = psutil.Process()
        memory_mb = round(process.memory_info().rss / 1024 / 1024, 1)
    except Exception:
        pass

    # psutil 不可用，回退到 /proc/self/statm
    if memory_mb is None or memory_mb == 0:
        try:
            with open('/proc/self/statm', 'r') as f:
                parts = f.read().split()
                if len(parts) >= 2:
                    # 第一列是总虚拟内存页数，第二列是常驻内存页数(RSS)
                    # 用第二列更准确
                    rss_pages = int(parts[1])
                    memory_mb = round(rss_pages * 4 / 1024, 1)
        except Exception:
            pass

    # 指纹缓存条数（前缀之和）+ 估算占用，前端「其他缓存」用
    work_id_count = len(_work_id_file_cache) + len(_work_id_sets)
    work_id_kb = round(work_id_cache_kb(), 1)

    return jsonify({
        'tag_cache': len(tag_parse_cache),
        'chapter_cache': len(chapter_cache),
        'image_cache': len(image_cache),
        'image_check_cache': len(_image_check_cache),
        'line_cache': len(line_cache),
        'line_cache_mb': round(line_cache_bytes() / 1024 / 1024, 2),
        'work_id_count': work_id_count,
        'work_id_kb': work_id_kb,
        'memory_mb': memory_mb
    })
