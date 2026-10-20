# 开发与维护说明（Docker 版）

面向想改代码、二次开发，或者让 AI 助手帮你维护部署的人。
日常使用看 [README.md](README.md)，命令速查看 [DOCKER-NOTES.md](DOCKER-NOTES.md)。

---

## 架构：源码挂载，不在镜像里

这是本项目和常见 Docker 镜像最大的不同：

**Dockerfile 只做三件事**

1. 装 Python 运行时与系统依赖（tzdata 等）
2. `COPY requirements.txt` 并 `pip install`
3. 创建目录骨架 `/app/data` `/app/templates` `/app/static` `/novels`

**它不 COPY 源码。** 源码由 compose 的 volume 挂载进 `/app`：

```yaml
volumes:
  - "${NOVEL_DIR}:/novels:ro"      # 书库，只读
  - "${APP_DIR}:/app"              # 项目目录
```

**好处**：改代码只需 `docker restart`，不用重建镜像，几秒生效。
**代价**：镜像不能单独分发——脱离这个挂载目录，它只是个空壳运行时。

---

## 容器启动流程

```
PID 1  docker-init（由 compose 的 init: true 注入，负责回收僵尸进程）
  └─ gunicorn -w 1 --threads 4 --max-requests 500 -b [::]:5000 novel_manager:app
```

三个设计决定，改动时注意配套：

**① PID 1 由 compose 的 `init: true` 提供**

Dockerfile 里因此**没有安装 tini，也没有 ENTRYPOINT**。
两者同时使用会造成两层 init 嵌套；而且 apt 装 tini 一旦失败，
ENTRYPOINT 指向不存在的路径会让容器直接起不来。
改其中一处必须同步另一处。

**② worker 数固定为 1**

应用状态（扫描进度、缓存）保存在进程内存里，多 worker 会导致状态不一致。
并发靠 `--threads 4` 处理，家庭规模足够。

**③ gunicorn 绑定 `[::]:5000` 而非 `0.0.0.0`**

compose 声明了 IPv6 网络，`ports: "5000:5000"` 会同时发布 IPv4 和 IPv6。
若应用只绑 `0.0.0.0`，IPv6 连接被 Docker proxy 接手后转发到容器内无人监听的 v6 地址，
表现为外网 v6 客户端连上又断、卡几秒才回退 v4。
引号是为了防止 shell 把 `[::]` 当 glob 展开。

---

## 数据存储

纯 JSON，无数据库，全部在 `data/`：

| 文件 | 内容 | 能否随代码分发 |
|---|---|---|
| `config.json` | 全局配置 + **用户表（含 scrypt 密码哈希）** | ❌ 含账号与个人偏好 |
| `secret_key` | 会话签名密钥，权限 600 | ❌ 泄露可伪造登录态 |
| `novel_cache.json` | 扫描缓存（可达 10MB+） | ❌ 可重建 |
| `reading_records/` | 每用户一个阅读记录文件 | ❌ 隐私 |
| `tag_rules.json` | 标签规则 | ⭕ 个性化积累 |
| `image_mapping.json` | 配图映射 | ⭕ |
| `emoji_mapping.json` | 表情映射 | ⭕ 需配合 `static/emojis/` |
| `scan.lock` / `scheduler.lock` | 扫描 / 调度互斥锁 | ❌ |

`reading_records/` 是多用户设计的体现：每人一个 `records_<hash>.json`，互相独立。

`secret_key` 丢失会让**所有用户需要重新登录**，迁移时记得一起带走。

---

## 构建与更新

```bash
# 改了 requirements.txt 才需要重建
docker compose build
docker compose up -d

# 完全重建（排除缓存干扰）
docker compose build --no-cache
docker compose up -d

# 只改了代码 / 模板 / 静态文件
docker restart novel-manager
```

`run-container.sh` 封装了「停止旧容器 → 重建镜像 → 启动 → 显示日志」的流程。
注意它刻意**先构建成功再停旧容器**——反过来做的话，构建失败会导致服务中断。

---

## 有状态的部分

容器重启不会丢数据（都在挂载的 `data/` 里），但有两处需要注意：

- **`data/secret_key`**：删了会让所有人重新登录
- **定时扫描**：由 `scheduler.lock` 保证单实例调度，多副本部署会互相干扰

---

## 常见的二次开发点

| 想改什么 | 位置 |
|---|---|
| 端口 / 挂载路径 | `.env` + `docker-compose.yml` |
| 用户表结构 | `data/config.json` 的 `users`，密码用 `generate_password_hash`（scrypt） |
| 默认配置 | 主程序里的 `DEFAULT_CONFIG` 字典 |
| 登录态 | Flask session，签名用 `SECRET_KEY` 或 `data/secret_key` |
| 章节切分正则 | 主程序中章节解析相关的正则常量 |
| 阅读页排版 | `templates/read_chapter.html` + `static/css/reader.css` |
| 每用户阅读偏好 | `users[<key>].preferences` |

---

## 迁移到新机器

1. 复制整个项目目录（**含 `data/`**，账号和阅读记录都在里面）
2. 修改 `.env` 里的 `NOVEL_DIR` 和 `APP_DIR` 为新机器的实际路径
3. `docker compose build && docker compose up -d`

注意 `data/secret_key` 要一起带走，否则所有用户需要重新登录。

---

## 自动化维护（给 AI 助手）

如果你是 AI 助手，正在帮用户维护这个部署，几个关键前提：

**① 源码不在镜像里，靠 volume 挂载**
改代码后 `docker restart` 即可，不要习惯性 `docker compose build`
（除非改了 `requirements.txt`）。

**② `novel_manager.py` 是 NAS 专用版本**
下划线命名，多用户带登录。桌面版是 `novel-manager.py`（连字符，无鉴权），
两者不可互换。本版必须用下划线，因为 gunicorn 用 `novel_manager:app` 导入，
Python 模块名不能含连字符。

**③ `DOCKER_ENV=true` 会覆盖 `novel_dir`**
程序检测到容器环境后忽略 `config.json` 里的 `novel_dir`，强制用 `/novels`。
要换书库位置，改 compose 的挂载。

**操作对应表**

| 用户说 | 该执行 |
|---|---|
| 改了代码 | `docker restart novel-manager` |
| 改了模板 / 静态文件 | `docker restart novel-manager` |
| 改了 requirements.txt | `docker compose build && docker compose up -d` |
| 改了 compose | `docker compose up -d` |
| 看日志 | `docker logs novel-manager --tail 100` |
| 数据备份 | 打包 `data/`，建议排除 `novel_cache.json*` |

**注意事项**

- 所有状态在 `data/`，`config.json` 含用户表和密码哈希，截屏或分享时必须隐去
- 单 worker 是刻意设计，不要为"提速"提高 worker 数
- PID 1 由 compose 的 `init: true` 提供，Dockerfile 里没有 tini 也没有 ENTRYPOINT，两者配套
- 如果是通过 SSH 操作宿主机，注意该环境下 git 推送需要走代理，直连会被重置
