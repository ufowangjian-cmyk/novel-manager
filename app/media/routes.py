# -*- coding: utf-8 -*-
"""media 蓝图：配图检测、音视频服务、映射表、头图。

划分见 `docs/blueprint-roadmap.md`（media = 10 条路由）。

共享物反向 import 主模块，原因见 `app/auth/routes.py` 顶部。
⚠️ `_image_mapping_cache` 走 `nm.*`：`save_image_mapping` 会重新赋值它。
"""

import os
import subprocess
import sys

from flask import jsonify, request, send_file

from . import media_bp

import novel_manager as nm
from novel_manager import (
    AUDIO_EXTENSIONS,
    IMAGE_EXTENSIONS,
    IMAGE_MAPPING_FILE,
    MIME_TYPES,
    VIDEO_EXTENSIONS,
    check_image_folder_cached,
    is_inside_novel_dir,
    list_header_bg_images,
    load_emoji_mapping_cached,
    load_image_mapping_cached,
    logger,
    resolve_media_path,
    save_json_file,
)


@media_bp.route('/api/header_bg_images')
def api_header_bg_images():
    return jsonify({'images': list_header_bg_images()})

@media_bp.route('/api/check_image_folder', methods=['POST'])
def check_image_folder():
    data = request.get_json(silent=True) or {}
    folders = data.get('folders', [])

    if not isinstance(folders, list):
        return jsonify({'exists': False, 'path': None}), 400

    # 只允许探测小说目录内的文件夹
    safe_folders = [str(f) for f in folders[:10] if f and is_inside_novel_dir(f)]
    if not safe_folders:
        return jsonify({'exists': False, 'path': None})

    return jsonify(check_image_folder_cached(safe_folders))

@media_bp.route('/api/local_image')
def serve_local_image():
    folder = request.args.get('folder', '')
    name = request.args.get('name', '')

    found = resolve_media_path(folder, name, IMAGE_EXTENSIONS)
    if not found:
        return '', 404

    img_path, ext = found
    resp = send_file(img_path, mimetype=MIME_TYPES.get(ext, 'application/octet-stream'))
    # send_file 默认吃 SEND_FILE_MAX_AGE_DEFAULT（30 天），配图文件夹里的图
    # 是被同名替换的高频对象——缓存 30 天会导致换了图浏览器不换。
    # no-cache + send_file 自带的 Last-Modified/ETag：每次带条件请求
    # 重新验证，没变回 304（几字节），变了立刻拿新图。
    resp.headers['Cache-Control'] = 'no-cache'
    return resp

@media_bp.route('/api/list_image_folder', methods=['POST'])
def list_image_folder():
    data = request.get_json(silent=True) or {}
    folder = data.get('folder', '')

    if not folder or not is_inside_novel_dir(folder) or not os.path.isdir(folder):
        return jsonify({'files': []})

    try:
        entries = os.listdir(folder)
    except OSError as e:
        logger.warning(f"列目录失败 {folder}: {e}")
        return jsonify({'files': []})

    files = [f for f in entries if os.path.splitext(f)[1].lower() in set(IMAGE_EXTENSIONS)]
    return jsonify({'files': files})

@media_bp.route('/api/open_folder', methods=['POST'])
def open_folder():
    data = request.get_json(silent=True) or {}
    path = data.get('path', '')

    # 只允许打开小说目录内的路径，避免被当成任意路径启动器
    if not path or not is_inside_novel_dir(path) or not os.path.exists(path):
        return jsonify({'success': False, 'message': '文件夹不存在或不在小说目录内'})

    try:
        if sys.platform == 'win32':
            os.startfile(path)  # noqa: S606 - 本机自用功能
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@media_bp.route('/api/local_video')
def serve_local_video():
    folder = request.args.get('folder', '')
    name = request.args.get('name', '')

    found = resolve_media_path(folder, name, VIDEO_EXTENSIONS)
    if not found:
        return '', 404

    video_path, ext = found
    resp = send_file(video_path, mimetype=MIME_TYPES.get(ext, 'video/mp4'))
    # 同 local_image：媒体文件不参与 30 天静态缓存（见上注释）
    resp.headers['Cache-Control'] = 'no-cache'
    return resp

@media_bp.route('/api/local_audio')
def serve_local_audio():
    folder = request.args.get('folder', '')
    name = request.args.get('name', '')

    found = resolve_media_path(folder, name, AUDIO_EXTENSIONS)
    if not found:
        return '', 404

    audio_path, ext = found
    resp = send_file(audio_path, mimetype=MIME_TYPES.get(ext, 'audio/mpeg'))
    # 同 local_image：媒体文件不参与 30 天静态缓存（见上注释）
    resp.headers['Cache-Control'] = 'no-cache'
    return resp

@media_bp.route('/api/emoji/image-mapping')
def get_image_mapping():
    return jsonify(load_image_mapping_cached())

@media_bp.route('/api/emoji/image-mapping/save', methods=['POST'])
def save_image_mapping():
    # 原本是 global _image_mapping_cache，改用 nm.X 赋值后不再需要
    try:
        mapping = request.get_json(silent=True)
        if not isinstance(mapping, dict):
            return jsonify({'success': False, 'message': '数据格式错误'})
        save_json_file(IMAGE_MAPPING_FILE, mapping)
        nm._image_mapping_cache = mapping
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@media_bp.route('/api/emoji/mapping')
def get_emoji_mapping():
    return jsonify(load_emoji_mapping_cached())
