// ========== 从 meta 标签读取所有后端数据 ==========
const APP_DATA = document.getElementById('app-data').dataset;
const USER_ROLE = APP_DATA.userRole;
// 用户标识改为不可猜的 key（不再是明文密码）
const USER_KEY = APP_DATA.userKey;
const IS_ADMIN = APP_DATA.isAdmin === 'true';

// ========== 安全调用包装 ==========
// 防止 common.js 未加载导致按钮点击后无响应

function safeNotify(msg, type = 'info') {
    try {
        if (typeof showNotification === 'function') {
            showNotification(msg, type);  // ← 改成 showNotification
        } else {
            console.log(`[${type}] ${msg}`);
            if (type === 'error') {
                alert(msg);
            }
        }
    } catch (e) {
        console.error('safeNotify 调用失败:', e, '原始消息:', msg);
    }
}
function safeLoading(show) {
    try {
        if (typeof showLoading === 'function') {
            showLoading(show);
        } else {
            // 降级：直接操作遮罩元素（如果存在）
            const overlay = document.getElementById('loadingOverlay');
            if (overlay) {
                overlay.style.display = show ? 'flex' : 'none';
            }
        }
    } catch (e) {
        console.error('safeLoading 调用失败:', e);
    }
}

// ========== 字体名称映射 ==========
const FONT_NAME_MAP = {
    'system-ui': '系统默认',
    "'LXGWWenKaiMono-Medium', '霞鹜文楷等宽 Medium', '霞鹜文楷内置', sans-serif": '📱 霞鹜文楷（内置·8.6MB）',
    "'CEJK01-9128-W04', '仓耳今楷01-9128-W04', '仓耳今楷内置', serif": '📱 仓耳今楷（内置·3.4MB）',
    "'HarmonyOS Sans SC', '鸿蒙黑体-HarmonyOS Sans SC', '鸿蒙黑体内置', sans-serif": '📱 鸿蒙黑体（内置·4.1MB）',
    "'WEILAIYUANMedium', '未来圆SC Medium', 'WeiLaiYuanSC', '未来圆内置', sans-serif": '📱 未来圆（内置·8.1MB）',
    "'京華老宋体v3.0', 'KingHwaOldSong', 'Songti SC', 'SimSun', '宋体', serif": '京華老宋体（系统字体）',
    "'HYWenHei-55W', '汉仪文黑-55W', '汉仪文黑内置', sans-serif": '📱 汉仪文黑（内置·1.5MB）',
    "'LantingXiHei-GBK', '兰亭羲之黑内置', sans-serif": '📱 兰亭羲之黑（内置·1.6MB）',
    "'FZDaBiaoSong', '方正大标宋内置', serif": '📱 方正大标宋（内置·1.4MB）',
    "'FZFangSong', '方正仿宋内置', serif": '📱 方正仿宋（内置·1.5MB）',
    "'FZKaiTi', '方正楷体内置', serif": '📱 方正楷体（内置·1.6MB）',
    "'汉仪润圆-55简', '汉仪润圆-55', sans-serif": '汉仪润圆',
    "'Microsoft YaHei', sans-serif": '微软雅黑',
    "'Songti SC', 'SimSun', serif": '宋体',
    "'KaiTi', '楷体', serif": '楷体',
    "'STKaiti', serif": '华文楷体',
    "'华文细黑', serif": '华文细黑',
    "'方正准圆_GBK', serif": '方正准圆_GBK',
    "'方正楷体_GBK', serif": '方正楷体_GBK',
    "'方正兰亭中黑_GBK', serif": '方正兰亭中黑_GBK'
};
// ========== 格式化主题名称 ==========
function formatThemeName(theme) {
    if (!theme) return '未设置';
    const themeMap = {
        'dark': '' + icon('moon', 'sm') + '暗色主题',
        'light': '' + icon('sun', 'sm') + '亮色主题',
        'auto': '' + icon('refresh-cw', 'sm') + '跟随系统'
    };
    return themeMap[theme] || theme;
}
// ========== 格式化字体名称 ==========
function formatFontName(fontFamily) {
    if (!fontFamily || fontFamily === '未设置') return '未设置';
    if (FONT_NAME_MAP[fontFamily]) {
        return FONT_NAME_MAP[fontFamily];
    }
    const match = fontFamily.match(/'([^']+)'/g);
    if (match && match.length >= 2) {
        return match[1].replace(/'/g, '');
    }
    if (match && match.length >= 1) {
        return match[0].replace(/'/g, '');
    }
    return fontFamily.length > 30 ? fontFamily.substring(0, 27) + '...' : fontFamily;
}
// ========== 时间戳格式化 ==========
function formatTimestamp(timestamp) {
    const date = new Date(timestamp * 1000);
    const now = new Date();
    const diff = now - date;
    if (diff < 24 * 60 * 60 * 1000) {
        return `今天 ${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`;
    } else if (diff < 2 * 24 * 60 * 60 * 1000) {
        return `昨天 ${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`;
    }
    return `${date.getMonth() + 1}-${date.getDate()} ${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`;
}

// ========== 用户记录管理 ==========
async function loadUserRecords() {
    const container = document.getElementById('userRecordsContainer');
    if (!container) return;

    if (!IS_ADMIN) {
        container.innerHTML = '<div class="empty-records">' + icon('lock', 'sm') + '只有管理员可以查看用户记录</div>';
        return;
    }

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    container.innerHTML = '<div class="loading-tags" style="text-align: center; padding: 30px;"><div class="loading-small"></div><span style="margin-left: 10px;">加载用户记录...</span></div>';

    try {
        const response = await fetch('/admin/user_records', {
            signal: controller.signal,
            headers: { 'Cache-Control': 'no-cache' }
        });
        clearTimeout(timeoutId);

        if (!response.ok) {
            if (response.status === 403) {
                container.innerHTML = '<div class="empty-records">' + icon('lock', 'sm') + '权限不足，只有管理员可以查看用户记录</div>';
                return;
            }
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        renderUserRecords(data, container);
    } catch (error) {
        console.error('加载用户记录失败:', error);
        if (error.name === 'AbortError') {
            container.innerHTML = '<div class="empty-records">' + icon('clock', 'sm') + ' 加载超时，请刷新页面重试</div>';
        } else {
            container.innerHTML = `<div class="empty-records">${icon('circle-x', 'sm')} 加载失败: ${error.message}</div>`;
        }
    }
}
// ========== 渲染用户记录（仅数量统计，不展示具体内容）==========
function renderUserRecords(userRecords, container) {
    if (!userRecords || Object.keys(userRecords).length === 0) {
        container.innerHTML = '<div class="empty-records">' + icon('file-text', 'sm') + '暂无用户阅读记录</div>';
        return;
    }

    // 按阅读本数倒序，读得多的排前面
    const entries = Object.entries(userRecords)
        .sort((a, b) => (b[1].count || 0) - (a[1].count || 0));

    let html = '<div class="user-records-list">';
    for (const [userName, data] of entries) {
        const roleClass = data.role === 'admin' ? 'admin' : 'user';
        const roleName = data.role === 'admin' ? '管理员' : '普通用户';
        const recordCount = data.count || 0;
        const lastRead = data.last_read ? formatTimestamp(data.last_read) : '从未阅读';

        html += `
                    <div class="user-record-item" data-user="${escapeAttr(userName)}">
                        <div class="user-record-row">
                            <div class="user-record-info">
                                <span class="user-record-name">${escapeHtml(userName)}</span>
                                <span class="record-badge ${roleClass}">${roleName}</span>
                                <span class="record-count-badge">${icon('library', 'sm')} ${recordCount} 本</span>
                                <span class="record-last-read" title="最近一次阅读时间">${icon('clock', 'xs')} ${escapeHtml(lastRead)}</span>
                            </div>
                            <button type="button" class="btn btn-danger btn-compact" onclick="clearUserRecords(this)" title="清除该用户的阅读记录">
                                ${icon('trash-2', 'sm')} 清除
                            </button>
                        </div>
                    </div>
                `;
    }
    html += '</div>';
    container.innerHTML = html;
}

// 转义用于 HTML 属性的值
function escapeAttr(value) {
    return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

// ========== 清除单个用户的阅读记录 ==========
async function clearUserRecords(btn) {
    const item = btn.closest('.user-record-item');
    const userName = item ? item.getAttribute('data-user') : '';
    if (!userName) return;

    if (!confirm(`确定要清除「${userName}」的阅读记录吗？此操作不可恢复！`)) {
        return;
    }

    btn.disabled = true;
    const originalText = btn.textContent;
    btn.innerHTML = icon('loader', 'sm');

    try {
        const response = await fetch('/admin/clear_user_records', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_display: userName })
        });
        const result = await response.json();

        if (result.success) {
            safeNotify(`已清除「${userName}」的阅读记录`, 'success');
            loadUserRecords();
        } else {
            safeNotify(result.message || '清除失败', 'error');
            btn.disabled = false;
            btn.textContent = originalText;
        }
    } catch (error) {
        console.error('清除用户记录失败:', error);
        safeNotify('清除失败，请重试', 'error');
        btn.disabled = false;
        btn.textContent = originalText;
    }
}

function refreshUserRecords() {
    loadUserRecords();
    loadUserList();
    safeNotify('正在刷新用户数据...', 'info');
}
// ========== 清除所有用户记录 ==========
async function clearAllUserRecords() {
 if (!confirm('确定要清除所有用户的阅读记录吗？此操作不可恢复！')) {
        return;
    }
    safeLoading(true);
    try {
        const response = await fetch('/admin/clear_all_records', { method: 'POST' });
        const result = await response.json();
        if (result.success) {
            safeNotify(`已清除所有用户的阅读记录，共 ${result.count} 个文件`, 'success');
            loadUserRecords();
        } else {
            safeNotify('清除失败: ' + result.message, 'error');
        }
    } catch (error) {
        safeNotify('清除失败: ' + error.message, 'error');
    } finally {
        safeLoading(false);
    }
}

// ========== 用户管理 ==========
async function loadUserList() {
    const container = document.getElementById('userListContainer');
    if (!container) return;

    container.innerHTML = '<div class="form-hint">' + icon('loader', 'sm') + ' 加载用户列表...</div>';

    try {
        const response = await fetch('/api/users/list');
        if (!response.ok) {
            if (response.status === 403) {
                container.innerHTML = '<div class="form-hint" style="color: #ff6b6b;">' + icon('lock', 'sm') + '权限不足</div>';
                return;
            }
            throw new Error(`HTTP ${response.status}`);
        }
        const users = await response.json();
        renderUserList(users, container);
        await loadUserRecords();
    } catch (error) {
        console.error('加载用户列表失败:', error);
        container.innerHTML = `<div class="form-hint" style="color: #ff6b6b;">${icon('circle-x', 'sm')} 加载失败: ${error.message}</div>`;
    }
}
// ========== 渲染用户列表 ==========
function renderUserList(users, container) {
    if (!users || users.length === 0) {
        container.innerHTML = '<div class="form-hint">' + icon('file-text', 'sm') + '暂无用户，请添加</div>';
        return;
    }

    let html = '<div style="max-height: 300px; overflow-y: auto;">';
    for (const user of users) {
        const roleClass = user.role === 'admin' ? 'admin' : 'user';
        const roleName = user.role === 'admin' ? '管理员' : '普通用户';
        const isCurrentUser = (user.key === USER_KEY);

        html += `
                    <div class="user-account-item" data-username="${user.key.replace(/'/g, "\\'")}" style="background: rgba(255,255,255,0.05); border-radius: 8px; padding: 10px; margin-bottom: 8px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                            <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                                <span style="display: inline-flex; align-items: center; gap: 5px; background: rgba(90, 143, 76, 0.25); padding: 2px 10px 2px 4px; border-radius: 12px; font-size: 11px;"><span class="user-avatar user-avatar--sm" style="--av-color: ${user.avatar_color || '#7BA05B'}">${icon(user.avatar_icon || 'user', 'xs')}</span>${escapeHtml(user.user_id || user.key)}</span>
                                <span class="record-badge ${roleClass}" style="font-size: 11px; padding: 2px 8px;">${roleName}</span>
                                ${isCurrentUser ? '<span style="font-size: 10px; background: #4caf50; padding: 2px 6px; border-radius: 10px;">当前用户</span>' : ''}
                            </div>
                            <div style="display: flex; gap: 8px;">
                                <button class="btn-edit-user" data-key="${user.key.replace(/"/g, '&quot;')}" data-role="${user.role}" data-userid="${(user.user_id || user.key).replace(/"/g, '&quot;')}" data-avatar-seed="${user.avatar_seed || 0}" data-preferences='${JSON.stringify(user.preferences || {}).replace(/'/g, "&#39;")}'style="background: #ffaa66; border: none; padding: 4px 10px; border-radius: 6px; cursor: pointer; font-size: 11px;">${icon('pencil', 'sm')} 编辑</button>
                                <button class="btn-delete-user" data-key="${user.key}" style="background:#ff6b6b;border:none;padding:4px 10px;border-radius:6px;cursor:pointer;font-size:11px;color:white;">${icon('trash-2', 'sm')} 删除</button>
                            </div>
                        </div>
                    </div>
                `;
    }
    html += '</div>';
    container.innerHTML = html;
}
// ========== 添加用户 ==========
function showAddUserModal() {
    const existingModal = document.querySelector('.modal');
    if (existingModal) existingModal.remove();

    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.innerHTML = `
                <div class="modal-content">
                    <div class="modal-header">
                        <h3>${icon('plus', 'sm')} 添加用户</h3>
                        <button class="modal-close"onclick="this.closest('.modal').remove()">${icon('x', 'sm')}</button>
                    </div>
                    <div class="modal-body">
                        <div class="form-group" style="margin-bottom: 15px;">
                            <label style="display: block; margin-bottom: 8px; color: #a0c0ff;">密码</label>
                            <input type="text" id="modal_user_password" placeholder="输入密码"autocomplete="off">
                        </div>
                        <div class="form-group" style="margin-bottom: 15px;">
                            <label style="display: block; margin-bottom: 8px; color: #a0c0ff;">显示名称</label>
                            <input type="text" id="modal_user_id" placeholder="显示名称（如：小明）"autocomplete="off">
                            <div class="form-hint" style="margin-top: 5px;">${icon('lightbulb', 'sm')} 用于在用户记录管理中显示</div>
                        </div>
                        <div class="form-group" style="margin-bottom: 15px;">
                            <label style="display: block; margin-bottom: 8px; color: #a0c0ff;">角色</label>
                            <select id="modal_user_role">
                                <option value="user">普通用户</option>
                                <option value="admin">管理员</option>
                            </select>
                        </div>
                        <div id="modal_user_hint" class="form-hint" style="margin-top: 10px;"></div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary"onclick="this.closest('.modal').remove()">取消</button>
                        <button class="btn btn-success"onclick="submitAddUser()">确认添加</button>
                    </div>
                </div>
            `;
    document.body.appendChild(modal);

    modal.addEventListener('click', function (e) {
        if (e.target === modal) {
            modal.remove();
        }
    });
}
// ========== 提交添加用户 ==========
function submitAddUser() {
    const password = document.getElementById('modal_user_password').value;
    const userId = document.getElementById('modal_user_id').value;
    const role = document.getElementById('modal_user_role').value;
    const hint = document.getElementById('modal_user_hint');

    if (!password) {
        hint.innerHTML = '' + icon('circle-x', 'sm') + '请输入密码';
        hint.style.color = '#f44336';
        return;
    }
    if (password.length < 4) {
        hint.innerHTML = '' + icon('circle-x', 'sm') + '密码长度至少4位';
        hint.style.color = '#f44336';
        return;
    }
    if (!userId) {
        hint.innerHTML = '' + icon('circle-x', 'sm') + '请输入显示名称';
        hint.style.color = '#f44336';
        return;
    }

    hint.innerHTML = icon('loader', 'sm') + ' 正在添加...';
    hint.style.color = '#ffaa66';

    fetch('/api/users/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: password, role: role, user_id: userId })
    })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                hint.innerHTML = '' + icon('check', 'sm') + '添加成功！';
                hint.style.color = '#4caf50';
                setTimeout(() => {
                    const modal = document.querySelector('.modal');
                    if (modal) modal.remove();
                    loadUserList();
                    loadUserRecords();
                    safeNotify(`用户 "${userId}"添加成功`, 'success');
                }, 1000);
            } else {
                hint.innerHTML = '' + icon('circle-x', 'sm') + ' ' + (data.message || '添加失败');
                hint.style.color = '#f44336';
            }
        })
        .catch(error => {
            hint.innerHTML = '' + icon('circle-x', 'sm') + '网络错误: ' + error.message;
            hint.style.color = '#f44336';
        });
}
// ========== 编辑用户 ==========
function showEditUserModal(userKey, role, userId, preferences = {}, avatarSeed = 0) {
    const existingModal = document.querySelector('.modal');
    if (existingModal) existingModal.remove();

    const modal = document.createElement('div');
    modal.className = 'modal';

    const escapedUserKey = userKey.replace(/[&<>]/g, function (m) {
        if (m === '&') return '&amp;';
        if (m === '<') return '&lt;';
        if (m === '>') return '&gt;';
        return m;
    });
    const escapedUserId = (userId || userKey).replace(/[&<>]/g, function (m) {
        if (m === '&') return '&amp;';
        if (m === '<') return '&lt;';
        if (m === '>') return '&gt;';
        return m;
    });

    const prefs = preferences || {};
    const fontSize = prefs.font_size || '未设置';
    const fontFamily = formatFontName(prefs.font_family || '');

    modal.innerHTML = `
                <div class="modal-content">
                    <div class="modal-header">
                        <h3>${icon('pencil', 'sm')} 编辑用户</h3>
                        <button class="modal-close"onclick="this.closest('.modal').remove()">${icon('x', 'sm')}</button>
                    </div>
                    <div class="modal-body">
                        <div class="form-group" style="margin-bottom: 15px;">
                            <label style="display: block; margin-bottom: 8px; color: #a0c0ff;">用户标识 (user key)</label>
                            <div style="background: rgba(90, 143, 76, 0.2); padding: 10px; border-radius: 8px; font-family: monospace;">
                                ${escapedUserKey}
                            </div>
                        </div>
                        <div class="form-group" style="margin-bottom: 15px;">
                            <label style="display: block; margin-bottom: 8px; color: #a0c0ff;">显示名称 (user_id)</label>
                            <input type="text" id="modal_edit_user_id" placeholder="显示名称"autocomplete="off" value="${escapedUserId}">
                            <div class="form-hint" style="margin-top: 5px;">${icon('lightbulb', 'sm')} 用于在用户记录管理中显示，建议使用易识别的昵称</div>
                        </div>
                        <div class="form-group" style="margin-bottom: 15px;">
                            <label style="display: block; margin-bottom: 8px; color: #a0c0ff;">${icon('smile', 'sm')} 头像</label>
                            <div style="display: flex; gap: 14px; align-items: flex-start;">
                                <div style="display: flex; flex-direction: column; align-items: center; gap: 6px; flex: none;">
                                    <span id="modal_avatar_preview" class="user-avatar" style="width: 56px; height: 56px; font-size: 26px;">🐱</span>
                                    <span style="font-size: 11px; color: #8a94a6;">预览</span>
                                </div>
                                <div style="flex: 1; min-width: 0;">
                                    <div id="modal_avatar_emoji" class="av-emoji-grid"></div>
                                    <div id="modal_avatar_color" class="av-color-row"></div>
                                </div>
                            </div>
                        </div>
                        <div class="form-group" style="margin-bottom: 15px;">
                            <label style="display: block; margin-bottom: 8px; color: #a0c0ff;">新密码</label>
                            <input type="text" id="modal_edit_password" placeholder="输入新密码（留空则不修改）"autocomplete="off">
                            <div class="form-hint" style="margin-top: 5px;">${icon('lightbulb', 'sm')} 留空则保持原密码不变</div>
                        </div>
                        <div class="form-group" style="margin-bottom: 15px;">
                            <label style="display: block; margin-bottom: 8px; color: #a0c0ff;">角色</label>
                            <select id="modal_edit_role">
                                <option value="user" ${role === 'user' ? 'selected' : ''}>普通用户</option>
                                <option value="admin" ${role === 'admin' ? 'selected' : ''}>管理员</option>
                            </select>
                        </div>
                        <div class="form-group" style="margin-bottom: 15px; padding: 10px; background: rgba(102,126,234,0.1); border-radius: 8px;">
                            <label style="display: block; margin-bottom: 8px; color: #a0c0ff;">${icon('book-open', 'sm')} 阅读偏好</label>
                            <div style="font-size: 13px; color: #aaa;">
                                <div>${icon('pencil', 'sm')} 字号: ${fontSize}px</div>
                                <div>${icon('type', 'sm')} 字体: ${fontFamily}</div>
                                <div>${icon('ruler', 'sm')} 行高: ${prefs.line_height || '未设置'}</div>
                                <div>${icon('palette', 'sm')} 主题: ${formatThemeName(prefs.theme)}</div>
                                <div>${icon('volume-2', 'sm')} 朗读语速: ${prefs.speech_rate || '未设置'}</div>
                                <div>${icon('music', 'sm')} 朗读音调: ${prefs.speech_pitch || '未设置'}</div>
                            </div>
                            <div class="form-hint" style="margin-top: 5px;">${icon('lightbulb', 'sm')} 偏好设置不会因编辑用户而丢失</div>
                        </div>
                        <div id="modal_edit_hint" class="form-hint" style="margin-top: 10px;"></div>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary"onclick="this.closest('.modal').remove()">取消</button>
                        <button class="btn btn-success"onclick="submitEditUser('${userKey}')">确认修改</button>
                    </div>
                </div>
            `;
    document.body.appendChild(modal);

    // 头像选择器要等 DOM 挂上去才能填（内部会拉一次 /api/avatar/options 并缓存）
    renderAvatarPicker(avatarSeed);

    modal.addEventListener('click', function (e) {
        if (e.target === modal) {
            modal.remove();
        }
    });
}

// ========== 头像选择器（编辑用户）==========
// 与后端的映射保持一致：emoji = seed % N，color = seed // N % 颜色数。
// 反过来算：seed = emojiIndex + colorIndex * N —— 选两个格子就能得到一个确定 seed。
const avatarPicker = { emoji: 0, color: 0, options: null, ready: false };

async function renderAvatarPicker(seed) {
    const box = document.getElementById('modal_avatar_emoji');
    const colorBox = document.getElementById('modal_avatar_color');
    if (!box || !colorBox) return;

    if (!avatarPicker.options) {
        try {
            const resp = await fetch('/api/avatar/options');
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            avatarPicker.options = await resp.json();
        } catch (err) {
            box.innerHTML = '<span style="font-size: 12px; color: #f44336;">头像选项加载失败</span>';
            return;
        }
    }

    const opts = avatarPicker.options;
    const total = opts.icons.length;
    const value = Math.abs(parseInt(seed, 10) || 0);
    avatarPicker.emoji = value % total;
    avatarPicker.color = Math.floor(value / total) % opts.colors.length;

    // avatarPicker.emoji 存的是「图标索引」（沿用旧字段名，避免大改）
    box.innerHTML = opts.icons.map(function (name, i) {
        return '<button type="button" class="av-pick' + (i === avatarPicker.emoji ? ' on' : '') +
            '" data-i="' + i + '">' + icon(name) + '</button>';
    }).join('');

    colorBox.innerHTML = opts.colors.map(function (color, i) {
        return '<button type="button" class="av-color' + (i === avatarPicker.color ? ' on' : '') +
            '" data-i="' + i + '" style="background: ' + color + ';"></button>';
    }).join('');

    box.querySelectorAll('.av-pick').forEach(function (btn) {
        btn.addEventListener('click', function () {
            avatarPicker.emoji = parseInt(btn.dataset.i, 10) || 0;
            syncAvatarPicker();
        });
    });
    colorBox.querySelectorAll('.av-color').forEach(function (btn) {
        btn.addEventListener('click', function () {
            avatarPicker.color = parseInt(btn.dataset.i, 10) || 0;
            syncAvatarPicker();
        });
    });

    avatarPicker.ready = true;
    syncAvatarPicker();
}

function syncAvatarPicker() {
    const opts = avatarPicker.options;
    if (!opts) return;
    const preview = document.getElementById('modal_avatar_preview');
    if (preview) {
        preview.innerHTML = icon(opts.icons[avatarPicker.emoji]);
        preview.style.setProperty('--av-color', opts.colors[avatarPicker.color]);
    }
    document.querySelectorAll('#modal_avatar_emoji .av-pick').forEach(function (btn, i) {
        btn.classList.toggle('on', i === avatarPicker.emoji);
    });
    document.querySelectorAll('#modal_avatar_color .av-color').forEach(function (btn, i) {
        btn.classList.toggle('on', i === avatarPicker.color);
    });
}

function currentAvatarSeed() {
    const opts = avatarPicker.options;
    if (!opts || !avatarPicker.ready) return null;   // 没加载出来就别提交，免得覆盖原头像
    const total = opts.icons.length;
    const seed = avatarPicker.emoji + avatarPicker.color * total;
    // seed=0 会被后端当成「未设置」，换成等价的 total × 颜色数
    return seed === 0 ? total * opts.colors.length : seed;
}
// ========== 提交编辑用户 ==========
function submitEditUser(userKey) {
    const newPassword = document.getElementById('modal_edit_password').value;
    const newUserId = document.getElementById('modal_edit_user_id').value;
    const role = document.getElementById('modal_edit_role').value;
    const hint = document.getElementById('modal_edit_hint');

    if (newPassword && newPassword.length < 4) {
        hint.innerHTML = '' + icon('circle-x', 'sm') + '密码长度至少4位';
        hint.style.color = '#f44336';
        return;
    }
    if (!newUserId) {
        hint.innerHTML = '' + icon('circle-x', 'sm') + '显示名称不能为空';
        hint.style.color = '#f44336';
        return;
    }

    hint.innerHTML = icon('loader', 'sm') + ' 正在修改...';
    hint.style.color = '#ffaa66';

    const requestData = {
        user_key: userKey,
        role: role,
        user_id: newUserId,
        keep_preferences: true
    };

    if (newPassword) {
        requestData.new_password = newPassword;
    }

    // 只有头像选项真的加载出来了才提交，否则会把用户原来的头像覆盖掉
    const avatarSeed = currentAvatarSeed();
    if (avatarSeed !== null) {
        requestData.avatar_seed = avatarSeed;
    }

    fetch('/api/users/edit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestData)
    })
        .then(async response => {
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.message || `HTTP ${response.status}`);
            }
            return data;
        })
        .then(data => {
            if (data.success) {
                hint.innerHTML = '' + icon('check', 'sm') + '修改成功';
                hint.style.color = '#4caf50';
                setTimeout(() => {
                    const modal = document.querySelector('.modal');
                    if (modal) modal.remove();
                    loadUserList();
                    loadUserRecords();
                    if (userKey === USER_KEY && newPassword) {
                        alert('您修改了自己的密码，请重新登录');
                        location.href = '/login';
                    }
                }, 1000);
            } else {
                hint.innerHTML = '' + icon('circle-x', 'sm') + ' ' + (data.message || '修改失败');
                hint.style.color = '#f44336';
            }
        })
        .catch(error => {
            console.error('编辑用户失败:', error);
            hint.innerHTML = '' + icon('circle-x', 'sm') + '网络错误: ' + error.message;
            hint.style.color = '#f44336';
        });
}
// ========== 删除用户 ==========
function deleteUser(userKey) {
    if (!confirm(`确定要删除该用户吗？此操作不可恢复！`)) {
        return;
    }
    safeLoading(true);
    fetch('/api/users/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_key: userKey })
    })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                safeNotify(`用户已删除`, 'success');
                loadUserList();
                loadUserRecords();
                if (userKey === USER_KEY) {
                    setTimeout(() => { location.href = '/login'; }, 1500);
                }
            } else {
                safeNotify('删除失败: ' + (data.message || '未知错误'), 'error');
            }
        })
        .catch(error => {
            console.error('删除用户失败:', error);
            safeNotify('删除失败: ' + error.message, 'error');
        })
        .finally(() => { safeLoading(false); });
}

// ========== 配置保存 ==========
function toggleCard(header) {
    const card = header.closest('.config-card');
    card.classList.toggle('collapsed');
}

// ========== 我的阅读偏好（每用户一份） ==========
// 走 /api/preferences 系列接口，与全局配置完全分离
const PREF_FIELDS = {
    number: ['font_size', 'line_height', 'paragraph_spacing',
             'per_page', 'words_per_page', 'max_tags_display'],
    text: ['font_family', 'theme', 'title_font_family', 'double_quote_font_family', 'single_quote_font_family', 'bracket_font_family', 'square_bracket_font_family', 'square_bracket_1_font_family', 'hollow_bracket_font_family', 'book_font_family',
           'default_sort_by', 'default_sort_order', 'date_format'],
    bool: ['auto_save_progress', 'show_word_count', 'indent_paragraph',
           'body_bold', 'body_italic', 'title_bold', 'title_italic',
           'double_quote_bold', 'double_quote_italic', 'single_quote_bold', 'single_quote_italic',
           'bracket_bold', 'bracket_italic', 'square_bracket_bold', 'square_bracket_italic',
           'square_bracket_1_bold', 'square_bracket_1_italic', 'hollow_bracket_bold', 'hollow_bracket_italic',
           'book_bold', 'book_italic']
};

// 字体设置里的「加粗 / 斜体」切换按钮（阅读偏好页使用，与阅读页交互一致）
function toggleConfigBi(btn) {
    const on = btn.getAttribute('aria-pressed') === 'true';
    btn.setAttribute('aria-pressed', on ? 'false' : 'true');
    btn.classList.toggle('on', !on);
    // 用户手动操作过，视为显式设置（保存时下发，而非「跟随默认」）
    delete btn.dataset.unset;
}

// 清掉阅读页的 localStorage 缓存：让「我的阅读偏好」保存/重置后，
// 重新打开或切回阅读页时以服务端为准，避免陈旧 localStorage 覆盖新设置。
// 同时会触发其它标签页的 storage 事件，使已打开的阅读页自动重新同步。
function clearReaderLocalCache() {
    const scopes = ['body', 'title', 'double_quote', 'single_quote', 'bracket',
                    'square_bracket', 'square_bracket_1', 'hollow_bracket', 'book'];
    const keys = ['reader_font_size', 'reader_font_family', 'reader_theme', 'reader_line_height'];
    scopes.forEach(s => {
        keys.push('reader_' + s + '_font_family');
        keys.push('reader_' + s + '_bold');
        keys.push('reader_' + s + '_italic');
    });
    keys.forEach(k => localStorage.removeItem(k));
}

async function loadMyPreferences() {
    try {
        const response = await fetch('/api/get_preferences');
        if (!response.ok) return;
        const data = await response.json();

        // 后端同时返回 overrides（我设置过的）和 effective（真正生效的值）
        const prefs = data.overrides || data;
        const effective = data.effective || {};

        PREF_FIELDS.number.forEach(key => {
            const el = document.getElementById('pref_' + key);
            if (!el) return;
            const val = prefs[key];
            el.value = (val === undefined || val === null || val === '') ? '' : val;
            // 占位提示显示「当前生效值」，让用户知道留空会用什么
            if (effective[key] !== undefined) {
                el.placeholder = `跟随默认（${effective[key]}）`;
            }
        });

        PREF_FIELDS.text.forEach(key => {
            const el = document.getElementById('pref_' + key);
            if (!el) return;
            el.value = prefs[key] || '';
            // 颜色选择器：回填后标记 dirty，确保「已设置过的颜色」会在下次保存时下发
            if (el.type === 'color') {
                el.dataset.dirty = (prefs[key] && prefs[key] !== '') ? '1' : '';
            }

            // 主题下拉：把「跟随默认」那一项标注成实际生效值。
            // 必须先还原原始文案，否则反复加载会叠加成「跟随默认（跟随默认（…））」
            if (key === 'theme' && el.options[0]) {
                if (el.options[0].dataset.original === undefined) {
                    el.options[0].dataset.original = el.options[0].textContent;
                }
                const base = el.options[0].dataset.original;
                const eff = effective[key];
                const opt = eff ? Array.from(el.options).find(o => o.value === String(eff)) : null;
                el.options[0].textContent = opt
                    ? `${base}（当前：${opt.textContent.trim()}）`
                    : base;
            }
        });

        PREF_FIELDS.bool.forEach(key => {
            const el = document.getElementById('pref_' + key);
            if (!el) return;
            const set = !(prefs[key] === undefined || prefs[key] === null || prefs[key] === '');
            const on = set && (prefs[key] === true || prefs[key] === 'true');
            if (el.tagName === 'BUTTON') {
                // 加粗/斜体 切换按钮
                el.setAttribute('aria-pressed', on ? 'true' : 'false');
                el.classList.toggle('on', on);
            } else if (el.tagName === 'SELECT') {
                // 三态下拉（如首行缩进）：未设置 -> 空值（跟随默认）
                el.value = set ? (on ? 'true' : 'false') : '';
            } else {
                // 普通复选框（如自动保存进度等）
                el.checked = on;
            }
            if (set) delete el.dataset.unset; else el.dataset.unset = '1';
        });
    } catch (error) {
        console.error('加载阅读偏好失败:', error);
    }
}

function collectMyPreferences() {
    const payload = {};

    PREF_FIELDS.number.forEach(key => {
        const el = document.getElementById('pref_' + key);
        if (!el) return;
        const raw = el.value.trim();
        if (raw === '') return;               // 留空 = 跟随默认，不下发
        const num = parseFloat(raw);
        if (!isNaN(num)) payload[key] = num;
    });

    PREF_FIELDS.text.forEach(key => {
        const el = document.getElementById('pref_' + key);
        if (!el) return;
        // 颜色选择器：浏览器默认值为 #000000，仅当用户手动改过（dirty）才下发，
        // 否则空值会被误当成「设为黑色」下发
        if (el.type === 'color' && !el.dataset.dirty) return;
        const raw = el.value;
        if (raw !== '') payload[key] = raw;   // 空 = 跟随默认
    });

    PREF_FIELDS.bool.forEach(key => {
        const el = document.getElementById('pref_' + key);
        if (!el) return;
        // 下拉的「空值」是明确的三态之一（跟随默认），必须直接跳过，
        // 不能落到下面的 false 分支里，否则会把用户的缩进设置误关掉
        if (el.tagName === 'SELECT' && el.value === '') return;
        // 按钮用 aria-pressed，下拉用 value，复选框用 checked
        let isOn;
        if (el.tagName === 'BUTTON') {
            isOn = el.getAttribute('aria-pressed') === 'true';
        } else if (el.tagName === 'SELECT') {
            isOn = el.value === 'true';
        } else {
            isOn = el.checked;
        }
        // 勾选/开启记 true；未开启且本来就是「未设置」的不下发
        if (isOn) {
            payload[key] = true;
        } else if (!el.dataset.unset) {
            payload[key] = false;
        }
    });

    return payload;
}

async function saveMyPreferences() {
    const payload = collectMyPreferences();

    safeLoading(true);
    try {
        const response = await fetch('/api/save_preferences', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (result.success) {
            safeNotify('阅读偏好已保存，阅读页立即生效', 'success');
            clearReaderLocalCache();   // 清掉阅读页 localStorage，避免陈旧缓存覆盖新设置
            loadMyPreferences();
        } else {
            safeNotify('保存失败: ' + (result.message || '未知错误'), 'error');
        }
    } catch (error) {
        safeNotify('保存失败: ' + error.message, 'error');
    } finally {
        safeLoading(false);
    }
}

async function resetMyPreferences() {
    if (!confirm('确定恢复为默认阅读设置吗？你的个人设置将被清除。')) return;

    // 空对象会被后端拒绝，这里显式把各项清空为「跟随默认」
    const payload = {};
    PREF_FIELDS.number.forEach(k => { payload[k] = ''; });
    PREF_FIELDS.text.forEach(k => { payload[k] = ''; });

    safeLoading(true);
    try {
        const response = await fetch('/api/save_preferences', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        if (result.success) {
            safeNotify('已恢复默认', 'success');
            // 前端也清空输入框
            Object.keys(PREF_FIELDS).forEach(type => {
                PREF_FIELDS[type].forEach(key => {
                    const el = document.getElementById('pref_' + key);
                    if (!el) return;
                    if (type === 'bool') {
                        if (el.tagName === 'BUTTON') {
                            el.setAttribute('aria-pressed', 'false');
                            el.classList.remove('on');
                        } else {
                            el.checked = false;
                        }
                        el.dataset.unset = '1';
                    }
                    else { el.value = ''; if (el.type === 'color') el.dataset.dirty = ''; }
                });
            });
            clearReaderLocalCache();   // 清掉阅读页 localStorage，恢复默认后同样避免陈旧缓存
            loadMyPreferences();
        } else {
            safeNotify('操作失败: ' + (result.message || '未知错误'), 'error');
        }
    } catch (error) {
        safeNotify('操作失败: ' + error.message, 'error');
    } finally {
        safeLoading(false);
    }
}

function safeNumber(id, defaultValue, minVal, maxVal) {
    let input = document.getElementById(id);
    if (!input) return defaultValue;
    let val = parseInt(input.value);
    if (isNaN(val)) val = defaultValue;
    if (val < minVal) val = minVal;
    if (val > maxVal) val = maxVal;
    if (input) input.value = val;
    return val;
}

function safeBool(id, defaultValue = false) {
    let input = document.getElementById(id);
    return input ? input.checked : defaultValue;
}

// 小数输入（行高、段间距）：与 safeNumber 同策略，但保留小数
function safeFloat(id, defaultValue, minVal, maxVal) {
    let input = document.getElementById(id);
    if (!input) return defaultValue;
    let val = parseFloat(input.value);
    if (isNaN(val)) val = defaultValue;
    if (val < minVal) val = minVal;
    if (val > maxVal) val = maxVal;
    input.value = val;
    return val;
}

// 读取管理员「阅读默认值」里字体加粗/斜体按钮的状态（按钮 id 不带 pref_ 前缀）
function adminBiState(id) {
    const el = document.getElementById(id);
    return el ? el.getAttribute('aria-pressed') === 'true' : false;
}

async function saveAllConfig() {
    safeLoading(true);
    // 普通用户看不到全局配置卡片，这些元素不存在；后端也会对非管理员返回 403。
    // 这里仍做一次判空，避免对 null 取 .value 抛异常。
    const formData = {
        font_size: safeNumber('font_size', 16, 12, 48),
        line_height: parseFloat(document.getElementById('line_height')?.value ?? 1.8),
        theme: document.getElementById('theme')?.value ?? 'dark',
        auto_save_progress: safeBool('auto_save_progress', true),
        show_word_count: safeBool('show_word_count', true),
        scan_interval_hours: safeNumber('scan_interval_hours', 0, 0, 168),
        max_file_size_mb: safeNumber('max_file_size_mb', 100, 1, 500),
        per_page: safeNumber('per_page', 100, 20, 500),
        words_per_page: safeNumber('words_per_page', 8000, 1000, 50000),
        max_tags_display: safeNumber('max_tags_display', 3, 1, 10),
        date_format: document.getElementById('date_format')?.value ?? 'YYYY-MM-DD',
        default_sort_by: document.getElementById('default_sort_by')?.value ?? 'title',
        default_sort_order: document.getElementById('default_sort_order')?.value ?? 'asc',
        auto_scan_on_start: safeBool('auto_scan_on_start', true),
        // 强制开启：站点必须登录才能访问，不再提供关闭入口（原「安全配置」卡片已移除）
        require_auth: true,
        // 段落排版默认值（字符串 "true"/"false"需转成布尔）
        indent_paragraph: document.getElementById('indent_paragraph')?.value !== 'false',
        paragraph_spacing: safeFloat('paragraph_spacing', 0.8, 0, 3),
        // 阅读默认值：字体设置（正文字体 + 8 类元素字体，空 = 跟随正文）
        font_family: document.getElementById('font_family')?.value ?? 'system-ui',
        title_font_family: document.getElementById('title_font_family')?.value ?? '',
        double_quote_font_family: document.getElementById('double_quote_font_family')?.value ?? '',
        single_quote_font_family: document.getElementById('single_quote_font_family')?.value ?? '',
        bracket_font_family: document.getElementById('bracket_font_family')?.value ?? '',
        square_bracket_font_family: document.getElementById('square_bracket_font_family')?.value ?? '',
        square_bracket_1_font_family: document.getElementById('square_bracket_1_font_family')?.value ?? '',
        hollow_bracket_font_family: document.getElementById('hollow_bracket_font_family')?.value ?? '',
        book_font_family: document.getElementById('book_font_family')?.value ?? '',
        // 字体加粗/斜体默认值（按钮 aria-pressed = 开启）
        body_bold: adminBiState('body_bold'), body_italic: adminBiState('body_italic'),
        title_bold: adminBiState('title_bold'), title_italic: adminBiState('title_italic'),
        double_quote_bold: adminBiState('double_quote_bold'), double_quote_italic: adminBiState('double_quote_italic'),
        single_quote_bold: adminBiState('single_quote_bold'), single_quote_italic: adminBiState('single_quote_italic'),
        bracket_bold: adminBiState('bracket_bold'), bracket_italic: adminBiState('bracket_italic'),
        square_bracket_bold: adminBiState('square_bracket_bold'), square_bracket_italic: adminBiState('square_bracket_italic'),
        square_bracket_1_bold: adminBiState('square_bracket_1_bold'), square_bracket_1_italic: adminBiState('square_bracket_1_italic'),
        hollow_bracket_bold: adminBiState('hollow_bracket_bold'), hollow_bracket_italic: adminBiState('hollow_bracket_italic'),
        book_bold: adminBiState('book_bold'), book_italic: adminBiState('book_italic'),
        // 标签自动化
        auto_tag_enabled: safeBool('auto_tag_enabled', true),
        enable_derived_tags: safeBool('enable_derived_tags', true)
    };

    try {
        const response = await fetch('/config/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData)
        });
        const result = await response.json();
        if (result.success) {
            safeNotify('配置已保存！点击"重载配置"生效', 'success');
        } else {
            safeNotify('保存失败: ' + result.message, 'error');
        }
    } catch (error) {
        safeNotify('保存失败: ' + error.message, 'error');
    } finally {
        safeLoading(false);
    }
}
// ========== 配置重载 ==========
async function reloadConfig() {
    safeLoading(true);
    try {
        const response = await fetch('/config/reload', { method: 'POST' });
        const result = await response.json();
        if (result.success) {
            safeNotify('配置已重载', 'success');
            setTimeout(() => location.reload(), 1000);
        } else {
            safeNotify('重载失败: ' + result.message, 'error');
        }
    } catch (error) {
        safeNotify('重载失败: ' + error.message, 'error');
    } finally {
        safeLoading(false);
    }
}
// ========== 配置导入导出 ==========
function exportConfig() {
    const configData = {
        require_auth: true,
        per_page: parseInt(document.getElementById('per_page')?.value ?? 100),
        words_per_page: parseInt(document.getElementById('words_per_page')?.value ?? 8000),
        max_tags_display: parseInt(document.getElementById('max_tags_display')?.value ?? 3),
        date_format: document.getElementById('date_format')?.value ?? 'YYYY-MM-DD',
        scan_interval_hours: parseInt(document.getElementById('scan_interval_hours')?.value ?? 0),
        max_file_size_mb: parseInt(document.getElementById('max_file_size_mb')?.value ?? 100),
        auto_scan_on_start: document.getElementById('auto_scan_on_start')?.checked ?? true,
        font_size: parseInt(document.getElementById('font_size')?.value ?? 16),
        line_height: parseFloat(document.getElementById('line_height')?.value ?? 1.8),
        theme: document.getElementById('theme')?.value ?? 'dark',
        auto_save_progress: document.getElementById('auto_save_progress')?.checked ?? true,
        show_word_count: document.getElementById('show_word_count')?.checked ?? true,
        default_sort_by: document.getElementById('default_sort_by')?.value ?? 'title',
        default_sort_order: document.getElementById('default_sort_order')?.value ?? 'asc',
        // 段落排版默认值
        indent_paragraph: document.getElementById('indent_paragraph')?.value !== 'false',
        paragraph_spacing: parseFloat(document.getElementById('paragraph_spacing')?.value ?? 0.8),
        // 阅读默认值：字体设置
        font_family: document.getElementById('font_family')?.value ?? 'system-ui',
        title_font_family: document.getElementById('title_font_family')?.value ?? '',
        double_quote_font_family: document.getElementById('double_quote_font_family')?.value ?? '',
        single_quote_font_family: document.getElementById('single_quote_font_family')?.value ?? '',
        bracket_font_family: document.getElementById('bracket_font_family')?.value ?? '',
        square_bracket_font_family: document.getElementById('square_bracket_font_family')?.value ?? '',
        square_bracket_1_font_family: document.getElementById('square_bracket_1_font_family')?.value ?? '',
        hollow_bracket_font_family: document.getElementById('hollow_bracket_font_family')?.value ?? '',
        book_font_family: document.getElementById('book_font_family')?.value ?? '',
        body_bold: adminBiState('body_bold'), body_italic: adminBiState('body_italic'),
        title_bold: adminBiState('title_bold'), title_italic: adminBiState('title_italic'),
        double_quote_bold: adminBiState('double_quote_bold'), double_quote_italic: adminBiState('double_quote_italic'),
        single_quote_bold: adminBiState('single_quote_bold'), single_quote_italic: adminBiState('single_quote_italic'),
        bracket_bold: adminBiState('bracket_bold'), bracket_italic: adminBiState('bracket_italic'),
        square_bracket_bold: adminBiState('square_bracket_bold'), square_bracket_italic: adminBiState('square_bracket_italic'),
        square_bracket_1_bold: adminBiState('square_bracket_1_bold'), square_bracket_1_italic: adminBiState('square_bracket_1_italic'),
        hollow_bracket_bold: adminBiState('hollow_bracket_bold'), hollow_bracket_italic: adminBiState('hollow_bracket_italic'),
        book_bold: adminBiState('book_bold'), book_italic: adminBiState('book_italic'),
        // 标签自动化
        auto_tag_enabled: document.getElementById('auto_tag_enabled')?.checked ?? true,
        enable_derived_tags: document.getElementById('enable_derived_tags')?.checked ?? true
    };

    const dataStr = JSON.stringify(configData, null, 2);
    const blob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `novel_config_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.json`;
    a.click();
    URL.revokeObjectURL(url);
    safeNotify('配置已导出', 'success');
}

function importConfig() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = function (e) {
        const file = e.target.files[0];
        const reader = new FileReader();
        reader.onload = function (evt) {
            try {
                const config = JSON.parse(evt.target.result);
                if (document.getElementById('per_page')) document.getElementById('per_page').value = config.per_page ?? 100;
                if (document.getElementById('words_per_page')) document.getElementById('words_per_page').value = config.words_per_page ?? 8000;
                if (document.getElementById('max_tags_display')) document.getElementById('max_tags_display').value = config.max_tags_display ?? 3;
                if (document.getElementById('date_format')) document.getElementById('date_format').value = config.date_format ?? 'YYYY-MM-DD';
                if (document.getElementById('scan_interval_hours')) document.getElementById('scan_interval_hours').value = config.scan_interval_hours ?? 0;
                if (document.getElementById('max_file_size_mb')) document.getElementById('max_file_size_mb').value = config.max_file_size_mb ?? 100;
                if (document.getElementById('auto_scan_on_start')) document.getElementById('auto_scan_on_start').checked = config.auto_scan_on_start ?? true;
                if (document.getElementById('font_size')) document.getElementById('font_size').value = config.font_size ?? 16;
                if (document.getElementById('line_height')) document.getElementById('line_height').value = config.line_height ?? 1.8;
                if (document.getElementById('theme')) document.getElementById('theme').value = config.theme ?? 'dark';
                if (document.getElementById('auto_save_progress')) document.getElementById('auto_save_progress').checked = config.auto_save_progress ?? true;
                if (document.getElementById('show_word_count')) document.getElementById('show_word_count').checked = config.show_word_count ?? true;
                if (document.getElementById('default_sort_by')) document.getElementById('default_sort_by').value = config.default_sort_by ?? 'title';
                if (document.getElementById('default_sort_order')) document.getElementById('default_sort_order').value = config.default_sort_order ?? 'asc';
                if (document.getElementById('indent_paragraph')) document.getElementById('indent_paragraph').value = (config.indent_paragraph === false) ? 'false' : 'true';
                if (document.getElementById('paragraph_spacing')) document.getElementById('paragraph_spacing').value = config.paragraph_spacing ?? 0.8;
                // 阅读默认值：字体设置
                const adminFontKeys = ['font_family', 'title_font_family', 'double_quote_font_family', 'single_quote_font_family', 'bracket_font_family', 'square_bracket_font_family', 'square_bracket_1_font_family', 'hollow_bracket_font_family', 'book_font_family'];
                adminFontKeys.forEach(k => {
                    const el = document.getElementById(k);
                    if (el) el.value = config[k] ?? '';
                });
                const adminBiKeys = ['body', 'title', 'double_quote', 'single_quote', 'bracket', 'square_bracket', 'square_bracket_1', 'hollow_bracket', 'book'];
                adminBiKeys.forEach(s => {
                    ['bold', 'italic'].forEach(t => {
                        const el = document.getElementById(s + '_' + t);
                        if (!el) return;
                        const on = !!(config[s + '_' + t]);
                        el.setAttribute('aria-pressed', on ? 'true' : 'false');
                        el.classList.toggle('on', on);
                    });
                });
                if (document.getElementById('auto_tag_enabled')) document.getElementById('auto_tag_enabled').checked = config.auto_tag_enabled ?? true;
                if (document.getElementById('enable_derived_tags')) document.getElementById('enable_derived_tags').checked = config.enable_derived_tags ?? true;
                safeNotify('配置已导入，请保存生效', 'success');
            } catch (error) {
                safeNotify('导入失败: 配置文件格式错误', 'error');
            }
        };
        reader.readAsText(file);
    };
    input.click();
}

// ========== 事件委托 ==========
document.body.addEventListener('click', function (e) {
    const deleteBtn = e.target.closest('.btn-delete-user');
    if (deleteBtn) {
        e.preventDefault();
        e.stopPropagation();
        const userKey = deleteBtn.getAttribute('data-key');
        if (userKey) {
            deleteUser(userKey);
        }
    }
});

document.body.addEventListener('click', function (e) {
    const editBtn = e.target.closest('.btn-edit-user');
    if (editBtn) {
        e.preventDefault();
        e.stopPropagation();
        const userKey = editBtn.getAttribute('data-key');
        const role = editBtn.getAttribute('data-role');
        const userId = editBtn.getAttribute('data-userid');
        const avatarSeed = parseInt(editBtn.getAttribute('data-avatar-seed'), 10) || 0;
        let preferences = {};
        try {
            const prefsStr = editBtn.getAttribute('data-preferences');
            if (prefsStr) {
                preferences = JSON.parse(prefsStr.replace(/&#39;/g, "'"));
            }
        } catch (e) { }
        showEditUserModal(userKey, role, userId, preferences, avatarSeed);
    }
});

// ========== 键盘快捷键 ==========
document.addEventListener('keydown', function (e) {
    if (e.ctrlKey && e.key === 's') {
        e.preventDefault();
        saveAllConfig();
    }
    if (e.ctrlKey && e.key === 'r') {
        e.preventDefault();
        reloadConfig();
    }
});


// ========== 内存管理 ==========

/*获取内存和缓存状态 */
async function refreshMemoryInfo() {
    const memoryEl = document.getElementById('currentMemory');
    const tagEl = document.getElementById('tagCacheCount');
    const chapterEl = document.getElementById('chapterCacheCount');
    const imageEl = document.getElementById('imageCacheCount');
    const lineEl = document.getElementById('lineCacheCount');
    const workIdEl = document.getElementById('workIdCacheCount');

    if (!memoryEl) return;

    // 用可选链防止某个元素不存在时报错
    if (memoryEl) memoryEl.innerHTML = icon('loader', 'sm') + ' 查询中...';
    if (tagEl) tagEl.innerHTML = icon('loader', 'sm');
    if (chapterEl) chapterEl.innerHTML = icon('loader', 'sm');
    if (imageEl) imageEl.innerHTML = icon('loader', 'sm');
    if (lineEl) lineEl.innerHTML = icon('loader', 'sm');
    if (workIdEl) workIdEl.innerHTML = icon('loader', 'sm');

    try {
        const response = await fetch('/api/cache/stats');

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        if (tagEl) tagEl.textContent = data.tag_cache ?? '0';
        if (chapterEl) chapterEl.textContent = data.chapter_cache ?? '0';
        if (imageEl) imageEl.textContent = data.image_cache ?? '0';
        if (lineEl) {
            // 阅读缓存是释放内存的大头，这里同时给出条数和占用
            const lc = data.line_cache ?? 0;
            const lcMb = data.line_cache_mb;
            lineEl.textContent = (lcMb !== undefined && lcMb > 0)
                ? `${lc} 条 · ${lcMb} MB`
                : `${lc} 条`;
        }
        if (workIdEl) {
            // 指纹缓存：过去从不清理也不显示，现在补上
            const wc = data.work_id_count ?? 0;
            const wkb = data.work_id_kb;
            workIdEl.textContent = (wkb !== undefined && wkb > 0)
                ? `${wc} 条 · ${wkb} KB`
                : `${wc} 条`;
        }

        if (data.memory_mb !== null && data.memory_mb !== undefined && data.memory_mb > 0) {
            if (memoryEl) memoryEl.textContent = `${data.memory_mb} MB`;
        } else {
 if (memoryEl) memoryEl.textContent = '仅缓存统计';
        }

    } catch (error) {
        console.error('获取缓存状态失败:', error);
 if (memoryEl) memoryEl.textContent = '获取失败';
 if (tagEl) tagEl.textContent = '';
 if (chapterEl) chapterEl.textContent = '';
 if (imageEl) imageEl.textContent = '';
 if (lineEl) lineEl.textContent = '';
 if (workIdEl) workIdEl.textContent = '';
    }
}

/*强制清理内存；deep=true 时连热缓存一起清空（含图片缓存、指纹缓存） */
async function forceCleanupMemory(deep = false) {
    const btn = document.getElementById(deep ? 'deepCleanupBtn' : 'cleanupBtn');
    const otherBtn = document.getElementById(deep ? 'cleanupBtn' : 'deepCleanupBtn');
    const resultEl = document.getElementById('cleanupResult');

    if (!btn) {
        console.error('找不到清理按钮');
        return;
    }

    const msg = deep
        ? '确定要「彻底清理」吗？\n\n会清空全部缓存，包括标签、章节、\n图片缓存和指纹缓存，不保留任何热缓存。\n\n内存降得最彻底，但之后首次访问小说列表和详情页会重新解析，明显变慢。'
        : '确定要清理缓存释放内存吗？\n\n这将释放标签缓存、章节缓存、图片缓存和指纹缓存，\n但会保留少量热缓存以加快下次访问。';
    if (!confirm(msg)) {
        return;
    }

    // 保存原始按钮文案，finally 里恢复
    const originalText = btn.textContent;

    btn.disabled = true;
    btn.innerHTML = icon('loader', 'sm') + (deep ? ' 彻底清理中...' : ' 清理中...');
    if (otherBtn) otherBtn.disabled = true;
    if (resultEl) {
        resultEl.innerHTML = icon('loader', 'sm') + (deep ? ' 正在彻底清理缓存...' : ' 正在清理缓存...');
        resultEl.style.color = '#ffaa66';
    }

    try {
        const response = await fetch('/api/force_cleanup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ deep: !!deep })
        });

        // 先尝试解析 JSON，失败则用文本
        let data;
        try {
            data = await response.json();
        } catch (jsonErr) {
            const text = await response.text().catch(() => '');
            throw new Error(`服务器返回非 JSON (HTTP ${response.status}): ${text.slice(0, 100)}`);
        }

        if (!response.ok) {
            if (response.status === 403) {
                throw new Error('权限不足，需要管理员权限');
            }
            throw new Error(data.message || `HTTP ${response.status}`);
        }

        if (!data.success) {
            throw new Error(data.message || '清理失败');
        }

        const result = data.result || {};
        const memoryMb = result.memory_mb !== undefined ? result.memory_mb : '未知';
        const released = (result.tag || 0) + (result.chapter || 0)
            + (result.image || 0) + (result.check || 0) + (result.line || 0)
            + (result.work_id_file || 0) + (result.work_id_set || 0);

        // 清理是「保留式」的：tag/chapter/image/work_id 会各留一批热缓存不清零，
        // 所以这里必须把「删了多少」和「还剩多少」都讲清楚，否则用户会以为没生效。
        // deep 模式 keep 全为 0，数字应当归零。
        const rem = result.remaining || {};
        const kept = (rem.tag || 0) + (rem.chapter || 0) + (rem.image || 0)
            + (rem.work_id_file || 0) + (rem.work_id_set || 0);

        if (resultEl) {
            const isDeep = !!result.deep;
            const lineCount = result.line || 0;
            const lineMb = result.line_mb || 0;
            // 热缓存（标签/章节/图片/指纹）本次实际删了多少——这才是计数芯片会不会动的关键
            const hotRemoved = (result.tag || 0) + (result.chapter || 0)
                + (result.image || 0) + (result.work_id_file || 0) + (result.work_id_set || 0);
            // 阅读缓存（line_cache）才是真正能释放的大头，优先讲清楚它
            let html = `${icon('circle-check', 'sm')} ${isDeep ? '彻底清理完成' : '释放内存完成'}`;
            if (lineCount > 0 || lineMb > 0) {
                html += `，已释放<strong>阅读缓存 ${lineCount} 条</strong>（约 <strong>${lineMb} MB</strong>）`;
            } else {
                html += `，阅读缓存当前为空（说明刚才没在读小说，无正文可释放）`;
            }

            if (isDeep) {
                html += `；已彻底清空全部热缓存`;
            } else if (hotRemoved > 0) {
                html += `；并清理热缓存 <strong>${hotRemoved}</strong> 条`;
            } else {
                html += `；<span class="cleanup-note">热缓存已在保留下限（标签≤${result.keep_tag ?? 100}·章节≤${result.keep_chapter ?? 30}`
                     + `·图片≤${result.keep_image ?? 100}·指纹≤${result.keep_work_id ?? 200}），计数不变属正常</span>`;
            }

            html += ` · 当前内存 <strong>${memoryMb} MB</strong>`
                 + `（书库为常驻数据，数字主要由它决定）`;

            resultEl.innerHTML = html;
            resultEl.title =
                `标签 删${result.tag || 0}/剩${rem.tag || 0}`
                + ` · 章节 删${result.chapter || 0}/剩${rem.chapter || 0}`
                + ` · 图片 删${result.image || 0}/剩${rem.image || 0}`
                + ` · 配图检测 ${result.check || 0} 条`
                + ` · 指纹 删${(result.work_id_file || 0) + (result.work_id_set || 0)}`
                + `/剩${(rem.work_id_file || 0) + (rem.work_id_set || 0)}`
                + ` · 映射表 ${result.mapping || 0} 份`
                + ` · 阅读缓存 ${result.line || 0} 条（约 ${lineMb} MB）`
                + `　|　GC 回收 ${result.gc_collected || 0} 个对象`
                + `　|　内存已归还系统：${result.memory_trimmed ? '是' : '否'}`;
            resultEl.classList.remove('error');
            resultEl.classList.add('show');
        }

        safeNotify(isDeepResult(data) ? '彻底清理完成' : '清理完成', 'success');

        // 500ms 后刷新一次内存显示
        setTimeout(refreshMemoryInfo, 500);

    } catch (error) {
        console.error('清理失败:', error);

        if (resultEl) {
 resultEl.textContent = `清理失败：${error.message}`;
            resultEl.title = '';
            resultEl.classList.add('show', 'error');
        }
        safeNotify(`清理失败: ${error.message}`, 'error');

    } finally {
        // 关键：无论成功失败，都要恢复按钮状态
        btn.disabled = false;
        btn.textContent = originalText
            || (deep ? '彻底清理（不留热缓存）' : '清理缓存释放内存');
        if (otherBtn) otherBtn.disabled = false;
    }
}

/* 从响应里判断本次是否 deep 模式（供 safeNotify 用，避免额外传参） */
function isDeepResult(data) {
    return !!(data && data.result && data.result.deep);
}

// ========== 页面初始化 ==========
// 应用主题并加载数据
(async function initConfig() {
    // 先确保主题正确
    if (typeof applyTheme === 'function') {
        await applyTheme();
    }

    // 延迟加载数据
    setTimeout(function () {
        loadUserRecords();
        if (IS_ADMIN) {
            loadUserList();
        }
    }, 100);

    // 刷新内存信息
    setTimeout(function () {
        refreshMemoryInfo();
    }, 300);
})();
