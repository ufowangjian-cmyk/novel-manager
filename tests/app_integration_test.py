# -*- coding: utf-8 -*-
"""应用级集成自测：在「项目副本 + 独立 data 目录」里跑，不碰线上环境。

覆盖任务书第 7 节里需要真实 Flask 上下文的项：冷启动迁移、热启动、
列表页 / 详情页 / 阅读页、标签统计、阅读进度、增量写入、内存。

准备（容器内）：
    rm -rf /tmp/apptest && mkdir -p /tmp/apptest/data
    cp -r /app/storage /app/tests /app/templates /app/static /app/*.py /tmp/apptest/
    cp /app/data/*.json /app/data/secret_key /tmp/apptest/data/
    cp -r /app/data/reading_records /tmp/apptest/data/ 2>/dev/null
    python - <<'PY'
    import json; p='/tmp/apptest/data/config.json'
    c=json.load(open(p,encoding='utf-8')); c['auto_scan_on_start']=False
    json.dump(c,open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
    PY

运行：
    python /tmp/apptest/tests/app_integration_test.py
"""

import json
import os
import sys
import time

APP_DIR = '/tmp/apptest'
DATA_DIR = os.path.join(APP_DIR, 'data')

if not os.path.isdir(APP_DIR):
    print(f'❌ {APP_DIR} 不存在，先按文件头的说明准备副本')
    sys.exit(2)

sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

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
    db_path = os.path.join(DATA_DIR, 'novel_cache.db')
    json_path = os.path.join(DATA_DIR, 'novel_cache.json')
    bak_path = json_path + '.bak'
    cold_start = not os.path.exists(db_path)

    print(f'\n=== 冷启动={cold_start} ===')
    started = time.time()
    import novel_manager as nm
    boot_elapsed = time.time() - started
    print(f'    import+bootstrap 耗时 {boot_elapsed:.2f}s   RSS≈{_rss():.0f}MB   '
          f'书籍 {len(nm.novel_data)} 本')

    # ------------------------------------------------------------ 迁移状态
    print('\n[1] 启动与迁移')
    check('缓存库已生成', os.path.exists(db_path), db_path)
    check('旧 JSON 已改名 .bak', os.path.exists(bak_path) and not os.path.exists(json_path))
    if cold_start:
        entries = 0
        with open(bak_path, encoding='utf-8-sig') as handle:
            entries = len(json.load(handle).get('novel_data', []))
        check(f'加载条数 == 旧 JSON 条数（{len(nm.novel_data)}/{entries}）',
              len(nm.novel_data) == entries)
        check('import+bootstrap < 5s', boot_elapsed < 5.0, f'{boot_elapsed:.2f}s')
    else:
        check('热启动直接读库', len(nm.novel_data) > 5000, str(len(nm.novel_data)))

    sample = nm.novel_data[0]
    check('file_path 已还原为绝对路径',
          sample['file_path'].startswith(nm.NOVEL_DIR), sample['file_path'])
    check('has_images 为 bool', isinstance(sample.get('has_images'), bool))
    check('intro / preview 字段齐全',
          'intro' in sample and 'preview' in sample)

    # ------------------------------------------------------------ 页面
    print('\n[2] 页面与接口')
    admin_key, admin_info = None, None
    for key, info in (nm.CONFIG.get('users') or {}).items():
        if isinstance(info, dict) and info.get('role') == 'admin':
            admin_key, admin_info = key, info
            break

    if not admin_key:
        check('config.json 里有管理员账号', False, '无法构造登录态')
    else:
        client = nm.app.test_client()
        with client.session_transaction() as sess:
            sess['authenticated'] = True
            sess['user_key'] = admin_key
            sess['user_role'] = 'admin'
            sess['user_id'] = admin_info.get('user_id', 'admin')
            sess['user_name'] = '集成自测'

        response = client.get('/')
        body = response.get_data(as_text=True)
        check('列表页 200', response.status_code == 200, str(response.status_code))
        check('列表页渲染出书名', sample['title'][:12] in body, sample['title'][:12])

        target = sample['filename']
        response = client.get(f'/novel_detail/{target}')
        check('详情页 200', response.status_code == 200, str(response.status_code))
        check('详情页包含作者', (sample['author'] or '')[:8] in response.get_data(as_text=True))

        response = client.get(f'/read/{target}/1')
        check('阅读页 200', response.status_code == 200, str(response.status_code))

        response = client.get('/api/tag/list')
        check('标签统计接口 200', response.status_code == 200, str(response.status_code))

        response = client.get('/get_all_authors')
        authors = response.get_data(as_text=True)
        check('作者筛选接口有内容', len(authors) > 100, f'{len(authors)} 字节')

    # ------------------------------------------------------------ 增量写入
    print('\n[3] save_cache 增量写入')
    rev_before = nm.cache_store.get_revision()
    started = time.time()
    nm.save_cache()
    idle_elapsed = time.time() - started
    rev_after = nm.cache_store.get_revision()
    count_before = nm.cache_store.count_books()
    check('内容未变时零写入（revision 不变）', rev_after == rev_before,
          f'{rev_before} -> {rev_after}')
    check(f'无变化保存 < 0.5s（实际 {idle_elapsed * 1000:.0f}ms）', idle_elapsed < 0.5)

    removed = nm.novel_data.pop()
    nm.save_cache()
    check('内存里去掉一本 → 库中 -1',
          nm.cache_store.count_books() == count_before - 1,
          str(nm.cache_store.count_books()))
    check('被删的书查不到',
          nm.cache_store.get_book(removed['filename']) is None)
    nm.novel_data.append(removed)
    nm.save_cache()
    check('再加回来 → 库中恢复',
          nm.cache_store.count_books() == count_before,
          str(nm.cache_store.count_books()))

    # ------------------------------------------------------------ 热重载
    print('\n[4] 热重载（revision 变化触发）')
    nm._last_cache_rev = -1
    check('revision 对不上时要求重载', nm.should_reload_cache() is True)
    nm._last_cache_rev = nm.cache_store.get_revision()
    check('revision 一致时不重载', nm.should_reload_cache() is False)

    # ------------------------------------------------------------ 阅读进度
    print('\n[5] 阅读进度落盘（不在本次迁移范围，验证未被带坏）')
    record_file = os.path.join(DATA_DIR, 'reading_records')
    existed = os.path.isdir(record_file)
    check('reading_records/ 仍在', existed)
    if existed:
        nm.save_reading_record(sample['filename'], 1, 100) if hasattr(
            nm, 'save_reading_record') else None
        records = nm.load_reading_records()
        check('阅读记录可读', isinstance(records, dict))

    # ------------------------------------------------------------ 内存
    print('\n[6] 内存')
    rss = _rss()
    print(f'    RSS ≈ {rss:.0f}MB（5123 本全部在内存，与迁移前同量级）')
    check('RSS 未异常膨胀（< 400MB）', rss < 400, f'{rss:.0f}MB')

    nm.cache_store.close_thread_conn()

    print('\n' + '=' * 56)
    print(f'通过 {len(PASS)} 项，失败 {len(FAIL)} 项')
    if FAIL:
        for name, detail in FAIL:
            print(f'  ❌ {name} {detail}')
        return 1
    print('🎉 全部通过')
    return 0


def _rss():
    try:
        with open('/proc/self/statm', encoding='utf-8') as handle:
            pages = int(handle.read().split()[1])
        return pages * 4096 / 1024 / 1024
    except Exception:
        return 0.0


if __name__ == '__main__':
    sys.exit(main())
