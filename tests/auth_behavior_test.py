# -*- coding: utf-8 -*-
"""auth 蓝图专项行为测试：登录 / 登出 / 用户管理 / 个人偏好。

跑在隔离副本里（会往副本的 config.json 注入一个测试用户），不碰真实数据。

    python tests/auth_behavior_test.py

覆盖的不只是「能登录」，还包括拆蓝图后最容易坏的两处：
  1. 端点改名前缀后，模板与代码里的 url_for 是否都能解析（BuildError）
  2. CONFIG 被整体重新赋值后，auth 是否还能读到最新用户表（from-import 分叉）
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

TEST_USER = 'auth_test_user'
TEST_PASS = 'test123456'


def check(name, condition, detail=''):
    if condition:
        PASS.append(name)
        print(f'  ✅ {name}')
    else:
        FAIL.append((name, detail))
        print(f'  ❌ {name}  {detail}')


def main():
    print(f'=== auth 行为测试（{APP_DIR}）===')

    # ---------- 准备：注入一个已知密码的管理员 ----------
    key = nm.new_user_key()
    users = dict(nm.CONFIG.get('users') or {})
    users[key] = {
        'role': 'admin',
        'user_id': TEST_USER,
        'password_hash': nm.hash_password(TEST_PASS),
        'avatar': {'seed': 777},
    }
    nm.CONFIG['users'] = users
    cm = nm.app.test_client()

    # ---------- 未登录 ----------
    print('\n[1] 未登录')
    response = cm.get('/')
    check('访问首页 302', response.status_code == 302, str(response.status_code))
    check('跳转到 /login', '/login' in (response.headers.get('Location') or ''),
          response.headers.get('Location'))
    response = cm.get('/login')
    body = response.get_data(as_text=True)
    check('登录页 200', response.status_code == 200)
    check('登录页渲染正常（有表单）', 'password' in body.lower())
    response = cm.get('/api/tag/list')
    check('未登录调 API 返回 401', response.status_code == 401, str(response.status_code))

    # ---------- 密码错误 ----------
    print('\n[2] 密码错误')
    response = cm.post('/login', data={'password': 'wrong-password'})
    body = response.get_data(as_text=True)
    check('错误密码仍返回 200', response.status_code == 200, str(response.status_code))
    check('页面提示密码错误', '密码错误' in body, body[:80])
    response = cm.get('/')
    check('失败后仍未登录（302）', response.status_code == 302, str(response.status_code))

    # ---------- 登录成功 ----------
    print('\n[3] 登录成功')
    response = cm.post('/login', data={'password': TEST_PASS})
    location = response.headers.get('Location') or ''
    check('登录成功 302', response.status_code == 302, str(response.status_code))
    check('跳回首页', location.endswith('/') or location == '/', location)
    response = cm.get('/')
    check('登录后首页 200', response.status_code == 200, str(response.status_code))

    # ---------- 用户管理 API ----------
    print('\n[4] 用户管理 API')
    response = cm.get('/api/users/list')
    body = response.get_data(as_text=True)
    check('用户列表 200', response.status_code == 200, str(response.status_code))
    check('列表含测试用户', TEST_USER in body)
    check('列表不含密码哈希', 'password_hash' not in body and 'scrypt' not in body,
          '存在哈希字段！')
    response = cm.get('/api/avatar/options')
    body = response.get_data(as_text=True)
    check('头像选项 200', response.status_code == 200)
    check('头像选项含 icons/colors', 'icons' in body and 'colors' in body)

    # ---------- 个人偏好 API ----------
    print('\n[5] 个人阅读偏好')
    response = cm.get('/api/get_preferences')
    check('读取偏好 200', response.status_code == 200, str(response.status_code))
    response = cm.post('/api/save_preferences', json={'font_size': 19})
    check('保存偏好 200', response.status_code == 200, str(response.status_code))
    response = cm.get('/api/get_preferences')
    payload = response.get_json() or {}
    check('偏好已生效（font_size=19）',
          (payload.get('effective') or {}).get('font_size') == 19,
          str((payload.get('effective') or {}).get('font_size')))
    response = cm.post('/api/save_preferences', json={'font_size': ''})
    check('传空字符串可清除覆盖', response.status_code == 200, str(response.status_code))

    # ---------- CONFIG 被整体替换后仍能读到新用户表 ----------
    # save_config_api / reload_config_api 里有 `global CONFIG; CONFIG = 新dict`。
    # 如果 auth 用 from-import 绑死了旧 dict，这里就会读到旧用户表 —— 静默 bug。
    print('\n[6] CONFIG 对象被替换后的一致性')
    replaced = dict(nm.CONFIG)
    replaced_users = dict(replaced.get('users') or {})
    replaced_users['u_replaced_probe'] = {
        'role': 'admin', 'user_id': 'replaced_probe',
        'password_hash': nm.hash_password('x' * 8),
    }
    replaced['users'] = replaced_users
    nm.CONFIG = replaced          # 模拟 save_config_api 的整体替换
    response = cm.get('/api/users/list')
    body = response.get_data(as_text=True)
    check('替换 CONFIG 后 auth 读到新用户表', 'replaced_probe' in body,
          '读到的还是旧对象（from-import 分叉）')
    nm.CONFIG['users'] = users    # 还原

    # ---------- 登出 ----------
    print('\n[7] 登出')
    response = cm.get('/logout')
    location = response.headers.get('Location') or ''
    check('登出 302', response.status_code == 302, str(response.status_code))
    check('跳转到登录页', '/login' in location, location)
    response = cm.get('/')
    check('登出后首页又 302', response.status_code == 302, str(response.status_code))
    response = cm.get('/api/get_preferences')
    check('登出后偏好接口 401', response.status_code == 401, str(response.status_code))

    # ---------- 端点名可用性 ----------
    print('\n[8] 端点命名空间')
    with nm.app.test_request_context():
        from flask import url_for
        try:
            url = url_for('auth.login')
            check('url_for(auth.login) 可用', url == '/login', url)
        except Exception as exc:  # noqa: BLE001
            check('url_for(auth.login) 可用', False, str(exc))
        try:
            url = url_for('auth.logout')
            check('url_for(auth.logout) 可用', url == '/logout', url)
        except Exception as exc:  # noqa: BLE001
            check('url_for(auth.logout) 可用', False, str(exc))

    print('\n' + '=' * 56)
    print(f'通过 {len(PASS)} 项，失败 {len(FAIL)} 项')
    if FAIL:
        for name, detail in FAIL:
            print(f'  ❌ {name} {detail}')
        return 1
    print('🎉 auth 行为测试全部通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
