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

// 渲染关键词列表（可删除、可编辑）
function renderKeywordList(keywords) {
    const container = document.getElementById('keywordListContainer');
    if (!keywords || keywords.length === 0) {
        container.innerHTML = '<div class="empty-hint">暂无关键词，点击"添加"创建</div>';
        return;
    }
    
    container.innerHTML = `
        <div class="tag-items">
            ${keywords.map((keyword, index) => `
                <div class="tag-item" data-index="${index}">
                    <span class="tag-name">${escapeHtml(keyword)}</span>
                    <button class="tag-edit"onclick="editKeyword(${index})">${icon('pencil', 'sm')}</button>
                    <button class="tag-delete"onclick="deleteKeyword(${index})">${icon('x', 'sm')}</button>
                </div>
            `).join('')}
        </div>
    `;
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
                <div class="alias-display-text" data-main="${escapeHtml(mainTag)}" data-aliases="${escapeHtml(aliasStr)}">
                    <span class="alias-main-badge">${escapeHtml(mainTag)}</span>
                    <span class="alias-arrow">${icon('arrow-right', 'sm')}</span>
                    <span class="alias-list-badge">${escapeHtml(aliasStr)}</span>
                    <button class="alias-delete" data-main="${escapeHtml(mainTag)}">${icon('trash-2', 'sm')}</button>
                </div>
            </div>
        `;
    }
    html += '</div>';
    container.innerHTML = html;

    // 事件委托：点击别名项 → 打开弹窗
    container.querySelectorAll('.alias-display-text').forEach(el => {
        el.addEventListener('click', function (e) {
            if (e.target.classList.contains('alias-delete')) return;
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
    
    container.innerHTML = `
        <div class="rule-items">
            ${rulesArray.map((rule, index) => `
                <div class="rule-item" data-index="${index}">
                    <span class="rule-source">${escapeHtml(rule.source)}</span>
                    <span class="rule-arrow">${icon('arrow-right', 'sm')}</span>
                    <span class="rule-derived">${escapeHtml(rule.derived)}</span>
                    <button class="rule-delete"onclick="deleteDerivedRule(${index})">${icon('x', 'sm')}</button>
                </div>
            `).join('')}
        </div>
    `;
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
async function deleteKeyword(index) {
    if (!confirm('确定要删除这个关键词吗？')) return;
    
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


// 编辑关键词
async function editKeyword(index) {
    const keyword = prompt('请输入新的关键词:');
    if (!keyword) return;
    
    const response = await fetch('/api/tag/keyword/edit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ index, keyword })
    });
    
    const result = await response.json();
    if (result.success) {
        showNotification('关键词已修改', 'success');
        loadTagRules();
    } else {
        showNotification(result.message, 'error');
    }
}


// 删除别名（原地编辑版本，接收 mainTag）
async function deleteAlias(mainTag) {
    if (!confirm('确定要删除这个别名映射吗？')) return;
    
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
async function deleteDerivedRule(index) {
    if (!confirm('确定要删除这个派生规则吗？')) return;
    
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

// 收集当前关键词（从DOM）
function collectKeywords() {
    const items = document.querySelectorAll('#keywordListContainer .tag-item');
    const keywords = [];
    items.forEach(item => {
        const nameSpan = item.querySelector('.tag-name');
        if (nameSpan) {
            keywords.push(nameSpan.textContent);
        }
    });
    return keywords;
}

// 收集当前别名（从DOM）
function collectAliases() {
    const items = document.querySelectorAll('#aliasListContainer .alias-item');
    const aliases = {};
    items.forEach(item => {
        const mainTag = item.dataset.main;
        const aliasStr = item.dataset.aliases;
        if (mainTag && aliasStr) {
            const list = aliasStr.split(/[ ,，]+/).filter(s => s.trim());
            aliases[mainTag] = list;
        }
    });
    return aliases;
}

// 收集当前派生规则（从DOM）
function collectImplications() {
    const items = document.querySelectorAll('#ruleListContainer .rule-item');
    const implications = {};
    items.forEach(item => {
        const sourceSpan = item.querySelector('.rule-source');
        const derivedSpan = item.querySelector('.rule-derived');
        if (sourceSpan && derivedSpan) {
            const source = sourceSpan.textContent;
            const derived = derivedSpan.textContent;
            if (!implications[source]) {
                implications[source] = [];
            }
            if (!implications[source].includes(derived)) {
                implications[source].push(derived);
            }
        }
    });
    return implications;
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
