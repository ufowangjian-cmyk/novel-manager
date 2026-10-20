// ============================================
// reader-search.js - 阅读页内搜索
// 依赖：common.js（debounce, escapeHtml, showNotification）
// 使用场景：read_chapter.html
// ============================================

(function() {
    'use strict';

    let searchAbortController = null;
    let currentResults = [];
    let currentResultIndex = -1;

    // ===== 打开搜索栏 =====
    function readerSearchOpen() {
        const bar = document.getElementById('readerSearchBar');
        const input = document.getElementById('readerSearchInput');
        if (!bar || !input) return;
        if (typeof vibrate === 'function') vibrate('light');
        bar.classList.add('active');
        setTimeout(() => input.focus(), 50);
    }

    // ===== 关闭搜索栏 =====
    function readerSearchClose() {
        const bar = document.getElementById('readerSearchBar');
        const panel = document.getElementById('searchResultsPanel');
        const input = document.getElementById('readerSearchInput');
        if (bar) bar.classList.remove('active');
        if (typeof vibrate === 'function') vibrate('light');
        if (panel) {
            panel.classList.remove('active');
            panel.innerHTML = '';
        }
        if (input) input.value = '';
        currentResults = [];
        currentResultIndex = -1;
    }

    // ===== 执行搜索（防抖）=====
    const doSearch = debounce(async (keyword) => {
        const panel = document.getElementById('searchResultsPanel');
        if (!panel) return;

        if (!keyword || keyword.length < 2) {
            panel.classList.remove('active');
            panel.innerHTML = '';
            return;
        }

        // 取消上一次请求
        if (searchAbortController) {
            searchAbortController.abort();
        }
        searchAbortController = new AbortController();

        // 显示加载状态
        panel.innerHTML = '<div class="search-result-info">' + icon('loader', 'sm') + ' 搜索中...</div>';
        panel.classList.add('active');

        try {
            const fp = (typeof filePath !== 'undefined' && filePath) ? filePath : '';
            const url = `/api/search_in_novel?file_path=${encodeURIComponent(fp)}&keyword=${encodeURIComponent(keyword)}`;

            const response = await fetch(url, { signal: searchAbortController.signal });
            const result = await response.json();

            if (!result.success) {
                panel.innerHTML = `<div class="search-no-result">${icon('circle-x', 'sm')} ${escapeHtml(result.message || '搜索失败')}</div>`;
                return;
            }

            renderResults(result, keyword);
        } catch (e) {
            if (e.name !== 'AbortError') {
                console.error('搜索失败:', e);
                panel.innerHTML = `<div class="search-no-result">${icon('circle-x', 'sm')} 网络错误</div>`;
            }
        }
    }, 300);

    // ===== 渲染结果（按章节分组）=====
    function renderResults(result, keyword) {
        const panel = document.getElementById('searchResultsPanel');
        if (!panel) return;

        currentResults = result.results || [];
        currentResultIndex = -1;

        // ===== 没有结果 =====
        if (currentResults.length === 0) {
            if (typeof vibrate === 'function') vibrate('light');
            panel.innerHTML = `<div class="search-no-result">${icon('search', 'sm')} 全书没有找到 "${escapeHtml(keyword)}"</div>`;
            panel.classList.add('active');
            return;
        }

        // ===== 有结果 =====
        if (typeof vibrate === 'function') vibrate('success');

        const escapedKeyword = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const regex = new RegExp(`(${escapedKeyword})`, 'gi');

        const chapterCount = result.chapter_count || 1;
        const truncated = result.has_more;

        // 统计条：明确这是全书搜索，和浏览器 Ctrl+F（只搜当页）区分开
        let html = `
            <div class="search-result-info">
                <span class="sr-info__main">全书找到 <strong>${result.total}</strong> 处</span>
                <span class="sr-info__sub">分布在 ${chapterCount} 章${truncated ? '（仅显示前 ' + result.total + '处）' : ''}</span>
                <button type="button" class="sr-info__close" onclick="readerSearchClose()" aria-label="关闭搜索">${icon('x', 'sm')}</button>
            </div>`;

        // 按章节分组渲染
        let lastChapter = null;
        let chapterSeq = 0;
        currentResults.forEach((r, i) => {
            if (r.chapter_text !== lastChapter) {
                lastChapter = r.chapter_text;
                chapterSeq++;
                html += `
                    <div class="sr-group-head">
                        <span class="sr-group__no">${chapterSeq}</span>
                        <span class="sr-group__name">${escapeHtml(r.chapter_text)}</span>
                    </div>`;
            }
            const highlightedText = escapeHtml(r.text).replace(regex, '<span class="highlight">$1</span>');
            html += `
                <div class="search-result-item" data-index="${i}" data-line="${r.line_number}">
                    <div class="text">${highlightedText}</div>
                    <div class="line">第 ${r.line_number} 行</div>
                </div>
            `;
        });

        panel.innerHTML = html;
        panel.classList.add('active');

        // 点击整条结果跳转
        panel.querySelectorAll('.search-result-item[data-line]').forEach(el => {
            el.addEventListener('click', () => {
                const lineNumber = parseInt(el.dataset.line);
                jumpToLine(lineNumber);
            });
        });
    }

    // ===== 跳转到指定行（B：带上关键词，落地后定位并高亮）=====
    function jumpToLine(lineNumber) {
        if (typeof vibrate === 'function') vibrate('medium');

        const keyword = (document.getElementById('readerSearchInput') || {}).value || '';
        readerSearchClose();

        const fp = (typeof filePath !== 'undefined' && filePath) ? filePath : '';
        // 目标行号直接进 read_chapter 路由，命中行由 ?hl= 在落地页高亮
        const params = new URLSearchParams();
        if (keyword.trim()) params.set('hl', keyword.trim());
        const qs = params.toString();
        window.location.href = `/read/${fp}/${lineNumber}${qs ? '?' + qs : ''}`;
    }

    // ===== 下一个 / 上一个（当前结果列表内循环滚动）=====
    function readerSearchNext() {
        if (currentResults.length === 0) return;
        currentResultIndex = (currentResultIndex + 1) % currentResults.length;
        if (typeof vibrate === 'function') vibrate('light');
        highlightActiveResult();
    }

    function readerSearchPrev() {
        if (currentResults.length === 0) return;
        currentResultIndex = (currentResultIndex - 1 + currentResults.length) % currentResults.length;
        highlightActiveResult();
    }

    function highlightActiveResult() {
        const panel = document.getElementById('searchResultsPanel');
        if (!panel) return;
        panel.querySelectorAll('.search-result-item').forEach(el => {
            el.style.background = '';
        });
        const target = panel.querySelector(`.search-result-item[data-index="${currentResultIndex}"]`);
        if (target) {
            target.style.background = 'var(--color-bg-tertiary)';
            target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }

    // ===== 初始化：绑定输入事件 =====
    function initReaderSearch() {
        const input = document.getElementById('readerSearchInput');
        if (!input) return;

        input.addEventListener('input', (e) => {
            doSearch(e.target.value.trim());
        });

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                if (currentResults.length > 0 && currentResultIndex >= 0) {
                    // Enter = 跳转到当前选中的结果
                    const r = currentResults[currentResultIndex];
                    if (r) jumpToLine(r.line_number);
                } else if (currentResults.length > 0) {
                    // 没选中 → 跳到第一个
                    jumpToLine(currentResults[0].line_number);
                }
            } else if (e.key === 'Escape') {
                e.preventDefault();
                readerSearchClose();
            }
        });

        // ===== 全局快捷键 =====
        // 注意：Ctrl+F / Cmd+F 故意「不拦截」，交给浏览器原生查找（只搜当前页）。
        // 本面板是全书搜索，两者分工不同，改用 Ctrl+Shift+F / F3 打开。
        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'f' || e.key === 'F')) {
                e.preventDefault();
                readerSearchOpen();
                return;
            }
            if (e.key === 'F3') {
                e.preventDefault();
                readerSearchOpen();
                return;
            }
            // 面板已打开时，Esc 关闭
            if (e.key === 'Escape') {
                const bar = document.getElementById('readerSearchBar');
                if (bar && bar.classList.contains('active')) {
                    readerSearchClose();
                }
            }
        });
    }

    // ===== B：落地页定位并高亮命中的行 =====
    // 由 ?hl=关键词 触发。仅在「跳转过来的那一行」及附近高亮，避免满页刷色。
    function applySearchHighlight() {
        const params = new URLSearchParams(window.location.search);
        const keyword = (params.get('hl') || '').trim();
        if (!keyword) return;

        const content = document.getElementById('readingContent');
        if (!content) return;

        const lines = content.querySelectorAll('.content-line');
        if (!lines.length) return;

        const kwLower = keyword.toLowerCase();
        const escaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const regex = new RegExp(`(${escaped})`, 'gi');
        let firstHit = null;

        lines.forEach(line => {
            if (line.classList.contains('separator')) return;
            const raw = line.textContent || '';
            if (!raw.toLowerCase().includes(kwLower)) return;

            // 逐个子节点替换，保留原有 <span> 等结构不被打碎
            highlightInElement(line, regex);
            if (!firstHit) firstHit = line;
        });

        if (firstHit) {
            // 等排版稳定（首屏字体/宽度注入完成）再滚动，否则会滚偏
            setTimeout(() => {
                firstHit.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }, 120);
        }
    }

    // 在元素内做关键词高亮，跳过已有标记和图片/链接
    function highlightInElement(el, regex) {
        const SKIP = /^(IMG|VIDEO|AUDIO|BUTTON|A|INPUT|SELECT|TEXTAREA|SCRIPT|STYLE)$/;
        const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
            acceptNode(node) {
                if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
                if (node.parentNode && SKIP.test(node.parentNode.nodeName)) return NodeFilter.FILTER_REJECT;
                if (node.parentNode && node.parentNode.classList &&
                    node.parentNode.classList.contains('search-hit')) {
                    return NodeFilter.FILTER_REJECT;
                }
                return NodeFilter.FILTER_ACCEPT;
            }
        });

        const targets = [];
        let n;
        while ((n = walker.nextNode())) {
            regex.lastIndex = 0;
            if (regex.test(n.nodeValue)) targets.push(n);
        }

        targets.forEach(node => {
            const frag = document.createDocumentFragment();
            const text = node.nodeValue;
            let last = 0;
            regex.lastIndex = 0;
            let m;
            while ((m = regex.exec(text)) !== null) {
                if (m.index > last) {
                    frag.appendChild(document.createTextNode(text.slice(last, m.index)));
                }
                const mark = document.createElement('mark');
                mark.className = 'search-hit';
                mark.textContent = m[0];
                frag.appendChild(mark);
                last = m.index + m[0].length;
                if (m[0].length === 0) regex.lastIndex++;  // 防零宽死循环
            }
            if (last < text.length) {
                frag.appendChild(document.createTextNode(text.slice(last)));
            }
            node.parentNode.replaceChild(frag, node);
        });
    }

    // ===== 暴露全局 =====
    window.readerSearchOpen = readerSearchOpen;
    window.readerSearchClose = readerSearchClose;
    window.readerSearchNext = readerSearchNext;
    window.readerSearchPrev = readerSearchPrev;
    window.initReaderSearch = initReaderSearch;
    window.applySearchHighlight = applySearchHighlight;

    console.log('✅ reader-search.js 已加载');
})();