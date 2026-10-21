// ===== 骨架屏加载 =====
function showSkeleton() {
    const tableWrapper = document.querySelector('.table-wrapper');
    const mobileCardList = document.querySelector('.mobile-card-list');

    if (!tableWrapper) return;

    const isMobile = window.innerWidth <= 768;

    if (isMobile) {
        const skeletonHTML = `
            <div class="skeleton-container">
                ${Array(8).fill(`
                    <div class="skeleton-card">
                        <div class="skeleton-card-title"></div>
                        <div class="skeleton-card-meta"></div>
                        <div class="skeleton-card-tags">
                            <div class="skeleton-tag"></div>
                            <div class="skeleton-tag"></div>
                            <div class="skeleton-tag"></div>
                        </div>
                        <div class="skeleton-card-footer"></div>
                    </div>
                `).join('')}
            </div>
        `;

        if (mobileCardList) {
            mobileCardList.style.display = 'block';
            mobileCardList.innerHTML = skeletonHTML;
        }
        const table = tableWrapper.querySelector('table');
        if (table) {
            table.style.display = 'none';
        }
    } else {
        // 非移动端：不直接覆盖 wrapper，而是隐藏原内容 + 插入骨架
        const table = tableWrapper.querySelector('table');
        if (table) {
            table.style.display = 'none';
        }
        const oldMobile = tableWrapper.querySelector('.mobile-card-list');
        if (oldMobile) {
            oldMobile.style.display = 'none';
        }

        // 移除旧骨架（如果重复调用）
        const oldSkeleton = tableWrapper.querySelector('.skeleton-table');
        if (oldSkeleton) oldSkeleton.remove();

        // 插入骨架表格（append，不覆盖）
        const skeletonHTML = `
            <table class="novel-table skeleton-table">
                <thead>
                    <tr>
                        <th>书名</th><th>作者</th><th>标签</th><th>字数</th>
                        <th>连载进度</th><th>发表网站</th><th>发表日期</th>
                    </tr>
                </thead>
                <tbody>
                    ${Array(15).fill(`
                        <tr class="skeleton-row">
                            <td><div class="skeleton-cell skeleton-cell-title"></div></td>
                            <td><div class="skeleton-cell skeleton-cell-author"></div></td>
                            <td>
                                <div class="skeleton-cell-tags">
                                    <div class="skeleton-cell-tag"></div>
                                    <div class="skeleton-cell-tag"></div>
                                </div>
                            </td>
                            <td><div class="skeleton-cell" style="width: 40px;"></div></td>
                            <td><div class="skeleton-cell" style="width: 50px;"></div></td>
                            <td><div class="skeleton-cell" style="width: 60px;"></div></td>
                            <td><div class="skeleton-cell" style="width: 70px;"></div></td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
        tableWrapper.insertAdjacentHTML('beforeend', skeletonHTML);
    }
}



function reloadWithSkeleton(url) {
    showSkeleton();
    window.location.href = url;
}

// ===== 选项卡切换功能 =====
function initTabs() {
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    const headerWrapper = document.getElementById('tabsHeaderWrapper');
    const hideBtn = document.getElementById('blockHideBtn');

    if (!tabBtns.length) return;

    let activeTabId = 'filter';
    const savedTab = localStorage.getItem('activeTab');
    if (savedTab) {
        activeTabId = savedTab;
    }

    // 隐藏 = 整个区块（区块头 + 内容面板）一起收起，首页回到干净的书架。
    // 想再打开：点头部右上角「菜单」里的任一区块项（见下方 tabBtns 的 onclick）。
    function setHidden(hidden) {
        if (headerWrapper) headerWrapper.classList.toggle('hidden', hidden);
        try {
            localStorage.setItem('tabsHidden', hidden ? 'true' : 'false');
        } catch (err) { /* 隐私模式等场景写不了，忽略 */ }
    }

    function switchTab(tabId) {
        tabBtns.forEach(btn => {
            if (btn.getAttribute('data-tab') === tabId) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });

        tabContents.forEach(content => {
            if (content.id === 'tab-' + tabId) {
                content.classList.add('active');
            } else {
                content.classList.remove('active');
            }
        });

        activeTabId = tabId;
        localStorage.setItem('activeTab', tabId);
    }

    // 初始：默认整块隐藏（与模板里 .tabs-header-wrapper.hidden 一致，防首屏闪烁）；
    // 上次手动展开过（tabsHidden === 'false'）则保持展开。
    setHidden(localStorage.getItem('tabsHidden') !== 'false');
    switchTab(activeTabId);

    // 点菜单里的区块项 = 显示该区块 + 切到它（不再有"点同一项收起"的旧行为）
    tabBtns.forEach(function (btn) {
        btn.onclick = function (e) {
            e.preventDefault();
            switchTab(this.getAttribute('data-tab'));
            setHidden(false);
        };
    });

    // 区块头右上角的一键隐藏
    if (hideBtn) {
        hideBtn.onclick = function (e) {
            e.preventDefault();
            setHidden(true);
        };
    }
}

// ===== 触摸反馈（仅移动端）=====
function initTouchFeedback() {
    if (window.innerWidth > 768) return;

    const selectors = [
        '.tab-btn', '.filter-tag', '.search-btn', '.reset-btn',
        '.scan-btn', '.recent-item-tab', '.pagination-btn',
        '.filter-title', '.open-btn', '.clear-records-btn'
    ].join(',');

    const addFeedback = (target) => {
        if (!target) return;
        target.classList.add('touch-active');

        const removeClass = () => {
            target.classList.remove('touch-active');
            target.removeEventListener('touchend', removeClass);
            target.removeEventListener('touchcancel', removeClass);
            target.removeEventListener('touchmove', removeClass);
        };

        target.addEventListener('touchend', removeClass, { once: true });
        target.addEventListener('touchcancel', removeClass, { once: true });
        target.addEventListener('touchmove', removeClass, { once: true });
    };

    document.body.addEventListener('touchstart', (e) => {
        addFeedback(e.target.closest(selectors));
    });

    document.body.addEventListener('mousedown', (e) => {
        const target = e.target.closest(selectors);
        if (!target) return;

        target.classList.add('touch-active');
        const removeClass = () => target.classList.remove('touch-active');
        target.addEventListener('mouseup', removeClass, { once: true });
    });
}

// ===== 折叠/展开功能 =====
function toggleSection(titleElement) {
    titleElement.closest('.filter-section')?.classList.toggle('collapsed');
}

// ===== 屏幕适配 =====
function checkScreenSizeAndDisplay() {
    const isMobile = window.innerWidth <= 768;
    const tableElem = document.querySelector('.table-wrapper table');
    const mobileCardList = document.querySelector('.mobile-card-list');

    if (tableElem && mobileCardList) {
        tableElem.style.display = isMobile ? 'none' : 'table';
        mobileCardList.style.display = isMobile ? 'block' : 'none';
    }
}

// ===== 扫描进度 =====
let scanning = false;
let progressInterval = null;
let displayedProgress = 0;   // 进度条已显示的百分比，只增不减

function startScan(fullScan = false) {
    console.log('startScan 被调用, fullScan=', fullScan, 'scanning=', scanning);

    if (scanning) {
        console.log('已有扫描任务进行中，忽略');
        showNotification('扫描任务已在运行中', 'warning');
        return;
    }

    scanning = true;
    const scanBtn = document.getElementById('scanBtn');
    const scanFullBtn = document.getElementById('scanFullBtn');
    if (scanBtn) scanBtn.disabled = true;
    if (scanFullBtn) scanFullBtn.disabled = true;

    const progressContainer = document.getElementById('progressContainer');
    if (progressContainer) progressContainer.style.display = 'block';

    const progressFill = document.getElementById('progressFill');
    const progressMessage = document.getElementById('progressMessage');
    displayedProgress = 0;
    if (progressFill) progressFill.style.width = '0%';
    if (progressMessage) progressMessage.textContent = '正在启动扫描...';

    const url = fullScan ? '/api/start_scan?full=true' : '/api/start_scan';
    console.log('请求URL:', url);

    fetch(url, {
        method: 'GET',
        headers: { 'Cache-Control': 'no-cache' }
    })
        .then(res => res.json())
        .then(data => {
            console.log('扫描启动响应:', data);
            if (data.status === 'started' || data.status === 'already_scanning') {
                if (progressInterval) clearInterval(progressInterval);
                progressInterval = setInterval(checkProgress, 400);
            } else {
                scanning = false;
                if (scanBtn) scanBtn.disabled = false;
                if (scanFullBtn) scanFullBtn.disabled = false;
                showNotification('启动扫描失败: ' + (data.message || '未知错误'), 'error');
                if (progressMessage) progressMessage.textContent = '启动失败';
            }
        })
        .catch(err => {
            console.error('扫描启动失败:', err);
            scanning = false;
            if (scanBtn) scanBtn.disabled = false;
            if (scanFullBtn) scanFullBtn.disabled = false;
            showNotification('网络错误，无法启动扫描', 'error');
        });
}

function checkProgress() {
    fetch('/api/scan_progress', {
        headers: { 'Cache-Control': 'no-cache' }
    })
        .then(res => res.json())
        .then(data => {
            console.log('进度响应:', data);
            updateProgressUI(data);

            if (data.status === 'completed') {
                clearInterval(progressInterval);
                scanning = false;
                const scanBtn = document.getElementById('scanBtn');
                const scanFullBtn = document.getElementById('scanFullBtn');
                if (scanBtn) scanBtn.disabled = false;
                if (scanFullBtn) scanFullBtn.disabled = false;
                showNotification('扫描完成！正在刷新页面...', 'success');
                setTimeout(() => window.location.reload(), 1500);
            } else if (data.status === 'error') {
                clearInterval(progressInterval);
                scanning = false;
                const scanBtn = document.getElementById('scanBtn');
                const scanFullBtn = document.getElementById('scanFullBtn');
                if (scanBtn) scanBtn.disabled = false;
                if (scanFullBtn) scanFullBtn.disabled = false;
                showNotification('扫描出错: ' + data.message, 'error');
            }
        })
        .catch(err => {
            console.error('获取进度失败:', err);
        });
}

function updateProgressUI(data) {
    const progressFill = document.getElementById('progressFill');
    const progressMessage = document.getElementById('progressMessage');
    const progressTime = document.getElementById('progressTime');

    if (!progressFill) return;

    if (data.status === 'scanning') {
        // 只增不减：不同阶段 total 会变化，避免百分比倒退造成视觉抖动
        displayedProgress = Math.max(displayedProgress, data.percentage || 0);
        progressFill.style.width = displayedProgress + '%';
        if (progressMessage) progressMessage.textContent = data.message || '正在扫描...';
        if (progressTime && data.elapsed !== undefined) {
            progressTime.textContent = `已用: ${formatTime(data.elapsed || 0)} | 剩余: ${formatTime(data.remaining || 0)}`;
        }
    } else if (data.status === 'completed') {
        progressFill.style.width = '100%';
        if (progressMessage) progressMessage.innerHTML = '' + icon('check', 'sm') + '扫描完成！';
        if (progressTime) progressTime.textContent = `共处理 ${data.total || 0} 个文件`;
    } else if (data.status === 'error') {
        progressFill.style.width = '0%';
        if (progressMessage) progressMessage.innerHTML = '' + icon('circle-x', 'sm') + ' ' + (data.message || '扫描出错');
        if (progressTime) progressTime.textContent = '';
    }
}

// ===== 分页功能 =====
function gotoPage(maxPage) {
    const pageInput = document.getElementById('gotoPage');
    if (!pageInput) return;

    let page = parseInt(pageInput.value);
    if (isNaN(page)) page = 1;
    if (page < 1) page = 1;
    if (page > maxPage) page = maxPage;

    const urlParams = new URLSearchParams(window.location.search);
    urlParams.set('page', page);

    if (!urlParams.has('sort')) {
        urlParams.set('sort', 'title');
    }
    if (!urlParams.has('order')) {
        urlParams.set('order', 'asc');
    }

    reloadWithSkeleton(`?${urlParams.toString()}`);
}

function initPagination(maxPage) {
    const gotoPageInput = document.getElementById('gotoPage');
    if (gotoPageInput) {
        gotoPageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                let page = parseInt(gotoPageInput.value);
                if (isNaN(page)) page = 1;
                if (page < 1) page = 1;
                if (page > maxPage) page = maxPage;

                const urlParams = new URLSearchParams(window.location.search);
                urlParams.set('page', page);

                if (!urlParams.has('sort')) {
                    urlParams.set('sort', 'title');
                }
                if (!urlParams.has('order')) {
                    urlParams.set('order', 'asc');
                }

                reloadWithSkeleton(`?${urlParams.toString()}`);
            }
        });
    }
}


async function loadAllItems(url, containerId, type, createLink) {
    const container = document.querySelector(containerId);
    if (!container || container.getAttribute('data-loaded') === 'all') return;

    const showAllBtn = container.querySelector('.show-all');
    if (showAllBtn) {
        showAllBtn.textContent = '加载中...';
        showAllBtn.style.pointerEvents = 'none';
    }

    try {
        const response = await fetch(url);
        const data = await response.json();
        const items = data[type];
        const params = getCurrentParams();

        container.innerHTML = '';

        const allLink = document.createElement('a');
        allLink.href = `?${params}`;
        allLink.className = 'filter-tag';
        allLink.textContent = '全部';
        if (!window.location.search.includes('author=') &&
            !window.location.search.includes('tag=') &&
            !window.location.search.includes('site=')) {
            allLink.classList.add('active');
        }
        container.appendChild(allLink);

        items.forEach(item => {
            if (item !== '全部') {
                container.appendChild(createLink(item, params));
            }
        });

        container.setAttribute('data-loaded', 'all');

        const collapseBtn = document.createElement('a');
        collapseBtn.href = '#';
        collapseBtn.className = 'show-all';
        collapseBtn.innerHTML = '收起 ' + icon('arrow-up', 'sm') + '';
        collapseBtn.onclick = (e) => {
            e.preventDefault();
            collapseItems(containerId, type);
        };
        container.appendChild(collapseBtn);

    } catch (error) {
        console.error(`加载${type}失败:`, error);
        const btn = container.querySelector('.show-all');
        if (btn) {
            btn.innerHTML = `显示全部 ${icon('arrow-right', 'sm')}`;
            btn.style.pointerEvents = 'auto';
        }
    } finally {
        if (showAllBtn) showAllBtn.style.pointerEvents = 'auto';
    }
}

function showAllAuthors(event) {
    event.preventDefault();
    loadAllItems('/get_all_authors', '#authorSection .filter-tags', 'authors', (author, params) => {
        const link = document.createElement('a');
        link.href = `?author=${encodeURIComponent(author)}${params ? '&' + params : ''}`;
        link.className = 'filter-tag';
        link.textContent = author;
        return link;
    });
}

function showAllTags(event) {
    event.preventDefault();
    loadAllItems('/get_all_tags', '#tagSection .filter-tags', 'tags', (tag, params) => {
        const link = document.createElement('a');
        link.href = `?tag=${encodeURIComponent(tag)}${params ? '&' + params : ''}`;
        link.className = 'filter-tag';
        link.textContent = tag;
        return link;
    });
}

function showAllSites(event) {
    event.preventDefault();
    loadAllItems('/get_all_sites', '#siteSection .filter-tags', 'sites', (site, params) => {
        const link = document.createElement('a');
        link.href = `?site=${encodeURIComponent(site)}${params ? '&' + params : ''}`;
        link.className = 'filter-tag';
        link.textContent = site;
        return link;
    });
}

async function collapseItems(containerId, type) {
    const container = document.querySelector(containerId);
    if (!container) return;

    container.innerHTML = '';
    container.removeAttribute('data-loaded');

    const url = type === 'authors' ? '/get_first_authors' :
        type === 'tags' ? '/get_first_tags' : '/get_first_sites';
    const itemKey = type === 'authors' ? 'authors' : type === 'tags' ? 'tags' : 'sites';

    try {
        const response = await fetch(url);
        const data = await response.json();

        const params = getCurrentParams();

        const allLink = document.createElement('a');
        allLink.href = `?${params}`;
        allLink.className = 'filter-tag';
        allLink.textContent = '全部';
        container.appendChild(allLink);

        data[itemKey].forEach(item => {
            const link = document.createElement('a');
            const queryParam = type === 'authors' ? 'author' : type === 'tags' ? 'tag' : 'site';
            link.href = `?${queryParam}=${encodeURIComponent(item)}${params ? '&' + params : ''}`;
            link.className = 'filter-tag';
            link.textContent = item;
            container.appendChild(link);
        });

        const showAllBtn = document.createElement('a');
        showAllBtn.href = '#';
        showAllBtn.className = 'show-all';
        const totalKey = type === 'authors' ? 'total' : type === 'tags' ? 'total' : 'total';
        showAllBtn.innerHTML = `显示全部 ${data[totalKey]} 个${type === 'authors' ? '作者' : type === 'tags' ? '标签' : '网站'} ${icon('arrow-right', 'sm')}`;
        showAllBtn.onclick = type === 'authors' ? showAllAuthors : type === 'tags' ? showAllTags : showAllSites;
        container.appendChild(showAllBtn);

    } catch (error) {
        console.error(`收起${type}失败:`, error);
    }
}

// ===== 书名处理 =====
const specialWords = [
    '同人续写', '同人续', '同人',
    '续写', '续写版', '增容', '增容版',
    '番外篇', '番外', '特别篇', '独立篇',
    '外传', '前传', '后传',
    '修改', '加料版', '修改版',
    '改编版', '改编', '新编', '新编版',
    '扩编', '扩编版', '扩写', '扩写版', '狼增版',
    '改写版', '改写',
    '修订版', '无绿版', '非绿版', '精修版'
];

// 需要格式化的书名容器：书架页的 .novel-title、卡片标题，以及「最近阅读」的标题。
// 统一维护在这里，避免以后新增一种书名容器时又漏掉一处。
const TITLE_SELECTORS = ['.novel-title', '.novel-card-title a', '.recent-card-title'];

// 书名通用格式化：主标题与括号副标题分行，敏感/版本词淡化高亮。
// 纯字符串进、纯字符串出（不碰 DOM），方便直接用于客户端模板。
function formatNovelTitleText(text) {
    var originalText = String(text == null ? '' : text);
    var result = originalText;

    if (/[（【]/.test(originalText)) {
        var firstBracketIndex = -1;
        for (var i = 0; i < originalText.length; i++) {
            if (originalText[i] === '（' || originalText[i] === '【') {
                firstBracketIndex = i;
                break;
            }
        }

        if (firstBracketIndex > 0) {
            var mainTitle = originalText.substring(0, firstBracketIndex);
            var bracketContent = originalText.substring(firstBracketIndex);
            result = mainTitle + '<br><span class="bracket-content">' + bracketContent + '</span>';
        } else if (firstBracketIndex === 0) {
            result = '<span class="bracket-content">' + originalText + '</span>';
        }
    }

    for (var j = 0; j < specialWords.length; j++) {
        var word = specialWords[j];
        var regex = new RegExp('(' + word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'g');
        result = result.replace(regex, '<span class="faint-highlight">$1</span>');
    }

    return result;
}

function formatNovelTitlesAndHighlight() {
    TITLE_SELECTORS.forEach(function (selector) {
        document.querySelectorAll(selector).forEach(function (el) {
            // 幂等：MutationObserver 会反复触发，已处理过的直接跳过
            if (el.hasAttribute('data-processed')) return;

            // 书名可能被历史逻辑改写过（例如卡片带「已读完」徽标），
            // 用 title 属性里的原始文本重建，避免二次转义或叠加标记。
            var source = el.getAttribute('title');
            el.innerHTML = formatNovelTitleText(source != null ? source : el.textContent);
            el.setAttribute('data-processed', 'true');
        });
    });

    document.querySelectorAll('.author-link').forEach(function (el) {
        if (el.hasAttribute('data-processed')) return;

        var originalText = el.textContent.trim();
        var hasBracket = /[（【[]/.test(originalText);

        if (hasBracket) {
            var firstBracketIndex = -1;
            for (var i = 0; i < originalText.length; i++) {
                if (originalText[i] === '（' || originalText[i] === '【' || originalText[i] === '[') {
                    firstBracketIndex = i;
                    break;
                }
            }

            if (firstBracketIndex > 0) {
                var mainAuthor = originalText.substring(0, firstBracketIndex);
                var bracketContent = originalText.substring(firstBracketIndex);

                if (/(\[(不详|未知|多人|网友|匿名|佚名)\]|（(不详|未知|多人|网友|匿名|佚名)）|【(不详|未知|多人|网友|匿名|佚名)】)/i.test(bracketContent)) {
                    el.innerHTML = mainAuthor + '<br><span class="faint-highlight">' + bracketContent + '</span>';
                } else {
                    el.innerHTML = mainAuthor + '<br><span class="bracket-content">' + bracketContent + '</span>';
                }
            } else if (firstBracketIndex === 0) {
                var bracketContent = originalText;
                if (/(\[(不详|未知|多人|网友|匿名|佚名)\]|（(不详|未知|多人|网友|匿名|佚名)）|【(不详|未知|多人|网友|匿名|佚名)】)/i.test(bracketContent)) {
                    el.innerHTML = '<span class="faint-highlight">' + bracketContent + '</span>';
                } else {
                    el.innerHTML = '<span class="bracket-content">' + bracketContent + '</span>';
                }
            }

            el.setAttribute('data-processed', 'true');
        }
    });

}

// ===== 每日推荐：换一本 =====
const RandomNovel = (function () {
    let currentWorkId = '';
    let loading = false;

    const el = (id) => document.getElementById(id);

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function formatWordCount(count) {
        const n = parseInt(count, 10) || 0;
        if (!n) return '';
        return n >= 10000 ? (n / 10000).toFixed(1) + '万字' : n + '字';
    }

    // 与服务端 templates/_random_card.html 保持一致
    function buildRandomCardHTML(n) {
        const aliases = (n.author_aliases && n.author_aliases.length)
            ? ` <span class="random-alias">（${escapeHtml(n.author_aliases.join('、'))}）</span>`
            : '';

        const meta = [];
        meta.push(`<span class="random-meta-item">${icon('pencil', 'sm')} ${escapeHtml(n.author || '未知作者')}${aliases}</span>`);
        if (n.site && n.site !== '未知网站') {
            meta.push(`<span class="random-meta-item">${icon('globe', 'sm')} ${escapeHtml(n.site)}</span>`);
        }
        const wc = formatWordCount(n.word_count);
        if (wc) meta.push(`<span class="random-meta-item">${icon('pencil', 'sm')} ${wc}</span>`);
        if (n.progress) meta.push(`<span class="random-meta-item">${icon('library', 'sm')} ${escapeHtml(n.progress)}</span>`);
        if (n.publish_date && n.publish_date !== '未知') {
            meta.push(`<span class="random-meta-item">${icon('calendar', 'sm')} ${escapeHtml(n.publish_date)}</span>`);
        }

        const tags = (n.tags || []).slice(0, 8).map(t =>
            `<a href="?tag=${encodeURIComponent(t)}" class="tag-badge">${escapeHtml(t)}</a>`
        ).join('');
        const moreTags = (n.tags && n.tags.length > 8)
            ? `<span class="tag-badge tag-more">+${n.tags.length - 8}</span>` : '';

        const intro = n.intro
            ? `<div class="random-intro-label">${icon('book-open', 'sm')} 简介 / 试读</div>
               <div class="random-intro">${escapeHtml(n.intro)}</div>`
            : `<div class="random-intro random-intro-empty">这本书没有可显示的简介，点开看看正文吧。</div>`;

        // 封面：有图显示图，没有则用书名首字占位。元素必须始终存在，
        // 否则 grid 会把右栏内容挤进 108px 的封面列。
        const initial = escapeHtml((n.title || '书').slice(0, 1));
        const cover = n.cover_url
            ? `<div class="random-cover" data-initial="${initial}">
                   <img src="${escapeHtml(n.cover_url)}" alt="${escapeHtml(n.title)} 封面" loading="lazy" referrerpolicy="no-referrer"
                        onerror="this.parentElement.classList.add('random-cover-empty');this.parentElement.textContent=this.parentElement.dataset.initial;">
               </div>`
            : `<div class="random-cover random-cover-empty" data-initial="${initial}">
                   <span class="random-cover-initial">${initial}</span>
               </div>`;

        return `
        <div class="random-card" data-work-id="${escapeHtml(n.work_id)}">
            ${cover}
            <div class="random-card-main">
                <h4 class="random-title">
                    <a href="${escapeHtml(n.detail_url)}">${escapeHtml(n.title)}</a>
                </h4>
                <div class="random-meta">${meta.join('')}</div>
                ${tags ? `<div class="random-tags">${tags}${moreTags}</div>` : ''}
            </div>
            <div class="random-intro-wrap">${intro}</div>
            <div class="random-card-actions">
                <a href="${escapeHtml(n.detail_url)}" class="btn btn-secondary">${icon('file', 'sm')} 查看详情</a>
                <a href="${escapeHtml(n.read_url)}" class="btn btn-success">${icon('book-open', 'sm')} 开始阅读</a>
            </div>
        </div>`;
    }

    function render(novel) {
        const body = el('randomCardBody');
        if (!body || !novel) return;
        body.innerHTML = buildRandomCardHTML(novel);
        currentWorkId = novel.work_id || '';
    }

    function swap() {
        if (loading) return;
        const btn = el('randomRefreshBtn');
        const body = el('randomCardBody');
        if (!body) return;

        loading = true;
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = icon('loader', 'sm') + ' 抽书中...';
        }
        body.classList.add('swapping');

        const params = new URLSearchParams();
        if (currentWorkId) params.set('exclude', currentWorkId);

        fetch('/api/random_novel?' + params.toString(), {
            headers: { 'Accept': 'application/json' }
        })
            .then(r => r.json())
            .then(data => {
                if (!data.success) throw new Error(data.message || '获取失败');
                render(data.novel);
            })
            .catch(err => {
                console.error('换一本失败:', err);
                if (typeof showNotification === 'function') {
                    showNotification('换一本失败，请重试', 'error');
                }
            })
            .finally(() => {
                loading = false;
                body.classList.remove('swapping');
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '' + icon('refresh-cw', 'sm') + '换一本';
                }
            });
    }

    function init() {
        const section = el('randomSection');
        if (!section) return;

        // 记住首屏那本的 work_id，这样第一次「换一本」就不会重复抽到它
        const card = section.querySelector('.random-card');
        if (card) currentWorkId = card.getAttribute('data-work-id') || '';

        const btn = el('randomRefreshBtn');
        if (btn) btn.addEventListener('click', swap);
    }

    return { init, swap, render, buildRandomCardHTML };
})();

// ===== 最近阅读：局部渲染 / 搜索 / 排序 / 加载更多 / 删除 =====
const RecentReads = (function () {
    // 分组标题的图标在渲染时才取，避免依赖脚本加载顺序
    // （曾因 main.js 早于 common.js 加载，顶层调用 icon() 抛错导致图标丢失）
    const GROUP_META = {
        today: { icon: 'calendar', text: '今天', order: 0 },
        yesterday: { icon: 'moon', text: '昨天', order: 1 },
        earlier: { icon: 'library', text: '更早', order: 2 }
    };
    const PAGE_SIZE = 12;

    let state = {
        records: [],      // 当前已加载的记录（已按服务端时间倒序）
        shown: 0,         // 已渲染条数
        total: 0,
        hasMore: false,
        keyword: '',
        sort: 'time',
        loading: false
    };

    const el = (id) => document.getElementById(id);

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    // 与服务端 templates/_recent_card.html 保持一致
    const PLACEHOLDER_AUTHORS = ['[不详]', '不详', '未知', '未知作者', '无', 'None', 'none'];

    function buildRecentCardHTML(rec) {
        const percent = (rec.progress_percent === null || rec.progress_percent === undefined)
            ? 0 : rec.progress_percent;
        const finished = rec.finished === true;
        // 进度文字里的「已读完」图标是 HTML（SVG），不能整体 escapeHtml，否则会显示成源码。
        // 图标走 HTML 原样插入，进度文字单独转义，与服务端 _recent_card.html 行为保持一致。
        const progressIcon = finished ? '' + icon('circle-check', 'sm') + ' ' : '';
        const progressText = rec.progress_text || '进度未知';
        const authorName = String(rec.author == null ? '' : rec.author).trim();
        const author = (authorName && PLACEHOLDER_AUTHORS.indexOf(authorName) === -1)
            ? `<span class="recent-author" title="${escapeHtml(authorName)}">${icon('pencil', 'sm')} ${escapeHtml(authorName)}</span>`
            : '';
        const missing = rec.missing_file
            ? '<span class="recent-missing-badge" title="文件已不在，可能被移动或删除">' + icon('circle-x', 'sm') + '文件丢失</span>'
            : '';
        const progressAttr = (rec.progress_percent === null || rec.progress_percent === undefined)
            ? '' : rec.progress_percent;
        // 与服务端 _recent_card.html 的 data-progress-known 保持一致：
        // 只有明确进度已知才写 '1'，否则老卡片会被当成真实的 0% 进度条。
        const progressKnownAttr = rec.progress_known ? '1' : '0';
        // 书名在这里就格式好（括号副标题分行 + 关键词淡化），
        // 与首屏服务端渲染的结果一致，不必等 MutationObserver 补处理。
        // title 属性用于「已读完」切换等回写场景，这里保持原始书名不变。
        const titleHtml = formatNovelTitleText(rec.title);

        return `
        <div class="recent-card-wrapper" data-work-id="${escapeHtml(rec.work_id)}" data-file-path="${escapeHtml(rec.file_path)}" data-title="${escapeHtml(rec.title)}" data-author="${escapeHtml(rec.author)}" data-chapter="${escapeHtml(rec.chapter)}" data-progress="${progressAttr}" data-progress-known="${progressKnownAttr}" data-finished="${finished ? '1' : '0'}">
            <a href="${escapeHtml(rec.url)}" class="recent-card">
                <div class="recent-card-head">
                    <div class="recent-card-title" title="${escapeHtml(rec.title)}" data-processed="true">${titleHtml}</div>
                </div>
                <div class="recent-card-info">
                    ${author}
                    <span class="recent-chapter" title="${escapeHtml(rec.chapter)}">${icon('book-open', 'sm')} ${escapeHtml(rec.chapter)}</span>
                </div>
                <div class="recent-progress${rec.progress_known ? '' : ' progress-unknown'}${finished ? ' progress-finished' : ''}">
                    <div class="recent-progress-track">
                        <div class="recent-progress-fill" style="width: ${percent}%"></div>
                    </div>
                    <span class="recent-progress-text">${progressIcon}${escapeHtml(progressText)}</span>
                </div>
                <div class="recent-card-foot">
                    <span class="recent-card-time">${icon('clock', 'xs')} ${escapeHtml(rec.time)}</span>
                    ${missing}
                </div>
            </a>
            <div class="recent-card-actions">
                <a href="${escapeHtml(rec.restart_url)}" class="recent-restart-btn" title="从头开始读">${icon('rotate-ccw', 'sm')}</a>
                <button type="button" class="recent-delete-btn" onclick="deleteSingleRecord(this)" data-work-id="${escapeHtml(rec.work_id)}" data-file-path="${escapeHtml(rec.file_path)}" title="删除这条记录" aria-label="删除这条记录">${icon('x', 'sm')}</button>
            </div>
        </div>`;
    }

    // 依据当前排序规则对「已加载」的记录重排，保证首屏和加载更多顺序一致
    function applySort(records) {
        const list = records.slice();
        if (state.sort === 'progress') {
            list.sort((a, b) => {
                const pa = (a.progress_percent === null || a.progress_percent === undefined) ? -1 : a.progress_percent;
                const pb = (b.progress_percent === null || b.progress_percent === undefined) ? -1 : b.progress_percent;
                return pb - pa;
            });
        } else if (state.sort === 'title') {
            list.sort((a, b) => String(a.title || '').localeCompare(String(b.title || ''), 'zh-Hans-CN'));
        }
        // sort === 'time'时保持服务端返回的时间倒序
        return list;
    }

    function renderGroups(records, { reset }) {
        const container = el('recentGroups');
        if (!container) return;

        const list = applySort(records);
        const byGroup = { today: [], yesterday: [], earlier: [] };
        list.forEach((rec) => {
            (byGroup[rec.group] || byGroup.earlier).push(rec);
        });

        let html = '';
        Object.keys(GROUP_META)
            .sort((a, b) => GROUP_META[a].order - GROUP_META[b].order)
            .forEach((key) => {
                const items = byGroup[key];
                if (!items || !items.length) return;
                html += `
                <section class="recent-group" data-group="${key}">
                    <h4 class="recent-group-title">
                        ${icon(GROUP_META[key].icon, 'sm')} ${GROUP_META[key].text}
                        <span class="recent-group-count">${items.length}</span>
                    </h4>
                    <div class="recent-grid">${items.map(buildRecentCardHTML).join('')}</div>
                </section>`;
            });

        container.innerHTML = html;
        container.hidden = records.length === 0;
        if (reset) container.dataset.rendered = '1';
    }

    function refreshChrome() {
        const stats = el('recentStatsBar');
        const toolbar = el('recentToolbar');
        const empty = el('recentEmptyState');
        const noMatch = el('recentNoMatch');
        const loadWrap = el('recentLoadMoreWrap');

        if (state.total === 0) {
            if (stats) stats.hidden = true;
            if (toolbar) toolbar.hidden = true;
            if (loadWrap) loadWrap.hidden = true;
            if (noMatch) noMatch.hidden = true;
            if (empty) empty.hidden = false;
            return;
        }

        if (stats) stats.hidden = false;
        if (toolbar) toolbar.hidden = false;
        if (empty) empty.hidden = true;
        if (noMatch) noMatch.hidden = state.records.length !== 0;

        // 计数与概览由服务端返回的 stats 计算
        const countLabel = el('recentCountLabel');
        if (countLabel) countLabel.textContent = `共 ${state.total} 条`;

        if (loadWrap) loadWrap.hidden = !state.hasMore;
    }

    function updateStats(stats) {
        if (!stats) return;
        const map = { statTotal: stats.total, statToday: stats.today,
                      statInProgress: stats.in_progress };
        Object.keys(map).forEach((id) => {
            const node = el(id);
            if (node) node.textContent = map[id];
        });
        const avg = el('statAvg');
        if (avg) avg.textContent = `${stats.avg_progress}%`;
    }

    function fetchRecords({ append }) {
        if (state.loading) return Promise.resolve();
        state.loading = true;

        const btn = el('recentLoadMoreBtn');
        if (btn && append) {
            btn.disabled = true;
            btn.textContent = '加载中...';
        }

        const params = new URLSearchParams({
            offset: append ? state.records.length : 0,
            limit: PAGE_SIZE
        });
        if (state.keyword) params.set('q', state.keyword);

        return fetch(`/api/recent_records?${params.toString()}`, {
            headers: { 'Accept': 'application/json' }
        })
            .then((r) => r.json())
            .then((data) => {
                if (!data || !data.success) throw new Error((data && data.message) || '加载失败');

                state.total = data.total;
                state.hasMore = data.has_more;
                state.records = append ? state.records.concat(data.records) : data.records;

                updateStats(data.stats);
                renderGroups(state.records, { reset: true });
                refreshChrome();
            })
            .catch((err) => {
                console.error('最近阅读加载失败:', err);
                if (typeof showNotification === 'function') {
                    showNotification('加载阅读记录失败', 'error');
                }
            })
            .finally(() => {
                state.loading = false;
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '' + icon('arrow-down', 'sm') + '加载更多记录';
                }
            });
    }

    // 就地移除卡片：不动整页、不丢当前滚动位置和选项卡状态
    function removeCard(workId, filePath) {
        const wrapper = document.querySelector(
            `.recent-card-wrapper[data-work-id="${workId}"]`
        ) || (filePath ? document.querySelector(
            `.recent-card-wrapper[data-file-path="${CSS.escape(filePath)}"]`
        ) : null);

        if (wrapper) {
            wrapper.classList.add('removing');
            setTimeout(() => {
                const grid = wrapper.parentElement;
                wrapper.remove();
                // 组内清空后整组移除，避免留下空标题
                if (grid && grid.classList.contains('recent-grid') && !grid.children.length) {
                    const section = grid.closest('.recent-group');
                    if (section) section.remove();
                }
            }, 180);
        }

        state.records = state.records.filter((r) => r.work_id !== workId);
    }

    // 删除后服务端会回传「前 12 条 + 总数 + has_more」。
    // 这里整体重建列表：已加载的窗口回到首页那批，之后仍可用「加载更多」
    // 通过 offset = state.records.length 继续拉取，分页不会错位。
    function setRecordsFromServer(data) {
        state.total = data.recent_total;
        state.records = data.records || [];
        state.hasMore = !!data.has_more;
        updateStats(data.stats);
        renderGroups(state.records, { reset: true });
        refreshChrome();
    }

    function bind() {
        const input = el('recentSearchInput');
        const clear = el('recentSearchClear');
        const sort = el('recentSortSelect');
        const more = el('recentLoadMoreBtn');

        if (input) {
            let timer = null;
            input.addEventListener('input', function () {
                const value = this.value.trim();
                if (clear) clear.hidden = !value;
                clearTimeout(timer);
                timer = setTimeout(() => {
                    state.keyword = value;
                    fetchRecords({ append: false });
                }, 250);
            });
        }

        if (clear) {
            clear.addEventListener('click', () => {
                if (input) input.value = '';
                clear.hidden = true;
                state.keyword = '';
                fetchRecords({ append: false });
            });
        }

        if (sort) {
            sort.addEventListener('change', function () {
                state.sort = this.value;
                renderGroups(state.records, { reset: false });
            });
        }

        if (more) {
            more.addEventListener('click', () => fetchRecords({ append: true }));
        }
    }

    function init() {
        const root = el('recentReadsTab');
        if (!root) return;
        bind();
        // 首屏由服务端渲染，这里只把状态对齐，避免多余请求
        const cards = root.querySelectorAll('.recent-card-wrapper');
        state.shown = cards.length;
        state.total = parseInt(el('recentCountLabel')?.textContent?.replace(/\D/g, '') || '0', 10) || cards.length;
        state.records = Array.prototype.map.call(cards, (node) => ({
            work_id: node.dataset.workId || '',
            file_path: node.dataset.filePath || '',
            title: node.dataset.title || '',
            author: node.dataset.author || '',
            chapter: node.dataset.chapter || '',
            // 首屏由服务端渲染，这里把「已读完」标记一并读回，否则点「加载更多」
            // 全量重渲染时（buildRecentCardHTML）会丢失该标记，已读完卡片退回成普通进度条
            finished: node.dataset.finished === '1',
            progress_percent: node.dataset.progress === '' ? null : parseInt(node.dataset.progress, 10),
            // 只有明确标记为 '1'才算进度已知；属性缺失按「未知」处理，
            // 否则老卡片会被当成真实的 0% 进度条
            progress_known: node.dataset.progressKnown === '1',
            progress_text: node.querySelector('.recent-progress-text')?.textContent.trim() || '',
            group: node.closest('.recent-group')?.dataset.group || 'earlier',
            time: node.querySelector('.recent-card-time')?.textContent.replace(/\s+/g, ' ').trim() || '',
            url: node.querySelector('.recent-card')?.getAttribute('href') || '',
            restart_url: node.querySelector('.recent-restart-btn')?.getAttribute('href') || '',
            missing_file: !!node.querySelector('.recent-missing-badge')
        }));
        state.hasMore = !!el('recentLoadMoreWrap') && !el('recentLoadMoreWrap').hidden;
        refreshChrome();
    }

    return { init, removeCard, setRecordsFromServer, state };
})();

// ===== 主页书名栏：标记「已读完」/ 取消 =====
function toggleFinished(btn) {
    const workId = btn.getAttribute('data-work-id') || '';
    const filePath = btn.getAttribute('data-file-path') || '';
    const title = btn.getAttribute('data-title') || '';
    const author = btn.getAttribute('data-author') || '';
    const wasFinished = btn.getAttribute('data-finished') === '1';
    const nextFinished = !wasFinished;

    if (!workId && !filePath) return;

    const originalText = btn.textContent;
    btn.disabled = true;
    btn.innerHTML = icon('loader', 'sm');

    fetch('/api/mark_read', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            work_id: workId,
            file_path: filePath,
            title: title,
            author: author,
            finished: nextFinished
        })
    })
        .then(r => r.json())
        .then(data => {
            if (!data.success) {
                showNotification(data.message || '标记失败', 'error');
                btn.disabled = false;
                btn.textContent = originalText;
                return;
            }

            // 就地切换按钮状态，不整页刷新
            btn.disabled = false;
            btn.setAttribute('data-finished', nextFinished ? '1' : '0');
            btn.classList.toggle('is-finished', nextFinished);
            btn.classList.toggle('is-none', !nextFinished);
            btn.innerHTML = nextFinished ? '' + icon('circle-check', 'sm') + '已读完' : '' + icon('square-check', 'sm') + '标记已读';
            btn.title = nextFinished ? '已标记为已读完，点击取消' : '标记这本书为已读完';

            // PC 表格和移动端卡片是两套 DOM，同步另一处的同 work_id 按钮
            syncFinishedButton(btn, workId, nextFinished);

            showNotification(nextFinished ? '已标记为已读完' : '已取消已读标记', 'success');
        })
        .catch(err => {
            console.error('标记已读失败:', err);
            showNotification('标记失败，请重试', 'error');
            btn.disabled = false;
            btn.textContent = originalText;
        });
}

// 同步同一本书在两套列表（表格 / 移动卡片）里的按钮显示
function syncFinishedButton(sourceBtn, workId, finished) {
    if (!workId) return;
    document.querySelectorAll(`.reading-status-btn[data-work-id="${CSS.escape(workId)}"]`)
        .forEach(other => {
            if (other === sourceBtn) return;
            other.setAttribute('data-finished', finished ? '1' : '0');
            other.classList.toggle('is-finished', finished);
            other.classList.toggle('is-none', !finished);
            other.innerHTML = finished ? '' + icon('circle-check', 'sm') + '已读完' : '' + icon('square-check', 'sm') + '标记已读';
        });
}

// ===== 删除单条阅读记录 =====
function deleteSingleRecord(btn) {
    const workId = btn.getAttribute('data-work-id');
    const filePath = btn.getAttribute('data-file-path');
    if (!workId && !filePath) return;

    const wrapper = btn.closest('.recent-card-wrapper');
    const title = wrapper ? (wrapper.dataset.title || '这条记录') : '这条记录';
    if (!confirm(`删除《${title}》的阅读记录？`)) return;

    const originalText = btn.textContent;
    btn.innerHTML = icon('loader', 'sm');
    btn.disabled = true;

    fetch('/api/delete_record', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ work_id: workId || '', file_path: filePath || '' })
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showNotification('已删除阅读记录', 'success');
                // 服务端已返回删除后的最新状态，前端就地更新，不再整页刷新
                if (typeof RecentReads !== 'undefined' && data.recent_total !== undefined) {
                    RecentReads.setRecordsFromServer(data);
                } else if (typeof RecentReads !== 'undefined') {
                    RecentReads.removeCard(workId);
                } else {
                    window.location.reload();
                }
            } else {
                showNotification(data.message || '删除失败', 'error');
                btn.textContent = originalText;
                btn.disabled = false;
            }
        })
        .catch(error => {
            console.error('删除失败:', error);
            showNotification('删除失败，请重试', 'error');
            btn.textContent = originalText;
            btn.disabled = false;
        });
}

// ===== 用户抽屉菜单（主页头部右上角：用户名/类型/配置/登出）=====
function initUserMenu() {
    const menu = document.getElementById('userMenu');
    const btn = document.getElementById('userMenuBtn');
    const dropdown = document.getElementById('userMenuDropdown');
    if (!menu || !btn || !dropdown) return;

    function setOpen(open) {
        dropdown.classList.toggle('active', open);
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    }

    btn.addEventListener('click', function (e) {
        e.stopPropagation();
        setOpen(!dropdown.classList.contains('active'));
    });

    // 点到菜单外：关闭
    document.addEventListener('click', function (e) {
        if (!menu.contains(e.target)) setOpen(false);
    });

    // Esc：关闭
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && dropdown.classList.contains('active')) setOpen(false);
    });

    // 点菜单项后关闭（配置直接跳转；登出有 confirm，点「取消」时菜单也已收起）
    dropdown.addEventListener('click', function (e) {
        if (e.target.closest('.user-menu-item')) setOpen(false);
    });
}

// ===== 「菜单」里的排序二级菜单 =====
function initUserMenuSort() {
    const toggle = document.getElementById('userMenuSortToggle');
    const panel = document.getElementById('userMenuSortPanel');
    if (!toggle || !panel) return;

    toggle.addEventListener('click', function (e) {
        // 必须阻止冒泡：initUserMenu 里有一条『点 .user-menu-item 就收起菜单』的委托，
        // 而父项为了复用样式也带着 .user-menu-item，不拦的话展开二级菜单的同时整个菜单被关掉。
        e.preventDefault();
        e.stopPropagation();
        const open = panel.classList.toggle('active');
        toggle.classList.toggle('open', open);
        toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });

    // 选排序项 = 普通链接跳转 + 服务端重排，这里不再做任何事。
    // 曾经在跳转前顺手把区块打开并切到「筛选与搜索」，结果变成"改个排序就把区块弹出来"，
    // 剑哥反馈多余 —— 排序只是改书架顺序，区块该藏着就藏着（想看得自己从菜单打开）。
}

// ===== 初始化 =====
document.addEventListener('DOMContentLoaded', () => {
    // common.js 已经处理了主题和背景轮播
    // 这里只初始化主页特有的功能
    initTabs();
    initUserMenu();
    initUserMenuSort();
    initTouchFeedback();
    checkScreenSizeAndDisplay();
    setTimeout(formatNovelTitlesAndHighlight, 200);
    if (typeof RecentReads !== 'undefined') RecentReads.init();
    if (typeof RandomNovel !== 'undefined') RandomNovel.init();

    // 优化 resize 事件
    window.addEventListener('resize', debounce(() => {
        checkScreenSizeAndDisplay();
        const isMobile = window.innerWidth <= 768;
        if (window._isMobile !== undefined && window._isMobile !== isMobile) {
            reloadWithSkeleton(window.location.href);
        }
        window._isMobile = isMobile;
    }, 300));

    window._isMobile = window.innerWidth <= 768;
});

// 监听动态加载的内容（「加载更多」、搜索/排序重渲染、删除卡片等都会重建 DOM）
let observer = null;

function initMutationObserver() {
    if (observer) {
        observer.disconnect();
    }

    observer = new MutationObserver(function () {
        formatNovelTitlesAndHighlight();
    });

    // 实际会被重建的容器是「最近阅读」的记录区（原来找的 .bookshelf-wrapper 并不存在）。
    // 仍然保留轮询：容器要等首屏渲染才出现，且每次重渲染只影响内容、容器本身不换。
    const container =
        document.getElementById('recentReadsTab') ||
        document.getElementById('recentGroups');

    if (container) {
        observer.observe(container, { childList: true, subtree: true });
        // 挂载后立刻先跑一次，处理已存在的元素
        formatNovelTitlesAndHighlight();
    }
}

// DOM 就绪后再初始化（而不是模块加载时）
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMutationObserver);
} else {
    initMutationObserver();
}

window.formatNovelTitles = formatNovelTitlesAndHighlight;

// ===== 扫描按钮绑定 =====
function bindScanButtons() {
    const scanBtn = document.getElementById('scanBtn');
    const scanFullBtn = document.getElementById('scanFullBtn');

    if (scanBtn) {
        const newScanBtn = scanBtn.cloneNode(true);
        scanBtn.parentNode.replaceChild(newScanBtn, scanBtn);

        newScanBtn.addEventListener('click', function (e) {
            e.preventDefault();
            console.log('增量扫描按钮被点击');
            startScan(false);
        });
    }

    if (scanFullBtn) {
        const newScanFullBtn = scanFullBtn.cloneNode(true);
        scanFullBtn.parentNode.replaceChild(newScanFullBtn, scanFullBtn);

        newScanFullBtn.addEventListener('click', function (e) {
            e.preventDefault();
            console.log('全量扫描按钮被点击');
            startScan(true);
        });
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindScanButtons);
} else {
    bindScanButtons();
}