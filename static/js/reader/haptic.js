// ============================================
// haptic.js - 震动反馈（Android 优先）
// 依赖：无
// iOS 不支持，调用会静默忽略
// ============================================

(function () {
    'use strict';

    // 震动模式配置
    const PATTERNS = {
        light: 10,              // 轻触
        medium: 20,             // 中等
        heavy: 50,              // 重
        success: [10, 40, 10],  // 成功
        error: [50, 30, 50],    // 错误
    };

    let enabled = true;

    // ===== 检查是否可用 =====
    function isSupported() {
        return 'vibrate' in navigator && typeof navigator.vibrate === 'function';
    }

    // ===== 触发震动 =====
    function vibrate(type = 'light') {
        if (!enabled) return;
        if (!isSupported()) return;

        const pattern = PATTERNS[type] || PATTERNS.light;

        try {
            navigator.vibrate(pattern);
        } catch (e) {
            // 静默失败
        }
    }

    // ===== 开关 =====
    function setEnabled(value) {
        enabled = !!value;
        localStorage.setItem('haptic_enabled', enabled ? '1' : '0');
        console.log(`📳 震动反馈: ${enabled ? '开启' : '关闭'}`);
    }

    function isEnabled() {
        return enabled;
    }

    // ===== 初始化（从 localStorage 读设置）=====
    function initHaptic() {
        const saved = localStorage.getItem('haptic_enabled');
        if (saved !== null) {
            enabled = saved === '1';
        }

        if (!isSupported()) {
            console.log('ℹ️ 当前设备不支持震动');
        }
    }

    // ===== 暴露全局 =====
    window.vibrate = vibrate;
    window.setHapticEnabled = setEnabled;
    window.isHapticEnabled = isEnabled;
    window.isHapticSupported = isSupported;
    window.initHaptic = initHaptic;

    console.log('✅ haptic.js 已加载');
})();