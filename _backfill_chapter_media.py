"""手动补齐章节媒体标注。

正常不需要跑：每次扫描收尾都会自动补齐（见 _scan_core 里的 backfill_chapter_media）。
保留这个入口只是为了不想等扫描时手动补一下。

用法：
    docker exec -it novel-manager python -u /app/_backfill_chapter_media.py
    docker exec -it novel-manager python -u /app/_backfill_chapter_media.py 200   # 只补前 200 本
"""
import sys
sys.path.insert(0, '/app')
import novel_manager as N

limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
res = N.backfill_chapter_media(
    on_progress=lambda d, t: print('  %d/%d 本' % (d, t), flush=True),
    limit=limit,
)
print('完成：', res)
