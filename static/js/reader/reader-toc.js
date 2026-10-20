// ============================================
// reader-toc.js - 阅读页目录抽屉
// 依赖：common.js
// 使用场景：read_chapter.html
// ============================================

(function () {
    'use strict';

    let drawerEl = null;
    let maskEl = null;
    let bodyEl = null;
    let isOpen = false;

    // ===== 打开 =====
    function openTocDrawer() {
        if (typeof vibrate === 'function') vibrate('light');
        if (!drawerEl) return;
        isOpen = true;
        drawerEl.classList.add('active');
        maskEl.classList.add('active');
        document.body.style.overflow = 'hidden';  // 防止背景滚动

        // 打开时自动滚动到当前章节
        scrollToCurrent();

        console.log('📑 目录抽屉已打开');
    }

    // ===== 关闭 =====
    function closeTocDrawer() {
        if (typeof vibrate === 'function') vibrate('light');
        if (!drawerEl) return;
        isOpen = false;
        drawerEl.classList.remove('active');
        maskEl.classList.remove('active');
        document.body.style.overflow = '';
        console.log('📑 目录抽屉已关闭');
    }

    // ===== 高亮 + 滚动到当前章节 =====
    function scrollToCurrent() {
        if (!bodyEl) return;

        // 从 app-data 读取当前章节行号（由模板渲染到 data 属性）
        const appData = document.getElementById('app-data');
        const currentLine = parseInt(appData?.dataset.currentLine) || 0;
        if (currentLine <= 0) return;

        const items = bodyEl.querySelectorAll('.toc-item');
        let target = null;
        for (const item of items) {
            const line = parseInt(item.dataset.line) || 0;
            if (line <= currentLine) {
                target = item;
            } else {
                break;
            }
        }

        if (target) {
            // 先清除可能存在的旧高亮
            bodyEl.querySelectorAll('.toc-item.current').forEach(el => {
                el.classList.remove('current');
            });

            target.classList.add('current');
            // 等抽屉动画结束再滚
            setTimeout(() => {
                target.scrollIntoView({ block: 'center', behavior: 'auto' });
            }, 280);
        }
    }

    // ===== 初始化 =====
    function initTocDrawer() {
        drawerEl = document.getElementById('tocDrawer');
        maskEl = document.getElementById('tocDrawerMask');
        bodyEl = document.getElementById('tocDrawerBody');

        if (!drawerEl || !maskEl || !bodyEl) {
            console.warn('⚠️ 目录抽屉元素缺失，跳过初始化');
            return;
        }

        // 点击章节后自动关闭抽屉（不加延迟，让浏览器先处理跳转）
        // 注意：空章节是不可点击的 <span>，不参与关闭逻辑
        bodyEl.querySelectorAll('a.toc-item').forEach(item => {
            item.addEventListener('click', () => {
                // 浏览器会跳转，抽屉关闭只是视觉上的
                closeTocDrawer();
            });
        });

        // 键盘：Esc 关闭
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && isOpen) {
                e.preventDefault();
                closeTocDrawer();
            }
        });

        console.log('✅ 目录抽屉已就绪，共 ' + bodyEl.querySelectorAll('.toc-item').length + '章');
    }

    // ===== 暴露全局 =====
    window.openTocDrawer = openTocDrawer;
    window.closeTocDrawer = closeTocDrawer;
    window.initTocDrawer = initTocDrawer;

    console.log('✅ reader-toc.js 已加载');
})();