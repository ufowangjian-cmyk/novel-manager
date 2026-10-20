// ============================================
// service-worker.js - PWA 离线缓存
// 注意：通过 /service-worker.js 路由暴露到根路径
// ============================================

// 缓存版本：改动后必须递增，否则浏览器会一直用旧的缓存
const CACHE_VERSION = 'novel-v16';
const PAGES_CACHE = `${CACHE_VERSION}-pages`;

// ===== 安装 =====
// v11 起不再预缓存、也不再拦截 /static/*：
// 静态资源交给浏览器 HTTP 缓存（响应头 Cache-Control: max-age=30天 +
// ETag + Vary: Accept-Encoding），比 SW 缓存更可靠。
// 原实现是「缓存优先 + 后台重验证」：手机 Firefox 实测每次翻页都把全部
// 静态资源重新下一遍（后台重验证绕过 HTTP 缓存）；且 8.6MB 字体等大文件
// 会把 CacheStorage 配额撑爆，导致 cache.put 静默失败、缓存形同虚设。
// 小说正文走 /api/ 本来就不缓存，离线本就读不了书，SW 静态缓存没有实际收益。
self.addEventListener('install', (event) => {
    self.skipWaiting();
});

// ===== 激活：清旧缓存 =====
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((names) => {
            return Promise.all(
                names
                    .filter((name) => !name.startsWith(CACHE_VERSION))
                    .map((name) => {
                        console.log('🗑️ 清除旧缓存:', name);
                        return caches.delete(name);
                    })
            );
        }).then(() => self.clients.claim())
    );
});

// ===== 拦截请求 =====
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);

    // 只处理同源、GET
    if (url.origin !== self.location.origin) return;
    if (request.method !== 'GET') return;

    // ===== API 请求：网络优先，不缓存 =====
    // 小说列表、阅读记录等必须实时
    if (url.pathname.startsWith('/api/')) {
        return;
    }

    // ===== 本地媒体 API：不缓存 =====
    if (url.pathname.startsWith('/api/local_')) {
        return;
    }

    // ===== 静态资源：不拦截，走浏览器 HTTP 缓存 =====
    if (url.pathname.startsWith('/static/')) {
        return;
    }

    // ===== manifest 和 SW：直接走网络 =====
    if (url.pathname === '/manifest.json' ||
        url.pathname === '/service-worker.js') {
        return;
    }

    // ===== 页面请求：网络优先，失败回退缓存 =====
    event.respondWith(
        fetch(request)
            .then((response) => {
                // 只缓存成功的 HTML 响应
                if (response.ok && response.headers.get('content-type')?.includes('text/html')) {
                    const clone = response.clone();
                    caches.open(PAGES_CACHE).then((cache) => {
                        cache.put(request, clone);
                    });
                }
                return response;
            })
            .catch(() => {
                return caches.match(request).then((cached) => {
                    if (cached) {
                        console.log('📦 离线回退:', url.pathname);
                        return cached;
                    }
                    // 完全没缓存，回退到登录页
                    return caches.match('/login');
                });
            })
    );
});

// ===== 收到新版本 SW 时立即接管 =====
self.addEventListener('message', (event) => {
    if (event.data === 'SKIP_WAITING') {
        self.skipWaiting();
    }
});
