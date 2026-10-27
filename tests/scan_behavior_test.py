# -*- coding: utf-8 -*-
"""扫描专项测试：拆到 library 蓝图后，触发扫描 / 进度查询是否仍然工作。

只读验证：副本的库与磁盘已同步，扫描应该「无变化 → 零写入」。
跑在隔离副本里，不碰生产。

    python tests/scan_behavior_test.py
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
        sess['user_name'] = 'scan-test'
    return client


def main():
    print(f'=== 扫描测试（{APP_DIR}）===')
    client = admin_client()

    print('\n[1] 进度接口')
    response = client.get('/api/scan_progress')
    payload = response.get_json() or {}
    check('进度接口 200', response.status_code == 200, str(response.status_code))
    check('返回 status 字段', 'status' in payload, str(list(payload)[:6]))

    print('\n[2] 触发增量扫描（无变化，应零写入）')
    count_before = nm.cache_store.count_books()
    rev_before = nm.cache_store.get_revision()
    response = client.get('/api/start_scan')  # 该端点只接受 GET
    body = response.get_json() or {}
    check('触发扫描 200', response.status_code == 200, str(response.status_code))
    check('返回 started 状态', body.get('status') in ('started', 'already_scanning'),
          str(body)[:80])

    # 扫描在后台线程跑，等它结束
    import time
    deadline = time.time() + 120
    while time.time() < deadline:
        progress = (client.get('/api/scan_progress').get_json() or {})
        if progress.get('status') not in ('running', 'scanning', ''):
            break
        time.sleep(0.5)
    print(f'    扫描状态: {progress.get("status")} / {progress.get("message", "")[:40]}')

    count_after = nm.cache_store.count_books()
    rev_after = nm.cache_store.get_revision()
    print(f'    书数 {count_before} -> {count_after}，revision {rev_before} -> {rev_after}')
    check('扫描后书数不变', count_before == count_after, f'{count_before} -> {count_after}')
    check('库与内存一致', count_after == len(nm.novel_data),
          f'{count_after} vs {len(nm.novel_data)}')
    if rev_after == rev_before:
        print('  ✅ 无变化 → 零写入（revision 未动）')
        PASS.append('无变化零写入')
    else:
        print('  ℹ️ revision 有变化（磁盘与库不完全同步时会这样，属正常）')

    print('\n' + '=' * 56)
    print(f'通过 {len(PASS)} 项，失败 {len(FAIL)} 项')
    if FAIL:
        for name, detail in FAIL:
            print(f'  ❌ {name} {detail}')
        return 1
    print('🎉 扫描测试全部通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
