# -*- coding: utf-8 -*-
"""reader 蓝图专项：阅读页、进度写入、标记已读、删记录、清空、书内搜索。

覆盖 10 条 reader 路由里的写入路径 —— 这些在行为基线里只测了"读"，
写坏了（比如 `save_reading_record` 引用丢失）基线是看不出来的。

跑在隔离副本里，会写 / 清副本的阅读记录。
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
        sess['user_name'] = 'reader-test'
    return client


def main():
    print(f'=== reader 蓝图测试（{APP_DIR}）===')
    client = admin_client()

    book = nm.novel_data[0]
    filename = book['filename']
    work_id = book.get('work_id') or ''
    print(f'# 测试书: {filename[:30]}… work_id={work_id[:12]}')

    # ---------- 从干净状态开始 ----------
    print('\n[1] 清空现有记录')
    client.post('/clear_records')
    response = client.get('/api/recent_records')
    payload = response.get_json() or {}
    items = payload.get('records') if isinstance(payload, dict) else payload
    check('清空后最近记录为空', not items, str(items)[:80])

    # ---------- 阅读页写进度 ----------
    print('\n[2] 打开阅读页（写进度）')
    response = client.get(f'/read/{filename}/1')
    check('阅读页 200', response.status_code == 200, str(response.status_code))
    check('页面含正文容器', 'reader' in response.get_data(as_text=True).lower())
    response = client.get('/api/recent_records')
    payload = response.get_json() or {}
    items = payload.get('records') if isinstance(payload, dict) else payload
    check('最近记录已出现该本书', bool(items), str(items)[:100])

    # ---------- 继续阅读 ----------
    print('\n[3] 继续阅读')
    response = client.get(f'/continue/{filename}')
    check('continue 302（有记录 → 跳到具体行）', response.status_code == 302,
          str(response.status_code))

    # ---------- 书内搜索 ----------
    print('\n[4] 书内搜索')
    keyword = (book.get('title') or '的')[:2]
    response = client.get(f'/api/search_in_novel?file_path={filename}&keyword={keyword}&limit=5')
    check('搜索接口 200', response.status_code == 200, str(response.status_code))
    body = response.get_json() or {}
    check('搜索返回结构正常', isinstance(body, dict), str(body)[:80])

    # ---------- 标记已读 ----------
    print('\n[5] 标记已读')
    response = client.post('/api/mark_read', json={
        'file_path': filename, 'finished': True,
        'title': book.get('title'), 'author': book.get('author'),
    })
    check('标记已读 200', response.status_code == 200, str(response.status_code))
    body = response.get_json() or {}
    check('标记成功', body.get('success') is True, str(body)[:100])

    # ---------- 删单条记录 ----------
    print('\n[6] 删除单条记录')
    response = client.post('/api/delete_record', json={'file_path': filename, 'work_id': work_id})
    check('删除记录 200', response.status_code == 200, str(response.status_code))
    body = response.get_json() or {}
    check('删除成功', body.get('success') is True, str(body)[:100])
    response = client.get('/api/recent_records')
    payload = response.get_json() or {}
    items = payload.get('records') if isinstance(payload, dict) else payload
    check('最近记录已减少', not items or len(items) == 0, str(len(items) if items else 0))

    # ---------- 无记录时 continue 的行为 ----------
    print('\n[7] 无记录时 continue（应回落到可读页或首页）')
    response = client.get(f'/continue/{filename}')
    check('continue 仍返回 302（不 500）', response.status_code == 302,
          str(response.status_code))

    # ---------- 管理员记录清理 ----------
    print('\n[8] 管理员清理接口')
    response = client.post('/admin/clear_all_records')
    check('admin/clear_all_records 不 500', response.status_code in (200, 302),
          str(response.status_code))

    print('\n' + '=' * 56)
    print(f'通过 {len(PASS)} 项，失败 {len(FAIL)} 项')
    if FAIL:
        for name, detail in FAIL:
            print(f'  ❌ {name} {detail}')
        return 1
    print('🎉 reader 测试全部通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
