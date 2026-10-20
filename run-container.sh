#!/bin/bash
#
# 小说管理器 - 一键重建并启动
#
# 用途：改了依赖(requirements.txt) / Dockerfile 后，想彻底重建时用。
#       日常只改代码或模板的话，用 docker restart novel-manager 就够了（更快）。
#
# 用法：在项目目录下执行
#     ./run-container.sh
#
# 设计要点：
#   1. 先构建，成功后才停旧容器
#      —— 否则构建失败会导致「旧容器已删、新容器没起」，服务直接中断。
#      现在的顺序保证：构建失败时旧容器仍在正常运行，用户无感知。
#   2. 启动后真实探测服务是否可用（读 HTTP 状态），而不是盲目报成功。
#
set -e

cd "$(dirname "$0")"

PORT=5000
CONTAINER=novel-manager

echo "🔨 构建镜像..."
# 构建失败会因 set -e 立即退出，此时旧容器仍在运行，服务不中断
docker compose build

echo ""
echo "🛑 停止并移除旧容器..."
docker compose down

echo ""
echo "🚀 启动新容器..."
docker compose up -d

echo ""
echo "📊 容器状态:"
docker compose ps

# ---------------------------------------------------------------------------
# 等待服务真正就绪
# 优先读 healthcheck 状态；若容器没有 healthcheck 则退化为 HTTP 探测
# ---------------------------------------------------------------------------
echo ""
echo "⏳ 等待服务就绪（最多 60 秒）..."

READY=0
for i in $(seq 1 60); do
    STATUS=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \
             "$CONTAINER" 2>/dev/null || echo "missing")

    if [ "$STATUS" = "healthy" ]; then
        READY=1
        break
    fi

    # 没有 healthcheck 时，用 HTTP 探测（容器内自带 python）
    if [ "$STATUS" = "none" ]; then
        if docker exec "$CONTAINER" python -c \
            "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/login')" \
            >/dev/null 2>&1; then
            READY=1
            break
        fi
    fi

    # 容器已经退出了，不必再等
    RUNNING=$(docker inspect --format='{{.State.Running}}' "$CONTAINER" 2>/dev/null || echo "false")
    if [ "$RUNNING" != "true" ]; then
        break
    fi

    sleep 1
done

echo ""
echo "📋 最近日志:"
docker compose logs --tail=20

echo ""
if [ "$READY" = "1" ]; then
    echo "✅ 服务已就绪，访问 http://NAS的IP:${PORT}"
    exit 0
else
    echo "❌ 服务未在预期时间内就绪"
    echo ""
    echo "排查建议："
    echo "  1. 看完整日志： docker logs ${CONTAINER} --tail 100"
    echo "  2. 看容器状态： docker compose ps"
    echo "  3. 看应用日志： tail -50 data/novel_manager.log"
    echo "  4. 试着手动探测： docker exec ${CONTAINER} python -c \"import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/login')\""
    exit 1
fi
