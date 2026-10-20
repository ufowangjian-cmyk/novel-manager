// ============================================
// reader-init.js - 阅读器初始化入口
// 依赖：reader-core.js, reader-viewer.js, reader-ui.js
// 使用场景：read_chapter.html
// ============================================

(function() {
    'use strict';

    async function initReader() {
        console.log('📖 初始化阅读器...');

        // 1. 检测设备类型
        const isMobile = window.innerWidth <= 768;
        const defaultSize = isMobile ? '20' : '24';
        let savedSize = localStorage.getItem('reader_font_size') || defaultSize;
        setFontSize(savedSize);
        highlightFontBtn(savedSize);

        // 2. 应用字体设置
        applySavedFontSettings();

        // 3. 初始化配图路径（使用全局 filePath）
        if (typeof filePath !== 'undefined' && filePath && typeof initLocalImagesAsync === 'function') {
            await initLocalImagesAsync(filePath);
        }

        // 4. 加载表情映射
        if (typeof loadEmojiMapping === 'function') {
            await loadEmojiMapping();
        }

        // 5. 转换内容
        if (typeof convertAllContent === 'function') {
            convertAllContent();
        }

        // 6. 章节标题美化
        if (typeof styleChapterTitles === 'function') {
            styleChapterTitles();
        }

        // 7. 图片查看器
        if (typeof initViewerJS === 'function') {
            setTimeout(() => initViewerJS('#readingContent'), 300);
        }

        // 8. 朗读
        if (typeof initSpeech === 'function') {
            initSpeech();
        }

        // 9. 图片错误处理
        if (typeof initImageErrorHandler === 'function') {
            initImageErrorHandler();
        }

        // 10. 键盘快捷键
        if (typeof initKeyboardShortcuts === 'function') {
            initKeyboardShortcuts();
        }

        console.log('✅ 阅读器初始化完成');
    }

    window.initReader = initReader;
    console.log('✅ reader-init.js 已加载');
})();