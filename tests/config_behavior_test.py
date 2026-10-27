# -*- coding: utf-8 -*-
"""配置保存/重载专项测试：拆到 library 后，`global CONFIG` 是否还能生效。

这是最危险的一处 —— 原代码里 save_config_api / reload_config_api 做的是
`global CONFIG; CONFIG = 新dict`（整个对象替换）。搬到蓝图后必须写成
`nm.CONFIG = 新dict`，否则：
  - 主模块的 CONFIG 不更新 → 全站继续用旧配置
  - 其他蓝图（auth）绑的也是旧对象 → 用户管理读到旧用户表

顺带验证 `apply_runtime_config()` 有没有把 NOVEL_DIR / PER_PAGE 同步到主模块。
"""

import os
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

_REAL_STDOUT = sys.stdout
sys.stdout = sys.stderr
try:
    import novel_manager as nm
finally:
    sys.stdout = _REAL_STDOUT

PASS = []
FAIL = []


def check(name, condition, detail=''):
    if condition:
        PASS.append(name)
        print(f'  ✅ {name}')
    else:
        FAIL.append((name, detail))
        print(f'  ❌ {name}  {detail}')


def admin_client():
    client = nm.app.test_client()
    admin_key = admin_info = None
    for key, info in (nm.CONFIG.get('users') or {}).items():
        if isinstance(info, dict) and info.get('role') == 'admin':
            admin_key, admin_info = key, info
            break
    with client.session_transaction() as sess:
        sess['authenticated'] = True
        sess['user_key'] = admin_key
        sess['user_role'] = 'admin'
        sess['user_id'] = admin_info.get('user_id', 'admin')
        sess['user_name'] = 'config-test'
    return client


def main():
    print(f'=== 配置保存/重载测试（{APP_DIR}）===')
    client = admin_client()

    original_per_page = nm.CONFIG.get('per_page', 100)
    original_per_page_const = nm.PER_PAGE
    print(f'# 初始 per_page={original_per_page}，PER_PAGE 常量={original_per_page_const}')

    # ---------- 保存 ----------
    print('\n[1] POST /config/save 改 per_page = 50')
    old_config_id = id(nm.CONFIG)
    response = client.post('/config/save', json={'per_page': 50})
    check('保存配置 200', response.status_code == 200, str(response.status_code))
    body = response.get_json() or {}
    check('返回 success', body.get('success') is True, str(body)[:80])

    check('主模块 CONFIG 的 per_page 已更新', nm.CONFIG.get('per_page') == 50,
          str(nm.CONFIG.get('per_page')))
    check('CONFIG 对象被整体替换（id 变化）', id(nm.CONFIG) != old_config_id,
          '同一对象（可能只做了原地更新）')
    check('apply_runtime_config 生效：PER_PAGE 常量同步', nm.PER_PAGE == 50,
          f'PER_PAGE={nm.PER_PAGE}')

    # ---------- 跨蓝图一致性 ----------
    print('\n[2] 其他蓝图能否读到新 CONFIG')
    response = client.get('/api/users/list')
    check('auth 用户列表仍 200（没绑死旧对象）', response.status_code == 200,
          str(response.status_code))
    response = client.get('/')
    check('index 仍 200（library 自己也读到新值）', response.status_code == 200,
          str(response.status_code))

    # ---------- 重载 ----------
    print('\n[3] POST /config/reload 从磁盘重载')
    response = client.post('/config/reload')
    check('重载 200', response.status_code == 200, str(response.status_code))
    check('重载后 per_page 仍是 50（已落盘）', nm.CONFIG.get('per_page') == 50,
          str(nm.CONFIG.get('per_page')))

    # ---------- 还原 ----------
    print('\n[4] 还原')
    response = client.post('/config/save', json={'per_page': original_per_page})
    check('还原成功', response.status_code == 200, str(response.status_code))
    check('CONFIG 已还原', nm.CONFIG.get('per_page') == original_per_page,
          str(nm.CONFIG.get('per_page')))

    # ---------- 配置页 ----------
    print('\n[5] 配置页渲染')
    response = client.get('/config')
    check('配置页 200', response.status_code == 200, str(response.status_code))
    check('配置页非空', len(response.get_data()) > 10000, str(len(response.get_data())))
    response = client.get('/config/get')
    payload = response.get_json() or {}
    check('/config/get 200', response.status_code == 200, str(response.status_code))
    check('/config/get 不含 users（脱敏）', 'users' not in payload, str(list(payload)[:8]))

    print('\n' + '=' * 56)
    print(f'通过 {len(PASS)} 项，失败 {len(FAIL)} 项')
    if FAIL:
        for name, detail in FAIL:
            print(f'  ❌ {name} {detail}')
        return 1
    print('🎉 配置测试全部通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
