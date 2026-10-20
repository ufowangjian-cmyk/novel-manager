// ==================== common.js - 公共函数库 ====================
// 所有页面共享的工具函数，避免重复定义

// ===== 图标（Lucide sprite）=====
// 与 templates/_icons.html 的 Jinja 宏保持一致的输出结构。
// 用法：icon('search')            -> <svg class="ic" ...><use href="/static/icons.svg#ic-search"></use></svg>
//      icon('trash-2', 'lg')     -> 20px
//      icon('x', 'sm', 'ic--danger')
// 注意：图标清单见 /static/icons.svg（由 _sprite_build.py 生成）
function icon(name, size, cls) {
    const sizeCls = size ? ' ic--' + size : '';
    const extra = cls ? ' ' + cls : '';
    return '<svg class="ic' + sizeCls + extra + '" aria-hidden="true">' +
           '<use href="/static/icons.svg#ic-' + name + '"></use></svg>';
}
window.icon = icon;

// ===== 主题管理 =====
function getSystemTheme() {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

async function getEffectiveTheme() {
    try {
        const response = await fetch('/config/get');
        const config = await response.json();
        let theme = config.theme || 'dark';
        if (theme === 'auto') {
            theme = getSystemTheme();
        }
        return theme;
    } catch (err) {
        console.error('获取主题配置失败:', err);
        return getSystemTheme();
    }
}

function applyThemeToPage(theme) {
    const root = document.documentElement;
    const body = document.body;

    // 更新 theme-color
    let themeColorMeta = document.querySelector('meta[name="theme-color"]');
    if (!themeColorMeta) {
        themeColorMeta = document.createElement('meta');
        themeColorMeta.name = 'theme-color';
        document.head.appendChild(themeColorMeta);
    }
    themeColorMeta.content = theme === 'light' ? '#ffffff' : '#131a12';

    // 动态切换 manifest（关键：让 Android PWA 状态栏跟随）
    const manifestLink = document.querySelector('link[rel="manifest"]');
    if (manifestLink) {
        // 加时间戳强制浏览器重新拉取
        // 只在主题变化时换 href：原来每次应用主题都拼 Date.now()，
        // 等于每次跳页都完整重下 manifest，浏览器缓存完全失效。
        const desired = `/manifest.json?theme=${theme}`;
        if (manifestLink.getAttribute('href') !== desired) {
            manifestLink.href = desired;
        }
    }

    if (theme === 'light') {
        root.classList.remove('dark-mode');
        if (body) body.classList.remove('dark-mode');
    } else {
        root.classList.add('dark-mode');
        if (body) body.classList.add('dark-mode');
    }
}

async function applyTheme() {
    const theme = await getEffectiveTheme();
    applyThemeToPage(theme);
    localStorage.setItem('theme', theme);
}

function watchSystemTheme() {
    const darkModeQuery = window.matchMedia('(prefers-color-scheme: dark)');

    const handleChange = async (e) => {
        try {
            const response = await fetch('/config/get');
            const config = await response.json();

            if (config.theme === 'auto') {
                const newTheme = e.matches ? 'dark' : 'light';
                applyThemeToPage(newTheme);
                localStorage.setItem('theme', newTheme);
            }
        } catch (err) {
            console.error('检查主题配置失败:', err);
        }
    };

    if (darkModeQuery.addEventListener) {
        darkModeQuery.addEventListener('change', handleChange);
    } else {
        darkModeQuery.addListener(handleChange);
    }
}

// 检查从配置页面返回时是否需要刷新主题
function checkThemeOnReturn() {
    if (window.location.search.includes('theme_updated=1')) {
        applyTheme();
        history.replaceState({}, '', window.location.pathname);
    }
}

// 监听 storage 变化（多标签页同步）
function watchThemeStorage() {
    window.addEventListener('storage', (e) => {
        if (e.key === 'theme') {
            fetch('/config/get')
                .then(res => res.json())
                .then(config => {
                    if (config.theme === 'auto') {
                        applyThemeToPage(getSystemTheme());
                    } else {
                        applyThemeToPage(e.newValue || 'dark');
                    }
                })
                .catch(() => {
                    applyThemeToPage(e.newValue || 'dark');
                });
        }
    });
}


// ===== 通知系统 =====
function showNotification(message, type = 'info') {
    let container = document.getElementById('notificationContainer');
    if (!container) {
        container = document.createElement('div');
        container.id = 'notificationContainer';
        container.className = 'notification-container';
        document.body.appendChild(container);

        // 注入通知样式（如果还没有）
        if (!document.getElementById('notificationStyles')) {
            const style = document.createElement('style');
            style.id = 'notificationStyles';
            style.textContent = `
                .notification-container {
                    position: fixed;
                    top: 20px;
                    right: 20px;
                    z-index: 9999;
                    max-width: 90vw;
                }
                .notification {
                    padding: 12px 24px;
                    border-radius: 8px;
                    margin-bottom: 10px;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.15);
                    animation: notificationSlideIn 0.3s ease;
                    cursor: pointer;
                    color: white;
                    font-size: 14px;
                    backdrop-filter: blur(10px);
                    -webkit-backdrop-filter: blur(10px);
                    border: 1px solid rgba(255,255,255,0.2);
                }
                .notification.success {
                    background: rgba(72, 187, 120, 0.85);
                }
                .notification.error {
                    background: rgba(245, 101, 101, 0.85);
                }
                .notification.warning {
                    background: rgba(237, 137, 54, 0.85);
                }
                .notification.info {
                    background: rgba(66, 153, 225, 0.85);
                }

                @keyframes notificationSlideIn {
                    from { transform: translateX(100%); opacity: 0; }
                    to { transform: translateX(0); opacity: 1; }
                }
                @keyframes notificationSlideOut {
                    from { transform: translateX(0); opacity: 1; }
                    to { transform: translateX(100%); opacity: 0; }
                }
                .notification.slide-out {
                    animation: notificationSlideOut 0.3s ease;
                }
            `;
            document.head.appendChild(style);
        }
    }

    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.innerHTML = message;
    notification.onclick = () => {
        notification.classList.add('slide-out');
        setTimeout(() => notification.remove(), 300);
    };

    container.appendChild(notification);

    setTimeout(() => {
        if (notification.parentNode) {
            notification.classList.add('slide-out');
            setTimeout(() => notification.remove(), 300);
        }
    }, 4000);
}


// ===== 加载遮罩 =====
function showLoading(show) {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) {
        overlay.style.display = show ? 'flex' : 'none';
    }
}


// ===== 防抖函数 =====
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func.apply(this, args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}


// ===== HTML 转义 =====
function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}


// ===== 格式化时间 =====
function formatTime(seconds) {
    if (seconds < 0) seconds = 0;
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}


// ===== 获取当前 URL 参数 =====
function getCurrentParams() {
    const params = new URLSearchParams(window.location.search);
    ['author', 'tag', 'site', 'page'].forEach(key => params.delete(key));
    return params.toString();
}


// ===== 头部背景图（每次加载页面随机换一张，不做定时轮播） =====
let bgCachedImages = null;
let bgCurrentImageIndex = -1;
let bgIsTransitioning = false;
let bgInitialized = false;
let bgPreloaded = new Set();

// 已成功加载过的背景图 URL 记在 localStorage：换图随机时优先挑
// 「确定已经在浏览器缓存里」的图，避免随机跳到一张还没下过的图现场下载。
const BG_LOADED_KEY = 'headerBgLoadedUrls';

function getKnownLoadedUrls() {
    try {
        const raw = localStorage.getItem(BG_LOADED_KEY);
        if (!raw) return new Set();
        const arr = JSON.parse(raw);
        return Array.isArray(arr) ? new Set(arr) : new Set();
    } catch (e) {
        return new Set();  // 隐私模式 / 存储被禁
    }
}

function markUrlLoaded(url) {
    try {
        const set = getKnownLoadedUrls();
        if (set.has(url)) return;
        set.add(url);
        // 只保留最近 300 条，防止无限增长
        localStorage.setItem(BG_LOADED_KEY, JSON.stringify(Array.from(set).slice(-300)));
    } catch (e) { /* 记不了不影响功能 */ }
}

function getHeaderImages() {
    const images = [];
    for (let i = 1; i <= 50; i++) {
        images.push(`/static/images/header-bg-${i}.webp`);
    }
    return images;
}

// 图片清单来源（按优先级）：
//   1. base.html 的 head 输出的 window.HEADER_BG_IMAGES
//      （后端 context_processor 注入，所有页面都有，含详情页）
//   2. /api/header_bg_images 轻量接口（一次请求）
//   3. 静态推断清单 header-bg-1..50（不探测，缺图由加载失败兜底）
// 曾经的兜底是「new Image() 逐张探测」——50 张全下完（约 11.7MB）才显示
// 第一张，详情页等没输出清单的页面首屏要等半分钟，已废除。
async function getExistingHeaderImages() {
    const provided = Array.isArray(window.HEADER_BG_IMAGES) ? window.HEADER_BG_IMAGES : [];
    if (provided.length > 0) {
        return provided;
    }
    try {
        const resp = await fetch('/api/header_bg_images');
        if (resp.ok) {
            const data = await resp.json();
            if (Array.isArray(data.images) && data.images.length > 0) {
                return data.images;
            }
        }
    } catch (e) { /* 落到静态清单 */ }
    return getHeaderImages();
}

function getBackgroundContainer(header) {
    let container = header.querySelector('.header-bg-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'header-bg-container';
        container.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            overflow: hidden;
            z-index: 0;
            border-radius: 15px;
        `;

        const bg1 = document.createElement('div');
        const bg2 = document.createElement('div');
        bg1.className = 'header-bg-layer header-bg-layer-1';
        bg2.className = 'header-bg-layer header-bg-layer-2';
        bg1.style.cssText = bg2.style.cssText = `
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
            transition: opacity 1.2s ease-in-out;
            opacity: 0;
            border-radius: 15px;
        `;

        container.appendChild(bg1);
        container.appendChild(bg2);

        if (getComputedStyle(header).position === 'static') {
            header.style.position = 'relative';
        }

        header.style.borderRadius = '15px';
        // ⚠️ 不要给 header 设 overflow:hidden（历史上设过，已移除）：
        // 背景圆角裁剪由上面的 .header-bg-container 自己负责
        // （它自带 overflow:hidden + border-radius，100% 覆盖 header）。
        // header 级裁剪会把溢出头部的内容切掉——典型受害者是主页右上角的
        // 用户抽屉下拉菜单（.user-menu-dropdown 绝对定位在头部下方弹出，
        // 被裁得只剩头部里那一小截）。添加任何头部悬浮层时留意这条。

        header.insertBefore(container, header.firstChild);

        header.bgLayers = {
            container: container,
            layer1: bg1,
            layer2: bg2,
            activeLayer: 1
        };
    }
    return header.bgLayers;
}

// instant=true 用于首图：没有前一张可过渡，1.2s 淡入纯属感知延迟，直接显示。
async function fadeInBackground(layers, imageUrl, targetLayer, instant = false) {
    return new Promise((resolve) => {
        const img = new Image();
        img.onload = () => {
            markUrlLoaded(imageUrl);
            targetLayer.style.backgroundImage = `url('${imageUrl}')`;
            if (instant) {
                targetLayer.style.transition = 'none';
                targetLayer.style.opacity = '1';
                requestAnimationFrame(() => requestAnimationFrame(() => {
                    targetLayer.style.transition = '';
                }));
                resolve();
                return;
            }
            setTimeout(() => {
                targetLayer.style.opacity = '1';
                setTimeout(resolve, 1200);
            }, 50);
        };
        img.onerror = () => {
            console.error(`图片加载失败: ${imageUrl}`);
            resolve();
        };
        img.src = imageUrl;
    });
}

async function switchBackground(layers, newImageUrl) {
    if (bgIsTransitioning) return;
    bgIsTransitioning = true;

    const activeLayer = layers.activeLayer === 1 ? layers.layer1 : layers.layer2;
    const inactiveLayer = layers.activeLayer === 1 ? layers.layer2 : layers.layer1;

    const img = new Image();
    img.onload = () => {
        markUrlLoaded(newImageUrl);
        inactiveLayer.style.backgroundImage = `url('${newImageUrl}')`;
        inactiveLayer.style.opacity = '0';

        void inactiveLayer.offsetHeight;

        activeLayer.style.opacity = '0';
        inactiveLayer.style.opacity = '1';

        layers.activeLayer = layers.activeLayer === 1 ? 2 : 1;

        setTimeout(() => {
            bgIsTransitioning = false;
        }, 1200);
    };
    img.onerror = () => {
        console.error(`图片加载失败: ${newImageUrl}`);
        bgIsTransitioning = false;
    };
    img.src = newImageUrl;
}

// 挑下一张：**优先从「已预热 / 历史已加载」的池子里选**。
// 弱网不卡的关键 —— 随机到还没下完的图时，切换那一刻才现场下载，
// 用户看到的就是空白或半张图。两个池子都空了才退回全量随机。
function getNextRandomImage(images) {
    if (images.length === 0) return null;
    if (images.length === 1) return images[0];

    const known = getKnownLoadedUrls();
    // 候选池：已预热 或 历史加载过（大概率已在浏览器缓存里），且不是当前这张
    const ready = images.filter((u, i) => (bgPreloaded.has(u) || known.has(u)) && i !== bgCurrentImageIndex);
    const pool = ready.length > 0 ? ready : images;

    let newIndex;
    if (pool.length === 1) {
        newIndex = images.indexOf(pool[0]);
    } else {
        do {
            newIndex = images.indexOf(pool[Math.floor(Math.random() * pool.length)]);
        } while (newIndex === bgCurrentImageIndex && pool.length > 1);
    }

    bgCurrentImageIndex = newIndex;
    return images[bgCurrentImageIndex];
}

// 串行预热：一张一张下载，不并发占满连接。
// 全部图片都已加载过（localStorage 有记录）时直接跳过，
// 避免每次跳页都做 50 次无谓的缓存往返。
function preloadInBackground(images) {
    const known = getKnownLoadedUrls();
    const pending = images.filter(u => !known.has(u));
    if (pending.length === 0) return new Set();

    let i = 0;
    const total = pending.length;
    const loaded = new Set();

    function next() {
        if (i >= total) return;
        const url = pending[i++];
        const img = new Image();
        img.onload = function () {
            loaded.add(url);
            markUrlLoaded(url);
            // 下一张；延后一点让出主线程，避免卡住页面交互
            setTimeout(next, 120);
        };
        img.onerror = function () {
            loaded.add(url);
            setTimeout(next, 120);
        };
        img.src = url;
    }

    next();
    return loaded;
}

// 应用头部背景图。
//
// 换图策略（剑哥 17:11 定）：
//   - **不做定时轮播**。原来每 8 秒主动换一张，即使你没在滚动页面
//     也在不停下载新图，白占带宽 —— 外网下会把带宽吃满。
//   - **每次刷新/跳页随机换一张**（被动换图）。图片本身走浏览器缓存，
//     不会重复下载同一张；加上后端给 static 加的 30 天长缓存，
//     换图只发生「每页第一次」，之后怎么刷都是瞬显。
async function setRandomHeaderBg(options = {}) {
    const { initialOnly = false } = options;

    if (bgInitialized) return;
    bgInitialized = true;

    const header = document.querySelector('.header');
    if (!header) return;

    try {
        if (!bgCachedImages) {
            bgCachedImages = await getExistingHeaderImages();
        }

        if (bgCachedImages && bgCachedImages.length > 0) {
            const layers = getBackgroundContainer(header);

            // 每次加载页面随机取一张（优先已缓存/已预热池，首图与当前显示的重复则顺延一位）
            const randomImage = getNextRandomImage(bgCachedImages);
            if (!randomImage) return;

            layers.activeLayer = 1;
            // 首图直显：缓存命中时不应再被 1.2s 淡入拖慢感知
            await fadeInBackground(layers, randomImage, layers.layer1, true);
            console.log(`已应用背景图片: ${randomImage}`);

            // 后台串行预热其余图片：下次刷新时几乎全在缓存里，切换瞬显。
            // 不并发、不阻塞首屏，也不做任何自动切换。
            // 手机流量/省流模式（base.html 设的 window.LOW_NETWORK）跳过：
            // 50 张共 11.7MB，弱网下后台下载会拖垮同期的一切操作。
            if (!window.LOW_NETWORK) {
                bgPreloaded = preloadInBackground(bgCachedImages);
            }
        } else {
            console.log('未找到header背景图片');
            header.style.background = 'var(--color-primary-dark)';
        }
    } catch (error) {
        console.error('设置背景图片失败:', error);
    }
}

async function nextBackground() {
    const header = document.querySelector('.header');
    if (!header || !bgCachedImages || bgCachedImages.length === 0) return;

    const layers = getBackgroundContainer(header);
    const nextImage = getNextRandomImage(bgCachedImages);
    if (nextImage) {
        await switchBackground(layers, nextImage);
    }
}

async function prevBackground() {
    await nextBackground();
}


// ===== 初始化公共功能 =====
// ==================== 内置字体预热 ====================
// BUILTIN_FONTS：内置字体清单。key = font.css 里 @font-face 注册的 family 名，
// url = woff2 地址（与 font.css 保持一致），size = 单文件体积（提示文案用）。
// 原定义在 reader-ui.js（仅阅读页可用），现提升至此供全站预热共用；
// reader-ui.js 改为引用本全局。新增内置字体时改这里 + font.css + 两个模板的字体下拉。
window.BUILTIN_FONTS = {
    '霞鹜文楷内置': { url: '/static/fonts/LXGWWenKaiMono-Medium.woff2', size: '8.6 MB', label: '霞鹜文楷' },
    '仓耳今楷内置': { url: '/static/fonts/CEJK01-9128-W04.woff2', size: '3.4 MB', label: '仓耳今楷' },
    '鸿蒙黑体内置': { url: '/static/fonts/HarmonyOS_Sans_SC.woff2', size: '4.1 MB', label: '鸿蒙黑体' },
    '未来圆内置': { url: '/static/fonts/WEILAIYUANMedium.woff2', size: '8.1 MB', label: '未来圆' },
    '汉仪文黑内置': { url: '/static/fonts/HYWenHei-55W.woff2', size: '1.5 MB', label: '汉仪文黑' },
    '兰亭羲之黑内置': { url: '/static/fonts/LantingXiHei-GBK.woff2', size: '1.6 MB', label: '兰亭羲之黑' },
    '方正大标宋内置': { url: '/static/fonts/FZDaBiaoSong.woff2', size: '1.4 MB', label: '方正大标宋' },
    '方正仿宋内置': { url: '/static/fonts/FZFangSong.woff2', size: '1.5 MB', label: '方正仿宋' },
    '方正楷体内置': { url: '/static/fonts/FZKaiTi.woff2', size: '1.6 MB', label: '方正楷体' }
};

/**
 * 提前下载字体栈里命中的内置字体（进 HTTP 缓存 + document.fonts 注册表）。
 * 用于首页等「还没用到字体」的页面：用户挑书时后台下好，点进详情页/阅读页
 * 立即可用，不经历 font-display:swap 的后备字体闪烁等待。
 * 详情页无需调用——简介本身已跟随正文字体，CSS 命中即触发下载（天然预热位）。
 *
 * 低网保护与 base.html 的 font.css 注入条件一致：
 * saveData/2g/3g 不预热；localStorage nm_load_fonts=1 可强制。
 * 同一 URL 重复请求命中 HTTP 缓存（max-age=30 天），已注册则直接跳过。
 *
 * @param {string} fontStack 字体栈，如 "'霞鹜文楷等宽 Medium', '霞鹜文楷内置', sans-serif"
 */
function warmupBuiltinFont(fontStack) {
    if (!fontStack || fontStack === 'system-ui') return;
    if (window.LOW_NETWORK) {
        try { if (localStorage.getItem('nm_load_fonts') !== '1') return; } catch (e) { return; }
    }
    if (typeof FontFace === 'undefined' || !document.fonts) return; // 老浏览器：留给 CSS 处理

    const names = String(fontStack).match(/'([^']+)'/g) || [];
    for (const raw of names) {
        const family = raw.replace(/'/g, '');
        const info = window.BUILTIN_FONTS[family];
        if (!info) continue;
        try {
            // 已注册过就直接复用（重复调用/翻页无成本）
            if (document.fonts.check(`16px "${family}"`)) return;
            const face = new FontFace(family, `url(${info.url})`, { display: 'swap' });
            face.load()
                .then(loaded => { document.fonts.add(loaded); })
                .catch(() => { /* 预热失败静默跳过：详情页简介/阅读页还会按需重试 */ });
        } catch (e) { /* ignore */ }
        return; // 只预热字体栈里第一个命中的内置字体
    }
}

function initCommon() {
    // 主题
    applyTheme();
    watchSystemTheme();
    watchThemeStorage();
    checkThemeOnReturn();

    // 头部背景图（延迟加载，不阻塞首屏；不做定时轮播）
    setTimeout(() => {
        setRandomHeaderBg();
    }, 300);
}

// ===== 统一页面初始化入口 =====
/**
 * 所有页面统一调用此函数完成公共初始化
 * @param {Object} options
 * @param {boolean} options.carousel   是否启用头部背景轮播，默认 true
 * @param {number}  options.interval   轮播间隔（毫秒），默认 8000
 * @param {boolean} options.initialOnly 只设置初始背景，不轮播，默认 false
 */
function initPage(options = {}) {
    // 注：原 carousel / interval 参数已移除 —— 定时轮播会白占带宽，
    //     现在改为「每次刷新换一张」，不再自动切换。
    const { initialOnly = false } = options;

    // 1. 主题
    applyTheme();
    watchSystemTheme();
    watchThemeStorage();
    checkThemeOnReturn();

    // 2. 头部背景图（延迟加载，不阻塞首屏；不做定时轮播）
    setTimeout(() => {
        setRandomHeaderBg({ initialOnly: initialOnly });
    }, 300);
}

// 注意：不再自动初始化，由各页面显式调用 initPage()
// initCommon() 保留供内部使用（兼容旧代码）

// 注：原页面卸载时 stopSlideshow 的钩子已移除（不再有定时轮播）

// 暴露全局函数（供 HTML 内联调用）
window.showNotification = showNotification;
window.showLoading = showLoading;
window.debounce = debounce;
window.escapeHtml = escapeHtml;
window.formatTime = formatTime;
window.applyTheme = applyTheme;
window.setRandomHeaderBg = setRandomHeaderBg;
window.nextBackground = nextBackground;
window.prevBackground = prevBackground;
window.getCurrentParams = getCurrentParams;
window.warmupBuiltinFont = warmupBuiltinFont;
window.initPage = initPage;

// ===== PWA: 注册 Service Worker =====
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/service-worker.js', {
            scope: '/'
        })
        .then((registration) => {
            console.log('✅ Service Worker 已注册:', registration.scope);

            // 检查更新
            registration.addEventListener('updatefound', () => {
                const newWorker = registration.installing;
                console.log('🔄 检测到新版本 Service Worker');

                newWorker.addEventListener('statechange', () => {
                    if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                        // 新版本已安装，等待用户刷新
                        console.log('✅ 新版本已就绪，下次刷新生效');
                    }
                });
            });
        })
        .catch((error) => {
            console.warn('⚠️ Service Worker 注册失败:', error);
            // 不抛错，PWA 失败不影响正常使用
        });
    });
}