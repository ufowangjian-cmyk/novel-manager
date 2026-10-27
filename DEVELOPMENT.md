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

`data/` 下的内容分三类：**SQLite 库**、纯 JSON、以及锁与密钥。

| 文件 | 内容 | 能否随代码分发 |
|---|---|---|
| `config.json` | 全局配置 + **用户表（含 scrypt 密码哈希）** | ❌ 含账号与个人偏好 |
| `secret_key` | 会话签名密钥，权限 600 | ❌ 泄露可伪造登录态 |
| `novel_cache.db` | **书籍缓存（SQLite，约 15MB）** | ❌ 可重建 |
| `novel_cache.json.bak` | 迁移前的旧缓存，只读备份，不参与运行 | ❌ 可重建 |
| `reading_records/` | 每用户一个阅读记录文件 | ❌ 隐私 |
| `tag_rules.json` | 标签规则 | ⭕ 个性化积累 |
| `image_mapping.json` | 配图映射 | ⭕ |
| `emoji_mapping.json` | 表情映射 | ⭕ 需配合 `static/emojis/` |
| `scan_stats.json` | 上次扫描的统计与中断标记 | ❌ 可重建 |
| `scan.lock` / `scheduler.lock` | 扫描 / 调度互斥锁 | ❌ |

`reading_records/` 是多用户设计的体现：每人一个 `records_<hash>.json`，互相独立。

`secret_key` 丢失会让**所有用户需要重新登录**，迁移时记得一起带走。

备份 `data/` 时可以直接排除 `novel_cache.db*` 和 `novel_cache.json*`——它们都是扫描
即可重建的派生数据。

---

## 存储层（SQLite）

书籍缓存在 `data/novel_cache.db`。**所有 SQL 只允许出现在 `storage/cache_store.py`**，
主程序通过它读写，不直接碰数据库（`novel_manager.py` 里除了 `CACHE_FILE` 这个迁移源
路径，没有任何地方再引用 `novel_cache.json`）。

### 为什么不用 JSON 了

原先 `novel_cache.json` 是整份读写：扫描一次、改个标签，都要把 10MB 全量
`json.load` + `json.dump` 一遍。在 NAS 上这一步能占整个扫描耗时的一半。
换 SQLite 后只写「内容真的变了」的行，没变化时一次写入都不发生。

实测（5123 本真实数据，容器内，同一份数据）：

| 指标 | 迁移前（JSON） | 迁移后（SQLite） |
|---|---|---|
| 启动耗时 | 1.40s | 1.44s |
| 启动后 RSS | 94.2MB | 64.9MB |
| 单本改动落盘 | 全量重写 ≈11MB | 1 行 |
| 无任何变化时保存 | 全量重写 ≈11MB | 0 行（只有一次 SELECT） |

启动耗时基本持平（大头是 Flask/模板导入，不是缓存解析），但常驻内存少了约 29MB
——`json.load` 那份 11MB 原文和中间结构不再常驻。

### 表结构

```sql
CREATE TABLE books (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,   -- 相对文件名（原 file_path / filename）
    title TEXT, author TEXT, tags TEXT,   -- tags 是逗号分隔字符串，不是 JSON 数组
    mtime REAL, size INTEGER,    -- size = 原 file_size
    cached_at REAL,              -- 入库时间，不参与变更判定
    extra TEXT                   -- 其余 13 个字段的 JSON
);
CREATE TABLE chapters (
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL, title TEXT,
    start_line INTEGER, end_line INTEGER, word_count INTEGER,
    PRIMARY KEY (book_id, idx)
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);  -- meta.revision
```

两个刻意的设计：

**① `books.extra` 存 13 个字段的 JSON**
原 JSON 每本 19 个字段，schema 的一等列只覆盖了 6 个（`path/title/author/tags/mtime/size`）。
为了 `list_books()` 的返回值与原结构**逐字段一致**（调用方 55 处读写逻辑一行都不用改），
其余字段（`filename/progress/file_hash/work_id/site/word_count/chapter_count/
publish_date/link/intro/preview/has_images/image_folder`）整体存 JSON，不拆表。
`tags` 在真实数据里本来就是逗号分隔字符串，按原样存，**不要**改成 `json.dumps`。

**② `meta.revision`**
原先靠 `os.path.getmtime(novel_cache.json)` 判断「缓存被别人改了，该重载」。
文件没了，改成每次写入 `revision + 1`，`should_reload_cache()` 比对它。

### 连接与事务约定

- **每线程独立连接**，存在 `threading.local` 里，绝不跨线程共享对象。gunicorn 是
  `-w 1 --threads 4`（自动用 gthread），4 个线程各自持有连接。
- 连接建立后统一执行：`busy_timeout=5000`、`cache_size=-1000`（1MB）、
  `temp_store=FILE`、`mmap_size=0`、`journal_mode=DELETE`、`foreign_keys=ON`。
- **`foreign_keys=ON` 必须开**，否则 `chapters` 的 `ON DELETE CASCADE` 静默失效。
- 多表写入在**单个事务**内，失败整体回滚；批量章节用 `executemany`。
- 章节索引目前不持久化（程序里 `chapter_cache` 是运行时内存缓存），所以
  `chapters` 表通常为空 —— 这是预期状态，不是 bug。

### 对外接口（`storage/cache_store.py`）

| 函数 | 用途 |
|---|---|
| `init_db(db_path)` | 建库建表，幂等 |
| `ensure_ready(json_path, db_path)` | 启动时调用：建库 + 需要时自动迁移，返回 `(imported, state)` |
| `list_books()` / `load_all()` | 全部书籍，顺序与迁移前 JSON 一致 |
| `get_book(path)` | 单本，没有返回 `None` |
| `upsert_book(book, chapters)` | 写单本 + 章节，单事务 |
| `delete_book(path)` | 删单本，章节级联 |
| `sync_all(books)` | **增量同步**（写路径主力）：diff 后只写变化行，返回 `inserted/updated/deleted/unchanged` |
| `migrate_from_json(json, db)` | 迁移，幂等，成功后源 JSON 改名 `.bak` |
| `get_revision()` | 供热重载判断 |
| `stats()` | 排查用概览 |

### 迁移与回滚

**迁移**（正常情况下不需要手动做，启动时自动完成）：

```bash
docker exec novel-manager python /app/migrate_cache.py --check   # 体检，不写库
docker exec novel-manager python /app/migrate_cache.py           # 手动迁移
```

- 幂等：库非空直接返回 0，不会重复导入
- 全量导入走单事务，失败整体回滚
- 成功后 `novel_cache.json` 改名 `novel_cache.json.bak`，**不删除**

**回滚**（三步，都在宿主机上做）：

```bash
cd /vol2/1000/docker/novel-manager
git checkout pre-sqlite-migration          # 1. 代码回到迁移前
cd data
mv novel_cache.json.bak novel_cache.json   # 2. 旧 JSON 改回来（没有 .bak 就用 .pre-sqlite）
rm -f novel_cache.db novel_cache.db-journal  # 3. 删掉库
docker restart novel-manager
```

`pre-sqlite-migration` 是迁移前打的 tag，`git show pre-sqlite-migration:novel_manager.py`
可以单独取出旧版主程序。回滚演练记录见 `docs/sqlite-migration-report.md`。

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

`data/novel_cache.db` 可以不带（15MB，启动后扫一遍就有）：不带时新机器首次启动
会走「库不存在 + 无旧 JSON」的分支，直接进入全量扫描。要带的话请先 `docker stop`，
运行中的 SQLite 库直接拷可能拿到未提交的事务。

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
| 改了 `storage/`（存储层） | `docker restart novel-manager` |
| 改了 requirements.txt | `docker compose build && docker compose up -d` |
| 改了 compose | `docker compose up -d` |
| 看日志 | `docker logs novel-manager --tail 100` |
| 数据备份 | 打包 `data/`，建议排除 `novel_cache.db*` 与 `novel_cache.json*` |
| 改完存储层要重跑自测 | `docker exec novel-manager python /app/tests/sqlite_selftest.py` |

**注意事项**

- 所有状态在 `data/`，`config.json` 含用户表和密码哈希，截屏或分享时必须隐去
- `storage/` 是**必需目录**，主程序启动时就 `from storage import cache_store`；
  只挂主程序文件、或复制项目时漏掉这个目录，容器会直接起不来（ModuleNotFoundError）
- 单 worker 是刻意设计，不要为"提速"提高 worker 数
- PID 1 由 compose 的 `init: true` 提供，Dockerfile 里没有 tini 也没有 ENTRYPOINT，两者配套
- 如果是通过 SSH 操作宿主机，git 推送走 SSH over 443（deploy key 已配好），
  **不需要开代理**；只有回退到 HTTPS + PAT 时才需要，详见 `推送指南.md`
