#!/bin/sh
# 在容器内准备一份隔离的项目副本（/tmp/apptest），用于集成自测。
# 不改动 /app/data 下任何线上文件。
set -e

rm -rf /tmp/apptest
mkdir -p /tmp/apptest/data

cp -r /app/storage /app/tests /app/templates /app/static /tmp/apptest/
cp /app/novel_manager.py /app/migrate_cache.py /tmp/apptest/
cp /app/data/*.json /app/data/secret_key /tmp/apptest/data/ 2>/dev/null || true
cp -r /app/data/reading_records /tmp/apptest/data/ 2>/dev/null || true

python - <<'PY'
import json
path = '/tmp/apptest/data/config.json'
with open(path, encoding='utf-8') as handle:
    config = json.load(handle)
config['auto_scan_on_start'] = False   # 自测期间手动控制扫描，避免等 5000 次 stat
with open(path, 'w', encoding='utf-8') as handle:
    json.dump(config, handle, ensure_ascii=False, indent=2)
print('auto_scan_on_start ->', config['auto_scan_on_start'])
PY

echo '--- /tmp/apptest/data ---'
ls -la /tmp/apptest/data
