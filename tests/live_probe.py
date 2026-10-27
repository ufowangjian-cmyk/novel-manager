# -*- coding: utf-8 -*-
"""线上探针：用真实 secret_key 签一个会话 cookie，走 HTTP 验证真实服务。

不导入 novel_manager（避免在独立进程里再起一遍 bootstrap），只读 data/ 下的
secret_key 与 config.json，因此对正在运行的服务没有任何副作用。

    python tests/live_probe.py [base_url]
"""

import json
import os
import sys
import urllib.parse
import urllib.request

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(APP_DIR, 'data')
BASE_URL = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:5000').rstrip('/')

if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

PASS = []
FAIL = []


def check(name, condition, detail=''):
    if condition:
        PASS.append(name)
        print(f'  ✅ {name}')
    else:
        FAIL.append((name, detail))
        print(f'  ❌ {name}  {detail}')


def build_cookie():
    """按 Flask 的 SecureCookieSessionInterface 规则签名 session。"""
    from flask import Flask
    from flask.sessions import SecureCookieSessionInterface

    with open(os.path.join(DATA_DIR, 'secret_key'), encoding='utf-8') as handle:
        secret = handle.read().strip()

    with open(os.path.join(DATA_DIR, 'config.json'), encoding='utf-8') as handle:
        config = json.load(handle)

    users = config.get('users') or {}
    admin_key = admin_user = None
    for key, info in users.items():
        if isinstance(info, dict) and info.get('role') == 'admin':
            admin_key, admin_user = key, info
            break
    if not admin_key:
        raise SystemExit('config.json 里没有管理员账号')

    app = Flask(__name__)
    app.secret_key = secret
    serializer = SecureCookieSessionInterface().get_signing_serializer(app)
    payload = {
        'authenticated': True,
        'user_key': admin_key,
        'user_role': 'admin',
        'user_id': admin_user.get('user_id', 'admin'),
        'user_name': f"{admin_user.get('user_id', 'admin')}（管理员）",
    }
    return serializer.dumps(payload), admin_user.get('user_id', 'admin')


def fetch(path, cookie):
    url = BASE_URL + urllib.parse.quote(path, safe='/?=&%')
    request = urllib.request.Request(url, headers={'Cookie': f'session={cookie}'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, response.read().decode('utf-8', 'replace')


def main():
    from storage import cache_store

    db_path = os.path.join(DATA_DIR, 'novel_cache.db')
    cache_store.set_db_path(db_path)
    stats = cache_store.stats()
    print(f'=== 库状态 === {stats}')

    cookie, user_id = build_cookie()
    print(f'=== 以 {user_id} 的会话访问 {BASE_URL} ===')

    status, body = fetch('/', cookie)
    check('列表页 200', status == 200, str(status))
    check('列表页有内容（> 50KB）', len(body) > 50000, f'{len(body)} 字节')
    check('列表页没退化成登录页', 'password' not in body[:4000].lower()
          or '登录' not in body[:2000])

    books = cache_store.list_books()
    sample = books[0]
    check('库里能取到书', bool(books), str(len(books)))

    status, body = fetch(f"/novel_detail/{sample['filename']}", cookie)
    check('详情页 200', status == 200, str(status))
    check('详情页含书名', (sample['title'] or '')[:10] in body)

    status, body = fetch(f"/read/{sample['filename']}/1", cookie)
    check('阅读页 200', status == 200, str(status))

    status, body = fetch('/api/cache/stats', cookie)
    check('缓存统计接口 200', status == 200, str(status))
    if status == 200:
        data = json.loads(body)
        print(f"    内存 RSS={data.get('memory_mb')}MB  "
              f"tag_cache={data.get('tag_cache')} chapter_cache={data.get('chapter_cache')}")
        check('接口返回内存数据', data.get('memory_mb') is not None)

    status, body = fetch('/get_all_tags', cookie)
    check('标签筛选接口有内容', status == 200 and len(body) > 100, f'{len(body)} 字节')

    status, body = fetch('/api/scan_progress', cookie)
    check('扫描进度接口 200', status == 200, str(status))

    print('\n' + '=' * 56)
    print(f'通过 {len(PASS)} 项，失败 {len(FAIL)} 项')
    if FAIL:
        for name, detail in FAIL:
            print(f'  ❌ {name} {detail}')
        return 1
    print('🎉 线上探针全部通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
