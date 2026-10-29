// ============================================
// reader-core.js - 阅读器内容处理核心
// 依赖：common.js
// 使用场景：novel_detail.html, read_chapter.html
// ============================================

(function () {
    'use strict';

    // ==================== 全局变量 ====================
    let currentNovelImagePath = null;
    let emojiMap = {};
    let imageMap = {};

    // ===== 转义 HTML =====
    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // ==================== 表情映射 ====================
    async function loadEmojiMapping() {
        try {
            const [emojiRes, imageRes] = await Promise.all([
                fetch('/api/emoji/mapping'),
                fetch('/api/emoji/image-mapping')
            ]);
            emojiMap = await emojiRes.json();
            imageMap = await imageRes.json();
            console.log(`✅ 加载 emoji 映射: ${Object.keys(emojiMap).length} 个`);
            console.log(`✅ 加载图片表情映射: ${Object.keys(imageMap).length} 个`);
        } catch (err) {
            console.error('加载表情映射失败:', err);
            emojiMap = {};
            imageMap = {};
        }
    }

    // ==================== 表情转换 ====================
    function convertBracketEmoji(text, bracketLeft, bracketRight) {
        const escapedLeft = bracketLeft.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const escapedRight = bracketRight.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const pattern = new RegExp(`${escapedLeft}([\\s\\S]*?)${escapedRight}`, 'g');

        return text.replace(pattern, (match, content) => {
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = content;
            const plainName = tempDiv.textContent.trim();
            if (!plainName) return match;

            let name = plainName.replace(/(的)?表情$/, '').trim();
            if (!name || /^https?:\/\//i.test(name)) return match;

            if (imageMap[name]) {
                return `<img src="${imageMap[name]}" class="custom-emoji" alt="${name}">`;
            }
            if (emojiMap[name]) {
                return emojiMap[name];
            }
            return match;
        });
    }

    function convertTextEmoji(text) {
        if (!text) return text;
        let result = text;
        result = convertBracketEmoji(result, '（', '）');
        result = convertBracketEmoji(result, '(', ')');
        result = convertBracketEmoji(result, '【', '】');
        result = convertBracketEmoji(result, '[', ']');
        result = result.replace(/\[表情[：:]\s*([^\]]+)\]/g, (match, content) => {
            let name = content.replace(/(的)?表情$/, '').trim();
            if (imageMap[name]) return `<img src="${imageMap[name]}" class="custom-emoji" alt="${name}">`;
            if (emojiMap[name]) return emojiMap[name];
            return match;
        });
        return result;
    }

    // 提取单个表情转换逻辑为独立函数
    function convertSingleEmojiMark(name, originalMatch) {
        if (/^https?:\/\//i.test(name)) return originalMatch;

        if (imageMap[name]) {
            return `<img src="${imageMap[name]}" class="custom-emoji" alt="${name}">`;
        }
        if (emojiMap[name]) {
            return emojiMap[name];
        }
        return originalMatch;
    }

    // ==================== 本地媒体标记识别 ====================
    // 统一识别 [img:xxx] / [图:xxx] / [image:xxx]
    //          [video:xxx] / [vid:xxx] / [视频:xxx]
    //          [audio:xxx] / [aud:xxx] / [音乐:xxx] / [音频:xxx]
    const LOCAL_MEDIA_MARK_PATTERN = /^(img|图|image|video|vid|视频|audio|aud|音乐|音频)[：:]/i;

    function isLocalMediaMark(text) {
        return LOCAL_MEDIA_MARK_PATTERN.test(text);
    }

    // ==================== 高亮功能 ====================
    function highlightQuotesAndBrackets(text) {
        if (!text) return text;
        let result = text;

        // 双引号（中文）- 允许内容包含HTML标签
        if (result.includes('\u201C') || result.includes('\u201D')) {
            result = result.replace(/\u201C((?:[^\u201D<]|<[^>]+>)+)\u201D/g,
                '<span class="highlight-quote-double">\u201C$1\u201D</span>');
        }

        // 日式括号 - 允许内容包含HTML标签
        if (result.includes('\u300C') || result.includes('\u300D')) {
            result = result.replace(/\u300C((?:[^\u300D<]|<[^>]+>)+)\u300D/g,
                '<span class="highlight-quote-double">\u300C$1\u300D</span>');
        }

        // 单引号（中文）- 允许内容包含HTML标签
        if (result.includes('\u2018') || result.includes('\u2019')) {
            result = result.replace(/[\u2018\u2019]((?:[^\u2019<]|<[^>]+>)+)[\u2018\u2019]/g,
                '<span class="highlight-quote-single">\u2018$1\u2019</span>');
        }

        // 英文单引号 - 允许内容包含HTML标签
        if (result.includes("'")) {
            result = result.replace(/'((?:[^'<]|<[^>]+>)+)'/g,
                '<span class="highlight-quote-single">\'$1\'</span>');
        }

        // 日式双括号 - 允许内容包含HTML标签
        if (result.includes('\u300E') || result.includes('\u300F')) {
            result = result.replace(/\u300E((?:[^\u300F<]|<[^>]+>)+)\u300F/g,
                '<span class="highlight-quote-single">\u300E$1\u300F</span>');
        }

        // 中文括号（）- 跨行支持，保护 <br> 标签
        if (result.includes('\uFF08') || result.includes('\uFF09')) {
            result = result.replace(/\uFF08((?:[^\uFF08\uFF09]|<br>|<[^>]+>)+)\uFF09/gi, (match, p1) => {
                if (p1.includes('http') || p1.includes('<a ')) return match;
                // 保留 <br> 标签，不转义
                return '<span class="highlight-bracket">\uFF08' + p1 + '\uFF09</span>';
            });
        }

        // 英文括号 - 跨行支持，保护 <br> 标签
        if (result.includes('(') || result.includes(')')) {
            result = result.replace(/\(((?:[^()]|<br>|<[^>]+>)+)\)/gi, (match, p1) => {
                if (p1.includes('http') || p1.includes('<a ')) return match;
                return '<span class="highlight-bracket">(' + p1 + ')</span>';
            });
        }

        // 方括号【】- 跨行支持，保护 <br> 标签
        if (result.includes('\u3010') || result.includes('\u3011')) {
            result = result.replace(/\u3010((?:[^\u3011]|<br>|<[^>]+>)+)\u3011/gi, (match, p1) => {
                if (p1.includes('http') || p1.includes('<a ')) return match;
                return '<span class="highlight-square-bracket">\u3010' + p1 + '\u3011</span>';
            });
        }

        // 半角方括号 [] - 跨行支持，跳过图片/视频/音频标记，保护 <br> 标签
        if (result.includes('[') || result.includes(']')) {
            result = result.replace(/\[((?:[^\[\]]|<br>|<[^>]+>)+)\]/gi, (match, p1) => {
                if (isLocalMediaMark(p1)) return match;
                if (p1.includes('http') || p1.includes('<a ')) return match;
                return '<span class="highlight-square-bracket-1">[' + p1 + ']</span>';
            });
        }

        // 全角方括号［］- 跨行支持，保护 <br> 标签（U+FF3B / U+FF3D）
        if (result.includes('［') || result.includes('］')) {
            result = result.replace(/［((?:[^］]|<br>|<[^>]+>)+)］/gi, (match, p1) => {
                if (p1.includes('http') || p1.includes('<a ')) return match;
                return '<span class="highlight-square-bracket-1">［' + p1 + '］</span>';
            });
        }

        // 中空方括号〖〗- 跨行支持，保护 <br> 标签
        if (result.includes('\u3016') || result.includes('\u3017')) {
            result = result.replace(/\u3016((?:[^\u3017]|<br>|<[^>]+>)+)\u3017/gi, (match, p1) => {
                if (p1.includes('http') || p1.includes('<a ')) return match;
                return '<span class="highlight-hollow-bracket">\u3016' + p1 + '\u3017</span>';
            });
        }

        // 书名号《》- 跨行支持，保护 <br> 标签
        if (result.includes('\u300A') || result.includes('\u300B')) {
            result = result.replace(/\u300A((?:[^\u300B]|<br>|<[^>]+>)+)\u300B/gi, (match, p1) => {
                if (p1.includes('http') || p1.includes('<a ')) return match;
                return '<span class="highlight-book">\u300A' + p1 + '\u300B</span>';
            });
        }

        return result;
    }

    // ==================== 图片链接转换 ====================

    // 常见的图片扩展名
    const IMAGE_EXTENSIONS = /\.(jpg|jpeg|png|gif|bmp|webp|svg)(\?.*)?$/i;

    // 判断是否是图片链接
    function isImageUrl(url) {
        if (IMAGE_EXTENSIONS.test(url)) return true;
        if (/[./](image|img|photo|pic|picture)[./]/i.test(url)) return true;
        return false;
    }

    // 创建带 fallback 的图片
    function createImageWithFallback(url) {
        const imgId = 'img_' + Math.random().toString(36).substr(2, 9);
        const safeUrl = url.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

        // 🔥 和老版本一样，紧凑一行，无换行无缩进
        return '<span class="image-wrapper" id="' + imgId + '-wrapper"><img src="' + safeUrl + '" class="inline-image" referrerpolicy="no-referrer" loading="lazy" data-img-id="' + imgId + '" data-fallback-url="' + safeUrl.replace(/&quot;/g, '&#34;') + '" alt="图片"><div class="image-fallback-placeholder" id="' + imgId + '-placeholder" style="display:none;"><img class="fallback-image" src="/static/images/image-placeholder.svg" alt="图片加载失败"><a href="' + safeUrl + '" target="_blank" rel="noopener noreferrer" class="fallback-link">查看原图</a></div></span>';
    }

    // URL 格式化函数
    function formatUrlForDisplay(url) {
        try {
            // 🔥 修复：先把 &amp; 替换为 &
            const decodedUrl = url.replace(/&amp;/g, '&');
            console.log('🔍 解码后 URL:', decodedUrl);
            
            const parsed = new URL(decodedUrl);
            let domain = parsed.hostname.replace(/^www\./, '');
            let mainDomain = domain.replace(/\.(com|org|net|cn|io|tv|me|cc|xyz|top|club|vip|gov|edu|mil|info|biz)$/i, '');
            if (mainDomain.includes('.')) {
                mainDomain = mainDomain.split('.').pop();
            }
            
            // 🔥 从解码后的 URL 中提取 tid
            const tidMatch = decodedUrl.match(/[?&]tid=(\d+)/i);
            if (tidMatch) {
                return `${mainDomain}/${tidMatch[1]}`;
            }
            
            const path = parsed.pathname;
            
            // 🔥 1. 优先匹配 thread-数字(-数字) 格式 (sis001风格)
            let numMatch = path.match(/thread-(\d+(?:-\d+)*)/i);
            if (numMatch) {
                return `${mainDomain}/${numMatch[1]}`;
            }
            
            // 🔥 2. 匹配常见的帖子ID格式：路径最后的数字（至少5位，避免匹配年份/日期）
            //    比如 /htm_data/1412/20/1281755.html 提取 1281755
            numMatch = path.match(/\/(\d{5,})(?:\.html|\/|$)/);
            if (numMatch) {
                return `${mainDomain}/${numMatch[1]}`;
            }
            
            // 🔥 3. 匹配 /数字/数字 格式（提取最后一个数字）
            numMatch = path.match(/\/(\d+)\/(\d+)(?:\.html|\/|$)/);
            if (numMatch) {
                // 如果最后一个数字 >= 10000，认为是帖子ID
                if (parseInt(numMatch[2]) >= 10000) {
                    return `${mainDomain}/${numMatch[2]}`;
                }
                // 否则返回 第一个数字/第二个数字
                return `${mainDomain}/${numMatch[1]}/${numMatch[2]}`;
            }
            
            // 🔥 4. 最后尝试匹配普通的 /数字 格式
            numMatch = path.match(/\/(\d+)(?:\/|$)/);
            if (numMatch) {
                return `${mainDomain}/${numMatch[1]}`;
            }
            
            return mainDomain;
        } catch (e) {
            return url.length > 40 ? url.substring(0, 37) + '…' : url;
        }
    }

    // 转换图片链接
    function convertImageLinks(text) {
        if (!text || !text.includes('http')) return text;
        const urlPattern = /https?:\/\/[a-zA-Z0-9][-a-zA-Z0-9._~:/?#[\]@!$&'()*+,;=%]+/g;

        return text.replace(urlPattern, (match) => {
            let url = match;

            const openBrackets = (url.match(/[\[(【（]/g) || []).length;
            const closeBrackets = (url.match(/[\])】）]/g) || []).length;
            while (closeBrackets > openBrackets) {
                const lastChar = url.charAt(url.length - 1);
                if (/[)\]】）]/.test(lastChar)) {
                    url = url.slice(0, -1);
                } else {
                    break;
                }
            }

            const allowedEndChars = /[a-zA-Z0-9\/?=&%#_\-~]$/;
            while (url.length > 0 && !allowedEndChars.test(url.charAt(url.length - 1))) {
                const lastChar = url.charAt(url.length - 1);
                if (/[,.，。、；;:：!！?？'"]/.test(lastChar)) {
                    url = url.slice(0, -1);
                } else {
                    break;
                }
            }

            if (url.length < 10) return match;

            try {
                new URL(url);
            } catch (e) {
                url = url.replace(/[^a-zA-Z0-9\/?=&%#_\-~]+$/, '');
            }

            if (isImageUrl(url)) {
                return createImageWithFallback(url);
            }

            const displayText = formatUrlForDisplay(url);

            return `<a href="${url}" target="_blank" rel="noopener noreferrer" data-converted="true" class="pretty-link" title="${url}">${displayText}</a>`;
        });
    }

    // ==================== 配图功能 ====================

    // 异步初始化本地配图
    async function initLocalImagesAsync(filePath) {
        return new Promise(async (resolve) => {
            console.log('🔍 initLocalImagesAsync 被调用，filePath:', filePath);

            // filePath 由后端 url_for 编码一次（中文原样编码成 %XX）。
            // 老链接里可能是被编码过两次的 %25XX，所以这里解码一次；
            // 文件名本身带 % 时 decodeURIComponent 会抛 URIError，兜底用原值。
            let decodedPath = filePath;
            try {
                decodedPath = decodeURIComponent(filePath);
            } catch (err) {
                console.warn('配图路径解码失败，按原值处理:', filePath);
            }
            const normalizedPath = decodedPath.replace(/\\/g, '/');
            let fileName, dirPath;

            if (normalizedPath.startsWith('/novels/')) {
                dirPath = '/novels';
                fileName = normalizedPath.replace('/novels/', '').replace(/\.(txt|TXT)$/, '');
            } else {
                let novelDir = '';
                try {
                    const configRes = await fetch('/config/get');
                    const config = await configRes.json();
                    novelDir = config.novel_dir || '';
                } catch (err) { }

                let fullPath = normalizedPath;
                if (fullPath.includes('/') || fullPath.includes('\\')) {
                    // 形如 novels/xxx.txt：后端渲染 file_path 时做了 lstrip('/')，
                    // 前导斜杠被去掉。若不补回，下面算出的配图目录是相对路径
                    // （相对进程 CWD），后端 os.path.exists 永远找不到，
                    // 全部标记都会显示"未找到配图文件夹"。
                    // Windows 盘符路径（C:/...）本身就是绝对路径，不补。
                    if (!fullPath.startsWith('/') && !/^[A-Za-z]:/.test(fullPath)) {
                        fullPath = '/' + fullPath;
                    }
                } else if (novelDir) {
                    // 纯文件名：拼到小说目录下
                    let cleanNovelDir = novelDir.replace(/\\/g, '/');
                    if (cleanNovelDir.endsWith('/')) cleanNovelDir = cleanNovelDir.slice(0, -1);
                    fullPath = `${cleanNovelDir}/${decodedPath}`;
                }
                fileName = fullPath.split('/').pop().replace(/\.(txt|TXT)$/, '');
                dirPath = fullPath.substring(0, fullPath.lastIndexOf('/'));
            }

            const possibleFolders = [
                `${dirPath}/${fileName}_images`,
                `${dirPath}/${fileName}_配图`,
                `${dirPath}/${fileName}`,
            ];

            try {
                const response = await fetch('/api/check_image_folder', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ folders: possibleFolders })
                });

                const data = await response.json();

                if (data.exists) {
                    currentNovelImagePath = data.path;
                    console.log('✅ 找到配图文件夹:', currentNovelImagePath);
                } else {
                    console.log('⚠️ 未找到配图文件夹');
                }
            } catch (err) {
                console.error('❌ 检查配图文件夹失败:', err);
            }

            resolve();
        });
    }

    // 解析图片参数
    function parseImageParams(params) {
        const result = {
            width: null,
            align: 'center',
            caption: null
        };

        if (!params) return result;

        let captionMatch = params.match(/caption=([^=]+?)(?=\s+(?:w|width|align)=|$)/i);
        if (captionMatch && captionMatch[1]) {
            let captionValue = captionMatch[1].trim();
            captionValue = captionValue.replace(/\s+$/, '');
            result.caption = captionValue;
            params = params.replace(/caption=[^=]+?(?=\s+(?:w|width|align)=|$)/i, '');
        }

        const paramPattern = /(\w+)=([^\s\]]+)/g;
        let match;
        while ((match = paramPattern.exec(params)) !== null) {
            const key = match[1].toLowerCase();
            const value = match[2];
            if (key === 'w' || key === 'width') {
                result.width = value;
            } else if (key === 'align') {
                result.align = value;
            }
        }

        return result;
    }

    // 创建本地图片元素
    function createLocalImageElement(folderPath, imageName, params, originalText) {
        const imgId = 'local_' + Math.random().toString(36).substr(2, 9);
        const imageUrl = `/api/local_image?folder=${encodeURIComponent(folderPath)}&name=${encodeURIComponent(imageName)}`;
        const widthStyle = params.width ? `max-width: ${params.width}px;` : '';

        let alignStyle = 'margin-left: auto; margin-right: auto;';
        let imgAlignStyle = 'display: block; margin: 0 auto;';
        if (params.align === 'left') {
            alignStyle = 'margin-left: 0; margin-right: auto;';
            imgAlignStyle = 'display: block;';
        } else if (params.align === 'right') {
            alignStyle = 'margin-left: auto; margin-right: 0;';
            imgAlignStyle = 'display: block;';
        }

        // 🔥 修复：trim() 去掉首尾空格
        let customCaption = params.caption || '';
        let caption = customCaption ? customCaption.trim() : '';
        const altText = caption || imageName;

        const figure = document.createElement('figure');
        figure.className = 'local-image-figure';
        figure.style.cssText = alignStyle;

        const img = document.createElement('img');
        img.src = imageUrl;
        img.className = 'local-image loaded';
        img.alt = altText;
        img.loading = 'lazy';
        img.style.cssText = widthStyle + imgAlignStyle + 'max-width:100%;height:auto;';

        img.onerror = function () {
            this.style.display = 'none';
            const placeholder = document.createElement('div');
            placeholder.className = 'local-image-error';
            placeholder.innerHTML = `
                <span class="error-icon">${icon('image', 'xl')}</span>
                <p>图片 "${escapeHtml(imageName)}"未找到</p>
                <p class="error-hint">请将图片放入配图文件夹</p>
                <button class="open-image-folder-btn"onclick="window.openImageFolder('${folderPath.replace(/'/g, "\\'")}')">
                    ${icon('folder-open', 'sm')} 打开配图文件夹
                </button>
            `;
            this.parentNode.appendChild(placeholder);
        };

        figure.appendChild(img);

        if (caption) {
            const figcaption = document.createElement('figcaption');
            figcaption.className = 'local-image-caption';
            figcaption.textContent = caption;
            // 🔥 内联样式强制取消缩进
            figcaption.style.textIndent = '0';
            figcaption.style.textAlign = 'center';
            figure.appendChild(figcaption);
        }

        return figure.outerHTML;
    }

    // 转换本地图片标记
    function convertLocalImages(text) {
        if (!text) return text;
        const localImagePattern = /\[(img|图|image)[：:]\s*([^\s\]]+)(?:\s+([^\]]*))?\]/gi;

        return text.replace(localImagePattern, (match, type, imageName, params) => {
            if (!currentNovelImagePath) {
                return `<span class="local-image-missing" title="未找到配图文件夹">${icon('camera', 'sm')} [${imageName}]</span>`;
            }
            const styleParams = parseImageParams(params);
            return createLocalImageElement(currentNovelImagePath, imageName, styleParams, match);
        });
    }

    // 查找相似的文件名
    async function findSimilarImage(folderPath, targetName) {
        try {
            const response = await fetch('/api/list_image_folder', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ folder: folderPath })
            });

            const data = await response.json();
            if (!data.files || data.files.length === 0) return null;

            const targetLower = targetName.toLowerCase();

            const exactMatch = data.files.find(f => {
                const name = f.replace(/\.[^.]+$/, '').toLowerCase();
                return name === targetLower;
            });
            if (exactMatch) return exactMatch;

            const containMatch = data.files.find(f => {
                const name = f.replace(/\.[^.]+$/, '').toLowerCase();
                return name.includes(targetLower) || targetLower.includes(name);
            });
            if (containMatch) return containMatch;

            return null;
        } catch (err) {
            console.error('列出文件夹失败:', err);
            return null;
        }
    }

    // 打开配图文件夹
    function openImageFolder(folderPath) {
        fetch('/api/open_folder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: folderPath })
        });
    }

    // ==================== 本地视频转换功能 ====================

    // 解析视频参数
    function parseVideoParams(params) {
        const result = {
            width: null,
            align: 'center',
            caption: null,
            autoplay: false,
            loop: false,
            muted: false
        };

        if (!params) return result;

        const captionPattern = /caption=([^\]]+)/i;
        const captionMatch = params.match(captionPattern);
        if (captionMatch && captionMatch[1]) {
            result.caption = captionMatch[1].trim();
            params = params.replace(captionPattern, '');
        }

        const paramPattern = /(\w+)=([^\s\]]+)/g;
        let match;
        while ((match = paramPattern.exec(params)) !== null) {
            const key = match[1].toLowerCase();
            const value = match[2];

            if (key === 'w' || key === 'width') {
                result.width = value;
            } else if (key === 'align') {
                result.align = value;
            } else if (key === 'autoplay') {
                result.autoplay = value === 'true' || value === '1';
            } else if (key === 'loop') {
                result.loop = value === 'true' || value === '1';
            } else if (key === 'muted') {
                result.muted = value === 'true' || value === '1';
            }
        }

        return result;
    }

    // 创建本地视频元素
    function createLocalVideoElement(folderPath, videoName, params) {
        const videoId = 'local_video_' + Math.random().toString(36).substr(2, 9);
        const videoUrl = `/api/local_video?folder=${encodeURIComponent(folderPath)}&name=${encodeURIComponent(videoName)}`;

        const posterCandidates = [
            videoName,
            `${videoName}_poster`,
            `${videoName}_cover`,
            videoName.replace(/_\d+$/, ''),
            videoName.replace(/[0-9]+$/, ''),
        ];

        let posterUrl = '';
        if (posterCandidates.length > 0 && posterCandidates[0]) {
            posterUrl = `/api/local_image?folder=${encodeURIComponent(folderPath)}&name=${posterCandidates[0]}`;
        }

        const widthStyle = params.width ? `max-width: ${params.width}px;` : '';

        let alignStyle = 'margin-left: auto; margin-right: auto;';
        if (params.align === 'left') {
            alignStyle = 'margin-left: 0; margin-right: auto;';
        } else if (params.align === 'right') {
            alignStyle = 'margin-left: auto; margin-right: 0;';
        }

        const attrs = [
            'controls',
            'preload="metadata"',
            ` style="width:100%;max-width:100%;border-radius:12px;box-shadow:0 4px 16px rgba(0,0,0,0.15);background:#000;display:block;"`
        ];

        if (posterUrl) {
            attrs.push(` poster="${posterUrl}"`);
        }

        if (params.autoplay) attrs.push('autoplay');
        if (params.loop) attrs.push('loop');
        if (params.muted) attrs.push('muted');

        let html = '<figure class="local-video-figure"';
        if (alignStyle || widthStyle) {
            html += ` style="${alignStyle} ${widthStyle}"`;
        }
        html += '>';
        html += `<video ${attrs.join(' ')}>`;
        html += `<source src="${videoUrl}" type="video/mp4">`;
        html += '您的浏览器不支持视频播放';
        html += '</video>';

        if (params.caption) {
            html += `<figcaption class="local-video-caption">${params.caption}</figcaption>`;
        }

        html += '</figure>';
        return html;
    }

    // 转换本地视频标记
    function convertLocalVideos(text) {
        if (!text) return text;
        if (!currentNovelImagePath) {
            const videoPattern = /\[(video|vid|视频)[：:]\s*([^\s\]]+)(?:\s+([^\]]*))?\]/gi;
            return text.replace(videoPattern, (match, type, videoName) => {
                return `<span class="local-video-missing">${icon('film', 'sm')} [${videoName}]</span>`;
            });
        }

        const localVideoPattern = /\[(video|vid|视频)[：:]\s*([^\s\]]+)(?:\s+([^\]]*))?\]/gi;
        return text.replace(localVideoPattern, (match, type, videoName, params) => {
            const styleParams = parseVideoParams(params);
            return createLocalVideoElement(currentNovelImagePath, videoName, styleParams);
        });
    }

    // ==================== 本地音频转换功能 ====================

    // 解析音频参数
    function parseAudioParams(params) {
        const result = {
            caption: null,
            autoplay: false,
            loop: false,
            muted: false,
            volume: 1.0,
            width: null,
            align: 'center'
        };

        if (!params) return result;

        const captionPattern = /caption=([^\]]+)/i;
        const captionMatch = params.match(captionPattern);
        if (captionMatch && captionMatch[1]) {
            result.caption = captionMatch[1].trim();
            params = params.replace(captionPattern, '');
        }

        const paramPattern = /(\w+)=([^\s\]]+)/g;
        let match;
        while ((match = paramPattern.exec(params)) !== null) {
            const key = match[1].toLowerCase();
            const value = match[2];

            if (key === 'w' || key === 'width') {
                result.width = value;
            } else if (key === 'align') {
                result.align = value;
            } else if (key === 'autoplay') {
                result.autoplay = value === 'true' || value === '1';
            } else if (key === 'loop') {
                result.loop = value === 'true' || value === '1';
            } else if (key === 'volume') {
                result.volume = parseFloat(value);
                if (isNaN(result.volume)) result.volume = 1.0;
                result.volume = Math.max(0, Math.min(1, result.volume));
            }
        }

        return result;
    }

    // 创建本地音频元素
    function createLocalAudioElement(folderPath, audioName, params) {
        const audioId = 'local_audio_' + Math.random().toString(36).substr(2, 9);
        const audioUrl = `/api/local_audio?folder=${encodeURIComponent(folderPath)}&name=${encodeURIComponent(audioName)}`;

        const widthStyle = params.width ? `max-width: ${params.width}px;` : '';

        let alignStyle = 'margin-left: auto; margin-right: auto;';
        if (params.align === 'left') {
            alignStyle = 'margin-left: 0; margin-right: auto;';
        } else if (params.align === 'right') {
            alignStyle = 'margin-left: auto; margin-right: 0;';
        }

        const attrs = [
            'controls',
            'preload="metadata"',
            ` style="width:100%;border-radius:8px;"`
        ];

        if (params.autoplay) attrs.push('autoplay');
        if (params.loop) attrs.push('loop');
        if (params.volume !== 1.0) attrs.push(`volume="${params.volume}"`);

        let html = '<figure class="local-audio-figure"';
        if (alignStyle || widthStyle) {
            html += ` style="${alignStyle} ${widthStyle}"`;
        }
        html += '>';
        html += `<audio ${attrs.join(' ')}>`;
        html += `<source src="${audioUrl}" type="audio/mpeg">`;
        html += '您的浏览器不支持音频播放';
        html += '</audio>';

        if (params.caption) {
            html += `<figcaption class="local-audio-caption">${params.caption}</figcaption>`;
        }

        html += '</figure>';
        return html;
    }

    // 转换本地音频标记
    function convertLocalAudios(text) {
        if (!text) return text;
        if (!currentNovelImagePath) {
            const audioPattern = /\[(audio|aud|音乐|音频)[：:]\s*([^\s\]]+)(?:\s+([^\]]*))?\]/gi;
            return text.replace(audioPattern, (match, type, audioName) => {
                return `<span class="local-audio-missing">${icon('music', 'sm')} [${audioName}]</span>`;
            });
        }

        const localAudioPattern = /\[(audio|aud|音乐|音频)[：:]\s*([^\s\]]+)(?:\s+([^\]]*))?\]/gi;
        return text.replace(localAudioPattern, (match, type, audioName, params) => {
            const styleParams = parseAudioParams(params);
            return createLocalAudioElement(currentNovelImagePath, audioName, styleParams);
        });
    }

    // ==================== 完结标记转换（完整版）====================

    // 完结标记配置
    const ENDING_MARKS = {
        chinese: [
            '全文完', '全书完', '全剧终', '本文完', '本书完', '本篇完', '完结', '完本', '完',
        ],
        brackets: [
            '全文完', '全书完', '全剧终', '完结', '本书完', '正文完', '本篇完', '完本', '完',
            'THE END', 'END',
        ],
        english: ['THE END', 'END']
    };

    // 自动生成带各种括号的完结标记
    function generateBracketedEndings() {
        const brackets = [
            ['（', '）'], ['[', ']'], ['【', '】'],
            ['《', '》'], ['——', '——'], ['－', '－'],
        ];
        const endings = [];
        for (const mark of ENDING_MARKS.brackets) {
            endings.push(mark);
            for (const [left, right] of brackets) {
                endings.push(`${left}${mark}${right}`);
            }
        }
        return endings;
    }

    // 获取完整的完结标记列表
    function getEndingMarkList() {
        const marks = [
            ...ENDING_MARKS.chinese,
            ...generateBracketedEndings(),
            ...ENDING_MARKS.english
        ];
        return [...new Map(marks.map(m => [m.toLowerCase(), m])).values()];
    }

    // 构建正则表达式
    function buildEndingPattern() {
        const marks = getEndingMarkList();
        const escapeRegex = (str) => str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const escapedMarks = marks.map(escapeRegex);
        escapedMarks.sort((a, b) => b.length - a.length);
        const pattern = `^(\\s*(${escapedMarks.join('|')})\\s*)$`;
        return new RegExp(pattern, 'i');
    }

    // 完结标记转换函数
    function convertEndingMark(text) {
        if (!text) return text;

        // 提取纯文本用于匹配（去除 HTML 标签）
        const tempDiv = document.createElement('div');
        tempDiv.innerHTML = text;
        const trimmed = tempDiv.textContent.trim();

        const pattern = buildEndingPattern();
        if (pattern.test(trimmed)) {
            return `<div class="ending-wrapper"><img src="/static/images/end.svg" alt="全文完" class="ending-image"></div>`;
        }
        return text;
    }

    // ==================== 图片、表情、链接转换、高亮（完整版）====================
    // 转换所有内容（完整版）
    function convertAllTextEmoji() {
        const readingContent = document.getElementById('readingContent');
        const lines = document.querySelectorAll('.content-line');

        if (!readingContent || lines.length === 0) return;

        console.log(`📝 开始处理 ${lines.length} 行...`);
        console.log('🔍 currentNovelImagePath =', currentNovelImagePath);

        const startTime = Date.now();
        const container = document.createElement('div');
        let convertedCount = 0;

        lines.forEach(line => {
            const newLine = document.createElement('div');
            newLine.className = line.className;

            if (line.hasAttribute('data-type')) {
                newLine.setAttribute('data-type', line.getAttribute('data-type'));
            }

            // ===== 关键修复：如果已有转换内容（图片、链接、高亮、表情），直接保留 =====
            if (line.querySelector('a[data-converted="true"], .inline-image, .local-image-figure, .custom-emoji, .highlight-quote-double, .highlight-quote-single, .highlight-bracket, .highlight-square-bracket, .highlight-book')) {
                newLine.innerHTML = line.innerHTML;
                container.appendChild(newLine);
                return;
            }

            const originalText = line.textContent;
            let convertedText = originalText;

            // ===== 第一步：先处理本地媒体（图片、视频、音频）=====
            let mediaPlaceholders = [];

            // 处理本地图片
            convertedText = convertedText.replace(/\[(img|图|image)[：:]\s*([^\s\]]+)(?:\s+([^\]]*))?\]/gi, (match, type, imageName, params) => {
                if (!currentNovelImagePath) {
                    return `<span class="local-image-missing" title="未找到配图文件夹">${icon('camera', 'sm')} [${imageName}]</span>`;
                }
                const styleParams = parseImageParams(params);
                const html = createLocalImageElement(currentNovelImagePath, imageName, styleParams, match);
                const placeholder = `__MEDIA_${mediaPlaceholders.length}__`;
                mediaPlaceholders.push(html);
                return placeholder;
            });

            // 处理本地视频
            convertedText = convertedText.replace(/\[(video|vid|视频)[：:]\s*([^\s\]]+)(?:\s+([^\]]*))?\]/gi, (match, type, videoName, params) => {
                if (!currentNovelImagePath) {
                    return `<span class="local-video-missing">${icon('film', 'sm')} [${videoName}]</span>`;
                }
                const styleParams = parseVideoParams(params);
                const html = createLocalVideoElement(currentNovelImagePath, videoName, styleParams);
                const placeholder = `__MEDIA_${mediaPlaceholders.length}__`;
                mediaPlaceholders.push(html);
                return placeholder;
            });

            // 处理本地音频
            convertedText = convertedText.replace(/\[(audio|aud|音乐|音频)[：:]\s*([^\s\]]+)(?:\s+([^\]]*))?\]/gi, (match, type, audioName, params) => {
                if (!currentNovelImagePath) {
                    return `<span class="local-audio-missing">${icon('music', 'sm')} [${audioName}]</span>`;
                }
                const styleParams = parseAudioParams(params);
                const html = createLocalAudioElement(currentNovelImagePath, audioName, styleParams);
                const placeholder = `__MEDIA_${mediaPlaceholders.length}__`;
                mediaPlaceholders.push(html);
                return placeholder;
            });

            // ===== 第二步：处理其他文本转换 =====
            convertedText = convertImageLinks(convertedText);
            convertedText = convertEndingMark(convertedText);
            convertedText = highlightQuotesAndBrackets(convertedText);
            convertedText = convertTextEmoji(convertedText);

            // ===== 第三步：还原媒体占位符 =====
            mediaPlaceholders.forEach((html, index) => {
                convertedText = convertedText.replace(`__MEDIA_${index}__`, html);
            });

            // ===== 第四步：如果有变化才更新 =====
            if (originalText !== convertedText) {
                convertedCount++;
            }
            newLine.innerHTML = convertedText;
            container.appendChild(newLine);
        });

        readingContent.innerHTML = container.innerHTML;
        console.log(`✅ 转换完成 (${convertedCount}行有变化), 耗时: ${Date.now() - startTime}ms`);

        // 清理图片行多余的空白节点
        setTimeout(() => {
            const content = document.getElementById('readingContent');
            const lines = content.querySelectorAll('.content-line');
            lines.forEach(line => {
                const hasImage = line.querySelector('.image-wrapper, .local-image-figure');
                if (hasImage) {
                    const walker = document.createTreeWalker(line, NodeFilter.SHOW_TEXT);
                    const nodesToRemove = [];
                    while (walker.nextNode()) {
                        if (walker.currentNode.textContent.trim() === '') {
                            nodesToRemove.push(walker.currentNode);
                        }
                    }
                    nodesToRemove.forEach(node => node.remove());
                    line.style.lineHeight = 'normal';
                    line.style.textIndent = '0';
                    line.style.marginBottom = '2px';
                }
            });
        }, 50);
    }

    // ==================== 暴露 API ====================
    window.loadEmojiMapping = loadEmojiMapping;
    window.convertTextEmoji = convertTextEmoji;
    window.convertSingleEmojiMark = convertSingleEmojiMark;
    window.highlightQuotesAndBrackets = highlightQuotesAndBrackets;
    window.convertImageLinks = convertImageLinks;
    window.isImageUrl = isImageUrl;
    window.createImageWithFallback = createImageWithFallback;
    window.formatUrlForDisplay = formatUrlForDisplay;
    window.initLocalImagesAsync = initLocalImagesAsync;
    window.convertLocalImages = convertLocalImages;
    window.convertLocalVideos = convertLocalVideos;
    window.convertLocalAudios = convertLocalAudios;
    window.findSimilarImage = findSimilarImage;
    window.openImageFolder = openImageFolder;
    window.convertAllTextEmoji = convertAllTextEmoji;
    window.convertEndingMark = convertEndingMark;
    window.getCurrentImagePath = () => currentNovelImagePath;
    console.log('✅ reader-core.js 已加载（完整版）');
})();