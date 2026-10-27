# -*- coding: utf-8 -*-
"""library 蓝图：书架的主体 —— 列表、详情、扫描、标签体系、站点配置。

划分见 `docs/blueprint-roadmap.md`（library = 43 条路由）。

本文件按批次追加，当前进度：

  批次 1  ✅ 筛选选项取数（get_all_*/get_first_*）、`/config/get`、
             `/config/save_sort`、随机推荐、扫描状态与触发、配置页/标签页壳
  批次 2  ⏳ 标签体系（26 条）
  批次 3  ⏳ index / novel_detail / save_config / reload_config

共享物仍从主模块反向 import（原因见 `app/auth/routes.py` 顶部说明）。
⚠️ `CONFIG` 一律用 `nm.CONFIG`：`save_config_api` / `reload_config_api` 会整体替换
   这个对象，from-import 会绑死旧 dict。
"""

import json
import os
import re
import threading
import time
import traceback
import urllib.parse

from flask import jsonify, redirect, render_template, request, session, url_for

from . import library_bp

import novel_manager as nm
from novel_manager import (
    CONFIG_FILE,
    CONFIG_SAVE_WHITELIST,
    SENSITIVE_CONFIG_KEYS,
    TAG_RULES_FILE,
    annotate_reading_status,
    apply_runtime_config,
    author_names_of,
    avatar_look,
    build_author_identity_map,
    build_recent_records,
    build_similar_urls,
    chapter_cache,
    compute_recent_stats,
    compute_work_id,
    ensure_avatar_seed,
    extract_intro_clean,
    extract_preview_clean,
    find_similar_novels,
    get_cache_overview,
    get_current_user_info,
    get_file_hash,
    get_filter_options_cached,
    get_work_id_from_cache,
    group_recent_records,
    hash_password,
    invalidate_filter_cache,
    is_admin,
    is_authenticated,
    is_file_readable,
    load_config,
    load_json_file,
    load_reading_records,
    load_scan_stats,
    load_tag_rules,
    logger,
    normalize_tag_keywords,
    parse_file_content_fast,
    parse_novel_details,
    password_used_by_others,
    pick_random_novel,
    remember_home_page,
    render_missing_page,
    resolve_home_page,
    resolve_novel_path,
    resolve_reader_prefs,
    resolve_record_by_path,
    save_cache,
    save_json_file,
    save_tag_rules_file,
    scan_novel_files_background,
    scan_progress,
    split_author_aliases,
    tag_parse_cache,
)


@library_bp.route('/api/scan_progress')
def get_scan_progress():
    if scan_progress['status'] == 'scanning':
        # 分阶段加权：增量的「检查书目」占 0-55%，「解析」占 55-100%；
        # 全量扫描没有检查阶段，直接 0-100%。这样 total 切换时百分比不会倒退。
        _cur = scan_progress['current']
        _tot = scan_progress['total']
        if scan_progress.get('phase') == 'scan_dir':
            percentage = int(_cur / _tot * 55) if _tot else 0
        elif scan_progress.get('incremental'):
            percentage = 55 + int(_cur / _tot * 45) if _tot else 55
        else:
            percentage = int(_cur / _tot * 100) if _tot else 0
        elapsed = time.time() - scan_progress['start_time'] if scan_progress['start_time'] else 0

        if scan_progress['current'] > 0:
            speed = scan_progress['current'] / elapsed if elapsed > 0 else 0
            remaining = (scan_progress['total'] - scan_progress['current']) / speed if speed > 0 else 0
        else:
            remaining = 0

        return jsonify({
            'status': scan_progress['status'],
            'current': scan_progress['current'],
            'total': scan_progress['total'],
            'percentage': percentage,
            'message': scan_progress['message'],
            'elapsed': int(elapsed),
            'remaining': int(remaining)
        })
    else:
        return jsonify({
            'status': scan_progress['status'],
            'message': scan_progress['message'],
            'total': scan_progress['total'],
            'current': scan_progress['current'],
            # 完成时明确给出 100%，前端不必自己推断
            'percentage': 100 if scan_progress['status'] == 'completed' else 0
        })

@library_bp.route('/api/start_scan')
def start_scan():
    full = request.args.get('full', 'false').lower() == 'true'
    print(f"📡 收到扫描请求: full={full}, 当前状态={scan_progress['status']}")

    if scan_progress['status'] != 'scanning':
        thread = threading.Thread(target=scan_novel_files_background, args=(full,))
        thread.daemon = True
        thread.start()
        print("✅ 已启动扫描线程")
        return jsonify({'status': 'started', 'full_scan': full})
    else:
        print("⚠️ 已有扫描任务进行中")
        return jsonify({'status': 'already_scanning'})

@library_bp.route('/get_all_authors')
def get_all_authors():
    authors, _, _ = get_filter_options_cached()
    return jsonify({'authors': authors})

@library_bp.route('/get_all_tags')
def get_all_tags():
    _, tags, _ = get_filter_options_cached()
    return jsonify({'tags': tags})

@library_bp.route('/get_all_sites')
def get_all_sites():
    _, _, sites = get_filter_options_cached()
    return jsonify({'sites': sites})

@library_bp.route('/get_first_authors')
def get_first_authors():
    authors, _, _ = get_filter_options_cached()
    return jsonify({'authors': authors[:100], 'total': len(authors)})

@library_bp.route('/get_first_tags')
def get_first_tags():
    _, tags, _ = get_filter_options_cached()
    return jsonify({'tags': tags[:50], 'total': len(tags)})

@library_bp.route('/get_first_sites')
def get_first_sites():
    _, _, sites = get_filter_options_cached()
    return jsonify({'sites': sites[:20], 'total': len(sites)})

@library_bp.route('/config/get')
def get_config_api():
    """返回前端需要的配置（脱敏：绝不返回 users/密码等敏感信息）"""
    safe_config = {k: v for k, v in nm.CONFIG.items() if k not in SENSITIVE_CONFIG_KEYS}
    return jsonify(safe_config)

@library_bp.route('/config/save_sort', methods=['POST'])
def save_sort_preference():
    try:
        data = request.get_json() or {}
        sort_by = data.get('sort_by', 'title')
        sort_order = data.get('sort_order', 'asc')
        if sort_by not in ('title', 'author', 'site', 'date', 'word_count'):
            sort_by = 'title'
        if sort_order not in ('asc', 'desc'):
            sort_order = 'asc'
        nm.CONFIG['default_sort_by'] = sort_by
        nm.CONFIG['default_sort_order'] = sort_order
        save_json_file(CONFIG_FILE, nm.CONFIG)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@library_bp.route('/api/random_novel')
def api_random_novel():
    """随机推荐一本书（供「每日推荐」选项卡的「换一本」使用）"""
    if not is_authenticated():
        return jsonify({'success': False, 'message': '未登录'}), 401

    exclude = (request.args.get('exclude') or '').strip()
    novel = pick_random_novel(exclude_work_id=exclude or None)
    if not novel:
        return jsonify({'success': False, 'message': '书库为空，请先扫描目录'})

    novel['detail_url'] = url_for('library.novel_detail', file_path=(novel.get('file_path') or '').lstrip('/'))
    novel['read_url'] = url_for('read_chapter',
                                file_path=(novel.get('file_path') or '').lstrip('/'), line_number=1)
    return jsonify({'success': True, 'novel': novel})

@library_bp.route('/config')
def config_page():
    return render_template('config.html', config=nm.CONFIG)

@library_bp.route('/tag_manager')
def tag_manager():
    return render_template('tag_manager.html')


@library_bp.route('/api/tag/stats')
def api_tag_stats():
    tag_count = {}
    for novel in nm.novel_data:
        if novel.get('tags') and novel['tags'] != '无':
            for tag in novel['tags'].split(','):
                tag = tag.strip()
                if tag:
                    tag_count[tag] = tag_count.get(tag, 0) + 1

    custom_tags = nm.CONFIG.get('custom_tags', [])
    return jsonify({
        'total_tags': len(tag_count),
        'used_tags': len([t for t in tag_count if tag_count[t] > 0]),
        'custom_tags': len(custom_tags),
        'derived_rules': len(nm.TAG_IMPLICATIONS)
    })

@library_bp.route('/api/tag/list')
def api_tag_list():
    tag_count = {}
    for novel in nm.novel_data:
        if novel.get('tags') and novel['tags'] != '无':
            for tag in novel['tags'].split(','):
                tag = tag.strip()
                if tag:
                    tag_count[tag] = tag_count.get(tag, 0) + 1

    tags = [{'name': k, 'count': v} for k, v in sorted(tag_count.items(), key=lambda x: -x[1])]
    return jsonify(tags)

@library_bp.route('/api/tag/derived-rules')
def api_tag_derived_rules():
    rules = []
    for source, derived_list in nm.TAG_IMPLICATIONS.items():
        for derived in derived_list:
            rules.append({'source': source, 'derived': derived})
    return jsonify(rules)

@library_bp.route('/api/tag/add', methods=['POST'])
def api_tag_add():
    data = request.get_json()
    tag = data.get('tag', '').strip()

    if not tag:
        return jsonify({'success': False, 'message': '标签名称不能为空'})

    if len(tag) > 20:
        return jsonify({'success': False, 'message': '标签名称不能超过20个字符'})

    custom_tags = nm.CONFIG.get('custom_tags', [])
    if tag not in custom_tags:
        custom_tags.append(tag)
        nm.CONFIG['custom_tags'] = custom_tags
        save_json_file(CONFIG_FILE, nm.CONFIG)

    return jsonify({'success': True})

@library_bp.route('/api/tag/edit', methods=['POST'])
def api_tag_edit():
    data = request.get_json()
    old_name = data.get('old_name', '').strip()
    new_name = data.get('new_name', '').strip()

    if not old_name or not new_name:
        return jsonify({'success': False, 'message': '标签名称不能为空'})

    count = 0
    for novel in nm.novel_data:
        if novel.get('tags') and novel['tags'] != '无':
            tags = novel['tags'].split(',')
            if old_name in tags:
                tags = [new_name if t == old_name else t for t in tags]
                novel['tags'] = ','.join(tags)
                count += 1

    custom_tags = nm.CONFIG.get('custom_tags', [])
    if old_name in custom_tags:
        custom_tags.remove(old_name)
        if new_name not in custom_tags:
            custom_tags.append(new_name)
        nm.CONFIG['custom_tags'] = custom_tags

    save_cache()
    save_json_file(CONFIG_FILE, nm.CONFIG)
    invalidate_filter_cache()

    return jsonify({'success': True, 'count': count})

@library_bp.route('/api/tag/delete', methods=['POST'])
def api_tag_delete():
    data = request.get_json()
    tag = data.get('tag', '').strip()

    if not tag:
        return jsonify({'success': False, 'message': '标签名称不能为空'})

    count = 0
    for novel in nm.novel_data:
        if novel.get('tags') and novel['tags'] != '无':
            tags = [t for t in novel['tags'].split(',') if t != tag]
            if len(tags) != len(novel['tags'].split(',')):
                novel['tags'] = ','.join(tags) if tags else '无'
                count += 1

    custom_tags = nm.CONFIG.get('custom_tags', [])
    if tag in custom_tags:
        custom_tags.remove(tag)
        nm.CONFIG['custom_tags'] = custom_tags

    save_cache()
    save_json_file(CONFIG_FILE, nm.CONFIG)
    invalidate_filter_cache()

    return jsonify({'success': True, 'count': count})

@library_bp.route('/api/tag/add-derived-rule', methods=['POST'])
def api_tag_add_derived_rule():
    data = request.get_json()
    source = data.get('source', '').strip()
    derived = data.get('derived', '').strip()

    if not source or not derived:
        return jsonify({'success': False, 'message': '请填写源标签和派生标签'})

    if source == derived:
        return jsonify({'success': False, 'message': '源标签和派生标签不能相同'})

    if source not in nm.TAG_IMPLICATIONS:
        nm.TAG_IMPLICATIONS[source] = []

    if derived not in nm.TAG_IMPLICATIONS[source]:
        nm.TAG_IMPLICATIONS[source].append(derived)

    # 统一写入 tag_rules.json（config.json 里的 tag_implications 不再使用，重启会丢）
    save_tag_rules_file()

    return jsonify({'success': True})

@library_bp.route('/api/tag/delete-derived-rule', methods=['POST'])
def api_tag_delete_derived_rule():
    data = request.get_json(silent=True) or {}
    index = data.get('index')

    if not isinstance(index, int) or isinstance(index, bool):
        return jsonify({'success': False, 'message': '索引无效'})

    rules = []
    for source, derived_list in nm.TAG_IMPLICATIONS.items():
        for derived in derived_list:
            rules.append({'source': source, 'derived': derived})

    if 0 <= index < len(rules):
        rule = rules[index]
        source = rule['source']
        derived = rule['derived']

        if source in nm.TAG_IMPLICATIONS:
            if derived in nm.TAG_IMPLICATIONS[source]:
                nm.TAG_IMPLICATIONS[source].remove(derived)
                if not nm.TAG_IMPLICATIONS[source]:
                    del nm.TAG_IMPLICATIONS[source]

        save_tag_rules_file()
        return jsonify({'success': True})

    return jsonify({'success': False, 'message': '规则不存在'})

@library_bp.route('/api/tag/export')
def api_tag_export():
    return jsonify({
        'custom_tags': nm.CONFIG.get('custom_tags', []),
        'tag_implications': nm.TAG_IMPLICATIONS
    })

@library_bp.route('/api/tag/import', methods=['POST'])
def api_tag_import():
    data = request.get_json(silent=True) or {}

    if 'custom_tags' in data and isinstance(data['custom_tags'], list):
        nm.CONFIG['custom_tags'] = data['custom_tags']

    if 'tag_implications' in data and isinstance(data['tag_implications'], dict):
        # 原本是 global TAG_IMPLICATIONS，改用 nm.X 赋值后不再需要
        nm.TAG_IMPLICATIONS = data['tag_implications']

    save_json_file(CONFIG_FILE, nm.CONFIG)
    save_tag_rules_file()
    invalidate_filter_cache()
    return jsonify({'success': True})

@library_bp.route('/api/tag/reset', methods=['POST'])
def api_tag_reset():
    # 原本是 global TAG_IMPLICATIONS，改用 nm.X 赋值后不再需要

    default_implications = {
        '绿帽': ['NTR', '绿系'],
        'NTR': ['绿系'],
    }
    nm.TAG_IMPLICATIONS = default_implications

    nm.CONFIG['custom_tags'] = []

    save_json_file(CONFIG_FILE, nm.CONFIG)
    save_tag_rules_file()
    invalidate_filter_cache()
    return jsonify({'success': True})

@library_bp.route('/api/tag/reapply', methods=['POST'])
def api_tag_reapply():
    count = 0
    for novel in nm.novel_data:
        file_path = novel.get('file_path')
        if file_path and os.path.exists(file_path):
            try:
                new_info = parse_file_content_fast(file_path)
            except Exception as e:
                logger.error(f"重新应用标签失败 {os.path.basename(file_path)}: {e}")
                continue
            if new_info.get('tags') != novel.get('tags'):
                novel['tags'] = new_info.get('tags', '无')
                count += 1

    save_cache()
    invalidate_filter_cache()
    return jsonify({'success': True, 'count': count})

@library_bp.route('/api/tag/rules/save', methods=['POST'])
def save_tag_rules():
    data = request.get_json(silent=True) or {}
    content = data.get('content', '')

    try:
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            return jsonify({'success': False, 'message': '规则必须是 JSON 对象'})
        save_json_file(TAG_RULES_FILE, parsed)
        return jsonify({'success': True})
    except json.JSONDecodeError as e:
        return jsonify({'success': False, 'message': f'JSON 格式错误: {e}'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@library_bp.route('/api/tag/rules/reload', methods=['POST'])
def reload_tag_rules():
    # 原本是 global TAG_IMPLICATIONS, TAG_ALIASES, TAG_KEYWORDS，改用 nm.X 赋值后不再需要

    try:
        # 复用 load_tag_rules()：字段缺失时自动回落默认值
        rules = load_tag_rules()
        nm.TAG_IMPLICATIONS = rules.get('implications', {})
        nm.TAG_ALIASES = rules.get('aliases', {})
        nm.TAG_KEYWORDS = normalize_tag_keywords(rules.get('keywords', []))
        tag_parse_cache.clear()
        invalidate_filter_cache()
        print("✅ 标签规则已重载，已清空缓存")
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@library_bp.route('/api/tag/rules/get')
def get_tag_rules():
    return jsonify({
        'keywords': nm.TAG_KEYWORDS,
        'aliases': nm.TAG_ALIASES,
        'implications': nm.TAG_IMPLICATIONS
    })

@library_bp.route('/api/tag/keyword/add', methods=['POST'])
def add_keyword():
    data = request.get_json(silent=True) or {}
    keyword = (data.get('keyword') or '').strip()

    if not keyword:
        return jsonify({'success': False, 'message': '关键词不能为空'})

    if keyword in nm.TAG_KEYWORDS:
        return jsonify({'success': False, 'message': '关键词已存在'})

    nm.TAG_KEYWORDS.append(keyword)
    save_tag_rules_file()
    return jsonify({'success': True})

@library_bp.route('/api/tag/keyword/delete', methods=['POST'])
def delete_keyword():
    data = request.get_json(silent=True) or {}
    index = data.get('index')

    if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(nm.TAG_KEYWORDS):
        nm.TAG_KEYWORDS.pop(index)
        save_tag_rules_file()
        return jsonify({'success': True})

    return jsonify({'success': False, 'message': '索引无效'})

@library_bp.route('/api/tag/keyword/edit', methods=['POST'])
def edit_keyword():
    data = request.get_json(silent=True) or {}
    index = data.get('index')
    keyword = (data.get('keyword') or '').strip()

    if not keyword:
        return jsonify({'success': False, 'message': '关键词不能为空'})

    if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(nm.TAG_KEYWORDS):
        nm.TAG_KEYWORDS[index] = keyword
        save_tag_rules_file()
        return jsonify({'success': True})

    return jsonify({'success': False, 'message': '索引无效'})

@library_bp.route('/api/tag/alias/add', methods=['POST'])
def add_alias():
    data = request.get_json(silent=True) or {}
    main = (data.get('main') or '').strip()
    aliases = data.get('aliases', [])

    if not main:
        return jsonify({'success': False, 'message': '主标签不能为空'})
    if not isinstance(aliases, list):
        return jsonify({'success': False, 'message': '别名格式错误'})

    nm.TAG_ALIASES[main] = [a.strip() for a in aliases if isinstance(a, str) and a.strip()]
    save_tag_rules_file()
    return jsonify({'success': True})

@library_bp.route('/api/tag/alias/edit', methods=['POST'])
def edit_alias():
    data = request.get_json(silent=True) or {}
    old_main = (data.get('old_main') or '').strip()
    new_main = (data.get('new_main') or '').strip()
    aliases = data.get('aliases', [])

    if not old_main or not new_main:
        return jsonify({'success': False, 'message': '标签名称不能为空'})
    if not isinstance(aliases, list):
        return jsonify({'success': False, 'message': '别名格式错误'})

    if old_main in nm.TAG_ALIASES:
        del nm.TAG_ALIASES[old_main]

    nm.TAG_ALIASES[new_main] = [a.strip() for a in aliases if isinstance(a, str) and a.strip()]

    save_tag_rules_file()
    return jsonify({'success': True})

@library_bp.route('/api/tag/alias/delete', methods=['POST'])
def delete_alias():
    data = request.get_json(silent=True) or {}
    main = (data.get('main') or '').strip()

    if main in nm.TAG_ALIASES:
        del nm.TAG_ALIASES[main]
        save_tag_rules_file()
        return jsonify({'success': True})

    return jsonify({'success': False, 'message': '别名不存在'})

@library_bp.route('/api/tag/alias/update', methods=['POST'])
def update_alias():
    data = request.get_json(silent=True) or {}
    main_tag = (data.get('main_tag') or '').strip()
    aliases_str = (data.get('aliases') or '').strip()
    if not isinstance(aliases_str, str):
        aliases_str = ''

    if not main_tag:
        return jsonify({'success': False, 'message': '主标签不能为空'})

    if not aliases_str:
        return jsonify({'success': False, 'message': '别名不能为空'})

    aliases_list = re.split(r'[ ,，]+', aliases_str)
    aliases_list = [a.strip() for a in aliases_list if a.strip()]

    if not aliases_list:
        return jsonify({'success': False, 'message': '别名不能为空'})

    nm.TAG_ALIASES[main_tag] = aliases_list
    save_tag_rules_file()
    return jsonify({'success': True})

@library_bp.route('/api/tag/rule/add', methods=['POST'])
def add_derived_rule():
    data = request.get_json()
    source = data.get('source', '').strip()
    derived_list = data.get('derived', [])

    if not source:
        return jsonify({'success': False, 'message': '源标签不能为空'})

    derived_list = [d.strip() for d in derived_list if d.strip()]

    if source not in nm.TAG_IMPLICATIONS:
        nm.TAG_IMPLICATIONS[source] = []

    for derived in derived_list:
        if derived not in nm.TAG_IMPLICATIONS[source]:
            nm.TAG_IMPLICATIONS[source].append(derived)

    save_tag_rules_file()
    return jsonify({'success': True})

@library_bp.route('/api/tag/rule/delete', methods=['POST'])
def delete_derived_rule():
    data = request.get_json(silent=True) or {}

    source = (data.get('source') or '').strip()
    derived = (data.get('derived') or '').strip()

    if source and derived:
        if source in nm.TAG_IMPLICATIONS and derived in nm.TAG_IMPLICATIONS[source]:
            nm.TAG_IMPLICATIONS[source].remove(derived)
            if not nm.TAG_IMPLICATIONS[source]:
                del nm.TAG_IMPLICATIONS[source]
            save_tag_rules_file()
            return jsonify({'success': True})
        return jsonify({'success': False, 'message': '规则不存在'})

    index = data.get('index')
    if not isinstance(index, int) or isinstance(index, bool):
        return jsonify({'success': False, 'message': '参数不完整'})

    rules = []
    for src, derived_list in nm.TAG_IMPLICATIONS.items():
        for d in derived_list:
            rules.append({'source': src, 'derived': d})

    if 0 <= index < len(rules):
        rule = rules[index]
        src = rule['source']
        d = rule['derived']

        if src in nm.TAG_IMPLICATIONS and d in nm.TAG_IMPLICATIONS[src]:
            nm.TAG_IMPLICATIONS[src].remove(d)
            if not nm.TAG_IMPLICATIONS[src]:
                del nm.TAG_IMPLICATIONS[src]

        save_tag_rules_file()
        return jsonify({'success': True})

    return jsonify({'success': False, 'message': '规则不存在'})

@library_bp.route('/api/tag/rules/preview')
def preview_tag_rules():
    return jsonify({
        'keywords': nm.TAG_KEYWORDS[:20],
        'keyword_total': len(nm.TAG_KEYWORDS),
        'aliases': nm.TAG_ALIASES,
        'implications': nm.TAG_IMPLICATIONS
    })

@library_bp.route('/api/tag/rules/import', methods=['POST'])
def import_tag_rules():
    # 原本是 global TAG_KEYWORDS, TAG_ALIASES, TAG_IMPLICATIONS，改用 nm.X 赋值后不再需要

    try:
        rules = request.get_json(silent=True) or {}

        if 'keywords' in rules:
            nm.TAG_KEYWORDS = normalize_tag_keywords(rules['keywords'])
        if 'aliases' in rules and isinstance(rules['aliases'], dict):
            nm.TAG_ALIASES = rules['aliases']
        if 'implications' in rules and isinstance(rules['implications'], dict):
            nm.TAG_IMPLICATIONS = rules['implications']

        save_tag_rules_file()
        tag_parse_cache.clear()
        invalidate_filter_cache()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@library_bp.route('/', methods=['GET', 'POST'])
def index():
    user_key, user_info = get_current_user_info()
    # 列表显示相关（排序 / 分页 / 日期格式）自 2026-10-19 起支持个人覆盖，
    # 统一走 resolve_reader_prefs：CONFIG 里的是「新用户默认值」，用户设过的覆盖它
    user_prefs = resolve_reader_prefs(user_info)
    date_format = user_prefs.get('date_format', 'YYYY-MM-DD')

    current_user_display = '用户'
    current_user_role = 'user'
    current_user_avatar = {'icon': 'user', 'color': '#8a94a6'}
    if user_info:
        current_user_display = user_info.get('user_id', '用户')
        current_user_role = user_info.get('role', 'user')
        if user_key:
            avatar_icon, avatar_color = avatar_look(ensure_avatar_seed(user_key))
            current_user_avatar = {'icon': avatar_icon, 'color': avatar_color}

    records = load_reading_records()
    recent_records = build_recent_records(records)

    authors, tags, sites = get_filter_options_cached()

    search_author = request.args.get('author', '').strip()
    search_tag = request.args.get('tag', '').strip()
    search_site = request.args.get('site', '').strip()
    search_text = request.args.get('search', '').strip()

    # 名号归属表：把马甲和主名视为同一个人（用于筛选与下拉分组）
    _author_identity_map = build_author_identity_map()

    filtered_data = nm.novel_data.copy()

    if search_text:
        needle = search_text.lower()

        def _match(n):
            return (needle in (n.get('title') or '').lower() or
                    needle in (n.get('author') or '').lower() or
                    needle in (n.get('tags') or '').lower() or
                    needle in (n.get('site') or '').lower())

        filtered_data = [n for n in filtered_data if _match(n)]

    if search_author:
        # 主名和马甲视为同一个人：选了「财狼少年」也列出「金鳞庸人」名下的全部书。
        # 兼容旧链接（整串匹配）。
        identity = _author_identity_map.get(search_author)

        def _author_match(n):
            raw = n.get('author') or '未知作者'
            if raw == search_author:
                return True
            if identity is None:
                return False
            return bool(identity & set(author_names_of(raw)))

        filtered_data = [n for n in filtered_data if _author_match(n)]

    if search_tag:
        # 精确匹配单个标签，避免「绿」命中「绿帽/绿系」
        filtered_data = [n for n in filtered_data
                         if search_tag in [t.strip() for t in (n.get('tags') or '').split(',') if t.strip()]]

    if search_site:
        filtered_data = [n for n in filtered_data if (n.get('site') or '未知网站') == search_site]

    sort_by = request.args.get('sort')
    sort_order = request.args.get('order')

    if not sort_by:
        sort_by = user_prefs.get('default_sort_by', 'title')
    if not sort_order:
        sort_order = user_prefs.get('default_sort_order', 'asc')

    def get_sort_key(novel):
        if sort_by == 'author':
            key = novel.get('author', '未知作者')
        elif sort_by == 'site':
            key = novel.get('site', '未知网站')
        elif sort_by == 'date':
            publish_date = novel.get('publish_date', '')
            if publish_date and publish_date != '未知':
                key = publish_date
            else:
                key = novel.get('filename', '')
        elif sort_by == 'word_count':
            key = novel.get('word_count', 0)
        else:
            key = novel.get('title', '')

        if key is None:
            key = ''

        if sort_by == 'word_count':
            return key

        if isinstance(key, str):
            return key.lower()
        return key

    reverse_order = (sort_order == 'desc')
    filtered_data.sort(key=get_sort_key, reverse=reverse_order)

    # page_arg 为 None 表示「没显式翻页」，这时才去用记忆里的页码
    page_arg = request.args.get('page', type=int)
    per_page = user_prefs.get('per_page', nm.PER_PAGE)
    try:
        per_page = int(per_page)
    except (TypeError, ValueError):
        per_page = nm.PER_PAGE
    if per_page <= 0:
        per_page = nm.PER_PAGE

    total = len(filtered_data)
    total_pages = max(1, (total + per_page - 1) // per_page)
    # 筛选/搜索视图不参与页码记忆（用户翻的是筛选结果，不能覆盖书架位置）
    has_filter = bool(search_author or search_tag or search_site or search_text)
    page = resolve_home_page(page_arg, has_filter, user_info, total_pages)

    start = (page - 1) * per_page
    end = start + per_page
    paginated_data = [n.copy() for n in filtered_data[start:end]]

    pagination = {
        'page': page,
        'per_page': per_page,
        'total': total,
        'pages': total_pages
    }

    # 记住这次停留的页码（page=1 会顺手清掉记忆）；只记纯浏览状态
    if not has_filter:
        remember_home_page(user_key, page, total_pages)

    for novel in paginated_data:
        # 🔥 标记文件状态
        fp = novel.get('file_path', '')
        if fp and os.path.exists(fp):
            try:
                cached_mtime = float(novel.get('mtime', 0))
                real_mtime = os.path.getmtime(fp)
                if cached_mtime and abs(cached_mtime - real_mtime) > 1:
                    novel['stale'] = True
            except (OSError, TypeError, ValueError):
                novel['missing'] = True
        else:
            novel['missing'] = True

        if novel.get('publish_date') and novel['publish_date'] != '未知':
            publish_date = novel['publish_date']
            match = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', publish_date)
            if match:
                year, month, day = match.groups()
                month = month.zfill(2)
                day = day.zfill(2)

                if date_format == 'YYYY-MM-DD':
                    novel['publish_date'] = f"{year}-{month}-{day}"
                elif date_format == 'YYYY/MM/DD':
                    novel['publish_date'] = f"{year}/{month}/{day}"
                elif date_format == 'YYYY年MM月DD日':
                    novel['publish_date'] = f"{year}年{month}月{day}日"

    # 书名栏的「已读完 / 阅读中」标记：只查当前页这 100 本，避免全量遍历
    annotate_reading_status(paginated_data, records)

    # 作者列：主名和马甲都是「可点的作者」，各自能筛出这个人的全部书。
    # 用 author_links 承载 [{name, is_alias}]，模板直接渲染成链接，
    # 不再把「金鳞庸人（uwkuk8k,财狼少年）」整串铺在列里。
    for novel in paginated_data:
        raw_author = novel.get('author') or ''
        main_author, aliases = split_author_aliases(raw_author)
        main_author = main_author or raw_author or '未知作者'

        links = [{'name': main_author, 'is_alias': False}]
        links += [{'name': a, 'is_alias': True} for a in aliases]

        novel['author_main'] = main_author
        novel['author_aliases'] = aliases
        novel['author_full'] = raw_author
        novel['author_links'] = links

    # 当前用户阅读偏好（首页字体预热用：挑书阶段后台下载配置的正文字体，
    # 与详情页简介/阅读页正文同一份值，保证三处字体一致）
    user_prefs = resolve_reader_prefs()

    return render_template('index.html',
        novels=paginated_data,
        authors=authors,
        tags=tags,
        sites=sites,
        recent_records=recent_records,
        recent_total=len(recent_records),
        recent_stats=compute_recent_stats(recent_records),
        recent_groups=group_recent_records(recent_records),
        # 每次刷新页面随机推荐一本；「换一本」按钮再走 /api/random_novel
        random_novel=pick_random_novel(),
        total_count=len(nm.novel_data),
        cache_stats=get_cache_overview(),
        scan_stats=load_scan_stats(),
        filtered_count=total,
        pagination=pagination,
        search_author=search_author,
        search_tag=search_tag,
        search_site=search_site,
        search_text=search_text,
        novel_dir=nm.NOVEL_DIR,
        sort_by=sort_by,
        sort_order=sort_order,
        current_user_display=current_user_display,
        current_user_role=current_user_role,
        current_user_avatar=current_user_avatar,
        user_prefs=user_prefs
    )

@library_bp.route('/novel_detail/<path:file_path>')
def novel_detail(file_path):
    # 安全解析：只允许小说目录内的 .txt，禁止绝对路径/../ 穿越
    resolved = resolve_novel_path(file_path)
    if not resolved:
        logger.warning(f"详情页：非法路径 {file_path}")
        return render_missing_page(str(file_path), 'deleted')
    file_path = resolved

    # ===== 🔥 文件有效性校验 =====
    if not os.path.exists(file_path):
        logger.warning(f"详情页：文件不存在 {file_path}")
        return render_missing_page(file_path, 'deleted')

    if not os.path.isfile(file_path):
        logger.warning(f"详情页：路径不是文件 {file_path}")
        return render_missing_page(file_path, 'deleted')

    if not is_file_readable(file_path):
        logger.warning(f"详情页：文件不可读 {file_path}")
        return render_missing_page(file_path, 'error')

    # 对比 mtime，判断缓存是否过期
    cached_novel = next(
        (n for n in nm.novel_data
         if os.path.basename(n.get('file_path', '')) == os.path.basename(file_path)),
        None
    )
    if cached_novel:
        try:
            cached_mtime = float(cached_novel.get('mtime', 0))
            current_mtime = os.path.getmtime(file_path)
            if cached_mtime and abs(cached_mtime - current_mtime) > 1:
                logger.warning(
                    f"详情页：文件已更新但缓存未同步 {os.path.basename(file_path)} "
                    f"(缓存mtime={cached_mtime}, 实际mtime={current_mtime})"
                )
                return render_missing_page(file_path, 'modified')
        except (OSError, TypeError, ValueError):
            return render_missing_page(file_path, 'error')

    if os.path.exists(file_path):
        current_hash = get_file_hash(file_path)

        # 清除可能损坏的缓存
        if file_path in chapter_cache:
            cached_info = chapter_cache[file_path]
            cached_intro = cached_info.get('intro', '') if isinstance(cached_info, dict) else ''
            # 如果缓存中的 intro 包含元数据关键词，清除缓存
            if cached_intro and any(kw in cached_intro for kw in ['书名：', '作者：', '标签：', '链接：']):
                print("🗑️ 清除损坏的缓存（intro 包含元数据）")
                del chapter_cache[file_path]
            elif cached_intro and len(cached_intro) < 5:
                print("🗑️ 清除损坏的缓存（intro 太短）")
                del chapter_cache[file_path]
            else:
                cached_hash = cached_info.get('file_hash', '') if isinstance(cached_info, dict) else ''
                if cached_hash != current_hash:
                    print("🗑️ 清除过期章节缓存")
                    del chapter_cache[file_path]

        if file_path in tag_parse_cache:
            cached_hash, cached_info = tag_parse_cache[file_path]
            cached_intro = cached_info.get('intro', '') if isinstance(cached_info, dict) else ''
            if cached_intro and any(kw in cached_intro for kw in ['书名：', '作者：', '标签：', '链接：']):
                print("🗑️ 清除损坏的 tag 缓存（intro 包含元数据）")
                del tag_parse_cache[file_path]
            elif cached_hash != current_hash:
                print("🗑️ 清除过期 tag 缓存")
                del tag_parse_cache[file_path]

    print(f"📂 修正后路径：{file_path}")

    detail_info = parse_novel_details(file_path)
    base_info = parse_file_content_fast(file_path)

    # 确保 intro 一致且正确
    final_intro = '无简介'
    
    # 优先使用 detail_info 中的 intro
    if detail_info.get('intro') and detail_info['intro'] != '无简介':
        detail_intro = detail_info['intro']
        # 验证是否有效
        if not any(kw in detail_intro for kw in ['书名：', '作者：', '标签：', '链接：']):
            final_intro = detail_intro
    
    # 如果 detail_info 无效，使用 base_info
    if final_intro == '无简介' and base_info.get('intro') and base_info['intro'] != '无简介':
        base_intro = base_info['intro']
        if not any(kw in base_intro for kw in ['书名：', '作者：', '标签：', '链接：']):
            final_intro = base_intro
    
    # 如果都无效，重新直接从文件提取
    if final_intro == '无简介':
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(5000)
            lines = content.splitlines()
            final_intro = extract_intro_clean(lines)
            if final_intro and final_intro != '无简介':
                # 更新缓存
                if file_path in chapter_cache:
                    chapter_cache[file_path]['intro'] = final_intro
                if file_path in tag_parse_cache:
                    _, cached_result = tag_parse_cache[file_path]
                    cached_result['intro'] = final_intro
        except Exception as e:
            logger.error(f"重新提取简介失败: {e}")

    # 更新 base_info 和 detail_info
    base_info['intro'] = final_intro
    detail_info['intro'] = final_intro

    # ===== 计算预览 =====
    final_preview = None
    if final_intro == '无简介':
        # 优先用 detail_info 里已有的 preview
        if detail_info.get('preview'):
            final_preview = detail_info['preview']
        elif base_info.get('preview'):
            final_preview = base_info['preview']
        else:
            # 兜底：直接从文件重新提取
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read(50000)
                lines = content.splitlines()
                final_preview = extract_preview_clean(lines)
            except Exception as e:
                logger.error(f"提取预览失败: {e}")

    link = base_info.get('link', '')
    if link and not link.startswith(('http://', 'https://')):
        link = 'https://' + link
        print(f"🔗 链接已修复: {link}")

    # 日期格式支持个人覆盖（全局默认 + 用户设置）
    date_format = resolve_reader_prefs().get('date_format', 'YYYY-MM-DD')
    publish_date = base_info.get('publish_date', '未知')

    if publish_date != '未知':
        match = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', publish_date)
        if match:
            year, month, day = match.groups()
            month = month.zfill(2)
            day = day.zfill(2)
            if date_format == 'YYYY-MM-DD':
                publish_date = f"{year}-{month}-{day}"
            elif date_format == 'YYYY/MM/DD':
                publish_date = f"{year}/{month}/{day}"
            elif date_format == 'YYYY年MM月DD日':
                publish_date = f"{year}年{month}月{day}日"

    back_page = request.args.get('page', 1, type=int)
    search_text = request.args.get('search', '')
    search_author = request.args.get('author', '')
    search_tag = request.args.get('tag', '')
    search_site = request.args.get('site', '')

    # 查询当前用户在这本书上的阅读记录（用于「继续阅读」/「已读」按钮）
    continue_line = None
    continue_chapter = ''
    is_finished = False
    has_record = False
    detail_work_id = ''
    if is_authenticated():
        detail_work_id, record = resolve_record_by_path(file_path)
        if record:
            has_record = True
            continue_line = record.get('line_number') or 1
            continue_chapter = record.get('chapter_text', '') or ''
            is_finished = bool(record.get('finished'))
        if not detail_work_id:
            # 还没读过这本书：用扫描缓存里的 work_id
            detail_work_id = get_work_id_from_cache(file_path) or ''
        if not detail_work_id:
            # 扫描缓存里也没有（例如还没扫过）：用内容指纹现算一个，
            # 保证「标记已读」按钮在任何情况下都能用
            detail_work_id = compute_work_id(file_path) or ''

    # 作者：和首页列表一致，主名和马甲各自做成可点链接（各自筛出这个人的全部书）
    detail_raw_author = base_info['author'] or ''
    detail_main_author, detail_aliases = split_author_aliases(detail_raw_author)
    detail_main_author = detail_main_author or detail_raw_author or '未知作者'
    detail_author_links = [{'name': detail_main_author, 'is_alias': False}]
    detail_author_links += [{'name': a, 'is_alias': True} for a in detail_aliases]

    # 读取当前用户阅读偏好（简介/预览跟随配置的正文字体，与阅读页一致）
    user_prefs = resolve_reader_prefs()

    # 相似书籍：扩展阅读用，无结果时模板整块不渲染，不影响详情页其它内容
    similar_novels = build_similar_urls(
        find_similar_novels(
            base_info['title'], base_info['author'], base_info['tags'],
            exclude_work_id=detail_work_id, exclude_path=file_path
        ),
        page=back_page, search=search_text, author=search_author,
        tag=search_tag, site=search_site
    )

    return render_template('novel_detail.html',
        title=base_info['title'],
        author=base_info['author'],
        author_main=detail_main_author,
        author_links=detail_author_links,
        site=base_info['site'],
        word_count=base_info['word_count'],
        publish_date=publish_date,
        file_path=urllib.parse.quote(file_path.lstrip('/')),
        link=link,
        intro=final_intro,
        preview=final_preview,
        all_chapters=detail_info['all_chapters'],
        chapters_level1=detail_info['chapters_level1'],
        chapters_level2=detail_info['chapters_level2'],
        chapters_level3=detail_info['chapters_level3'],
        tags=base_info['tags'],
        back_page=back_page,
        search_text=search_text,
        search_author=search_author,
        search_tag=search_tag,
        search_site=search_site,
        continue_line=continue_line,
        continue_chapter=continue_chapter,
        is_finished=is_finished,
        has_record=has_record,
        detail_work_id=detail_work_id,
        user_prefs=user_prefs,
        similar_novels=similar_novels
    )

@library_bp.route('/config/save', methods=['POST'])
def save_config_api():
    # 原本是 global CONFIG，改用 nm.X 赋值后不再需要

    # 纵深防御：before_request 已经把 /config/save 列为管理员专属，
    # 这里再独立校验一次，避免以后有人误改 ADMIN_EXACT_PATHS 而失去保护。
    # （用户的个人阅读偏好走 /api/save_preferences，不受此限制）
    if not is_admin():
        return jsonify({'success': False, 'message': '权限不足，仅管理员可修改全局配置'}), 403

    try:
        new_config = request.get_json(silent=True) or {}
        if not isinstance(new_config, dict):
            return jsonify({'success': False, 'message': '数据格式错误'})

        current_config = load_json_file(CONFIG_FILE, {}) or {}
        if not isinstance(current_config.get('users'), dict):
            current_config['users'] = {}

        ignored_keys = []
        for key, value in new_config.items():
            if key == 'password':
                # 修改当前登录用户的密码（只存哈希，用户 key 不变）
                new_password = (value or '').strip() if isinstance(value, str) else ''
                if not new_password:
                    continue
                if len(new_password) < 4:
                    return jsonify({'success': False, 'message': '密码长度至少4位'})
                user_key, user_info = get_current_user_info()
                if not user_key or not user_info:
                    return jsonify({'success': False, 'message': '登录状态已失效，请重新登录'}), 401
                if password_used_by_others(new_password, exclude_key=user_key):
                    return jsonify({'success': False, 'message': '该密码已被其它用户使用，请更换'})
                user_info['password_hash'] = hash_password(new_password)
                current_config['users'][user_key] = user_info
                session['user_name'] = f"{user_info.get('user_id', '用户')}（{'管理员' if user_info.get('role') == 'admin' else '普通用户'}）"
                continue

            if key not in CONFIG_SAVE_WHITELIST:
                ignored_keys.append(key)
                continue

            if key == 'novel_dir':
                novel_dir = str(value or '').strip()
                if not novel_dir or not os.path.isdir(novel_dir):
                    return jsonify({'success': False, 'message': f'小说目录不存在：{novel_dir}'})
                current_config[key] = novel_dir
                continue

            if key in ('per_page', 'words_per_page', 'max_tags_display', 'max_file_size_mb'):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    return jsonify({'success': False, 'message': f'配置 {key} 必须是整数'})
                if value <= 0:
                    return jsonify({'success': False, 'message': f'配置 {key} 必须大于 0'})

            if key == 'scan_interval_hours':
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    return jsonify({'success': False, 'message': '扫描间隔必须是数字'})

            current_config[key] = value

        save_json_file(CONFIG_FILE, current_config)
        nm.CONFIG = current_config
        apply_runtime_config()

        if ignored_keys:
            logger.warning(f"⚠️ 已忽略不允许修改的配置项: {ignored_keys}")
        print("✅ 配置已保存")
        return jsonify({'success': True, 'ignored': ignored_keys})

    except Exception as e:
        logger.error(f"❌ 保存配置失败: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)})

@library_bp.route('/config/reload', methods=['POST'])
def reload_config_api():
    # 原本是 global CONFIG，改用 nm.X 赋值后不再需要

    # 纵深防御，同 /config/save
    if not is_admin():
        return jsonify({'success': False, 'message': '权限不足，仅管理员可重载全局配置'}), 403

    try:
        nm.CONFIG = load_config()
        apply_runtime_config()
        print("✅ 配置已重载")
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})
