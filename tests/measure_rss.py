# -*- coding: utf-8 -*-
"""测量启动后的 RSS 与耗时：python measure_rss.py <app_dir>"""
import os
import sys
import time

APP_DIR = sys.argv[1]
sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)


def rss_mb():
    with open('/proc/self/statm', encoding='utf-8') as handle:
        pages = int(handle.read().split()[1])
    return pages * 4096 / 1024 / 1024


started = time.time()
import novel_manager as nm  # noqa: E402

elapsed = time.time() - started
print(f'{os.path.basename(APP_DIR)}: 启动 {elapsed:.2f}s | RSS {rss_mb():.1f}MB | '
      f'书籍 {len(nm.novel_data)} 本')
