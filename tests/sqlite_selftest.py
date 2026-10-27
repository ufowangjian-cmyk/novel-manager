# -*- coding: utf-8 -*-
"""storage/cache_store.py 自测（在容器内跑，覆盖任务书第 7 节清单中可自动化的项）。

用法（容器内）：
    python /app/tests/sqlite_selftest.py

不需要真实书库，只需要 data/novel_cache.json 或 .bak 存在。
全部在临时目录里操作，不碰线上 data/novel_cache.db。
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

from storage import cache_store  # noqa: E402

DATA_DIR = os.path.join(APP_DIR, 'data')
SOURCE_JSON = os.path.join(DATA_DIR, 'novel_cache.json')
if not os.path.exists(SOURCE_JSON):
    SOURCE_JSON = os.path.join(DATA_DIR, 'novel_cache.json.bak')

PASS = []
FAIL = []


def check(name, condition, detail=''):
    if condition:
        PASS.append(name)
        print(f'  ✅ {name}')
    else:
        FAIL.append((name, detail))
        print(f'  ❌ {name}  {detail}')


def main():
    if not os.path.exists(SOURCE_JSON):
        print(f'⚠️ 找不到源 JSON（{SOURCE_JSON}），跳过真实数据用例')
        return 1

    work = tempfile.mkdtemp(prefix='cache_selftest_')
    json_path = os.path.join(work, 'novel_cache.json')
    db_path = os.path.join(work, 'novel_cache.db')
    shutil.copyfile(SOURCE_JSON, json_path)

    with open(json_path, encoding='utf-8-sig') as handle:
        raw = json.load(handle)
    raw_books = raw.get('novel_data', [])
    print(f'\n=== 源 JSON：{len(raw_books)} 条，{os.path.getsize(json_path)/1024/1024:.2f} MB ===')

    # ---------------------------------------------------------------- 建表
    print('\n[1] init_db 建表')
    cache_store.init_db(db_path)
    con = sqlite3.connect(db_path)
    tables = {row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    indexes = {row[0] for row in con.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    con.close()
    check('books/chapters/meta 表已建', {'books', 'chapters', 'meta'} <= tables, str(tables))
    check('idx_books_mtime 索引已建', 'idx_books_mtime' in indexes, str(indexes))
    check('idx_books_path 索引已建', 'idx_books_path' in indexes, str(indexes))
    check('init_db 幂等（重复调用不报错）', cache_store.init_db(db_path) == db_path)

    # ---------------------------------------------------------------- 迁移
    print('\n[2] migrate_from_json（真实数据）')
    started = time.time()
    imported = cache_store.migrate_from_json(json_path, db_path)
    elapsed = time.time() - started
    check(f'导入条数 == JSON 条目数（{imported}/{len(raw_books)}）', imported == len(raw_books))
    check(f'导入耗时 < 5s（实际 {elapsed:.2f}s）', elapsed < 5.0)
    check('源 JSON 已重命名为 .bak', os.path.exists(json_path + '.bak') and not os.path.exists(json_path))
    check('迁移后 books 行数一致',
          cache_store.count_books(db_path) == len(raw_books),
          f"{cache_store.count_books(db_path)}")

    # ---------------------------------------------------------------- 逐字段
    print('\n[3] 逐字段兼容（db 读出来 == 原 JSON 条目）')
    db_books = cache_store.list_books(db_path)
    check('顺序与 JSON 一致（按入库顺序）',
          [b.get('filename') for b in db_books] == [b.get('filename') for b in raw_books])
    key_set_ok = all(set(a.keys()) == set(b.keys()) for a, b in zip(raw_books, db_books))
    check('字段名集合完全一致（19 个键）', key_set_ok)
    mismatches = []
    for index, (a, b) in enumerate(zip(raw_books, db_books)):
        if a != b:
            diff = {k: (a.get(k), b.get(k)) for k in set(a) | set(b) if a.get(k) != b.get(k)}
            mismatches.append((index, a.get('filename'), diff))
    check(f'19 个字段逐值相等（不一致 {len(mismatches)} 条）', not mismatches,
          str(mismatches[:2]))
    type_ok = all(
        isinstance(b.get('has_images'), bool)
        and isinstance(b.get('file_size'), int)
        and isinstance(b.get('mtime'), float)
        for b in db_books
    )
    check('关键字段类型未漂移（bool/int/float）', type_ok)

    # ---------------------------------------------------------------- 幂等
    print('\n[4] 迁移幂等')
    shutil.copyfile(json_path + '.bak', json_path)  # 故意把 JSON 放回来
    again = cache_store.migrate_from_json(json_path, db_path)
    check('库非空时重复迁移返回 0', again == 0, str(again))
    check('重复迁移不重复导入', cache_store.count_books(db_path) == len(raw_books))
    os.remove(json_path)

    # ---------------------------------------------------------------- 单本读写
    print('\n[5] get_book / upsert_book / delete_book')
    sample = raw_books[0]
    got = cache_store.get_book(sample['file_path'], db_path)
    check('get_book 命中且字段一致', got == sample, str(got)[:120] if got else 'None')
    check('get_book 未命中返回 None', cache_store.get_book('不存在的书.txt', db_path) is None)

    new_book = dict(sample)
    new_book['file_path'] = 'selftest_new_book.txt'
    new_book['filename'] = 'selftest_new_book.txt'
    new_book['title'] = '自测新增书'
    new_book['tags'] = '测试,自测'
    chapters = [
        {'idx': 1, 'title': '第一章', 'start_line': 1, 'end_line': 100, 'word_count': 900},
        {'idx': 2, 'title': '第二章', 'start_line': 101, 'end_line': 260, 'word_count': 1500},
    ]
    cache_store.upsert_book(new_book, chapters, db_path)
    check('新增后总数为 +1',
          cache_store.count_books(db_path) == len(raw_books) + 1,
          str(cache_store.count_books(db_path)))
    check('章节写入 2 行', cache_store.count_chapters(db_path) == 2)
    got_chapters = cache_store.get_chapters('selftest_new_book.txt', db_path)
    check('章节顺序/内容正确',
          [c['idx'] for c in got_chapters] == [1, 2] and got_chapters[1]['title'] == '第二章')

    # 空章节的书也要能存在
    empty_book = dict(new_book)
    empty_book['file_path'] = 'selftest_empty_chapters.txt'
    empty_book['filename'] = 'selftest_empty_chapters.txt'
    cache_store.upsert_book(empty_book, [], db_path)
    check('允许 books 有行、chapters 无行（空章节书）',
          cache_store.get_book('selftest_empty_chapters.txt', db_path) is not None)

    # 级联删除
    con = sqlite3.connect(db_path)
    con.execute('PRAGMA foreign_keys = ON')
    con.execute('DELETE FROM books WHERE path = ?', ('selftest_new_book.txt',))
    con.commit()
    left = con.execute('SELECT COUNT(*) FROM chapters c '
                       'LEFT JOIN books b ON b.id = c.book_id WHERE b.id IS NULL').fetchone()[0]
    con.close()
    check('foreign_keys=ON 时手动删除级联清空章节', left == 0, f'孤儿章节 {left}')

    deleted = cache_store.delete_book('selftest_empty_chapters.txt', db_path)
    check('delete_book 返回 True 且行已消失',
          deleted and cache_store.get_book('selftest_empty_chapters.txt', db_path) is None)
    check('delete_book 删不存在的书返回 False',
          cache_store.delete_book('根本没这书.txt', db_path) is False)

    # ---------------------------------------------------------------- sync_all
    print('\n[6] sync_all 增量同步')
    current = cache_store.load_all(db_path)
    rev_before = cache_store.get_revision(db_path)
    result = cache_store.sync_all(current, db_path=db_path)
    check('全量内容未变时零写入',
          result['inserted'] == 0 and result['updated'] == 0 and result['deleted'] == 0,
          str(result))
    check('零写入时不 bump revision', cache_store.get_revision(db_path) == rev_before)

    one_changed = [dict(b) for b in current]
    one_changed[3]['tags'] = '被改过的标签'
    one_changed[3]['title'] = '被改过的书名'
    one_changed.append({
        'file_path': 'sync_all_new.txt', 'filename': 'sync_all_new.txt',
        'title': 'sync 新增', 'author': 'x', 'tags': '无', 'mtime': 1.0,
        'file_size': 10, 'file_hash': 'h', 'work_id': 'w', 'site': 's',
        'word_count': 1, 'chapter_count': 0, 'progress': '1', 'publish_date': '',
        'link': '', 'intro': '无简介', 'preview': None, 'has_images': False,
        'image_folder': None,
    })
    result = cache_store.sync_all(one_changed, db_path=db_path)
    check('单本改动 → 只写 1 行 updated + 1 行 inserted',
          result['updated'] == 1 and result['inserted'] == 1, str(result))
    check('改动后内容已落库',
          cache_store.get_book(current[3]['file_path'], db_path)['title'] == '被改过的书名')
    check('revision 已递增', cache_store.get_revision(db_path) > rev_before)

    removed = [b for b in one_changed if b['file_path'] != 'sync_all_new.txt']
    result = cache_store.sync_all(removed, db_path=db_path)
    check('移除一本书 → deleted=1', result['deleted'] == 1, str(result))
    check('移除后查不到', cache_store.get_book('sync_all_new.txt', db_path) is None)

    # 失败回滚：故意传一个会在 executemany 阶段炸掉的入参
    before = cache_store.count_books(db_path)
    broken = [dict(b) for b in removed]
    broken[0]['file_path'] = None  # 被跳过，不会炸
    broken.append({'file_path': object(), 'filename': 'x'})  # sqlite 无法绑定 → 抛错
    try:
        cache_store.sync_all(broken, db_path=db_path)
        raised = False
    except Exception:
        raised = True
    after = cache_store.count_books(db_path)
    check('写入异常时整体回滚（行数不变）', raised or before == after, f'{before} -> {after}')

    # ---------------------------------------------------------------- 并发
    print('\n[7] 并发：多读 + 单写')
    errors = []
    stop = threading.Event()

    def reader():
        try:
            while not stop.is_set():
                cache_store.list_books(db_path)
                cache_store.get_book(raw_books[0]['file_path'], db_path)
                cache_store.get_revision(db_path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f'reader: {exc}')

    def writer():
        try:
            for i in range(5):
                book = dict(raw_books[1])
                book['file_path'] = f'concurrent_{i}.txt'
                book['filename'] = f'concurrent_{i}.txt'
                cache_store.upsert_book(book, [], db_path)
                time.sleep(0.02)
            for i in range(5):
                cache_store.delete_book(f'concurrent_{i}.txt', db_path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f'writer: {exc}')

    threads = [threading.Thread(target=reader) for _ in range(3)]
    for thread in threads:
        thread.start()
    write_thread = threading.Thread(target=writer)
    write_thread.start()
    write_thread.join()
    stop.set()
    for thread in threads:
        thread.join()
    check('并发读写无 database is locked / 跨线程报错', not errors, '; '.join(errors[:3]))

    # ---------------------------------------------------------------- 查询计划
    print('\n[8] EXPLAIN QUERY PLAN')
    con = sqlite3.connect(db_path)
    plan_path = con.execute(
        'EXPLAIN QUERY PLAN SELECT * FROM books WHERE path = ?', ('x.txt',)).fetchall()
    plan_mtime = con.execute(
        'EXPLAIN QUERY PLAN SELECT * FROM books ORDER BY mtime').fetchall()
    con.close()
    path_plan = ' | '.join(str(row[-1]) for row in plan_path)
    mtime_plan = ' | '.join(str(row[-1]) for row in plan_mtime)
    print(f'    path 查询: {path_plan}')
    print(f'    mtime 排序: {mtime_plan}')
    check('path 查询走索引（非全表扫描）',
          'USING INDEX' in path_plan.upper() or 'USING COVERING INDEX' in path_plan.upper(),
          path_plan)
    check('mtime 排序走索引', 'USING INDEX idx_books_mtime' in mtime_plan, mtime_plan)

    # ---------------------------------------------------------------- 清理
    cache_store.close_thread_conn(db_path)
    shutil.rmtree(work, ignore_errors=True)

    print('\n' + '=' * 56)
    print(f'通过 {len(PASS)} 项，失败 {len(FAIL)} 项')
    if FAIL:
        for name, detail in FAIL:
            print(f'  ❌ {name} {detail}')
        return 1
    print('🎉 全部通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
