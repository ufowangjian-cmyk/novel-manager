# -*- coding: utf-8 -*-
"""核对当前代码树是否等于某个 git tag（默认 pre-modularization）。

    python tests/verify_state.py [tag]
"""

import hashlib
import os
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAG = sys.argv[1] if len(sys.argv) > 1 else 'pre-modularization'

CHECK_FILES = [
    'novel_manager.py',
    'storage/cache_store.py',
    'storage/__init__.py',
    'migrate_cache.py',
    'docs/sqlite-migration-report.md',
    'tests/sqlite_selftest.py',
    'DEVELOPMENT.md',
]


def git(*args):
    return subprocess.run(['git'] + list(args), cwd=APP_DIR,
                          capture_output=True, text=True).stdout.strip()


def blob_hash(path):
    """git hash-object，绕过 index 直接算工作区文件。"""
    return git('hash-object', path)


def main():
    print(f'=== 工作区 vs {TAG} ===')
    diff = git('diff', '--stat', TAG, 'HEAD')
    print(diff if diff else '(空：已提交的树与 tag 完全一致)')

    out = git('status', '--porcelain')
    print(f'=== 未提交改动 ===\n{out if out else "(空：工作区干净)"}')

    print('=== 关键文件逐个比对 ===')
    bad = 0
    for name in CHECK_FILES:
        path = os.path.join(APP_DIR, name)
        if not os.path.isfile(path):
            print(f'  ❌ {name}  文件不存在')
            bad += 1
            continue
        here = blob_hash(name)
        there = git('rev-parse', f'{TAG}:{name}')
        if here == there:
            print(f'  ✅ {name}')
        else:
            print(f'  ❌ {name}  {here[:8]} != {there[:8]}')
            bad += 1

    print('=== 模块化残留检查（应全部为 0）===')
    leftovers = ['app/', 'library_bp', 'reader_bp', 'media_bp', 'core_bp',
                 "url_for('library.", "url_for('reader.", "url_for('auth."]
    for token in leftovers:
        if token.endswith('/'):
            hit = os.path.isdir(os.path.join(APP_DIR, token))
        else:
            hit = subprocess.run(
                ['grep', '-rIl', token, '--include=*.py', '--include=*.html',
                 'novel_manager.py', 'storage', 'templates'],
                cwd=APP_DIR, capture_output=True, text=True).stdout.strip()
        print(f'  {"❌ 存在" if hit else "✅ 无"}  {token}')
        if hit:
            bad += 1

    print(f'\n结论：{"❌ 有 %d 处不符合" % bad if bad else "✅ 状态与 " + TAG + " 一致"}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
