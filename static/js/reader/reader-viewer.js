// ============================================
// reader-viewer.js - 图片查看器（增强版）
// 依赖：common.js, viewer.min.js
// 使用场景：novel_detail.html, read_chapter.html
// ============================================

(function() {
    'use strict';

    let viewerInstance = null;
    let currentContainer = null;
    let imageCount = 0;
    let isFullscreen = false;

    // ===== 配置选项 =====
    const DEFAULT_OPTIONS = {
        // 工具栏布局 - 完整版
        toolbar: {
            zoomIn: 4,
            zoomOut: 4,
            oneToOne: 4,
            reset: 4,
            prev: 4,
            play: 4,
            next: 4,
            rotateLeft: 4,
            rotateRight: 4,
            flipHorizontal: 4,
            flipVertical: 4,
        },
        // 导航栏缩略图
        navbar: true,
        // 标题显示
        title: true,
        // 工具提示（显示缩放比例）
        tooltip: true,
        // 可移动
        movable: true,
        // 可缩放
        zoomable: true,
        // 可旋转
        rotatable: true,
        // 可翻转
        scalable: true,
        // 过渡动画
        transition: true,
        // 全屏支持
        fullscreen: true,
        // 键盘快捷键
        keyboard: true,
        // 背景遮罩
        backdrop: true,
        // 加载动画
        loading: true,
        // 循环浏览
        loop: false,
        // 最小缩放比
        minZoomRatio: 0.01,
        // 最大缩放比
        maxZoomRatio: 100,
        // 缩放步进
        zoomRatio: 0.1,
        // 自动播放间隔（毫秒）
        interval: 3000,
        // 是否自动播放
        autoplay: false,
        // 点击切换放大
        toggleOnDblclick: true,
        // 鼠标滚轮缩放
        zoomOnWheel: true,
        // 触摸缩放
        zoomOnTouch: true,
        // 触摸旋转
        rotateOnTouch: true,
        // 触摸滑动切换
        slideOnTouch: true,
    };

    // ===== 核心初始化函数 =====
    function initViewerJS(containerSelector, options) {
        // 销毁旧实例
        if (viewerInstance) {
            destroyViewer();
        }

        const container = containerSelector 
            ? document.querySelector(containerSelector)
            : document.getElementById('readingContent') || document.querySelector('.intro-content');
        
        if (!container) {
            console.warn('⚠️ 未找到图片容器');
            return null;
        }

        // 查找所有图片
        const images = container.querySelectorAll('.local-image, .inline-image, img[data-viewer]');
        if (images.length === 0) {
            console.log('📷 没有找到可查看的图片');
            return null;
        }

        currentContainer = container;
        imageCount = images.length;

        // ===== 预处理图片 =====
        images.forEach((img, index) => {
            // 设置 alt
            if (!img.alt || img.alt === '') {
                const figure = img.closest('.local-image-figure');
                if (figure) {
                    const figcaption = figure.querySelector('.local-image-caption');
                    if (figcaption) {
                        img.alt = figcaption.textContent.trim();
                    }
                }
                if (!img.alt) {
                    const match = img.src.match(/name=([^&]+)/);
                    img.alt = match ? decodeURIComponent(match[1]) : `图片 ${index + 1}`;
                }
            }
            
            // 设置 data-original 用于高清图（如有需要）
            const dataOriginal = img.getAttribute('data-original');
            if (dataOriginal && !img.dataset.originalUrl) {
                img.dataset.originalUrl = dataOriginal;
            }

            // 添加点击查看器的事件（Viewer.js 会自动处理，但为了兼容）
            if (!img.hasAttribute('data-viewer')) {
                img.setAttribute('data-viewer', '');
            }
        });

        if (typeof Viewer === 'undefined') {
            console.warn('⚠️ Viewer.js 未加载');
            return null;
        }

        // ===== 合并选项 =====
        const mergedOptions = {
            ...DEFAULT_OPTIONS,
            ...options,
            // 自定义 URL 获取函数（支持 data-original）
            url: function(img) {
                return img.dataset.originalUrl || img.src;
            },
            // 图片加载完成后回调
            viewed: function(event) {
                if (typeof vibrate === 'function') vibrate('light');
                console.log(`👁️ 查看图片 #${event.detail.index + 1}/${imageCount}`);
                updateImageCounter(event.detail.index);
            },
            // 显示时回调
            shown: function() {
                console.log('📖 图片查看器已打开');
                document.body.classList.add('viewer-open');
                updateToolbarState();
            },
            // 隐藏时回调
            hidden: function() {
                console.log('📖 图片查看器已关闭');
                document.body.classList.remove('viewer-open');
            },
            // 缩放回调
            zoomed: function(event) {
                updateZoomInfo(event.detail.ratio);
            },
            // 旋转回调
            rotated: function(event) {
                console.log(`🔄 旋转: ${event.detail.degree}°`);
            },
        };

        // ===== 创建 Viewer 实例 =====
        try {
            viewerInstance = new Viewer(container, mergedOptions);
            
            // 额外功能：图片计数器
           // addImageCounter();
            
            // 额外功能：下载按钮
            addDownloadButton();
            
            // 额外功能：信息面板
            addInfoPanel();

            // 额外功能：全屏切换（浏览器全屏）
            addFullscreenToggle();

            // 键盘快捷键增强
            enhanceKeyboardShortcuts();

            console.log(`✅ Viewer.js 已启动，共 ${imageCount} 张图片`);
            return viewerInstance;
            
        } catch (error) {
            console.error('❌ Viewer.js 初始化失败:', error);
            return null;
        }
    }

    // ===== 图片计数器 =====
    function addImageCounter() {
        // 在查看器关闭后清理
        const style = document.createElement('style');
        style.id = 'viewer-counter-style';
        style.textContent = `
            .viewer-counter {
                position: fixed;
                bottom: 80px;
                left: 50%;
                transform: translateX(-50%);
                color: #fff;
                background: rgba(0,0,0,0.6);
                padding: 6px 16px;
                border-radius: 20px;
                font-size: 14px;
                z-index: 2016;
                opacity: 0;
                transition: opacity 0.3s ease;
                pointer-events: none;
                user-select: none;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            }
            .viewer-counter.show {
                opacity: 1;
            }
            .viewer-toolbar .viewer-download {
                background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/%3E%3Cpolyline points='7 10 12 15 17 10'/%3E%3Cline x1='12' y1='15' x2='12' y2='3'/%3E%3C/svg%3E");
                background-size: 60%;
                background-position: center;
                background-repeat: no-repeat;
            }
            .viewer-info {
                position: fixed;
                top: 20px;
                right: 20px;
                color: rgba(255,255,255,0.7);
                font-size: 12px;
                z-index: 2016;
                text-align: right;
                pointer-events: none;
                opacity: 0;
                transition: opacity 0.3s ease;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                line-height: 1.6;
                text-shadow: 0 1px 4px rgba(0,0,0,0.5);
            }
            .viewer-info.show {
                opacity: 1;
            }
            .viewer-info .info-filename {
                font-size: 14px;
                color: #fff;
            }
            .viewer-info .info-dimension {
                font-size: 12px;
                color: rgba(255,255,255,0.5);
            }
        `;
        document.head.appendChild(style);

        // 创建计数器元素
        let counter = document.getElementById('viewer-counter');
        if (!counter) {
            counter = document.createElement('div');
            counter.id = 'viewer-counter';
            counter.className = 'viewer-counter';
            counter.textContent = '1 / 1';
            document.body.appendChild(counter);
        }

        // 监听显示/隐藏
        const observer = new MutationObserver(() => {
            const viewer = document.querySelector('.viewer-container');
            if (viewer && viewer.style.display !== 'none' && !viewer.classList.contains('viewer-hide')) {
                counter.classList.add('show');
            } else {
                counter.classList.remove('show');
            }
        });
        observer.observe(document.body, { childList: true, subtree: true });
        window._viewerObserver = observer;
    }

    function updateImageCounter(index) {
        const counter = document.getElementById('viewer-counter');
        if (counter) {
            counter.textContent = `${index + 1} / ${imageCount}`;
            counter.classList.add('show');
            clearTimeout(counter._timeout);
            counter._timeout = setTimeout(() => {
                counter.classList.remove('show');
            }, 2000);
        }
    }

    // ===== 下载按钮 =====
    function addDownloadButton() {
        // 等待工具栏渲染
        setTimeout(() => {
            const toolbar = document.querySelector('.viewer-toolbar ul');
            if (!toolbar) return;

            // 检查是否已存在
            if (toolbar.querySelector('.viewer-download')) return;

            const li = document.createElement('li');
            li.className = 'viewer-download';
            li.setAttribute('role', 'button');
            li.setAttribute('tabindex', '0');
            li.setAttribute('aria-label', '下载图片');
            li.title = '下载图片 (D)';
            
            li.addEventListener('click', function(e) {
                e.stopPropagation();
                downloadCurrentImage();
            });
            
            li.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    downloadCurrentImage();
                }
            });

            // 插入到工具栏末尾
            toolbar.appendChild(li);
        }, 300);
    }

    function downloadCurrentImage() {
        if (!viewerInstance || !viewerInstance.image) return;

        const img = viewerInstance.image;
        const url = img.currentSrc || img.src;
        const filename = img.alt || 'image';
        
        // 使用 fetch 下载
        fetch(url)
            .then(response => response.blob())
            .then(blob => {
                const link = document.createElement('a');
                link.href = URL.createObjectURL(blob);
                link.download = `${filename}.${blob.type.split('/')[1] || 'jpg'}`;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                URL.revokeObjectURL(link.href);
            })
            .catch(() => {
                // fallback: 直接打开新窗口
                window.open(url, '_blank');
            });
    }

    // ===== 信息面板 =====
    function addInfoPanel() {
        let info = document.getElementById('viewer-info');
        if (!info) {
            info = document.createElement('div');
            info.id = 'viewer-info';
            info.className = 'viewer-info';
            info.innerHTML = `
                <div class="info-filename"></div>
                <div class="info-dimension"></div>
            `;
            document.body.appendChild(info);
        }

        // 在 viewed 事件中更新信息
        const originalViewed = DEFAULT_OPTIONS.viewed;
        DEFAULT_OPTIONS.viewed = function(event) {
            if (originalViewed) originalViewed(event);
            const img = event.detail.image;
            const info = document.getElementById('viewer-info');
            if (info) {
                const filename = info.querySelector('.info-filename');
                const dimension = info.querySelector('.info-dimension');
                if (filename) filename.textContent = img.alt || '图片';
                if (dimension) dimension.textContent = `${img.naturalWidth} × ${img.naturalHeight}`;
                info.classList.add('show');
                clearTimeout(info._timeout);
                info._timeout = setTimeout(() => {
                    info.classList.remove('show');
                }, 3000);
            }
        };
    }

    // ===== 全屏切换 =====
    function addFullscreenToggle() {
        document.addEventListener('keydown', function(e) {
            // 必须排除修饰键：否则 Ctrl+F（浏览器查找）/ Cmd+F 会被这里抢走
            if (e.ctrlKey || e.metaKey || e.altKey) return;
            if (e.key === 'f' || e.key === 'F') {
                const viewer = document.querySelector('.viewer-container');
                if (viewer && viewer.style.display !== 'none' && !viewer.classList.contains('viewer-hide')) {
                    e.preventDefault();
                    toggleFullscreen();
                }
            }
        });

        // 添加工具栏按钮
        setTimeout(() => {
            const toolbar = document.querySelector('.viewer-toolbar ul');
            if (!toolbar) return;
            if (toolbar.querySelector('.viewer-fullscreen')) return;

            const li = document.createElement('li');
            li.className = 'viewer-fullscreen';
            li.setAttribute('role', 'button');
            li.setAttribute('tabindex', '0');
            li.setAttribute('aria-label', '全屏');
            li.title = '全屏 (F)';
            li.style.backgroundImage = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='15 3 21 3 21 9'/%3E%3Cpolyline points='9 21 3 21 3 15'/%3E%3Cline x1='21' y1='3' x2='14' y2='10'/%3E%3Cline x1='3' y1='21' x2='10' y2='14'/%3E%3C/svg%3E")`;
            li.style.backgroundSize = '60%';
            li.style.backgroundPosition = 'center';
            li.style.backgroundRepeat = 'no-repeat';

            li.addEventListener('click', function(e) {
                e.stopPropagation();
                toggleFullscreen();
            });

            toolbar.appendChild(li);
        }, 500);
    }

    function toggleFullscreen() {
        const viewer = document.querySelector('.viewer-container');
        if (!viewer) return;

        if (!document.fullscreenElement) {
            viewer.requestFullscreen?.() || 
            viewer.webkitRequestFullscreen?.() || 
            viewer.msRequestFullscreen?.();
            isFullscreen = true;
        } else {
            document.exitFullscreen?.() || 
            document.webkitExitFullscreen?.() || 
            document.msExitFullscreen?.();
            isFullscreen = false;
        }
    }

    // ===== 键盘快捷键增强 =====
    function enhanceKeyboardShortcuts() {
        document.addEventListener('keydown', function(e) {
            const viewer = document.querySelector('.viewer-container');
            if (!viewer || viewer.style.display === 'none' || viewer.classList.contains('viewer-hide')) return;

            // R - 重置
            if (e.key === 'r' || e.key === 'R') {
                e.preventDefault();
                if (viewerInstance) viewerInstance.reset();
            }
            
            // 1 - 缩放到 100%
            if (e.key === '1') {
                e.preventDefault();
                if (viewerInstance) viewerInstance.zoomTo(1, true);
            }

            // Space - 播放/暂停
            if (e.key === ' ' && !e.target.matches('input, textarea, button')) {
                e.preventDefault();
                if (viewerInstance) {
                    viewerInstance.played ? viewerInstance.stop() : viewerInstance.play();
                }
            }

            // O - 旋转 90°
            if (e.key === 'o' || e.key === 'O') {
                e.preventDefault();
                if (viewerInstance) viewerInstance.rotate(90);
            }

            // Shift+O - 逆时针旋转 90°
            if (e.key === 'O' && e.shiftKey) {
                e.preventDefault();
                if (viewerInstance) viewerInstance.rotate(-90);
            }
        });
    }

    // ===== 更新工具栏状态 =====
    function updateToolbarState() {
        // 可在此添加播放状态等更新
    }

    // ===== 更新缩放信息 =====
    function updateZoomInfo(ratio) {
        // 可在此添加缩放百分比显示
    }

    // ===== 刷新查看器 =====
    function refreshViewer(options) {
        if (viewerInstance) {
            const container = currentContainer;
            destroyViewer();
            return initViewerJS(container, options);
        }
        return initViewerJS(currentContainer, options);
    }

    // ===== 销毁查看器 =====
    function destroyViewer() {
        if (viewerInstance) {
            try {
                viewerInstance.destroy();
            } catch (e) {
                console.warn('销毁查看器时出错:', e);
            }
            viewerInstance = null;
        }
        
        // 清理 DOM 元素
        ['viewer-counter', 'viewer-info'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.remove();
        });
        
        const style = document.getElementById('viewer-counter-style');
        if (style) style.remove();

        if (window._viewerObserver) {
            window._viewerObserver.disconnect();
            window._viewerObserver = null;
        }

        document.body.classList.remove('viewer-open');
        console.log('🗑️ Viewer.js 已销毁');
    }

    // ===== 获取实例 =====
    function getViewerInstance() {
        return viewerInstance;
    }

    // ===== 获取当前图片信息 =====
    function getCurrentImageInfo() {
        if (!viewerInstance || !viewerInstance.image) return null;
        const img = viewerInstance.image;
        return {
            index: viewerInstance.index,
            total: imageCount,
            url: img.currentSrc || img.src,
            alt: img.alt || '图片',
            width: img.naturalWidth,
            height: img.naturalHeight,
            ratio: viewerInstance.imageData?.ratio || 1,
            rotate: viewerInstance.imageData?.rotate || 0,
            scaleX: viewerInstance.imageData?.scaleX || 1,
            scaleY: viewerInstance.imageData?.scaleY || 1,
        };
    }

    // ===== 跳到指定图片 =====
    function viewImage(index) {
        if (!viewerInstance) return;
        const idx = Math.max(0, Math.min(index, imageCount - 1));
        viewerInstance.view(idx);
    }

    // ===== 切换到下一张 =====
    function nextImage() {
        if (viewerInstance) viewerInstance.next();
    }

    // ===== 切换到上一张 =====
    function prevImage() {
        if (viewerInstance) viewerInstance.prev();
    }

    // ===== 重置所有变换 =====
    function resetImage() {
        if (viewerInstance) viewerInstance.reset();
    }

    // ===== 放大 =====
    function zoomIn(ratio) {
        if (viewerInstance) viewerInstance.zoom(ratio || 0.1, true);
    }

    // ===== 缩小 =====
    function zoomOut(ratio) {
        if (viewerInstance) viewerInstance.zoom(-(ratio || 0.1), true);
    }

    // ===== 旋转 =====
    function rotateImage(degrees) {
        if (viewerInstance) viewerInstance.rotate(degrees);
    }

    // ===== 水平翻转 =====
    function flipHorizontal() {
        if (viewerInstance && viewerInstance.imageData) {
            const scaleX = -(viewerInstance.imageData.scaleX || 1);
            viewerInstance.scaleX(scaleX);
        }
    }

    // ===== 垂直翻转 =====
    function flipVertical() {
        if (viewerInstance && viewerInstance.imageData) {
            const scaleY = -(viewerInstance.imageData.scaleY || 1);
            viewerInstance.scaleY(scaleY);
        }
    }

    // ===== 自动播放切换 =====
    function togglePlay() {
        if (!viewerInstance) return;
        if (viewerInstance.played) {
            viewerInstance.stop();
        } else {
            viewerInstance.play();
        }
    }

    // ===== 导出 =====
    window.initViewerJS = initViewerJS;
    window.refreshViewer = refreshViewer;
    window.destroyViewer = destroyViewer;
    window.getViewerInstance = getViewerInstance;
    window.getCurrentImageInfo = getCurrentImageInfo;
    window.viewImage = viewImage;
    window.nextImage = nextImage;
    window.prevImage = prevImage;
    window.resetImage = resetImage;
    window.zoomIn = zoomIn;
    window.zoomOut = zoomOut;
    window.rotateImage = rotateImage;
    window.flipHorizontal = flipHorizontal;
    window.flipVertical = flipVertical;
    window.togglePlay = togglePlay;

    console.log('✅ reader-viewer.js (增强版) 已加载');
    console.log('📖 快捷键: [F]全屏 [R]重置 [1]100% [Space]播放 [O]旋转');
    console.log('📖 点击图片查看器左侧/右侧翻页');

})();