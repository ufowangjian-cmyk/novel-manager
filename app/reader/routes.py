# -*- coding: utf-8 -*-
"""reader 蓝图：阅读页、阅读进度、书内搜索、阅读记录清理。

划分见 `docs/blueprint-roadmap.md`（reader = 10 条路由）。

注意：`read_chapter` 是模板里被引用最多的端点（10 处 `url_for`），改端点名时
代码与模板必须同批改，否则运行时 BuildError。

共享物反向 import 主模块，原因见 `app/auth/routes.py` 顶部。
⚠️ `CONFIG` / `WORDS_PER_PAGE` 走 `nm.*`：这两个会被整体重新赋值
   （`save_config_api` / `apply_runtime_config`）。
"""

import os
import time
import traceback
import urllib.parse

from flask import jsonify, redirect, render_template, request, session, url_for

from . import reader_bp

import novel_manager as nm
from novel_manager import (
    LEVEL1_PATTERN,
    LEVEL2_PATTERN,
    LEVEL3_PATTERN,
    READING_RECORD_DIR,
    _PATH_INDEX_KEY,
    _coerce_records_payload,
    _recent_record_matches,
    _recent_record_to_json,
    _resolve_work_id_for_request,
    build_recent_records,
    build_similar_urls,
    chapter_cache,
    compute_progress_ratio,
    compute_recent_stats,
    compute_work_id,
    current_user_key,
    delete_reading_record_by_work_id,
    file_lock,
    find_similar_novels,
    get_file_hash,
    get_user_record_file,
    get_work_id_from_cache,
    highlight_crossline_brackets,
    is_admin,
    is_authenticated,
    is_file_readable,
    load_json_file,
    load_novel_content,
    load_reading_payload,
    load_reading_records,
    logger,
    normalize_record_path,
    normalize_user_info,
    page_has_content,
    parse_file_content_fast,
    parse_novel_details,
    parse_novel_details_from_content,
    render_missing_page,
    resolve_novel_path,
    resolve_reader_prefs,
    resolve_record_by_path,
    save_json_file,
    save_reading_record,
    set_reading_record_finished,
    tag_parse_cache,
)


@reader_bp.route('/read/<path:file_path>/<int:line_number>')
def read_chapter(file_path, line_number):
    # 每页字数支持个人覆盖（原先是模块级全局 WORDS_PER_PAGE，改不了个人习惯）
    try:
        per_page_words = int(resolve_reader_prefs().get('words_per_page', nm.WORDS_PER_PAGE))
    except (TypeError, ValueError):
        per_page_words = nm.WORDS_PER_PAGE
    if per_page_words <= 0:
        per_page_words = nm.WORDS_PER_PAGE
    resolved = resolve_novel_path(file_path)
    if not resolved:
        logger.warning(f"阅读页：非法路径 {file_path}")
        return render_missing_page(str(file_path), 'deleted')
    file_path = resolved

    back_page = request.args.get('list_page', 1, type=int)
    search_text = request.args.get('search', '')
    search_author = request.args.get('author', '')
    search_tag = request.args.get('tag', '')
    search_site = request.args.get('site', '')

    # ===== 🔥 文件有效性校验 =====
    if not os.path.exists(file_path) or not os.path.isfile(file_path):
        logger.warning(f"阅读页：文件不存在 {file_path}")
        return render_missing_page(file_path, 'deleted')

    file_size = os.path.getsize(file_path)
    max_file_size_mb = nm.CONFIG.get('max_file_size_mb', 100)
    try:
        max_bytes = int(float(max_file_size_mb) * 1024 * 1024)
    except (TypeError, ValueError):
        max_bytes = 100 * 1024 * 1024
    if max_bytes > 0 and file_size > max_bytes:
        return f"文件过大（{file_size / 1024 / 1024:.1f} MB，上限 {max_file_size_mb} MB），无法在线阅读", 413

    if not is_file_readable(file_path):
        logger.warning(f"阅读页：文件不可读 {file_path}")
        return render_missing_page(file_path, 'error')

    try:
        page = request.args.get('page', 1, type=int)

        current_file_hash = get_file_hash(file_path)

        # 已经在读的这条记录对应的 work_id（下面解析到就复用，保证写回同一条）
        _old_work_id = None
        cache_cleared = False
        if file_path in chapter_cache:
            cached_info = chapter_cache[file_path]
            if isinstance(cached_info, dict):
                cached_hash = cached_info.get('file_hash', '')
            else:
                cached_hash = ''
            if cached_hash != current_file_hash:
                print(f"🔄 检测到文件被修改，清除章节缓存: {os.path.basename(file_path)}")
                del chapter_cache[file_path]
                cache_cleared = True

        if file_path in tag_parse_cache:
            cached_hash, _ = tag_parse_cache[file_path]
            if cached_hash != current_file_hash:
                del tag_parse_cache[file_path]

        if cache_cleared:
            # 用 work_id 解析旧记录：改文件名也能找回上次读到哪
            _old_work_id, _old_record = resolve_record_by_path(file_path)
            if _old_record:
                old_chapter_text = _old_record.get('chapter_text', '')
                if old_chapter_text:
                    found = False
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        for i, line in enumerate(f):
                            if line.strip() == old_chapter_text.strip():
                                line_number = i + 1
                                found = True
                                print(f"✅ 智能恢复章节: '{old_chapter_text[:30]}...' -> 行{line_number}")
                                break
                            if i > 50000:
                                break
                    if not found:
                        print("⚠️ 未找到原章节，从第1行开始")
                        line_number = 1

        # 没触发缓存清理时，也要先解析出当前文件对应的 work_id（改名后的第一次访问就走这里）
        if _old_work_id is None:
            _old_work_id, _old_record = resolve_record_by_path(file_path)

        content, all_lines, encoding = load_novel_content(file_path)
        total_lines = len(all_lines)

        if file_path in chapter_cache:
            detail_info = chapter_cache[file_path]
            detail_info['encoding'] = encoding
        else:
            detail_info = parse_novel_details_from_content(content, all_lines)
            detail_info['encoding'] = encoding
            detail_info['file_hash'] = current_file_hash
            chapter_cache[file_path] = detail_info

        all_chapters = detail_info['all_chapters']

        is_virtual_chapter = (len(all_chapters) == 1 and
                              all_chapters[0]['text'] == '全文阅读')

        current_chapter = None
        prev_chapter = None
        next_chapter = None
        chapter_index = -1

        if is_virtual_chapter:
            current_chapter = all_chapters[0]
            chapter_index = 0
            line_number = current_chapter['line_number']
            print(f"📖 虚拟章节模式: line_number 修正为 {line_number}")
        else:
            for i, chapter in enumerate(all_chapters):
                if chapter['line_number'] <= line_number:
                    current_chapter = chapter
                    chapter_index = i
                else:
                    break

            # 兜底：line_number 落在第一个章节标题之前（例如「每日推荐」用
            # line_number=1 进入，而文件开头是书名/作者/简介，首章标题在第 5 行）。
            # 这种情况下上面的循环一次都没命中，必须显式回退到第一章——
            # 注意不能在这里 return，因为后面还要据此算 prev/next 章节。
            if current_chapter is None and all_chapters:
                current_chapter = all_chapters[0]
                chapter_index = 0
                print("⚠️ 未找到匹配章节，使用第一个章节")

            if current_chapter:
                # 上一章/下一章跳过空章节（只有标题没有正文），
                # 避免阅读页的 ◀ ▶ 按钮把用户带到空白页。
                # 找不到非空章节时退回相邻章节，保证按钮不会凭空消失。
                #
                # 这段必须在「兜底回退」之后统一执行：之前兜底分支只设了
                # chapter_index=0 却没算 next_chapter，导致单页短首章
                # （next_page 也为 None）被误判成全书读完，▶ 变灰且显示「返回列表」。
                if chapter_index > 0:
                    prev_chapter = next(
                        (c for c in reversed(all_chapters[:chapter_index])
                         if not c.get('is_empty')),
                        all_chapters[chapter_index - 1]
                    )
                if chapter_index < len(all_chapters) - 1:
                    next_chapter = next(
                        (c for c in all_chapters[chapter_index + 1:]
                         if not c.get('is_empty')),
                        all_chapters[chapter_index + 1]
                    )
                line_number = current_chapter['line_number']

        if current_chapter:
            chapter_start = current_chapter['line_number'] - 1
            chapter_end = total_lines
            for chapter in all_chapters:
                if chapter['line_number'] > current_chapter['line_number']:
                    chapter_end = chapter['line_number'] - 1
                    break

            chapter_lines = all_lines[chapter_start:chapter_end]
            processed_lines = [line.lstrip(' \t\u3000') if line.strip() else '' for line in chapter_lines]

            total_words = sum(len(line) for line in chapter_lines)

            if total_words > per_page_words:
                total_pages = (total_words + per_page_words - 1) // per_page_words
                page = max(1, min(page, total_pages))

                page_starts = [0]
                char_count = 0

                for i, line in enumerate(chapter_lines):
                    char_count += len(line)
                    if char_count >= per_page_words * len(page_starts):
                        page_starts.append(i)

                if len(page_starts) < total_pages:
                    page_starts.append(len(chapter_lines))

                start_idx = page_starts[page - 1]
                end_idx = page_starts[page] if page < len(page_starts) else len(chapter_lines)

                if page == 1:
                    start_idx = 0

                current_lines = processed_lines[start_idx:end_idx]
                start_line = chapter_start + start_idx + 1
                end_line = chapter_start + end_idx
                prev_page = page - 1 if page > 1 else None
                next_page = page + 1 if page < total_pages else None
            else:
                current_lines = processed_lines
                start_line = chapter_start + 1
                end_line = chapter_end
                total_pages = 1
                prev_page = None
                next_page = None
        else:
            # 兜底：本书未解析出任何章节（无章节结构的纯文本小说）。
            # 改用字数分页，与上方「按章节字数分页」行为保持一致，
            # 不再写死 300 行，否则配置页的「每页显示字数」对它无效。
            total_words_all = sum(len(line) for line in all_lines)

            if total_words_all > per_page_words:
                total_pages = (total_words_all + per_page_words - 1) // per_page_words
                page = max(1, min(page, total_pages))

                page_starts = [0]
                char_count = 0
                for i, line in enumerate(all_lines):
                    char_count += len(line)
                    if char_count >= per_page_words * len(page_starts):
                        page_starts.append(i)
                if len(page_starts) < total_pages:
                    page_starts.append(len(all_lines))

                start_idx = page_starts[page - 1]
                end_idx = page_starts[page] if page < len(page_starts) else len(all_lines)
                if page == 1:
                    start_idx = 0
            else:
                start_idx = 0
                end_idx = len(all_lines)
                total_pages = 1

            current_lines = [line.lstrip(' \t\u3000') if line.strip() else '' for line in all_lines[start_idx:end_idx]]
            start_line = start_idx + 1
            end_line = end_idx
            prev_page = page - 1 if page > 1 else None
            next_page = page + 1 if page < total_pages else None

        if current_lines:
            full_text = '\n'.join(current_lines)
            processed_text = highlight_crossline_brackets(full_text)
            current_lines = processed_text.split('\n')

        if file_path in tag_parse_cache:
            cached_hash, base_info = tag_parse_cache[file_path]
        else:
            base_info = parse_file_content_fast(file_path)

        # work_id 优先沿用已解析到的记录（保证改名/改内容后仍写回同一条记录），
        # 其次用扫描缓存，最后按当前内容现算。
        work_id = _old_work_id
        if not work_id:
            work_id = get_work_id_from_cache(file_path)
        if not work_id:
            work_id = compute_work_id(file_path)

        if not work_id:
            print("⚠️ 无法计算 work_id，跳过本次阅读记录写入")
            save_success = False
        else:
            chapter_text = '全文阅读' if is_virtual_chapter else (current_chapter['text'] if current_chapter else '正文')
            # 进度语义：line_number 是原始文件行号，不同书切章方式不同，不能直接当进度用。
            # 这里把「第几章 / 共几章」在写入时算好存下来，首页进度条才有可靠依据。
            total_chapters = len(all_chapters) if all_chapters else 0
            progress_ratio = compute_progress_ratio(chapter_index, total_chapters, page, total_pages)

            # 是否已经读到全书最后一页：没有下一章、也没有下一页。
            # 满足时自动标记「已读」，首页进度直接显示 100%（否则最后一页只能算出 ~88%）。
            # 与 read_chapter.html 里「返回列表」按钮的显示条件保持一致。
            reached_the_end = (next_chapter is None and next_page is None)

            # 用户如果手动取消过「已读」，再次翻到最后一页也不强行改回来；
            # 但显式标记过的已读要保留（这里只做「置真」，不主动置假）。
            prev_finished = bool(_old_record.get('finished')) if _old_record else False

            record = {
                'work_id': work_id,
                'title': base_info['title'],
                'author': base_info['author'],
                'line_number': line_number,
                'chapter_text': chapter_text,
                'timestamp': time.time(),
                'file_path': file_path,
                'filename': os.path.basename(file_path),
                'page': page,
                'total_pages': total_pages,
                'is_virtual': is_virtual_chapter,
                'chapter_index': chapter_index if chapter_index >= 0 else None,
                'total_chapters': total_chapters,
                'progress_ratio': progress_ratio,
                'finished': bool(reached_the_end or prev_finished)
            }
            save_success = save_reading_record(record)

    except Exception as e:
        print(f"❌ 读取文件失败：{str(e)}")
        traceback.print_exc()
        return f"读取文件失败：{str(e)}"

    # 读取当前用户偏好（用于跨设备同步字体/字号/排版）
    user_prefs = resolve_reader_prefs()

    # 相似书籍：只在全书最后一页出现（与模板里「返回列表」同条件）
    try:
        at_the_end = (next_chapter is None and next_page is None)
    except NameError:
        at_the_end = False
    similar_novels = []
    if at_the_end:
        similar_novels = build_similar_urls(
            find_similar_novels(
                base_info['title'], base_info['author'], base_info['tags'],
                exclude_path=file_path
            ),
            page=back_page, search=search_text, author=search_author,
            tag=search_tag, site=search_site
        )

    return render_template('read_chapter.html',
        title=base_info['title'],
        author=base_info['author'],
        file_path=urllib.parse.quote(file_path.lstrip('/')),
        content_lines=current_lines,
        start_line=start_line,
        end_line=end_line,
        total_lines=total_lines,
        all_chapters=all_chapters,
        current_chapter=current_chapter,
        prev_chapter=prev_chapter,
        next_chapter=next_chapter,
        page=page,
        total_pages=total_pages,
        prev_page=prev_page,
        next_page=next_page,
        file_size=file_size,
        save_success=save_success,
        user_prefs=user_prefs,
        current_page_words=sum(len(line) for line in current_lines),
        has_content=page_has_content(current_lines),
        back_page=back_page,
        search_text=search_text,
        search_author=search_author,
        search_tag=search_tag,
        search_site=search_site,
        is_virtual_chapter=is_virtual_chapter,
        similar_novels=similar_novels
    )

@reader_bp.route('/continue/<path:file_path>')
def continue_reading(file_path):
    resolved = resolve_novel_path(file_path)
    if not resolved:
        logger.warning(f"继续阅读：非法路径 {file_path}")
        return redirect(url_for('library.index'))
    file_path = resolved

    # 按 work_id 解析阅读记录（改文件名后依然能续读）
    work_id, record = resolve_record_by_path(file_path)

    if record:
        if record.get('is_virtual', False):
            if os.path.exists(file_path):
                detail_info = parse_novel_details(file_path)
                if detail_info['all_chapters']:
                    record['line_number'] = detail_info['all_chapters'][0]['line_number']
                    print(f"🔧 修复虚拟章节起始行: {record['line_number']}")

        # 首页「最近阅读」卡片直接进这里，必须带上记录里的分页，
        # 否则读到第 2/2 页的书会被打回第 1 页。
        target_page = record.get('page', 1) or 1
        kwargs = {}
        if target_page > 1:
            kwargs['page'] = target_page

        url = url_for('reader.read_chapter',
                      file_path=urllib.parse.quote(file_path.lstrip('/')),
                      line_number=record.get('line_number', 1),
                      **kwargs)

        return redirect(url)
    else:
        return redirect(url_for('reader.read_chapter',
                               file_path=urllib.parse.quote(file_path.lstrip('/')),
                               line_number=1))

@reader_bp.route('/clear_records', methods=['POST'])
def clear_records():
    if not is_authenticated():
        return redirect(url_for('auth.login'))

    user_key = current_user_key()
    if not user_key:
        return redirect(url_for('auth.login'))
    record_file = get_user_record_file(user_key)
    try:
        with file_lock(record_file + '.lock'):
            if os.path.exists(record_file):
                os.remove(record_file)
            save_json_file(record_file, {})
        logger.info(f"🗑️ 用户清除了自己的阅读记录: {record_file}")
        return redirect(url_for('library.index'))
    except Exception as e:
        logger.error(f"❌ 清除记录失败：{e}")
        return redirect(url_for('library.index'))

@reader_bp.route('/api/recent_records')
def api_recent_records():
    """最近阅读列表：支持 offset/limit 分页与关键字过滤"""
    if not is_authenticated():
        return jsonify({'success': False, 'message': '未登录'}), 401

    offset = max(0, request.args.get('offset', 0, type=int))
    limit = request.args.get('limit', 12, type=int)
    limit = max(1, min(limit, 100))
    keyword = (request.args.get('q') or '').strip().lower()

    records = build_recent_records(load_reading_records())

    if keyword:
        records = [r for r in records if _recent_record_matches(r, keyword)]

    window = records[offset:offset + limit]
    return jsonify({
        'success': True,
        'total': len(records),
        'offset': offset,
        'limit': limit,
        'has_more': offset + limit < len(records),
        'stats': compute_recent_stats(records),
        'records': [_recent_record_to_json(r) for r in window]
    })

@reader_bp.route('/api/delete_record', methods=['POST'])
def delete_reading_record():
    if not is_authenticated():
        return jsonify({'success': False, 'message': '未登录'}), 401

    data = request.get_json(silent=True) or {}
    work_id = (data.get('work_id') or '').strip()
    file_path = data.get('file_path', '')

    try:
        # 首选 work_id 精确删除；老前端只传 file_path 时按路径解析出 work_id
        if not work_id and file_path:
            resolved = resolve_novel_path(file_path)
            if resolved:
                work_id, _ = resolve_record_by_path(resolved)
            if not work_id:
                # 兜底：直接用归一化路径在索引里找
                payload = load_reading_payload()
                work_id = payload[_PATH_INDEX_KEY].get(normalize_record_path(file_path))

        if not work_id:
            return jsonify({'success': False, 'message': '记录不存在'})

        if delete_reading_record_by_work_id(work_id):
            print(f"✅ 已删除阅读记录: work_id={work_id[:8]}... ({file_path or '-'})")
            # 把删除后的最新状态一并返回，前端就地更新计数/进度/空状态，无需整页刷新
            remaining = build_recent_records(load_reading_records())
            return jsonify({
                'success': True,
                'work_id': work_id,
                'recent_total': len(remaining),
                'stats': compute_recent_stats(remaining),
                'records': [_recent_record_to_json(r) for r in remaining[:12]],
                'has_more': len(remaining) > 12
            })
    except Exception as e:
        logger.error(f"❌ 删除阅读记录失败: {e}")
        return jsonify({'success': False, 'message': str(e)})

    return jsonify({'success': False, 'message': '记录不存在'})

@reader_bp.route('/api/mark_read', methods=['POST'])
def api_mark_read():
    """手动标记「已读」（finished=true）/ 取消已读（finished=false）

    标记已读要求记录已存在（读过至少一次）。若还没有记录，
    前端应先跳转阅读页写入记录，或由本接口返回 needs_read 提示。
    """
    if not is_authenticated():
        return jsonify({'success': False, 'message': '未登录'}), 401

    data = request.get_json(silent=True) or {}
    finished = data.get('finished', True)
    finished = bool(finished)

    work_id = _resolve_work_id_for_request(data)
    if not work_id:
        return jsonify({'success': False, 'message': '找不到这本书，请先扫描一次'})

    # 允许「没读过也直接标记已读」：前端会带上书名/作者/路径，
    # 记录不存在时用这些信息创建一条最小记录。
    seed = {
        'title': (data.get('title') or '').strip(),
        'author': (data.get('author') or '').strip(),
        'file_path': data.get('file_path') or '',
        'chapter_text': (data.get('chapter_text') or '').strip(),
    }

    try:
        ok, record = set_reading_record_finished(work_id, finished, seed=seed)
        if not ok:
            return jsonify({'success': False, 'message': '标记失败：缺少书名等必要信息'})

        remaining = build_recent_records(load_reading_records())
        refreshed = None
        for r in remaining:
            if r.get('work_id') == work_id:
                refreshed = _recent_record_to_json(r)
                break

        logger.info(f"{'✅ 已标记为已读' if finished else '↩️ 已取消已读'}: work_id={work_id[:8]}...")
        return jsonify({
            'success': True,
            'work_id': work_id,
            'finished': finished,
            'record': refreshed,
            'recent_total': len(remaining),
            'stats': compute_recent_stats(remaining)
        })
    except Exception as e:
        logger.error(f"❌ 标记已读失败: {e}")
        return jsonify({'success': False, 'message': str(e)})

@reader_bp.route('/api/search_in_novel')
def api_search_in_novel():
    """在当前小说内搜索关键词（类似 TXT 编辑器的 Ctrl+F）"""
    if not is_authenticated():
        return jsonify({'success': False, 'message': '未登录'}), 401

    raw_path = request.args.get('file_path', '')
    keyword = request.args.get('keyword', '').strip()
    limit = request.args.get('limit', 50, type=int)
    if limit is None or limit <= 0:
        limit = 50
    limit = min(limit, 500)

    if not raw_path or not keyword:
        return jsonify({'success': False, 'message': '参数不完整'})

    file_path = resolve_novel_path(raw_path)
    if not file_path:
        return jsonify({'success': False, 'message': '非法路径'}), 400

    if not os.path.exists(file_path):
        return jsonify({'success': False, 'message': '文件不存在'})

    if len(keyword) < 2:
        return jsonify({'success': False, 'message': '关键词至少 2 个字符'})

    try:
        # ===== 1. 读文件（复用带缓存的读取逻辑）=====
        _content, lines, _encoding = load_novel_content(file_path)

        # ===== 2. 找所有章节（用于标注每行属于哪一章）=====
        chapters = []
        for i, line in enumerate(lines):
            line_clean = line.strip()
            if not line_clean or len(line_clean) > 100:
                continue
            if (LEVEL1_PATTERN.match(line_clean) or
                LEVEL2_PATTERN.match(line_clean) or
                LEVEL3_PATTERN.match(line_clean)):
                chapters.append({'line_number': i, 'text': line_clean})

        # ===== 3. 搜索 =====
        keyword_lower = keyword.lower()
        results = []
        chapter_idx = 0
        chapter_text = '正文'
        chapter_line = 1

        for i, line in enumerate(lines):
            # 章节指针只前进，避免每行都遍历章节
            while chapter_idx < len(chapters) and chapters[chapter_idx]['line_number'] <= i:
                chapter_text = chapters[chapter_idx]['text']
                chapter_line = chapters[chapter_idx]['line_number'] + 1
                chapter_idx += 1

            if keyword_lower in line.lower():
                # 提取上下文
                text = line.strip()
                if len(text) > 120:
                    pos = text.lower().find(keyword_lower)
                    start = max(0, pos - 40)
                    end = min(len(text), pos + len(keyword) + 40)
                    text = ('...' if start > 0 else '') + text[start:end] + ('...' if end < len(text) else '')

                results.append({
                    'line_number': i + 1,
                    'text': text,
                    'chapter_text': chapter_text,
                    'chapter_line': chapter_line
                })

                if len(results) >= limit:
                    break

        # ===== 4. 统计命中分布在多少章（面板里显示「全书 N 处 / M 章」）=====
        # 按 chapter_text 归组，保持首次出现的顺序（即书内顺序）
        chapter_groups = []
        _seen = {}
        for r in results:
            name = r['chapter_text']
            if name not in _seen:
                _seen[name] = len(chapter_groups)
                chapter_groups.append({
                    'chapter_text': name,
                    'chapter_line': r['chapter_line'],
                    'count': 0
                })
            chapter_groups[_seen[name]]['count'] += 1

        return jsonify({
            'success': True,
            'keyword': keyword,
            'total': len(results),
            'has_more': len(results) >= limit,
            'chapter_count': len(chapter_groups),
            'chapter_groups': chapter_groups,
            'results': results
        })

    except Exception as e:
        logger.error(f"搜索失败: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@reader_bp.route('/admin/clear_all_records', methods=['POST'])
def admin_clear_all_records():
    """管理员清除所有用户的阅读记录"""
    if not is_admin():
        return jsonify({'success': False, 'message': '权限不足'}), 403

    count = 0
    try:
        if os.path.exists(READING_RECORD_DIR):
            for filename in os.listdir(READING_RECORD_DIR):
                if filename.startswith('records_') and filename.endswith('.json'):
                    file_path = os.path.join(READING_RECORD_DIR, filename)
                    os.remove(file_path)
                    count += 1
            os.makedirs(READING_RECORD_DIR, exist_ok=True)
            print(f"🗑️ 管理员清除了所有用户的阅读记录，共 {count} 个文件")
        return jsonify({'success': True, 'count': count})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@reader_bp.route('/admin/clear_user_records', methods=['POST'])
def admin_clear_user_records():
    """管理员清除指定用户的阅读记录"""
    if not is_admin():
        return jsonify({'success': False, 'message': '权限不足'}), 403

    data = request.get_json(silent=True) or {}
    user_display = data.get('user_display', '')

    users = nm.CONFIG.get('users', {}) or {}

    target_key = None
    for key, user_info in users.items():
        display_name = normalize_user_info(user_info, key).get('user_id', key)
        if display_name == user_display:
            target_key = key
            break

    if not target_key:
        return jsonify({'success': False, 'message': '用户不存在'})

    record_file = get_user_record_file(target_key)
    try:
        with file_lock(record_file + '.lock'):
            if os.path.exists(record_file):
                os.remove(record_file)
            save_json_file(record_file, {})
        logger.info(f"🗑️ 管理员清除了用户 {user_display} 的阅读记录")
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@reader_bp.route('/admin/user_records')
def admin_user_records():
    """管理员查看各用户的阅读【数量】统计。

    隐私边界：这里刻意不返回书名/作者/章节/阅读位置等任何内容字段。
    管理员只需要知道「谁读了几本、最近什么时候读过」，
    读什么书属于用户隐私，不通过该接口暴露。
    """
    if not is_admin():
        return jsonify({'error': '权限不足'}), 403

    users = nm.CONFIG.get('users', {}) or {}
    user_records = {}

    for key, user_info in users.items():
        info = normalize_user_info(user_info, key)
        role = info.get('role', 'user')
        display_name = info.get('user_id', key)

        record_file = get_user_record_file(key)
        entry = {'count': 0, 'role': role, 'last_read': None}

        if os.path.exists(record_file):
            try:
                payload = _coerce_records_payload(load_json_file(record_file, {}))
                records = payload['records']
                entry['count'] = len(records)

                # 只取最近一次阅读的时间戳用于展示「多久没读了」，
                # 不带出这条记录指向的是哪本书。
                timestamps = [r.get('timestamp') for r in records.values()
                              if isinstance(r, dict) and r.get('timestamp')]
                if timestamps:
                    entry['last_read'] = max(timestamps)
            except Exception as e:
                logger.error(f"读取用户记录失败 {display_name}: {e}")

        user_records[display_name] = entry

    return jsonify(user_records)
