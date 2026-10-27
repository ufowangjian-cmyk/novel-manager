# -*- coding: utf-8 -*-
"""把某个路径的渲染结果 dump 成文件，用于 A/B 两套代码的 HTML 逐行 diff。

    python tests/dump_page.py <app_dir> <path> <out_file> [admin]

admin 传 1 时注入管理员会话，否则匿名。
random 固定种子，保证同一版本的两次渲染可比。
"""

import os
import random
import sys

app_dir, path, out_file = sys.argv[1], sys.argv[2], sys.argv[3]
as_admin = len(sys.argv) > 4 and sys.argv[4] == '1'

sys.path.insert(0, app_dir)
os.chdir(app_dir)

_REAL_STDOUT = sys.stdout
sys.stdout = sys.stderr
try:
    import novel_manager as nm
finally:
    sys.stdout = _REAL_STDOUT

client = nm.app.test_client()
if as_admin:
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
        sess['user_name'] = 'diff'

random.seed(20261027)
response = client.get(path)
body = response.get_data(as_text=True)

with open(out_file, 'w', encoding='utf-8', newline='\n') as handle:
    handle.write(body)

print(f'{app_dir} {path} -> {response.status_code}, {len(body)} 字节 -> {out_file}',
      file=sys.stderr)
