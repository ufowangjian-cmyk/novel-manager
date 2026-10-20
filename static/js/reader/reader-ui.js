// ============================================
// reader-ui.js - 阅读器交互控制
// 依赖：common.js, reader-core.js
// 使用场景：read_chapter.html
// ============================================
(function() {
    'use strict';
    // ==================== 偏好保存统一入口 ====================
    function savePreference(key, value) {
        const payload = {};
        payload[key] = value;
        return fetch('/api/save_preferences', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).catch(err => console.error(`保存 ${key} 失败:`, err));
    }
    // 轻提示（不刷新）
    // duration 传 0 表示常驻，直到被下一次 showFontTip 替换或被 hideFontTip 关掉。
    // 字体下载提示需要常驻：18MB 在外网可能要几分钟，1.2 秒就消失等于没提示。
    function showFontTip(text, color, duration) {
        const old = document.getElementById('reader-font-tip');
        if (old) old.remove();
        const tip = document.createElement('div');
        tip.id = 'reader-font-tip';
        tip.textContent = text;
        tip.style.cssText = `position: fixed; top: 20px; right: 20px;
            background: ${color || '#4caf50'}; color: white;
            padding: 8px 16px; border-radius: 8px;
            z-index: 10000; font-size: 14px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            transition: opacity 0.3s ease;
        `;
        document.body.appendChild(tip);
        const ms = (duration === undefined) ? 1200 : duration;
        if (ms > 0) {
            setTimeout(() => {
                tip.style.opacity = '0';
                setTimeout(() => tip.remove(), 300);
            }, ms);
        }
        return tip;
    }
    function hideFontTip() {
        const tip = document.getElementById('reader-font-tip');
        if (!tip) return;
        tip.style.opacity = '0';
        setTimeout(() => tip.remove(), 300);
    }

    // ==================== 内置字体按需加载 ====================
    // 内置字体单文件最大 8.6MB（霞鹜文楷）。过去只靠 CSS @font-face +
    // font-display:swap 触发下载，问题是浏览器不暴露任何进度/成功/失败事件：
    //   1) 用户看不到"正在下载"，以为没生效 → 刷新 → 18MB 从头再来，永远下不完；
    //   2) 弱网下失败是静默的，用户只会觉得"字体坏了"。
    // 这里改用 FontFace API 显式加载，并给出真实反馈。
    //   key  → 字体在 CSS 里注册的 family 名（font.css 的 @font-face 名）
    //   size → 单文件体积，仅用于提示文案
    // 内置字体清单已提升到 common.js（首页预热等全站场景共用），此处引用同一份，勿重复定义
    const BUILTIN_FONTS = window.BUILTIN_FONTS;
    // 注：京华老宋体已不再内置（删除了 18.4MB 的 KingHwaOldSong.woff2），
    // 改为纯系统字体。它不在上表内，pickBuiltinFamily 会返回 null，
    // ensureBuiltinFont 直接放行，不会触发任何下载。

    // 从字体栈字符串里挑出内置 @font-face 名（如
    // "'霞鹜文楷等宽 Medium', '霞鹜文楷内置', sans-serif" → 霞鹜文楷内置）
    function pickBuiltinFamily(fontStack) {
        if (!fontStack) return null;
        const names = String(fontStack).match(/'([^']+)'/g) || [];
        for (const raw of names) {
            const name = raw.replace(/'/g, '');
            if (BUILTIN_FONTS[name]) return name;
        }
        return null;
    }

    // 已加载/加载中的缓存，避免重复下载（FontFace 本身也有缓存，
    // 但这里避免重复发起 Promise 与重复弹提示）
    const fontLoadState = {};

    // 确保某个内置字体可用。返回 Promise<boolean>（是否可用）。
    // 兼容不支持 FontFace 的老浏览器：直接放行，退回原来的 CSS 行为。
    function ensureBuiltinFont(fontStack, opts) {
        const family = pickBuiltinFamily(fontStack);
        if (!family) return Promise.resolve(true);           // 不是内置字体，无需下载
        if (typeof FontFace === 'undefined' || !document.fonts) {
            return Promise.resolve(true);                     // 老浏览器：留给 CSS 处理
        }
        if (fontLoadState[family] === 'done') return Promise.resolve(true);
        if (fontLoadState[family] === 'loading') return fontLoadState[family + ':promise'];

        const info = BUILTIN_FONTS[family];
        fontLoadState[family] = 'loading';

        const face = new FontFace(family, `url(${info.url})`, { display: 'swap' });
        const p = face.load().then(loaded => {
            document.fonts.add(loaded);
            fontLoadState[family] = 'done';
            return true;
        }).catch(err => {
            // 失败要能被重试：清掉状态，否则用户再次选择时直接返回旧 Promise
            fontLoadState[family] = 'failed';
            console.warn(`内置字体加载失败: ${family}`, err);
            return false;
        });

        fontLoadState[family + ':promise'] = p;
        return p;
    }

    // 当前生效字体是否已在本地可用（用于页面载入时提示"字体正在下载"）
    function builtinFontReady(fontStack) {
        const family = pickBuiltinFamily(fontStack);
        if (!family) return true;
        if (typeof document.fonts === 'undefined') return true;
        try { return document.fonts.check(`16px "${family}"`); } catch (e) { return true; }
    }
    // ==================== 字号 ====================
    // 字号区间与步长（点 A- / A+ 时每次 ±2px）
    const FONT_MIN = 14;
    const FONT_MAX = 40;
    const FONT_STEP = 2;
    function getCurrentFontSize() {
        const content = document.querySelector('.reading-content');
        if (content) {
            const inline = parseFloat(content.style.fontSize);
            if (!isNaN(inline)) return inline;
            const computed = parseFloat(getComputedStyle(content).fontSize);
            if (!isNaN(computed)) return computed;
        }
        return 24;
    }
    function setFontSize(size) {
        const content = document.querySelector('.reading-content');
        if (!content) return;
        const val = Math.max(FONT_MIN, Math.min(FONT_MAX, Math.round(size)));
        content.style.setProperty('font-size', val + 'px', 'important');
        localStorage.setItem('reader_font_size', val);
        highlightFontBtn(val);
        syncSetDrawerSize(val);
        savePreference('font_size', val);
    }
    // A- / A+ 步进
    function stepFontSize(delta) {
        setFontSize(getCurrentFontSize() + delta);
    }
    // 抽屉里的字号数值同步
    function syncSetDrawerSize(size) {
        const el = document.getElementById('setSizeVal');
        if (el) el.textContent = size;
    }
    function highlightFontBtn(size) {
        document.querySelectorAll('.font-btn').forEach(btn => {
            btn.classList.remove('active');
        });
        const activeBtn = document.getElementById('font' + size);
        if (activeBtn) activeBtn.classList.add('active');
    }
    function setFontFamily(fontFamily) {
        // 1) 立即应用（不刷新）
        //    先把字体栈写上，文字立刻以回退字体显示（不等下载），
        //    这与 font-display:swap 的行为一致，但下面能拿到真实进度。
        const content = document.getElementById('readingContent');
        if (content) content.style.fontFamily = fontFamily;
        const wrapper = document.querySelector('.reading-content');
        if (wrapper) wrapper.style.fontFamily = fontFamily;
        // 2) 本地存储
        localStorage.setItem('reader_font_family', fontFamily);
        // 3) 服务端保存
        savePreference('font_family', fontFamily);
        // 4) 内置字体：显式按需下载 + 真实反馈（非内置字体立即返回 true）
        ensureBuiltinFont(fontFamily).then(ok => {
            if (ok) {
                // 下载完成提示由 ensureBuiltinFont 负责，这里不重复弹
                return;
            }
            // 失败：提示已由 ensureBuiltinFont 给出，这里补一句"已回退"，
            // 让用户明白当前看到的是系统字体而非"字体没生效"
            console.warn('内置字体不可用，已回退到系统字体');
        });
    }
    // ==================== 分元素字体 / 颜色（标题/正文/引号/括号） ====================
    // 标题默认字体（与 reader.css 中 .chapter-title 的硬设保持一致，便于「恢复默认」时还原）
    const TITLE_DEFAULT_FONT = "'Segoe UI', '微软雅黑', sans-serif";
    // 每个可单独设字体的作用域：标题 + reader-core 里的全部高亮类型
    const SCOPE_SELECTORS = {
        title:            '#readingContent .chapter-title-level1, #readingContent .chapter-title-level2, #readingContent .chapter-title-level3, #readingContent .chapter-title-level1 .chapter-number, #readingContent .chapter-title-level2 .chapter-number, #readingContent .chapter-title-level3 .chapter-number',
        double_quote:     '#readingContent .highlight-quote-double',
        single_quote:     '#readingContent .highlight-quote-single',
        bracket:          '#readingContent .highlight-bracket',           // 圆括号 （）()
        square_bracket:   '#readingContent .highlight-square-bracket',    // 方头括号 【】
        square_bracket_1: '#readingContent .highlight-square-bracket-1',  // 方括号 [] ［］
        hollow_bracket:   '#readingContent .highlight-hollow-bracket',    // 空心括号 〖〗
        book:             '#readingContent .highlight-book',              // 书名号 《》
    };
    const FONT_SCOPES = Object.keys(SCOPE_SELECTORS);
    // 作用域 → app-data 注入键（驼峰，对应 data-xxx-font-family）
    const SCOPE_APPKEY = {
        title: 'titleFontFamily',
        double_quote: 'doubleQuoteFontFamily',
        single_quote: 'singleQuoteFontFamily',
        bracket: 'bracketFontFamily',
        square_bracket: 'squareBracketFontFamily',
        square_bracket_1: 'squareBracket1FontFamily',
        hollow_bracket: 'hollowBracketFontFamily',
        book: 'bookFontFamily',
    };
    // 把某个作用域的字体栈应用到对应 DOM。fontStack 为空则清除内联字体，回退继承/默认值。
    function applyScopeFont(scope, fontStack) {
        const sel = SCOPE_SELECTORS[scope];
        if (!sel) return;
        const els = document.querySelectorAll(sel);
        els.forEach(el => {
            if (fontStack && fontStack !== '') {
                el.style.setProperty('font-family', fontStack, 'important');
            } else {
                el.style.removeProperty('font-family');
            }
        });
        if (fontStack) ensureBuiltinFont(fontStack);
    }
    // 作用域 → 模板下拉框 id（必须与 read_chapter.html 中的 select id 严格对应！
    // 模板用的是驼峰命名，如 doubleQuoteFontSelect，不能用简单的「去掉下划线」，
    // 否则匹配不上、applySavedFontSettings 无法回填抽屉下拉，导致在配置页改了字体、
    // 阅读页抽屉里仍显示旧值。）
    const SCOPE_SELECT_IDS = {
        title: 'titleFontSelect',
        double_quote: 'doubleQuoteFontSelect',
        single_quote: 'singleQuoteFontSelect',
        bracket: 'bracketFontSelect',
        square_bracket: 'squareBracketFontSelect',
        square_bracket_1: 'squareBracket1FontSelect',
        hollow_bracket: 'hollowBracketFontSelect',
        book: 'bookFontSelect',
    };
    function scopeSelectId(scope) {
        return SCOPE_SELECT_IDS[scope] || (scope.replace(/_/g, '') + 'FontSelect');
    }
    // 模板下拉调用：应用 + 记忆 + 落库
    function setScopeFont(scope, fontStack) {
        applyScopeFont(scope, fontStack);
        localStorage.setItem('reader_' + scope + '_font_family', fontStack);
        savePreference(scope + '_font_family', fontStack);
    }
    // ==================== 分元素 加粗 / 斜体 ====================
    // 作用域 = 正文(wrapper) + 标题 + reader-core 全部高亮类型
    const STYLE_SELECTORS = Object.assign({ body: '.reading-content' }, SCOPE_SELECTORS);
    const STYLE_SCOPES = Object.keys(STYLE_SELECTORS);
    const STYLE_APPKEY = {
        body:             { bold: 'bodyBold',            italic: 'bodyItalic' },
        title:            { bold: 'titleBold',           italic: 'titleItalic' },
        double_quote:     { bold: 'doubleQuoteBold',     italic: 'doubleQuoteItalic' },
        single_quote:     { bold: 'singleQuoteBold',     italic: 'singleQuoteItalic' },
        bracket:          { bold: 'bracketBold',         italic: 'bracketItalic' },
        square_bracket:   { bold: 'squareBracketBold',   italic: 'squareBracketItalic' },
        square_bracket_1: { bold: 'squareBracket1Bold',  italic: 'squareBracket1Italic' },
        hollow_bracket:   { bold: 'hollowBracketBold',   italic: 'hollowBracketItalic' },
        book:             { bold: 'bookBold',            italic: 'bookItalic' },
    };
    // 默认加粗：跟随各作用域 CSS 现状（粗的保持粗，避免升级回归）
    const DEFAULT_BOLD = {
        body: false, title: true, double_quote: false, single_quote: false,
        bracket: false, square_bracket: true, square_bracket_1: false,
        hollow_bracket: true, book: true,
    };
    function readBool(appVal, lsVal, def) {
        const a = (appVal === undefined || appVal === null) ? null : String(appVal).toLowerCase();
        if (a === 'true' || a === '1') return true;
        if (a === 'false' || a === '0') return false;
        if (lsVal === '1') return true;
        if (lsVal === '0') return false;
        return !!def;
    }
    // 是否有显式保存值（app-data 或 localStorage 非空）
    function hasVal(v) { return v !== undefined && v !== null && v !== ''; }
    // 把某个作用域的加粗/斜体应用到对应 DOM。
    // on=true/false 显式设为 bold/italic/normal（!important 覆盖）；
    // on===null 表示「交还 CSS 默认」——移除内联样式，保留 reader.css 中写死的斜体/字重。
    function applyScopeStyle(scope, type, on) {
        const sel = STYLE_SELECTORS[scope];
        if (!sel) return;
        const prop = type === 'bold' ? 'font-weight' : 'font-style';
        const val = on === null ? null
            : (on ? (type === 'bold' ? 'bold' : 'italic') : 'normal');
        document.querySelectorAll(sel).forEach(el => {
            if (val === null) el.style.removeProperty(prop);
            else el.style.setProperty(prop, val, 'important');
        });
    }
    // 模板按钮调用：切换 + 记忆 + 落库
    function toggleScopeStyle(btn) {
        const scope = btn.dataset.scope;
        const type = btn.dataset.style; // bold | italic
        const on = !btn.classList.contains('on');
        btn.classList.toggle('on', on);
        btn.setAttribute('aria-checked', on ? 'true' : 'false');
        applyScopeStyle(scope, type, on);
        const key = scope + (type === 'bold' ? '_bold' : '_italic');
        localStorage.setItem('reader_' + key, on ? '1' : '0');
        savePreference(key, on);
    }
    function syncStyleBtn(scope, type, on) {
        const btn = document.querySelector('.set-bi[data-scope="' + scope + '"][data-style="' + type + '"]');
        if (!btn) return;
        btn.classList.toggle('on', !!on);
        btn.setAttribute('aria-checked', on ? 'true' : 'false');
    }
    // ==================== 行高 / 段距 / 首行缩进 ====================
    function setLineHeight(value) {
        const v = Math.max(1.2, Math.min(2.6, parseFloat(value) || 1.8));
        document.documentElement.style.setProperty('--reader-line-height', v);
        localStorage.setItem('reader_line_height', v);
        const el = document.getElementById('setLineHeightVal');
        if (el) el.textContent = v.toFixed(1);
        savePreference('line_height', v);
    }
    function setParagraphSpacing(value) {
        const v = Math.max(0, Math.min(2, parseFloat(value)));
        if (isNaN(v)) return;
        document.documentElement.style.setProperty('--reader-paragraph-spacing', v + 'rem');
        const el = document.getElementById('setParaSpacingVal');
        if (el) el.textContent = v.toFixed(1);
        savePreference('paragraph_spacing', v);
    }
    function toggleIndent(btn) {
        if (!btn) return;
        const on = !btn.classList.contains('on');
        btn.classList.toggle('on', on);
        btn.setAttribute('aria-checked', on ? 'true' : 'false');
        document.documentElement.style.setProperty('--reader-text-indent', on ? '2em' : '0');
        savePreference('indent_paragraph', on);
    }
    // ==================== 背景主题 ====================
    const READER_THEMES = ['default', 'paper', 'white', 'green', 'sepia', 'gray', 'night'];
    function applyReaderTheme(theme, opts) {
        const options = opts || {};
        const t = READER_THEMES.indexOf(theme) >= 0 ? theme : 'default';
        const box = document.querySelector('.reader-container') || document.body;
        if (box) box.setAttribute('data-reader-theme', t);
        // 高亮选中的色块
        document.querySelectorAll('#setThemes .set-theme').forEach(btn => {
            btn.classList.toggle('on', btn.getAttribute('data-rt') === t);
        });
        // 浏览器地址栏 / 状态栏配色跟着走，避免夜里刺眼
        syncChromeColor();
        if (!options.silent) {
            localStorage.setItem('reader_theme', t);
        }
        if (!options.skipSave) {
            savePreference('reader_theme', t);
        }
    }
    // 读取当前主题对应的背景色，同步给 <meta theme-color>
    function syncChromeColor() {
        const box = document.querySelector('.reader-container');
        if (!box) return;
        const bg = getComputedStyle(box).getPropertyValue('--reader-bg-primary').trim();
        if (!bg) return;
        const meta = document.querySelector('meta[name="theme-color"]');
        if (meta) meta.setAttribute('content', bg);
    }
    // ==================== 设置抽屉开关 ====================
    function openSetDrawer() {
        const drawer = document.getElementById('setDrawer');
        const mask = document.getElementById('setDrawerMask');
        if (!drawer) return;
        drawer.classList.add('active');
        if (mask) mask.classList.add('active');
        document.body.style.overflow = 'hidden';
    }
    function closeSetDrawer() {
        const drawer = document.getElementById('setDrawer');
        const mask = document.getElementById('setDrawerMask');
        if (drawer) drawer.classList.remove('active');
        if (mask) mask.classList.remove('active');
        document.body.style.overflow = '';
    }
    // 恢复默认：重置排版项，以及分元素的字体/颜色
    function resetReaderSettings() {
        if (!confirm('恢复默认阅读设置（含字体）？')) return;
        const defaults = { size: 24, lh: 1.8, ps: 0.8, indent: true, theme: 'default' };
        setFontSize(defaults.size);
        const lh = document.getElementById('setLineHeight');
        if (lh) lh.value = defaults.lh;
        setLineHeight(defaults.lh);
        const ps = document.getElementById('setParaSpacing');
        if (ps) ps.value = defaults.ps;
        setParagraphSpacing(defaults.ps);
        const indentBtn = document.getElementById('setIndent');
        if (indentBtn) {
            indentBtn.classList.add('on');
            indentBtn.setAttribute('aria-checked', 'true');
        }
        document.documentElement.style.setProperty('--reader-text-indent', '2em');
        savePreference('indent_paragraph', true);
        applyReaderTheme(defaults.theme);
        // 分元素字体一并恢复默认（标题回默认，其余回「跟随正文」）
        const syncSel = (id, val) => { const s = document.getElementById(id); if (s) s.value = val; };
        FONT_SCOPES.forEach(scope => {
            const def = scope === 'title' ? TITLE_DEFAULT_FONT : '';
            setScopeFont(scope, def);
            syncSel(scopeSelectId(scope), def);
        });
        // 加粗/斜体 一并恢复默认：清除显式设置，回到配置默认值（DEFAULT_BOLD），不再交还 CSS
        STYLE_SCOPES.forEach(scope => {
            applyScopeStyle(scope, 'bold', DEFAULT_BOLD[scope]);
            applyScopeStyle(scope, 'italic', false);
            savePreference(scope + '_bold', '');
            savePreference(scope + '_italic', '');
            localStorage.removeItem('reader_' + scope + '_bold');
            localStorage.removeItem('reader_' + scope + '_italic');
            syncStyleBtn(scope, 'bold', DEFAULT_BOLD[scope]);
            syncStyleBtn(scope, 'italic', false);
        });
        showFontTip('已恢复默认');
    }
    // ==================== 按住拖动翻页（抓手） ====================
    // 手势判据（两者都满足才算拖拽）：
    //   ① 按住超过 HOLD_DELAY —— 否则双击选词会被拖走
    //   ② 移动超过 MOVE_THRESHOLD —— 否则与「点击正文切工具栏」冲突
    const DRAG_HOLD_DELAY = 150;   // ms，按住多久才算拖拽
    const DRAG_MOVE_THRESHOLD = 5; // px，超过多少位移才算拖拽
    let dragScrollEnabled = true;
    let dragState = null;
    let suppressNextClick = false;

    // 是否允许用鼠标圈选文字。默认 false（拖拽优先）——
    // 允许圈选时，mousedown 不再 preventDefault，浏览器原生选词正常工作。
    let textSelectEnabled = false;

    // 桌面端判定：有精确指针 + 能 hover 才是桌面。
    // 比 innerWidth <= 768 准 —— 触屏笔记本不该被当成移动端。
    function isDesktopPointer() {
        return !!(window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches);
    }
    // 与沉浸模式共用同一份可交互元素白名单：图片/链接/按钮上不启动拖拽
    const DRAG_EXCLUDE_SELECTOR = 'a, img, video, audio, button, input, select, textarea, label, .emoji, [data-img-id], .image-wrapper, .local-video-figure';
    function isDragScrollOn() {
        return dragScrollEnabled;
    }
    function initDragScroll() {
        const wrapper = document.getElementById('contentWrapper');
        if (!wrapper) return;
        // 从阅读设置抽屉的开关状态恢复（与后端 user_prefs 注入保持一致）
        const dragBtn = document.getElementById('setDragScroll');
        if (dragBtn) dragScrollEnabled = dragBtn.classList.contains('on');
        const selBtn = document.getElementById('setTextSelect');
        if (selBtn) textSelectEnabled = selBtn.classList.contains('on');
        // mousedown：记录起点，启动按住计时器
        wrapper.addEventListener('mousedown', function (e) {
            if (!dragScrollEnabled) return;
            // 只响应主键；中键/右键交给浏览器自己处理
            if (e.button !== 0) return;
            if (e.target.closest(DRAG_EXCLUDE_SELECTOR)) return;
            // 关键：必须在 mousedown 阶段就掐掉原生选词。
            // 浏览器的选词在「按下瞬间」就开始了，等到 mousemove 里再
            // preventDefault 已经太晚 —— 表现就是拖拽时仍会圈出一段文字。
            // 允许圈选（textSelectEnabled）时不干预，走浏览器原生行为。
            if (!textSelectEnabled) {
                e.preventDefault();
            }
            dragState = {
                startY: e.clientY,
                lastY: e.clientY,
                startX: e.clientX,
                active: false,
                holdTimer: null
            };
            // 按住超过阈值时间才进入拖拽；期间若已移动超出阈值则提前激活，
            // 这样「快速拖一下」不会被 150ms 延迟拖住
            dragState.holdTimer = setTimeout(function () {
                if (dragState && !dragState.active) {
                    activateDrag();
                }
            }, DRAG_HOLD_DELAY);
        });
        // mousemove：移动超阈值才激活拖拽；激活后跟随滚动
        wrapper.addEventListener('mousemove', function (e) {
            if (!dragState) return;
            const dy = e.clientY - dragState.startY;
            const dx = e.clientX - dragState.startX;
            if (!dragState.active) {
                // 明显是横向滑动（未来若加左右翻页手势）时不误判为拖拽
                if (Math.abs(dx) > Math.abs(dy)) {
                    clearDragState();
                    return;
                }
                if (Math.abs(dy) < DRAG_MOVE_THRESHOLD) return;
                // 移动已超阈值 → 取消延迟，立即进入拖拽
                clearTimeout(dragState.holdTimer);
                activateDrag();
            }
            e.preventDefault();
            const deltaY = dragState.lastY - e.clientY; // 手指下移 → 内容上移
            dragState.lastY = e.clientY;
            window.scrollBy(0, deltaY);
        });
        // mouseup / 离开窗口：结束拖拽
        function endDrag() {
            if (!dragState) return;
            const wasActive = dragState.active;
            clearDragState();
            // 拖拽结束后浏览器还会派发一次 click，必须吞掉，
            // 否则会误触发「点击正文切换工具栏」
            if (wasActive) {
                suppressNextClick = true;
                setTimeout(function () { suppressNextClick = false; }, 0);
            }
        }
        wrapper.addEventListener('mouseup', endDrag);
        wrapper.addEventListener('mouseleave', endDrag);
        window.addEventListener('mouseup', endDrag);
        window.addEventListener('blur', endDrag);
        // 拖拽时阻止图片/文字原生拖拽，避免出现虚影
        wrapper.addEventListener('dragstart', function (e) {
            if (dragState && dragState.active) e.preventDefault();
        });
    }
    function activateDrag() {
        if (!dragState) return;
        dragState.active = true;
        document.body.classList.add('is-drag-scrolling');
    }
    function clearDragState() {
        if (!dragState) return;
        clearTimeout(dragState.holdTimer);
        dragState = null;
        document.body.classList.remove('is-drag-scrolling');
    }
    // 切换「圈选文字」（与「按住拖动翻页」互斥）。偏好存后端，刷新后保留。
    function toggleTextSelect(btn) {
        if (!btn) return;
        const on = !btn.classList.contains('on');
        btn.classList.toggle('on', on);
        btn.setAttribute('aria-checked', on ? 'true' : 'false');
        textSelectEnabled = on;
        savePreference('text_select', on);
        // 互斥：开启圈选则关闭「按住拖动翻页」
        if (on) {
            dragScrollEnabled = false;
            const dragBtn = document.getElementById('setDragScroll');
            if (dragBtn) {
                dragBtn.classList.remove('on');
                dragBtn.setAttribute('aria-checked', 'false');
            }
            savePreference('drag_scroll', false);
        }
        if (typeof showFontTip === 'function') {
            showFontTip(on ? '已开启圈选文字' : '已关闭圈选文字');
        }
    }

    function isTextSelectOn() {
        return textSelectEnabled;
    }

    function toggleDragScroll(btn) {
        if (!btn) return;
        const on = !btn.classList.contains('on');
        btn.classList.toggle('on', on);
        btn.setAttribute('aria-checked', on ? 'true' : 'false');
        dragScrollEnabled = on;
        clearDragState();
        savePreference('drag_scroll', on);
        // 互斥：开启拖动翻页则关闭「圈选文字」
        if (on) {
            textSelectEnabled = false;
            const selBtn = document.getElementById('setTextSelect');
            if (selBtn) {
                selBtn.classList.remove('on');
                selBtn.setAttribute('aria-checked', 'false');
            }
            savePreference('text_select', false);
        }
    }
    // ==================== 沉浸模式 ====================
    let immersiveEnabled = true;
    let immersiveTimer = null;
    let immersiveHintShown = false;
    function setBarsHidden(hidden) {
        const top = document.getElementById('readerTop');
        const bottom = document.getElementById('readerBottom');
        if (top) top.classList.toggle('is-hidden', hidden);
        if (bottom) bottom.classList.toggle('is-hidden', hidden);
    }
    function areBarsHidden() {
        const top = document.getElementById('readerTop');
        return !!(top && top.classList.contains('is-hidden'));
    }
    function toggleImmersive() {
        if (!immersiveEnabled) return;
        const hide = !areBarsHidden();
        setBarsHidden(hide);
        if (typeof vibrate === 'function') vibrate('light');
        // 首次呼出工具栏时给个提示
        if (!hide && !immersiveHintShown) {
            immersiveHintShown = true;
            const hint = document.getElementById('immersiveHint');
            if (hint) {
                hint.classList.add('show');
                setTimeout(() => hint.classList.remove('show'), 2000);
            }
        }
        // 显示工具栏后 3 秒自动收起
        if (!hide) {
            clearTimeout(immersiveTimer);
            immersiveTimer = setTimeout(() => setBarsHidden(true), 3000);
        }
    }
    function initImmersive() {
        const wrapper = document.getElementById('contentWrapper');
        if (!wrapper) return;
        // 点击正文：可交互元素一律放行，其余切换工具栏
        wrapper.addEventListener('click', function (e) {
            // 刚完成一次拖拽 → 这次 click 是拖拽的尾巴，不是「点击正文」，忽略
            if (suppressNextClick) {
                suppressNextClick = false;
                return;
            }
            // 图片/链接/视频/音频/按钮/表情/灯箱 等一律不触发沉浸切换
            if (e.target.closest('a, img, video, audio, button, input, select, textarea, label, .emoji, [data-img-id], .image-wrapper, .local-video-figure')) {
                return;
            }
            // 有文字被选中时不切换（方便复制）
            const sel = window.getSelection();
            if (sel && sel.toString().length > 0) return;
            toggleImmersive();
        });
        // 顶栏/底栏自身被点击时，重置自动收起计时
        [document.getElementById('readerTop'), document.getElementById('readerBottom')].forEach(el => {
            if (!el) return;
            el.addEventListener('click', () => {
                if (!areBarsHidden()) {
                    clearTimeout(immersiveTimer);
                    immersiveTimer = setTimeout(() => setBarsHidden(true), 3000);
                }
            });
        });
        initJumpButtons();
    }
    // ==================== 悬浮跳顶/跳底 ====================
    function initJumpButtons() {
        const jump = document.getElementById('readerJump');
        if (!jump) return;
        const update = () => {
            const y = window.scrollY || document.documentElement.scrollTop || 0;
            jump.hidden = y < 300;
        };
        window.addEventListener('scroll', update, { passive: true });
        update();
    }
    function jumpToTop() {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
    function jumpToBottom() {
        window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' });
    }
    // ==================== 抽屉初始化 ====================
    function initSetDrawer() {
        // 背景主题色块
        document.querySelectorAll('#setThemes .set-theme').forEach(btn => {
            btn.addEventListener('click', () => {
                applyReaderTheme(btn.getAttribute('data-rt'));
            });
        });
        // 行高 / 段距滑条初值同步
        const lh = document.getElementById('setLineHeight');
        if (lh) {
            const v = parseFloat(lh.value) || 1.8;
            document.documentElement.style.setProperty('--reader-line-height', v);
            const el = document.getElementById('setLineHeightVal');
            if (el) el.textContent = v.toFixed(1);
        }
        const ps = document.getElementById('setParaSpacing');
        if (ps) {
            const v = parseFloat(ps.value);
            if (!isNaN(v)) {
                document.documentElement.style.setProperty('--reader-paragraph-spacing', v + 'rem');
                const el = document.getElementById('setParaSpacingVal');
                if (el) el.textContent = v.toFixed(1);
            }
        }
        // 字号数值同步
        syncSetDrawerSize(getCurrentFontSize());
        // 应用当前背景主题（服务端已渲染到 data 属性，这里只同步色块高亮 + 地址栏）
        const appData = document.getElementById('app-data')?.dataset || {};
        const theme = appData.readerTheme || localStorage.getItem('reader_theme') || 'default';
        applyReaderTheme(theme, { skipSave: true });
    }
    // ==================== 阅读偏好同步（服务端为权威，localStorage 仅兜底） ====================
    // 当阅读页已在后台标签页打开、用户在「我的阅读偏好」改了设置后切回，或收到
    // localStorage 变更事件时，自动从服务器重新拉取并应用，避免停留在旧的 localStorage 快照。
    let _serverPrefs = null;   // 从 /api/get_preferences 拉取的最新偏好（与 app-data dataset 同形状）
    let _refreshTimer = null;

    // 返回当前生效的偏好来源：优先用服务器拉取值，其次用首屏注入的 app-data，
    // 二者皆无（极旧页面）才回退 localStorage。
    function activePrefs() {
        if (_serverPrefs) return { data: _serverPrefs, present: true };
        const el = document.getElementById('app-data');
        return { data: el ? el.dataset : {}, present: !!el };
    }

    // 把后端返回的有效偏好映射成与 app-data dataset 同形状的键（驼峰），供 applySavedFontSettings 复用。
    function mapPrefsToDataset(eff) {
        const m = {};
        m.fontSize = (eff.font_size != null) ? String(eff.font_size) : '';
        m.fontFamily = eff.font_family || '';
        m.readerTheme = eff.reader_theme || 'default';
        FONT_SCOPES.forEach(scope => { m[SCOPE_APPKEY[scope]] = eff[scope + '_font_family'] || ''; });
        STYLE_SCOPES.forEach(scope => {
            const ak = STYLE_APPKEY[scope];
            m[ak.bold] = (eff[scope + '_bold'] != null) ? String(eff[scope + '_bold']) : '';
            m[ak.italic] = (eff[scope + '_italic'] != null) ? String(eff[scope + '_italic']) : '';
        });
        return m;
    }

    async function refreshPrefsFromServer() {
        try {
            const res = await fetch('/api/get_preferences');
            if (!res.ok) return;
            const data = await res.json();
            const eff = data.effective || data.overrides || data || {};
            _serverPrefs = mapPrefsToDataset(eff);
            applySavedFontSettings();
            applyReaderTheme(_serverPrefs.readerTheme || 'default', { skipSave: true });
        } catch (e) {
            console.error('拉取最新阅读偏好失败:', e);
        }
    }

    function scheduleRefreshPrefs() {
        if (_refreshTimer) clearTimeout(_refreshTimer);
        _refreshTimer = setTimeout(refreshPrefsFromServer, 150);
    }

    async function applySavedFontSettings() {
        const { data: appData, present: appPresent } = activePrefs();
        // 服务端/app-data 存在时以其为权威（空 = 跟随默认）；仅当二者皆无才回退 localStorage，
        // 彻底杜绝「在配置页改了、阅读页仍显示陈旧 localStorage 值」的问题。
        const finalSize = appPresent ? (appData.fontSize || '') : (localStorage.getItem('reader_font_size') || '');
        const finalBody = appPresent ? (appData.fontFamily || 'system-ui') : (localStorage.getItem('reader_font_family') || 'system-ui');
        // （各作用域字体统一在下方按 SCOPE 循环处理）

        // 字号
        if (finalSize) {
            const content = document.querySelector('.reading-content');
            if (content) content.style.setProperty('font-size', finalSize + 'px', 'important');
            highlightFontBtn(finalSize);
            syncSetDrawerSize(finalSize);
        }
        // 正文字体：应用到容器，正文行与引号/括号高亮 span 自然继承
        if (finalBody) {
            const content = document.getElementById('readingContent');
            if (content) content.style.setProperty('font-family', finalBody, 'important');
            const wrapper = document.querySelector('.reading-content');
            if (wrapper) wrapper.style.setProperty('font-family', finalBody, 'important');
        }
        // 标题 + reader-core 全部高亮类型：各自应用已保存字体（空 = 跟随正文/默认）
        const syncSel = (id, val) => { const s = document.getElementById(id); if (s && val) s.value = val; };
        FONT_SCOPES.forEach(scope => {
            const def = scope === 'title' ? TITLE_DEFAULT_FONT : '';
            // 服务端/app-data 存在时以其为准（空=跟随默认），不再被陈旧 localStorage 覆盖
            const val = appPresent ? (appData[SCOPE_APPKEY[scope]] || def)
                                   : (localStorage.getItem('reader_' + scope + '_font_family') || def);
            applyScopeFont(scope, val);
            syncSel(scopeSelectId(scope), val);
        });

        // 加粗 / 斜体：以配置为准（服务端合并的全局默认 + 管理员默认值 + 用户覆盖），
        // 始终注入内联 !important，作为唯一权威，不再依赖 reader.css 写死的字重/斜体。
        // 未显式设置时回退到配置默认值 DEFAULT_BOLD/false（而非 CSS），确保「管理员/默认设置」一定生效。
        STYLE_SCOPES.forEach(scope => {
            const ak = STYLE_APPKEY[scope];
            const appB = appData[ak.bold], lsB = localStorage.getItem('reader_' + scope + '_bold');
            const appI = appData[ak.italic], lsI = localStorage.getItem('reader_' + scope + '_italic');
            let bold, italic;
            if (appPresent) {
                const boldExplicit = hasVal(appB);
                bold = boldExplicit ? readBool(appB, null, DEFAULT_BOLD[scope]) : DEFAULT_BOLD[scope];
                const italicExplicit = hasVal(appI);
                italic = italicExplicit ? readBool(appI, null, false) : false;
            } else {
                const boldExplicit = lsB !== null;
                bold = boldExplicit ? readBool(null, lsB, DEFAULT_BOLD[scope]) : DEFAULT_BOLD[scope];
                const italicExplicit = lsI !== null;
                italic = italicExplicit ? readBool(null, lsI, false) : false;
            }
            applyScopeStyle(scope, 'bold', bold);
            applyScopeStyle(scope, 'italic', italic);
            // 按钮反映实际生效值（bold/italic 恒为配置值，不会为 null）
            syncStyleBtn(scope, 'bold', bold);
            syncStyleBtn(scope, 'italic', italic);
        });

        // 同步正文字体下拉
        syncSel('fontFamilySelect', finalBody);

        // 🔥 关键：删除首屏注入的 <style>
        document.getElementById('boot-reader-font')?.remove();
        document.getElementById('boot-reader-size')?.remove();
    }
    // ==================== 朗读功能 ====================
    let currentUtterance = null;
    let isPlaying = false;
    let currentPlayIndex = 0;
    let speechLines = [];
    function getCurrentPageText() {
        const lines = document.querySelectorAll('.content-line');
        const texts = [];
        lines.forEach(line => {
            const text = line.textContent || line.innerText;
            const trimmed = text.trim();
            if (trimmed.length > 0 && !/^[*＊—－~～……·•\-=]{3,}$/.test(trimmed) && trimmed.length > 1) {
                texts.push(trimmed);
            }
        });
        return texts;
    }
    function clearHighlightLine() {
        document.querySelectorAll('.content-line.speech-highlight').forEach(line => {
            line.classList.remove('speech-highlight');
        });
    }
    function highlightCurrentLine(index) {
        clearHighlightLine();
        if (index < 0 || index >= speechLines.length) return;
        const lines = document.querySelectorAll('.content-line');
        let lineIndex = 0;
        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            const text = (line.textContent || line.innerText).trim();
            if (text.length > 0 && !/^[*＊—－~～……·•\-=]{3,}$/.test(text) && text.length > 1) {
                if (lineIndex === index) {
                    line.classList.add('speech-highlight');
                    line.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    break;
                }
                lineIndex++;
            }
        }
    }
    function stopSpeech() {
        if (window.speechSynthesis) window.speechSynthesis.cancel();
        currentUtterance = null;
        isPlaying = false;
        currentPlayIndex = 0;
        speechLines = [];
        const speechBtn = document.getElementById('speechBtn');
        if (speechBtn) {
            // 图标是内联 SVG，由 .speaking 类切换显隐（见 reader.css）。
            // 这里只切类名和 title，绝不写 textContent/innerHTML —— 那会抹掉 SVG。
            speechBtn.title = '朗读本章';
            speechBtn.classList.remove('speaking');
        }
        clearHighlightLine();
    }
    function speakNextLine(rate, pitch) {
        if (!isPlaying || currentPlayIndex >= speechLines.length) {
            stopSpeech();
            return;
        }
        const text = speechLines[currentPlayIndex];
        if (!text || text.length === 0) {
            currentPlayIndex++;
            speakNextLine(rate, pitch);
            return;
        }
        highlightCurrentLine(currentPlayIndex);
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = rate;
        utterance.pitch = pitch;
        utterance.lang = 'zh-CN';
        if (window.speechSynthesis.getVoices) {
            const voices = window.speechSynthesis.getVoices();
            const chineseVoice = voices.find(v => v.lang.includes('zh-CN'));
            if (chineseVoice) utterance.voice = chineseVoice;
        }
        utterance.onend = () => {
            setTimeout(() => {
                if (isPlaying) {
                    currentPlayIndex++;
                    speakNextLine(rate, pitch);
                }
            }, 200);
        };
        utterance.onerror = () => {
            currentPlayIndex++;
            speakNextLine(rate, pitch);
        };
        currentUtterance = utterance;
        window.speechSynthesis.speak(utterance);
    }
    function speakCurrentPage() {
        if (!('speechSynthesis'in window)) {
            alert('您的浏览器不支持语音朗读功能');
            return;
        }
        if (isPlaying) { stopSpeech(); return; }
        speechLines = getCurrentPageText();
        if (speechLines.length === 0) {
            alert('当前页面没有可朗读的文本内容');
            return;
        }
        isPlaying = true;
        currentPlayIndex = 0;
        const speechBtn = document.getElementById('speechBtn');
        if (speechBtn) {
            speechBtn.title = '停止朗读';
            speechBtn.classList.add('speaking');
        }
        const rate = parseFloat(document.getElementById('speechRateSelect')?.value || '1.0');
        const pitch = parseFloat(document.getElementById('speechPitchSelect')?.value || '1.0');
        speakNextLine(rate, pitch);
    }
    async function initSpeech() {
        const speechBtn = document.getElementById('speechBtn');
        if (!speechBtn) return;
        let rate = localStorage.getItem('speech_rate') || '1.0';
        let pitch = localStorage.getItem('speech_pitch') || '1.0';
        try {
            const res = await fetch('/api/get_preferences');
            if (res.ok) {
                const prefs = await res.json();
                if (prefs.speech_rate) rate = prefs.speech_rate;
                if (prefs.speech_pitch) pitch = prefs.speech_pitch;
                localStorage.setItem('speech_rate', rate);
                localStorage.setItem('speech_pitch', pitch);
            }
        } catch (err) { console.error('加载朗读偏好失败:', err); }
        const rateSelect = document.getElementById('speechRateSelect');
        const pitchSelect = document.getElementById('speechPitchSelect');
        if (rateSelect) rateSelect.value = rate;
        if (pitchSelect) pitchSelect.value = pitch;
    }
    async function setSpeechRate(value) {
        localStorage.setItem('speech_rate', value);
        await savePreference('speech_rate', value);
    }
    async function setSpeechPitch(value) {
        localStorage.setItem('speech_pitch', value);
        await savePreference('speech_pitch', value);
    }
    // ==================== 行号跳转 ====================
    function jumpToLine(maxLine) {
        const input = document.getElementById('jumpLine');
        if (!input) return;
        let line = parseInt(input.value);
        if (isNaN(line) || line < 1) { alert('请输入有效的行号'); return; }
        if (line > maxLine) line = maxLine;
        window.location.href = '?line=' + line;
    }
    // ==================== 章节标题美化 ====================
    function styleChapterTitles() {
        const lines = document.querySelectorAll('.content-line');
        // 每个正则两个捕获组：1 = 章节号，2 = 标题
        // 注意：chapterPart 用捕获组，titlePart 用 (.*)
        const level1Pattern = /^\s*(第(?:\d+|[〇零一二三四五六七八九十百千万]+)[册集卷部]|[上下前后中终序][册集卷部])\s*[：:·\s]*(.*)$/;
        const level2Pattern = /^\s*(第(?:\d+|[〇零一二三四五六七八九十百千万]+)[篇章]|[上下前后中终序][篇章]|楔子|引子|引言|前言|正文|番外|序言|后记|尾声)\s*[：:·\s]*(.*)$/;
        const level3Pattern = /^\s*(第(?:\d+|[〇零一二三四五六七八九十百千万]+)[节回幕目]|[上下前后中终序][节回幕目])\s*[：:·\s]*(.*)$/;
        lines.forEach(line => {
            const originalText = line.textContent;
            const trimmedText = originalText.replace(/^[\s\u3000]+|[\s\u3000]+$/g, '');
            if (trimmedText.length === 0) return;
            // ===== 分隔符检测（分类识别）=====
            const textWithoutSpaces = trimmedText.replace(/[\s\u3000]/g, '');
            let separatorType = null;
            let separatorDisplay = '';
            // 0. 省略号类
            if (/^[…⋯]{2,}$/.test(textWithoutSpaces) || /^\.{3,}$/.test(textWithoutSpaces)) {
                separatorType = 'ellipsis';
                separatorDisplay = '……';
            }
            // 1. 点类
            else if (/^[○●◎·•]{2,}$/.test(textWithoutSpaces)) {
                separatorType = 'dot';
                separatorDisplay = '·  ·  ·  ·  ·  ·';
            }
            // 2. 星类
            else if (/^[＊*※◇♦♢★☆]{2,}$/.test(textWithoutSpaces)) {
                separatorType = 'star';
                separatorDisplay = '✦  ✦  ✦  ✦  ✦';
            }
            // 3. 线类
            else if (/^[~～—–─＝=_\-]{2,}$/.test(textWithoutSpaces)) {
                separatorType = 'line';
                separatorDisplay = '';
            }
            // 4. 花类
            else if (/^[♡♥☀☁☂✿❀🌸♪♫♩→←↑↓]{2,}$/.test(textWithoutSpaces)) {
                separatorType = 'flower';
                separatorDisplay = '✧  ✧  ✧  ✧  ✧';
            }
            // 5. 通用 fallback
            else {
                const separatorChars = '[○●◎\\.·•＊*◇♦♢★☆~～—–─＝=_\\-♡♥☀☁☂✿❀🌸♪♫♩→←↑↓]';
                if (new RegExp(`^${separatorChars}{2,}$`).test(textWithoutSpaces)) {
                    separatorType = 'dot';
                    separatorDisplay = '·  ·  ·  ·  ·  ·';
                }
            }
            if (separatorType) {
                line.className = 'content-line separator';
                line.setAttribute('data-type', separatorType);
                line.innerHTML = separatorDisplay;
                return;
            }
            // ===== 标题检测（判断等级 + 提取，一套正则搞定）=====
            let levelClass = '';
            let match = null;
            if ((match = trimmedText.match(level1Pattern))) {
                levelClass = 'chapter-title-level1';
            } else if ((match = trimmedText.match(level2Pattern))) {
                levelClass = 'chapter-title-level2';
            } else if ((match = trimmedText.match(level3Pattern))) {
                levelClass = 'chapter-title-level3';
            }
            if (levelClass && match) {
                line.className = `content-line ${levelClass}`;
                const chapterPart = (match[1] || '').trim();
                const titlePart = (match[2] || '').trim();
                if (chapterPart && titlePart) {
                    line.innerHTML = `<span class="chapter-number">${chapterPart}</span><br>${titlePart}`;
                } else if (chapterPart) {
                    line.innerHTML = `<span class="chapter-number">${chapterPart}</span>`;
                }
                // 如果只有标题没有章节号，保持原样即可
            }
        });
        // ===== 移动端居中 =====
        if (window.innerWidth <= 768) {
            document.querySelectorAll('.chapter-title-level1, .chapter-title-level2, .chapter-title-level3').forEach(title => {
                title.style.textAlign = 'center';
            });
            document.querySelectorAll('.separator').forEach(sep => {
                sep.style.textAlign = 'center';
                if (sep.getAttribute('data-type') === 'line' ||
                    sep.getAttribute('data-type') === 'equals') {
                    sep.style.display = 'block';
                    sep.style.width = '100%';
                }
            });
        }
    }
    // ==================== 图片错误处理 ====================
    function initImageErrorHandler() {
        const readingContent = document.getElementById('readingContent');
        if (!readingContent) return;
        readingContent.addEventListener('load', function(e) {
            const img = e.target;
            if (img.classList && img.classList.contains('inline-image')) {
                img.classList.add('loaded');
            }
        }, true);
        readingContent.addEventListener('error', function(e) {
            const img = e.target;
            if (!img.classList || !img.classList.contains('inline-image')) return;
            const imgId = img.getAttribute('data-img-id');
            if (!imgId) return;
            if (img.hasAttribute('data-retried')) {
                img.style.display = 'none';
                const placeholder = document.getElementById(imgId + '-placeholder');
                if (placeholder) placeholder.style.display = 'flex';
                return;
            }
            img.setAttribute('data-retried', 'true');
            setTimeout(() => {
                const src = img.src;
                img.src = src + (src.includes('?') ? '&' : '?') + '_t=' + Date.now();
            }, 500);
        }, true);
    }
    // ==================== 键盘快捷键 ====================
    function initKeyboardShortcuts() {
        document.addEventListener('keydown', function(e) {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA') return;
            // 设置抽屉打开时，只保留 Esc，避免误触翻页
            const setDrawer = document.getElementById('setDrawer');
            if (setDrawer && setDrawer.classList.contains('active')) {
                if (e.key === 'Escape') {
                    closeSetDrawer();
                    e.preventDefault();
                }
                return;
            }
            if (e.key === 'ArrowLeft') {
                // 底栏里同时有 <a> 和 <button>，用 class 精确定位翻页链接
                const prevBtn = document.querySelector('.bottom-bar .chapter-switch-btn:not(.disabled)');
                if (prevBtn && prevBtn.tagName === 'A') {
                    window.location.href = prevBtn.href;
                }
                e.preventDefault();
            }
            if (e.key === 'ArrowRight') {
                const links = document.querySelectorAll('.bottom-bar a.chapter-switch-btn');
                const nextBtn = links[links.length - 1];
                if (nextBtn) {
                    window.location.href = nextBtn.href;
                }
                e.preventDefault();
            }
            if (e.key === 'g' && !e.ctrlKey && !e.metaKey) {
                // 跳行输入框已收进设置抽屉：先打开抽屉，聚焦才有意义
                openSetDrawer();
                const jumpInput = document.getElementById('jumpLine');
                if (jumpInput) {
                    setTimeout(() => { jumpInput.focus(); jumpInput.select(); }, 320);
                }
                e.preventDefault();
            }
            if (e.key === 'Escape') {
                const active = document.activeElement;
                if (active && (active.tagName === 'INPUT' || active.tagName === 'SELECT')) {
                    active.blur();
                }
                closeSetDrawer();
                e.preventDefault();
            }
            if (typeof vibrate === 'function') {
                vibrate('light');
            }
        });
    }
    // ===== 暴露全局 API =====
    window.setFontSize = setFontSize;
    window.stepFontSize = stepFontSize;
    window.setFontFamily = setFontFamily;
    window.setLineHeight = setLineHeight;
    window.setParagraphSpacing = setParagraphSpacing;
    window.toggleIndent = toggleIndent;
    window.applyReaderTheme = applyReaderTheme;
    window.openSetDrawer = openSetDrawer;
    window.closeSetDrawer = closeSetDrawer;
    window.resetReaderSettings = resetReaderSettings;
    window.initSetDrawer = initSetDrawer;
    window.toggleImmersive = toggleImmersive;
    window.initImmersive = initImmersive;
    window.jumpToTop = jumpToTop;
    window.jumpToBottom = jumpToBottom;
    window.applySavedFontSettings = applySavedFontSettings;
    // 后台标签页里的阅读页：切回前台、或收到配置页清 localStorage 的 storage 事件时，
    // 自动从服务器重新同步阅读偏好（修复「在配置页改了、阅读页不生效」）。
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') scheduleRefreshPrefs();
    });
    window.addEventListener('storage', (e) => {
        if (e.key && e.key.indexOf('reader_') === 0) scheduleRefreshPrefs();
    });
    window.setScopeFont = setScopeFont;
    window.toggleScopeStyle = toggleScopeStyle;
    // 供阅读页初始化时调用：加载完成后主动从服务器拉一次最新偏好，
    // 覆盖可能被浏览器缓存的 app-data（修复「配置页改完、重新打开阅读页仍显示旧字体」）。
    window.refreshPrefsFromServer = refreshPrefsFromServer;
    window.applyScopeStyle = applyScopeStyle;
    window.speakCurrentPage = speakCurrentPage;
    window.stopSpeech = stopSpeech;
    window.initSpeech = initSpeech;
    window.setSpeechRate = setSpeechRate;
    window.setSpeechPitch = setSpeechPitch;
    window.jumpToLine = jumpToLine;
    window.styleChapterTitles = styleChapterTitles;
    window.initImageErrorHandler = initImageErrorHandler;
    window.initKeyboardShortcuts = initKeyboardShortcuts;
    // 按住拖动翻页：必须导出。reader-ui.js 是 IIFE，函数默认是局部的，
    // 模板里的 typeof initDragScroll === 'function' 判定的是全局，
    // 不导出就拿到 undefined —— 初始化根本不执行（抓手光标来自 CSS，
    // 所以光标变了但拖拽没生效，非常难排查）。
    window.initDragScroll = initDragScroll;
    window.toggleDragScroll = toggleDragScroll;
    window.toggleTextSelect = toggleTextSelect;
    window.isTextSelectOn = isTextSelectOn;
    console.log('✅ reader-ui.js 已加载');
})();
