# -*- coding: utf-8 -*-
"""书籍缓存的 SQLite 存储层 —— 全项目唯一的 SQLite 入口。

替换原来 `data/novel_cache.json` 的全量 `json.load` / `json.dump`：
    - 读：一次查询拿回全部书籍（启动加载），或按 path 取单本（详情/校验）
    - 写：只写发生变化的行（sync_all 做 diff），不再整份重写十几 MB

对外契约
--------
`load_all()` / `list_books()` / `get_book()` 返回的 dict **与原 JSON 里的条目
逐字段一致**（19 个键，字段名、类型都不变），调用方无需改逻辑：

    filename, progress, file_size, file_hash, mtime, file_path, work_id,
    title, author, site, word_count, chapter_count, tags, publish_date,
    link, intro, preview, has_images, image_folder

约定（改这里之前先读）
----------------------
1. 只用标准库 sqlite3，不引入 ORM / 迁移框架。
2. 所有 SQL 只允许出现在本文件。
3. 每线程独立连接（threading.local），绝不跨线程共享。
4. 多表写入（books + chapters + revision）必须在单个事务内。
5. 全部参数化查询，禁止拼 SQL 字符串。
6. 小说正文不入库，只存元数据与章节索引。
"""

import json
import os
import sqlite3
import threading
import time

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
# 除任务书要求的列之外，多了一个 books.extra：
#   原 JSON 每本有 19 个字段，而 schema 里的一等列只覆盖 7 个（path/title/
#   author/tags/mtime/size/cached_at）。为了让返回值与原结构逐字段兼容，
#   其余 13 个字段整体序列化成 JSON 存在 extra 里（不做拆表，也不影响索引列）。
# meta 表存 revision，替代原来的「JSON 文件 mtime」做热重载判断。
_SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id          INTEGER PRIMARY KEY,
    path        TEXT UNIQUE NOT NULL,
    title       TEXT,
    author      TEXT,
    tags        TEXT,
    mtime       REAL,
    size        INTEGER,
    cached_at   REAL,
    extra       TEXT
);

CREATE TABLE IF NOT EXISTS chapters (
    book_id     INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    idx         INTEGER NOT NULL,
    title       TEXT,
    start_line  INTEGER,
    end_line    INTEGER,
    word_count  INTEGER,
    level       INTEGER,
    is_empty    INTEGER,
    PRIMARY KEY (book_id, idx)
);

CREATE INDEX IF NOT EXISTS idx_books_mtime ON books(mtime);
CREATE INDEX IF NOT EXISTS idx_books_path  ON books(path);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# books.extra 里保存的字段（顺序固定 —— sync_all 靠序列化结果做变更判定，
# 顺序一变就会误判成「有变化」而白写一遍）
_EXTRA_FIELDS = (
    'filename', 'progress', 'file_hash', 'work_id', 'site',
    'word_count', 'chapter_count', 'publish_date', 'link',
    'intro', 'preview', 'has_images', 'image_folder',
)

# 对外返回的字段顺序，沿用原 JSON 的书写顺序（便于人工比对 dump）
_FIELD_ORDER = (
    'filename', 'progress', 'file_size', 'file_hash', 'mtime', 'file_path',
    'work_id', 'title', 'author', 'site', 'word_count', 'chapter_count',
    'tags', 'publish_date', 'link', 'intro', 'preview', 'has_images',
    'image_folder',
)

_UPSERT_BOOK = """
INSERT INTO books (path, title, author, tags, mtime, size, cached_at, extra)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(path) DO UPDATE SET
    title     = excluded.title,
    author    = excluded.author,
    tags      = excluded.tags,
    mtime     = excluded.mtime,
    size      = excluded.size,
    cached_at = excluded.cached_at,
    extra     = excluded.extra
"""

_INSERT_CHAPTER = """
INSERT OR REPLACE INTO chapters
    (book_id, idx, title, start_line, end_line, word_count, level, is_empty)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

# ---------------------------------------------------------------------------
# 连接管理
# ---------------------------------------------------------------------------
_local = threading.local()
_write_lock = threading.RLock()
_db_path = None          # init_db 之后记住的默认库路径


def set_db_path(db_path):
    """设置后续所有调用默认使用的库路径。"""
    global _db_path
    _db_path = os.path.abspath(db_path)


def _resolve(db_path=None):
    if db_path:
        return os.path.abspath(db_path)
    if _db_path:
        return _db_path
    raise RuntimeError('cache_store 尚未初始化：请先调用 init_db(db_path)')


def _connect(db_path):
    conn = sqlite3.connect(
        db_path,
        timeout=5.0,              # 与 busy_timeout 呼应，双保险
        isolation_level='DEFERRED',
        check_same_thread=True,   # 跨线程用连接直接报错，别让它静默出错
    )
    conn.row_factory = sqlite3.Row
    # NAS 上容量/内存都紧，缓存压到 1MB，禁止 mmap，事务日志走 rollback journal
    conn.execute('PRAGMA busy_timeout = 5000')
    conn.execute('PRAGMA cache_size = -1000')
    conn.execute('PRAGMA temp_store = FILE')
    conn.execute('PRAGMA mmap_size = 0')
    conn.execute('PRAGMA foreign_keys = ON')
    try:
        # journal_mode 只在能拿到写锁时才切得动；已切过就立即返回，抢占失败不影响连接可用
        conn.execute('PRAGMA journal_mode = DELETE')
    except sqlite3.OperationalError:
        pass
    return conn


def _get_conn(db_path=None):
    """取本线程的连接；没有就建一个。

    用 threading.local + 创建线程标识双保险：万一进程 fork 后子进程复用了父进程
    的线程本地变量，标识对不上会重建连接，避免 "SQLite objects created in a
    thread can only be used in that same thread"。
    """
    path = _resolve(db_path)
    state = getattr(_local, 'conns', None)
    if state is None:
        state = {}
        _local.conns = state

    entry = state.get(path)
    if entry is not None and entry[0] == threading.get_ident():
        return entry[1]
    if entry is not None:
        try:
            entry[1].close()
        except Exception:
            pass

    conn = _connect(path)
    state[path] = (threading.get_ident(), conn)
    return conn


def close_thread_conn(db_path=None):
    """关闭本线程持有的连接（测试/退出时用，业务代码不需要调）。"""
    state = getattr(_local, 'conns', None) or {}
    path = _resolve(db_path)
    entry = state.pop(path, None)
    if entry is not None:
        try:
            entry[1].close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 建库
# ---------------------------------------------------------------------------
def init_db(db_path):
    """建库建表（幂等）。返回库路径。"""
    path = os.path.abspath(db_path)
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    set_db_path(path)
    conn = _get_conn(path)
    with _write_lock:
        conn.executescript(_SCHEMA)
        _ensure_chapter_columns(conn)
        conn.commit()
    return path


def _ensure_chapter_columns(conn):
    """给老库的 chapters 表补列（幂等）。

    chapters 表最初只有标题/行号/字数，后来要能从库里还原整份章节结构
    （详情页不必再读全文），才加了 level（1 册 / 2 章 / 3 节）和
    is_empty（仅标题无正文）。CREATE TABLE IF NOT EXISTS 不会给已存在的
    表加列，所以必须显式 ALTER。
    """
    cols = {row['name'] for row in conn.execute('PRAGMA table_info(chapters)')}
    if 'level' not in cols:
        conn.execute('ALTER TABLE chapters ADD COLUMN level INTEGER')
    if 'is_empty' not in cols:
        conn.execute('ALTER TABLE chapters ADD COLUMN is_empty INTEGER')


# ---------------------------------------------------------------------------
# 行 <-> dict
# ---------------------------------------------------------------------------
def _dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'))


def _clean_text(value):
    """JSON 里 null 存进 TEXT 列时保持 None，不要变成字符串 'None'。"""
    return value


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _book_to_row(book):
    """dict -> SQL 参数元组。"""
    path = book.get('file_path') or book.get('filename') or ''
    extra = {key: book.get(key) for key in _EXTRA_FIELDS}
    return (
        path,
        _clean_text(book.get('title')),
        _clean_text(book.get('author')),
        _clean_text(book.get('tags')),
        _to_float(book.get('mtime')),
        _to_int(book.get('file_size')),
        time.time(),
        _dumps(extra),
    )


def _row_to_book(row):
    """SQL 行 -> 与原 JSON 完全一致的 dict（19 个键）。"""
    extra = {}
    raw_extra = row['extra']
    if raw_extra:
        try:
            loaded = json.loads(raw_extra)
            if isinstance(loaded, dict):
                extra = loaded
        except (ValueError, TypeError):
            extra = {}

    file_path = row['path']
    book = {
        'filename': extra.get('filename') or os.path.basename(file_path or ''),
        'progress': extra.get('progress'),
        'file_size': _to_int(row['size']),
        'file_hash': extra.get('file_hash'),
        'mtime': _to_float(row['mtime']),
        'file_path': file_path,
        'work_id': extra.get('work_id'),
        'title': row['title'],
        'author': row['author'],
        'site': extra.get('site'),
        'word_count': _to_int(extra.get('word_count')),
        'chapter_count': _to_int(extra.get('chapter_count')),
        'tags': row['tags'],
        'publish_date': extra.get('publish_date'),
        'link': extra.get('link'),
        'intro': extra.get('intro'),
        'preview': extra.get('preview'),
        'has_images': bool(extra.get('has_images')),
        'image_folder': extra.get('image_folder'),
    }
    # 兜底：文件里没存过的键补成与旧读取逻辑一致的默认值
    if book['intro'] is None:
        book['intro'] = '无简介'
    return book


def _chapter_rows(book_id, chapters):
    rows = []
    for index, chapter in enumerate(chapters or []):
        if isinstance(chapter, dict):
            idx = chapter.get('idx', index)
            rows.append((
                book_id,
                _to_int(idx),
                _clean_text(chapter.get('title')),
                _to_int(chapter.get('start_line')),
                _to_int(chapter.get('end_line')),
                _to_int(chapter.get('word_count')),
                _to_int(chapter.get('level')) or None,
                1 if chapter.get('is_empty') else 0,
            ))
        else:  # (idx, title, start, end, words[, level, is_empty]) 之类的元组
            values = list(chapter) + [None] * (7 - len(chapter))
            rows.append((
                book_id,
                _to_int(values[0], index),
                _clean_text(values[1]),
                _to_int(values[2]),
                _to_int(values[3]),
                _to_int(values[4]),
                _to_int(values[5]) or None,
                1 if values[6] else 0,
            ))
    return rows


# ---------------------------------------------------------------------------
# revision：替代原来的「缓存文件 mtime」，用于跨线程/跨进程判断是否需要热重载
# ---------------------------------------------------------------------------
def _bump_revision(conn):
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('revision', '1') "
        "ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)"
    )


def get_revision(db_path=None):
    conn = _get_conn(db_path)
    row = conn.execute("SELECT value FROM meta WHERE key = 'revision'").fetchone()
    if not row or row['value'] is None:
        return 0
    try:
        return int(row['value'])
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# 读
# ---------------------------------------------------------------------------
def list_books(db_path=None):
    """全部书籍，顺序与迁移前 JSON 里的条目顺序一致（按入库顺序）。"""
    conn = _get_conn(db_path)
    rows = conn.execute(
        "SELECT id, path, title, author, tags, mtime, size, extra "
        "FROM books ORDER BY id"
    ).fetchall()
    return [_row_to_book(row) for row in rows]


def load_all(db_path=None):
    """list_books 的别名（启动加载用，语义更明确）。"""
    return list_books(db_path)


def get_book(path, db_path=None):
    """按文件路径（相对路径/文件名）取单本，没有返回 None。"""
    if not path:
        return None
    conn = _get_conn(db_path)
    row = conn.execute(
        "SELECT id, path, title, author, tags, mtime, size, extra "
        "FROM books WHERE path = ?",
        (path,),
    ).fetchone()
    return _row_to_book(row) if row else None


def count_books(db_path=None):
    conn = _get_conn(db_path)
    row = conn.execute("SELECT COUNT(*) AS n FROM books").fetchone()
    return int(row['n']) if row else 0


def count_chapters(db_path=None):
    conn = _get_conn(db_path)
    row = conn.execute("SELECT COUNT(*) AS n FROM chapters").fetchone()
    return int(row['n']) if row else 0


def get_chapters(path, db_path=None):
    """按书籍路径取章节索引（正文不在此）。"""
    if not path:
        return []
    conn = _get_conn(db_path)
    rows = conn.execute(
        "SELECT c.idx, c.title, c.start_line, c.end_line, c.word_count, "
        "       c.level, c.is_empty "
        "FROM chapters c JOIN books b ON b.id = c.book_id "
        "WHERE b.path = ? ORDER BY c.idx",
        (path,),
    ).fetchall()
    return [
        {
            'idx': row['idx'],
            'title': row['title'],
            'start_line': row['start_line'],
            'end_line': row['end_line'],
            'word_count': row['word_count'],
            'level': row['level'],
            'is_empty': bool(row['is_empty']),
        }
        for row in rows
    ]


def stats(db_path=None):
    """给自测/排查用的概览。"""
    path = _resolve(db_path)
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    return {
        'db_path': path,
        'books': count_books(path),
        'chapters': count_chapters(path),
        'size_bytes': size,
        'revision': get_revision(path),
    }


# ---------------------------------------------------------------------------
# 写（单本）
# ---------------------------------------------------------------------------
def upsert_book(book, chapters=None, db_path=None):
    """写入/更新一本书 + 其章节索引，单事务。返回 book_id。"""
    path = book.get('file_path') or book.get('filename') or ''
    if not path:
        raise ValueError('upsert_book 需要 file_path 或 filename')

    conn = _get_conn(db_path)
    with _write_lock:
        try:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute(_UPSERT_BOOK, _book_to_row(book))
            row = conn.execute('SELECT id FROM books WHERE path = ?', (path,)).fetchone()
            book_id = int(row['id'])
            conn.execute('DELETE FROM chapters WHERE book_id = ?', (book_id,))
            rows = _chapter_rows(book_id, chapters)
            if rows:
                conn.executemany(_INSERT_CHAPTER, rows)
            _bump_revision(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return book_id


def delete_book(path, db_path=None):
    """删除一本书；章节靠 ON DELETE CASCADE 一起走。返回是否删到了行。"""
    if not path:
        return False
    conn = _get_conn(db_path)
    with _write_lock:
        try:
            conn.execute('BEGIN IMMEDIATE')
            cursor = conn.execute('DELETE FROM books WHERE path = ?', (path,))
            deleted = cursor.rowcount > 0
            if deleted:
                _bump_revision(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return deleted


# ---------------------------------------------------------------------------
# 写（全量同步：只写变化行）
# ---------------------------------------------------------------------------
def sync_all(books, chapters_map=None, db_path=None):
    """以入参 books 为准做增量同步 —— 替代原来「重建整份 JSON 再 dump」。

    - 新增 / 字段有变化的书：UPSERT
    - 入参里已不存在的书：DELETE（章节级联）
    - 一个事务内完成；没变化时不写任何行（只做一次 SELECT）

    返回 {'inserted', 'updated', 'deleted', 'unchanged'}。
    """
    conn = _get_conn(db_path)
    chapters_map = chapters_map or {}
    result = {'inserted': 0, 'updated': 0, 'deleted': 0, 'unchanged': 0, 'chapters': 0}

    with _write_lock:
        existing = {}
        for row in conn.execute(
            'SELECT id, path, title, author, tags, mtime, size, extra FROM books'
        ):
            existing[row['path']] = (
                row['title'], row['author'], row['tags'],
                row['mtime'], row['size'], row['extra'],
            )

        to_write = []
        seen = set()
        for book in books:
            path = book.get('file_path') or book.get('filename') or ''
            if not path:
                continue
            seen.add(path)
            row = _book_to_row(book)
            # 参与比较的只有内容列；cached_at 每次都新，不参与
            signature = (row[1], row[2], row[3], row[4], row[5], row[7])
            old = existing.get(path)
            if old is None:
                result['inserted'] += 1
                to_write.append(row)
            elif old != signature:
                result['updated'] += 1
                to_write.append(row)
            else:
                result['unchanged'] += 1

        to_delete = [path for path in existing if path not in seen]
        result['deleted'] = len(to_delete)

        if not to_write and not to_delete and not chapters_map:
            return result

        try:
            conn.execute('BEGIN IMMEDIATE')
            if to_write:
                conn.executemany(_UPSERT_BOOK, to_write)
            # 章节写入不能挂在 to_write 上：全量重扫时书的元数据通常没变
            # （unchanged），但章节索引可能是第一次落库；只更新章节这场景
            # 也会因为 to_write 为空而整段被跳过。
            if chapters_map:
                result['chapters'] = _write_chapters(conn, chapters_map)
            if to_delete:
                conn.executemany(
                    'DELETE FROM books WHERE path = ?',
                    [(path,) for path in to_delete],
                )
            _bump_revision(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return result


def _write_chapters(conn, chapters_map):
    """按书籍路径整体替换章节索引，返回写入的章节行数。

    chapters_map: {book_path: [{'title','start_line','end_line','word_count','level','is_empty'}]}
    只处理 map 里出现的书；不在 map 里的书章节保持原样（增量扫描没解析到的书）。
    """
    id_rows = []
    paths = list(chapters_map.keys())
    # 分批查 id：全量扫描一次可能带 5000+ 本书，SQLite 对单条语句的
    # 变量个数有上限（旧版本 999），分批最稳
    for i in range(0, len(paths), 500):
        chunk = paths[i:i + 500]
        id_rows.extend(conn.execute(
            'SELECT id, path FROM books WHERE path IN (%s)'
            % ','.join('?' * len(chunk)),
            chunk,
        ).fetchall())
    ids = {row['path']: int(row['id']) for row in id_rows}

    written = 0
    for path, chapter_list in chapters_map.items():
        book_id = ids.get(path)
        if book_id is None:
            continue
        conn.execute('DELETE FROM chapters WHERE book_id = ?', (book_id,))
        rows = _chapter_rows(book_id, chapter_list)
        if rows:
            conn.executemany(_INSERT_CHAPTER, rows)
            written += len(rows)
    return written


# ---------------------------------------------------------------------------
# 从 JSON 迁移（幂等）
# ---------------------------------------------------------------------------
def migrate_from_json(json_path, db_path):
    """把旧版 novel_cache.json 导入 SQLite。

    幂等：库已存在且 books 非空 → 直接返回 0，不重复导入。
    全量导入走单事务，失败整体回滚。
    成功后把 JSON 重命名为 `<json>.bak`（已存在则保留，不覆盖、不删除）。
    返回导入条数。
    """
    json_path = os.path.abspath(json_path)
    db_path = os.path.abspath(db_path)

    init_db(db_path)
    conn = _get_conn(db_path)

    already = count_books(db_path)
    if already > 0:
        return 0

    if not os.path.exists(json_path):
        return 0

    with open(json_path, 'r', encoding='utf-8-sig') as handle:
        data = json.load(handle)

    if isinstance(data, dict):
        books = data.get('novel_data') or []
    elif isinstance(data, list):
        books = data
    else:
        books = []

    rows = []
    for book in books:
        if not isinstance(book, dict):
            continue
        row = _book_to_row(book)
        if not row[0]:
            continue
        rows.append(row)

    if not rows:
        return 0

    with _write_lock:
        try:
            conn.execute('BEGIN IMMEDIATE')
            conn.executemany(_UPSERT_BOOK, rows)
            _bump_revision(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    _rename_to_bak(json_path)
    return len(rows)


def _rename_to_bak(json_path):
    """迁移成功后把源 JSON 留成只读备份。"""
    if not os.path.exists(json_path):
        return None
    bak_path = json_path + '.bak'
    if os.path.exists(bak_path):
        return bak_path
    try:
        os.replace(json_path, bak_path)
        return bak_path
    except OSError:
        return None


def count_json_entries(json_path):
    """数一下旧 JSON 里有多少条目（自测对账用，不写库）。"""
    if not os.path.exists(json_path):
        return 0
    with open(json_path, 'r', encoding='utf-8-sig') as handle:
        data = json.load(handle)
    if isinstance(data, dict):
        return len(data.get('novel_data') or [])
    if isinstance(data, list):
        return len(data)
    return 0


def ensure_ready(json_path, db_path):
    """应用启动时调用：建库 + 需要时自动从 JSON 迁移。

    返回 (imported_count, state)，state ∈ {'migrated', 'existing', 'empty'}。
    """
    db_path = os.path.abspath(db_path)
    existed = os.path.exists(db_path)
    init_db(db_path)

    if count_books(db_path) > 0:
        return 0, 'existing'

    if os.path.exists(json_path):
        imported = migrate_from_json(json_path, db_path)
        if imported > 0:
            return imported, 'migrated'

    # 库不存在、JSON 也不存在（或 JSON 是空的）→ 交给调用方走首次扫描
    return 0, 'empty' if not existed or count_books(db_path) == 0 else 'existing'
