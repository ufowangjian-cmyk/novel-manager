#!/bin/sh
# 生成模块化重构的三份基线文档，落到 docs/（容器内 /app == 仓库目录）。
#   1. blueprint-roadmap.md   路由 → 目标蓝图（77 条全覆盖）
#   2. url_map_before.txt     url_map 快照（拆分前）
#   3. behavior_baseline.json 32 项行为基线（状态码 + 响应哈希）
set -e
cd /app

python tests/gen_route_table.py > docs/blueprint-roadmap.md 2>/dev/null || true
python tests/snapshot_url_map.py > docs/url_map_before.txt 2>/dev/null || true

if [ -f /tmp/b1.json ]; then
    cp /tmp/b1.json docs/behavior_baseline.json
fi

echo '--- 产物 ---'
wc -l docs/blueprint-roadmap.md docs/url_map_before.txt
ls -la docs/behavior_baseline.json 2>/dev/null || echo 'behavior_baseline.json 缺失'

echo -n '未分类路由数: '
grep -c 'UNCLASSIFIED' docs/blueprint-roadmap.md 2>/dev/null || echo 0

echo -n 'url_map 路由数: '
head -1 docs/url_map_before.txt
