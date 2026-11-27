// 加载标签规则
async function loadTagRules() {
    const response = await fetch('/api/tag/rules/get');
    const rules = await response.json();
    
    // 渲染关键词列表
    renderKeywordList(rules.keywords);
    
    // 渲染别名列表
    renderAliases(rules.aliases);
    
    // 渲染派生规则列表
    renderRuleList(rules.implications);
}

// 渲染关键词列表（只删除，不在此处编辑 —— 打错了就删掉重加，和配置页「书名高亮词」一致）
function renderKeywordList(keywords) {
    const container = document.getElementById('keywordListContainer');
    if (!keywords || keywords.length === 0) {
        container.innerHTML = '<div class="empty-hint">暂无关键词，点击"添加"创建</div>';
        return;
    }

    // 胶囊本身就是按钮：点开弹窗改/删，不再每个胶囊挂一个 ×（2026-11-23）
    container.innerHTML = `
        <div class="tag-items">
            ${keywords.map((keyword, index) => `
                <button type="button" class="tag-item" data-index="${index}" data-keyword="${escapeHtml(keyword)}">
                    <span class="tag-name">${escapeHtml(keyword)}</span>
                </button>
            `).join('')}
        </div>
    `;

    container.querySelectorAll('.tag-item').forEach(el => {
        el.addEventListener('click', function () {
            const kw = this.dataset.keyword;
            const idx = Number(this.dataset.index);
            openChipEditor({
                title: '编辑关键词',
                value: kw,
                hint: '改完点保存；也可以直接删除。规则改动只对之后的扫描生效。',
                onSave: function (v) { if (v !== kw) renameKeyword(idx, v); },
                onDelete: function () { deleteKeyword(idx, true); }
            });
        });
    });
}

// 关键词重命名：接口只有 add / delete，这里先删旧的再加新的
async function renameKeyword(index, newKeyword) {
    const delResp = await fetch('/api/tag/keyword/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ index })
    });
    const delResult = await delResp.json();
    if (!delResult.success) {
        showNotification('重命名失败: ' + (delResult.message || '删除旧词失败'), 'error');
        return;
    }

    const addResp = await fetch('/api/tag/keyword/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keyword: newKeyword })
    });
    const addResult = await addResp.json();
    if (!addResult.success) {
        showNotification('重命名失败: ' + (addResult.message || '新词未能添加'), 'error');
        loadTagRules();
        return;
    }

    showNotification('关键词已更新', 'success');
    loadTagRules();
}

// 渲染别名列表 - 弹窗编辑版（安全版）
function renderAliases(aliases) {
    const container = document.getElementById('aliasListContainer');
    if (!container) return;

    if (!aliases || Object.keys(aliases).length === 0) {
        container.innerHTML = '<div class="empty-hint">暂无别名映射，点击上方添加</div>';
        return;
    }

    let html = '<div class="alias-items">';
    for (const [mainTag, aliasList] of Object.entries(aliases)) {
        const aliasStr = Array.isArray(aliasList) ? aliasList.join(', ') : aliasList;

        html += `
            <div class="alias-item">
                <button type="button" class="alias-display-text" data-main="${escapeHtml(mainTag)}" data-aliases="${escapeHtml(aliasStr)}">
                    <span class="alias-main-badge">${escapeHtml(mainTag)}</span>
                    <span class="alias-arrow">${icon('arrow-right', 'sm')}</span>
                    <span class="alias-list-badge">${escapeHtml(aliasStr)}</span>
                </button>
            </div>
        `;
    }
    html += '</div>';
    container.innerHTML = html;

    // 事件委托：点击别名项 → 打开弹窗
    container.querySelectorAll('.alias-display-text').forEach(el => {
        el.addEventListener('click', function () {
            openAliasModal(this.dataset.main, this.dataset.aliases);
        });
    });

    // 事件委托：删除按钮
    container.querySelectorAll('.alias-delete').forEach(btn => {
        btn.addEventListener('click', function (e) {
            e.stopPropagation();
            deleteAlias(this.dataset.main);
        });
    });
}

// 打开别名编辑弹窗
let currentEditingMainTag = null;

function openAliasModal(mainTag, aliasesStr) {
    currentEditingMainTag = mainTag;
    const modal = document.getElementById('aliasModal');
    const mainTagInput = document.getElementById('modalMainTag');
    const aliasesTextarea = document.getElementById('modalAliases');
    
    mainTagInput.value = mainTag;
    aliasesTextarea.value = aliasesStr;
    
    modal.style.display = 'flex';
    // 自动聚焦到文本框
    setTimeout(() => aliasesTextarea.focus(), 100);
}

// 从弹窗里删除当前编辑的别名映射
function deleteAliasFromModal() {
    if (!currentEditingMainTag) return;
    var mainTag = currentEditingMainTag;
    closeAliasModal();
    deleteAlias(mainTag, true);
}

// 关闭弹窗
function closeAliasModal() {
    const modal = document.getElementById('aliasModal');
    modal.style.display = 'none';
    currentEditingMainTag = null;
}

// 从弹窗保存别名
async function saveAliasFromModal() {
    if (!currentEditingMainTag) {
        showNotification('编辑失败：找不到主标签', 'error');
        closeAliasModal();
        return;
    }
    
    const newAliases = document.getElementById('modalAliases').value.trim();
    
    if (!newAliases) {
        showNotification('别名不能为空', 'error');
        return;
    }
    
    // 显示加载状态
    const saveBtn = document.querySelector('#aliasModal .btn-success');
    const originalText = saveBtn.innerHTML;
    saveBtn.innerHTML = icon('loader', 'sm') + ' 保存中...';
    saveBtn.disabled = true;
    
    try {
        const response = await fetch('/api/tag/alias/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                main_tag: currentEditingMainTag, 
                aliases: newAliases 
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showNotification('别名已更新', 'success');
            closeAliasModal();
            loadTagRules(); // 刷新列表
        } else {
            showNotification('更新失败: ' + (result.message || '未知错误'), 'error');
        }
    } catch (err) {
        console.error('更新失败:', err);
        showNotification('更新失败: ' + err.message, 'error');
    } finally {
        saveBtn.innerHTML = originalText;
        saveBtn.disabled = false;
    }
}

// 点击弹窗外层关闭
document.addEventListener('click', function(e) {
    const modal = document.getElementById('aliasModal');
    if (modal && modal.style.display === 'flex') {
        if (e.target.classList.contains('modal-overlay')) {
            closeAliasModal();
        }
    }
});

// ESC 键关闭弹窗
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        const modal = document.getElementById('aliasModal');
        if (modal && modal.style.display === 'flex') {
            closeAliasModal();
        }
    }
});

// 辅助函数
function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>]/g, function(m) {
        if (m === '&') return '&amp;';
        if (m === '<') return '&lt;';
        if (m === '>') return '&gt;';
        return m;
    });
}

// 渲染派生规则列表
function renderRuleList(implications) {
    const container = document.getElementById('ruleListContainer');
    const rulesArray = [];
    
    for (const [source, derivedList] of Object.entries(implications)) {
        for (const derived of derivedList) {
            rulesArray.push({ source, derived });
        }
    }
    
    if (rulesArray.length === 0) {
        container.innerHTML = '<div class="empty-hint">暂无派生规则</div>';
        return;
    }
    
    // 胶囊即按钮：点开弹窗改/删（2026-11-23）
    container.innerHTML = `
        <div class="rule-items">
            ${rulesArray.map((rule, index) => `
                <button type="button" class="rule-item" data-index="${index}">
                    <span class="rule-source">${escapeHtml(rule.source)}</span>
                    <span class="rule-arrow">${icon('arrow-right', 'sm')}</span>
                    <span class="rule-derived">${escapeHtml(rule.derived)}</span>
                </button>
            `).join('')}
        </div>
    `;

    container.querySelectorAll('.rule-item').forEach(el => {
        el.addEventListener('click', function () {
            const idx = Number(this.dataset.index);
            const rule = rulesArray[idx];
            if (!rule) return;
            openChipEditor({
                title: '编辑派生规则',
                fields: [
                    { label: '源标签', value: rule.source, placeholder: '例如：jk' },
                    { label: '派生标签', value: rule.derived, placeholder: '例如：制服诱惑' }
                ],
                hint: '分别修改源标签和派生标签，互不影响；也可以直接删除这条规则。',
                onSave: function (values) { renameRule(rule, values[0], values[1]); },
                onDelete: function () { deleteDerivedRule(idx, true); }
            });
        });
    });
}

// 派生规则重命名：接口只有 add / delete，这里先删旧规则再加新规则。
// 源标签与派生标签分别传入（弹窗里是两个独立输入框），不再解析文本。
async function renameRule(oldRule, source, derived) {
    source = String(source || '').trim();
    derived = String(derived || '').trim();
    if (!source || !derived) return;
    if (source === oldRule.source && derived === oldRule.derived) return;

    const delResp = await fetch('/api/tag/rule/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: oldRule.source, derived: oldRule.derived })
    });
    const delResult = await delResp.json();
    if (!delResult.success) {
        showNotification('修改失败: ' + (delResult.message || '删除旧规则失败'), 'error');
        return;
    }

    const addResp = await fetch('/api/tag/rule/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: source, derived: [derived] })
    });
    const addResult = await addResp.json();
    if (!addResult.success) {
        showNotification('修改失败: ' + (addResult.message || '新规则未能添加'), 'error');
        loadTagRules();
        return;
    }

    showNotification('派生规则已更新', 'success');
    loadTagRules();
}

// 添加关键词
async function addKeyword() {
    const keyword = document.getElementById('newKeyword').value.trim();
    if (!keyword) {
        showNotification('请输入关键词', 'error');
        return;
    }
    
    const response = await fetch('/api/tag/keyword/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keyword })
    });
    
    const result = await response.json();
    if (result.success) {
        showNotification('关键词已添加', 'success');
        document.getElementById('newKeyword').value = '';
        loadTagRules(); // 重新加载
    } else {
        showNotification(result.message, 'error');
    }
}

// 删除关键词
async function deleteKeyword(index, skipConfirm) {
    if (!skipConfirm && !confirm('确定要删除这个关键词吗？')) return;
    
    const response = await fetch('/api/tag/keyword/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ index })
    });
    
    const result = await response.json();
    if (result.success) {
        showNotification('关键词已删除', 'success');
        loadTagRules();
    }
}

// 添加别名（支持全角逗号）
async function addAlias() {
    const mainTag = document.getElementById('aliasMainTag').value.trim();
    const aliases = document.getElementById('aliasTag').value.trim();
    
    if (!mainTag || !aliases) {
        showNotification('请填写主标签和别名', 'error');
        return;
    }
    
    // 支持半角逗号、全角逗号、空格作为分隔符
    const aliasList = aliases.split(/[ ,，]+/).filter(s => s.trim());
    
    const response = await fetch('/api/tag/alias/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ main: mainTag, aliases: aliasList })
    });
    
    const result = await response.json();
    if (result.success) {
        showNotification('别名映射已添加', 'success');
        document.getElementById('aliasMainTag').value = '';
        document.getElementById('aliasTag').value = '';
        loadTagRules();
    }
}

// 添加派生规则（支持全角逗号）
async function addDerivedRule() {
    const source = document.getElementById('sourceTag').value.trim();
    const derived = document.getElementById('derivedTag').value.trim();
    
    if (!source || !derived) {
        showNotification('请填写源标签和派生标签', 'error');
        return;
    }
    
    // 支持半角逗号、全角逗号、空格作为分隔符
    const derivedList = derived.split(/[ ,，]+/).filter(s => s.trim());
    
    const response = await fetch('/api/tag/rule/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source, derived: derivedList })
    });
    
    const result = await response.json();
    if (result.success) {
        showNotification('派生规则已添加', 'success');
        document.getElementById('sourceTag').value = '';
        document.getElementById('derivedTag').value = '';
        loadTagRules();
    }
}




// 删除别名（原地编辑版本，接收 mainTag）
async function deleteAlias(mainTag, skipConfirm) {
    if (!skipConfirm && !confirm('确定要删除这个别名映射吗？')) return;
    
    const response = await fetch('/api/tag/alias/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ main: mainTag })
    });
    
    const result = await response.json();
    if (result.success) {
        showNotification('别名已删除', 'success');
        loadTagRules();
    } else {
        showNotification(result.message || '删除失败', 'error');
    }
}

// 删除派生规则 - 修复版（发送 source 和 derived）
async function deleteDerivedRule(index, skipConfirm) {
    if (!skipConfirm && !confirm('确定要删除这个派生规则吗？')) return;
    
    // 获取当前规则列表，找到对应的 source 和 derived
    const response = await fetch('/api/tag/rules/get');
    const rules = await response.json();
    const implications = rules.implications;
    
    // 构建规则数组
    const rulesArray = [];
    for (const [source, derivedList] of Object.entries(implications)) {
        for (const derived of derivedList) {
            rulesArray.push({ source, derived });
        }
    }
    
    if (index >= 0 && index < rulesArray.length) {
        const { source, derived } = rulesArray[index];
        
        // 改为发送 source 和 derived
        const deleteResponse = await fetch('/api/tag/rule/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ source, derived })  // 改为发送 source 和 derived
        });
        
        const result = await deleteResponse.json();
        if (result.success) {
            showNotification('派生规则已删除', 'success');
            loadTagRules();
        } else {
            showNotification(result.message || '删除失败', 'error');
        }
    }
}




// 重载标签规则
async function reloadTagRules() {
    showLoading(true);
    
    const response = await fetch('/api/tag/rules/reload', {
        method: 'POST'
    });
    
    const result = await response.json();
    showLoading(false);
    
    if (result.success) {
        showNotification('标签规则已重载', 'success');
        loadTagRules();
    } else {
        showNotification('重载失败: ' + result.message, 'error');
    }
}

// 重置标签规则
async function resetTagRules() {
    if (!confirm('确定要重置所有标签规则吗？这将删除所有自定义的关键词、别名和派生规则！')) return;
    
    showLoading(true);
    
    const response = await fetch('/api/tag/reset', {
        method: 'POST'
    });
    
    const result = await response.json();
    showLoading(false);
    
    if (result.success) {
        showNotification('标签规则已重置', 'success');
        loadTagRules();
    } else {
        showNotification('重置失败: ' + result.message, 'error');
    }
}
