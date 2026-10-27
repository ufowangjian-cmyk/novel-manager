# -*- coding: utf-8 -*-
"""标签体系专项测试：证明拆到 library 蓝图后，对全局状态的写入仍然生效。

这是本次拆分最容易静默失败的地方：
  - api_tag_edit / delete / reapply 会遍历并修改 novel_data 里每本书的 tags
  - api_tag_reset / import / reload 会**重新赋值** TAG_IMPLICATIONS 等
如果这些操作用了 from-import 的副本（而不是 nm.X），返回值会"成功"，
但内存里的数据没变 —— 页面刷新就看出不对了。

跑在隔离副本里，会改动副本的标签与缓存。
"""

import json
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
PROBE_OLD = '人妻'      # 批量数据里最常见的标签之一
PROBE_NEW = 'zz自测标签'


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
        sess['user_name'] = 'tag-test'
    return client


def tag_of(book_title_part):
    for book in nm.novel_data:
        if book_title_part in (book.get('title') or ''):
            return book.get('tags')
    return None


def main():
    print(f'=== 标签体系测试（{APP_DIR}）===')
    client = admin_client()

    # ---------- 读 ----------
    print('\n[1] 读接口')
    response = client.get('/api/tag/list')
    check('标签列表 200', response.status_code == 200, str(response.status_code))
    payload = response.get_json()
    check('标签列表有内容', bool(payload), str(type(payload)))
    response = client.get('/api/tag/stats')
    check('标签统计 200', response.status_code == 200, str(response.status_code))
    response = client.get('/api/tag/rules/get')
    rules = response.get_json() or {}
    check('规则接口 200', response.status_code == 200)
    check('规则含 keywords/implications',
          bool(rules.get('keywords')) and isinstance(rules.get('implications'), dict))
    response = client.get('/api/tag/export')
    check('导出 200', response.status_code == 200, str(response.status_code))

    # ---------- 改：遍历 novel_data ----------
    print('\n[2] 改标签（遍历 nm.novel_data）')
    before = sum(1 for book in nm.novel_data
                 if PROBE_OLD in (book.get('tags') or '').split(','))
    response = client.post('/api/tag/edit', json={'old_name': PROBE_OLD, 'new_name': PROBE_NEW})
    body = response.get_json() or {}
    check('编辑标签 200', response.status_code == 200, str(response.status_code))
    check(f'返回的改动数 > 0（{body.get("count")}，改前 {before} 本）',
          (body.get('count') or 0) > 0, str(body))
    after = sum(1 for book in nm.novel_data
                if PROBE_NEW in (book.get('tags') or '').split(','))
    check('内存 novel_data 里真的出现了新标签', after > 0, f'{after} 本')
    still_old = sum(1 for book in nm.novel_data
                    if PROBE_OLD in (book.get('tags') or '').split(','))
    check('旧标签已被替换掉', still_old == 0, f'还剩 {still_old} 本')
    response = client.get('/api/tag/list')
    check('列表接口能看到新标签', PROBE_NEW in json.dumps(response.get_json(), ensure_ascii=False))

    print('\n[3] 删除标签')
    response = client.post('/api/tag/delete', json={'tag': PROBE_NEW})
    body = response.get_json() or {}
    check('删除标签 200', response.status_code == 200, str(response.status_code))
    check('删除影响了若干本', (body.get('count') or 0) > 0, str(body))
    left = sum(1 for book in nm.novel_data
               if PROBE_NEW in (book.get('tags') or '').split(','))
    check('内存里已无该标签', left == 0, f'还剩 {left} 本')

    # ---------- 改：重新赋值 TAG_* 全局 ----------
    print('\n[4] 规则重置（重新赋值 nm.TAG_IMPLICATIONS）')
    response = client.post('/api/tag/reset')
    check('重置规则 200', response.status_code == 200, str(response.status_code))
    check('nm.TAG_IMPLICATIONS 仍在', isinstance(nm.TAG_IMPLICATIONS, dict))

    print('\n[5] 规则重载（重新赋值 nm.TAG_* 三个全局）')
    before_kw = len(nm.TAG_KEYWORDS or [])
    response = client.post('/api/tag/rules/reload')
    check('重载规则 200', response.status_code == 200, str(response.status_code))
    check('重载后 keywords 非空', len(nm.TAG_KEYWORDS or []) > 0,
          f'{before_kw} -> {len(nm.TAG_KEYWORDS or [])}')
    check('重载后 aliases 是 dict', isinstance(nm.TAG_ALIASES, dict))
    check('重载后 implications 是 dict', isinstance(nm.TAG_IMPLICATIONS, dict))

    # ---------- 写盘一致性 ----------
    print('\n[6] 落库')
    nm.save_cache()
    reloaded = nm.cache_store.load_all()
    probe = [b for b in reloaded if PROBE_NEW in (b.get('tags') or '').split(',')]
    check('改动已同步到 SQLite（库里无残留自测标签）', not probe, f'{len(probe)} 本')

    print('\n' + '=' * 56)
    print(f'通过 {len(PASS)} 项，失败 {len(FAIL)} 项')
    if FAIL:
        for name, detail in FAIL:
            print(f'  ❌ {name} {detail}')
        return 1
    print('🎉 标签体系测试全部通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
