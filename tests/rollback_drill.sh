#!/bin/sh
# 回滚演练：证明拆完 auth 之后，退回到 pre-modularization 仍能正常启动。
# 全程在副本里做，不碰 /app 的代码与 data。
#
# 前置：容器里没有 git，旧版主程序由宿主机取出后放进容器：
#   cd <repo> && git show pre-modularization:novel_manager.py > /tmp/old_nm.py
#   docker cp /tmp/old_nm.py novel-manager:/tmp/old_nm.py
set -e
cd /app

echo '--- 1. 旧主程序（由宿主机从 tag 取出）---'
wc -l /tmp/old_nm.py

echo '--- 2. 造回滚副本（当前阶段2代码的副本，只替换代码）---'
rm -rf /tmp/rollback2
cp -a /tmp/modtest /tmp/rollback2
cp /tmp/old_nm.py /tmp/rollback2/novel_manager.py
rm -rf /tmp/rollback2/app          # 旧版本没有 app/ 包

echo '--- 3. 旧代码启动并导出路由表 ---'
cd /tmp/rollback2
python tests/snapshot_url_map.py > /tmp/rollback_routes.txt 2>/dev/null
head -2 /tmp/rollback_routes.txt

echo '--- 4. 与拆分前基线比对：必须逐字节一致（含端点名，无蓝图前缀）---'
if diff docs/url_map_before.txt /tmp/rollback_routes.txt > /tmp/rollback_diff.txt; then
    echo 'ROLLBACK_ROUTES_IDENTICAL'
else
    echo 'ROLLBACK_ROUTES_DIFF:'
    head -10 /tmp/rollback_diff.txt
    exit 1
fi

echo '--- 5. 回滚后端点名回到无前缀形态（抽查）---'
grep -E '\| (login|logout|index)$' /tmp/rollback_routes.txt | head -3

echo
echo '说明：行为一致性不在本脚本里重复验，见'
echo '  - tests/snapshot_behavior.py --diff（32 项页面/接口哈希）'
echo '  - tests/auth_behavior_test.py（27 项登录/登出/用户管理）'
echo '两者都跑在「当前代码 + 干净副本」上；副本 config 一旦被 auth 测试注入过'
echo '用户，再拿来比对 api_users_list 的哈希就会假报警，所以这里不掺和。'
