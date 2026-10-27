#!/bin/sh
# 为模块化重构准备隔离副本：/tmp/modtest
# 代码 + data 全量复制，任何读/写都只落在副本里，绝不碰 /app/data。
set -e

APP=/app
DST=/tmp/modtest

rm -rf "$DST"
mkdir -p "$DST"

# 代码（app/ 拆分后也要带上；现在还没有就先跳过）
# ⚠️ 必须用 cp -a（保留 mtime）：静态资源的 ?v= 指纹取的是文件 mtime，
# 用 cp -r 复制会让副本里所有静态文件变成"刚刚修改"，指纹全变，
# 导致行为基线里所有页面的哈希都误报不一致（血泪教训）。
for item in storage tests templates static novel_manager.py migrate_cache.py docs app; do
    if [ -e "$APP/$item" ]; then
        cp -a "$APP/$item" "$DST/"
    fi
done

# 运行时数据全量复制（含 novel_cache.db，避免副本里重新迁移）
cp -a "$APP/data" "$DST/data"

# 自测期间关掉自动扫描，避免 5000 次 stat 干扰计时
python - <<'PY'
import json
path = '/tmp/modtest/data/config.json'
with open(path, encoding='utf-8') as handle:
    config = json.load(handle)
config['auto_scan_on_start'] = False
with open(path, 'w', encoding='utf-8') as handle:
    json.dump(config, handle, ensure_ascii=False, indent=2)
print('auto_scan_on_start ->', config['auto_scan_on_start'])
PY

echo '--- /tmp/modtest ---'
ls /tmp/modtest
