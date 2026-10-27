# -*- coding: utf-8 -*-
"""把 data/novel_cache.json 迁移到 data/novel_cache.db（可独立运行）。

应用启动时也会自动做同样的事（见 novel_manager.bootstrap → load_cache →
cache_store.ensure_ready），这个脚本只用于手动迁移 / 排查。

    python migrate_cache.py            # 正常迁移
    python migrate_cache.py --check    # 只体检，不写库
    python migrate_cache.py --db /tmp/x.db --json /tmp/x.json

幂等：库已存在且 books 非空 → 直接退出，不重复导入。
成功后源 JSON 改名成 novel_cache.json.bak（已存在则保留），不删除。
"""

import argparse
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from storage import cache_store  # noqa: E402

DEFAULT_DATA_DIR = os.path.join(BASE_DIR, 'data')
DEFAULT_JSON = os.path.join(DEFAULT_DATA_DIR, 'novel_cache.json')
DEFAULT_DB = os.path.join(DEFAULT_DATA_DIR, 'novel_cache.db')


def main(argv=None):
    parser = argparse.ArgumentParser(description='novel_cache.json -> SQLite')
    parser.add_argument('--json', default=DEFAULT_JSON, help='源 JSON 路径')
    parser.add_argument('--db', default=DEFAULT_DB, help='目标库路径')
    parser.add_argument('--check', action='store_true', help='只体检，不写库')
    args = parser.parse_args(argv)

    json_path = os.path.abspath(args.json)
    db_path = os.path.abspath(args.db)

    print(f'源 JSON : {json_path} ({_exists_text(json_path)})')
    print(f'目标库  : {db_path} ({_exists_text(db_path)})')

    if args.check:
        entries = cache_store.count_json_entries(json_path)
        print(f'JSON 条目数: {entries}')
        if os.path.exists(db_path):
            cache_store.set_db_path(db_path)
            print(f'库中书籍数 : {cache_store.count_books(db_path)}')
            print(f'库中章节数 : {cache_store.count_chapters(db_path)}')
            print(f'revision   : {cache_store.get_revision(db_path)}')
            print(f'库文件大小 : {os.path.getsize(db_path) / 1024 / 1024:.2f} MB')
        return 0

    started = time.time()
    imported = cache_store.migrate_from_json(json_path, db_path)
    elapsed = time.time() - started

    if imported == 0:
        existing = cache_store.count_books(db_path)
        print(f'ℹ️ 无需迁移（库中已有 {existing} 本，或源 JSON 不存在）')
        return 0

    entries = cache_store.count_json_entries(json_path + '.bak')
    print(f'✅ 导入 {imported} 本，耗时 {elapsed:.2f}s')
    print(f'✅ 校验：JSON {entries} 本 / 库 {cache_store.count_books(db_path)} 本')
    print(f'✅ 备份：{json_path}.bak')
    mismatched = entries != cache_store.count_books(db_path)
    if mismatched:
        print('❌ 条数不一致，请检查')
        return 1
    return 0


def _exists_text(path):
    if not os.path.exists(path):
        return '不存在'
    return f'{os.path.getsize(path) / 1024 / 1024:.2f} MB'


if __name__ == '__main__':
    sys.exit(main())
