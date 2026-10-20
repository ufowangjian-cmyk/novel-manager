FROM python:3.9-slim

WORKDIR /app

ENV DOCKER_ENV=true \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai

# 时区设置
# 注意：不再安装 tini —— docker-compose.yml 里已用 `init: true`，
# 由 Docker 注入 docker-init 作为 PID 1 负责回收僵尸进程。
# 两者同时使用会造成两层 init 嵌套（虽不致命，但属冗余，
# 且一旦 apt 装 tini 失败，ENTRYPOINT 指向不存在的路径会让容器无法启动）。
RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# 只装依赖，不 COPY 源码（源码靠 volume 挂载）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 创建目录骨架（挂载前存在，挂载后由宿主机覆盖）
RUN mkdir -p /app/data /app/templates /app/static /novels

EXPOSE 5000

# PID 1 由 compose 的 init: true 提供（docker-init），这里直接跑 gunicorn
CMD ["gunicorn", "-w", "1", "--threads", "4", "-b", "0.0.0.0:5000", "--timeout", "120", "novel_manager:app"]