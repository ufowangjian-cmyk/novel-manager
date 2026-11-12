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
| `reading_records/` | 每用户一个阅读记录文件 | ❌ 隐私 |
| `tag_rules.json` | 标签规则 | ⭕ 个性化积累 |
| `image_mapping.json` | 配图映射 | ⭕ |
| `emoji_mapping.json` | 表情映射 | ⭕ 需配合 `static/emojis/` |
| `scan_stats.json` | 上次扫描的统计与中断标记 | ❌ 可重建 |
| `scan.lock` / `scheduler.lock` | 扫描 / 调度互斥锁 | ❌ |

`reading_records/` 是多用户设计的体现：每人一个 `records_<hash>.json`，互相独立。

`secret_key` 丢失会让**所有用户需要重新登录**，迁移时记得一起带走。

备份 `data/` 时可以直接排除 `novel_cache.db*`——它是扫描即可重建的派生数据。

> **关于 `novel_cache.json.bak`**：迁移时会把旧 JSON 改名保留，但它不参与运行。
> 本机这份已于 2026-10-27 清理（另存有 zip 备份）。因此现在 `data/` 里没有旧 JSON，
> 缓存只剩 `novel_cache.db` 一份；万一库丢了，删掉它重扫一遍即可，不需要旧 JSON。

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
- 成功后 `novel_cache.json` 改名 `novel_cache.json.bak`（该备份本机已于 2026-10-27 清理）

**回滚**（三步，都在宿主机上做）：

```bash
cd /path/to/novel-manager                  # 换成你的项目目录
git checkout pre-sqlite-migration          # 1. 代码回到迁移前
cd data
mv novel_cache.json.bak novel_cache.json   # 2. 旧 JSON 改回来（本机已清理，需从 zip 备份取出）
rm -f novel_cache.db novel_cache.db-journal  # 3. 删掉库
docker restart novel-manager
```

`pre-sqlite-migration` 是迁移前打的 tag，`git show pre-sqlite-migration:novel_manager.py`
可以单独取出旧版主程序。这条路径演练过一次：旧主程序能正常读回整库，路由表与迁移前
逐字节一致，说明回滚可用。

> 本机的 `novel_cache.json.bak` 已清理，第 2 步的旧 JSON 要从 zip 备份里取；
> 或者干脆跳过第 2 步——旧代码在没有 JSON 时会重新扫描生成缓存（慢一点，但结果一样）。

### 查询计划与索引取舍

生产库实测（`EXPLAIN QUERY PLAN`）：

```
按路径查单本   -> SEARCH books USING INDEX sqlite_autoindex_books_1 (path=?)
按 mtime 排序  -> SCAN books USING INDEX idx_books_mtime
章节连表       -> SEARCH b USING COVERING INDEX sqlite_autoindex_books_1 (path=?)
               | SEARCH c USING COVERING INDEX sqlite_autoindex_chapters_1 (book_id=?)
全量加载       -> SCAN books
按作者筛选     -> SCAN books          ← 故意不建索引
```

- `path` 走的是 `UNIQUE` 约束自带的 `sqlite_autoindex_books_1`。`idx_books_path` 与它
  功能重叠，但显式建了、保留（多一棵小索引，开销可忽略）。
- **作者 / 标签故意不建索引**：程序从不按作者查库——所有筛选都在内存的 `novel_data`
  上做，建索引只会拖慢写入。将来真要把筛选下推到 SQL，再加也不迟。
- `journal_mode=delete`、`mmap_size=0` 均已确认生效（本次不切 WAL）。

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

## 缓存与失效

| 缓存 | 位置 | 容量 | 失效方式 |
|---|---|---|---|
| `line_cache` | 进程内存 | 64MB LRU | 重启 |
| `chapter_cache` | 进程内存 | 200 条 | `chapter_cache.clear()` |
| `novel_cache.db` | `data/` | 全库 | 重新扫描 |

**改了数据库就必须失效 `chapter_cache`。** `parse_novel_details()` 判断缓存能否复用
只看 `file_hash`：书文件没动就一直命中，那份 `all_chapters` 仍是旧数据。
`backfill_chapter_media()` 曾经只写库、不清缓存，结果是详情页配图徽章不出现、
增量扫描多少次都没用、只有重启容器才好（2026-11-05 踩过）。现在的做法是 backfill
真补了书就 `chapter_cache.clear()`——重建时先命中 SQLite 章节索引，几十毫秒，
而扫描本身是低频操作，直接清最省事。

另外两条：

- 加列先 `PRAGMA table_info` 查，再 `ALTER`（SQLite 没有 `ADD COLUMN IF NOT EXISTS`）
- 详情页目录是懒渲染：首屏 `DETAIL_CHAPTERS_FIRST=200`，超出走 `/api/novel_chapters`；
  给 `url_for` 传路径要用**未编码**的原始路径

头部那个内存占用胶囊的目录是硬设的 `/novels`（容器内的挂载点），桌面版没有这个概念，
不要跟着改。

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
| 静态资源版本号 | `versioned_url_for()` 已全局注入 `?v=<mtime>`，模板里**绝不手写** `?v=`（会变成双问号） |
| 每用户阅读偏好 | `users[<key>].preferences` |

---

## 阅读页渲染（改之前必须知道）

### 处理顺序

整章文本先做引号 / 括号配对高亮，**再**按屏切页——否则跨行括号会被切页截断。
例外是 `is_virtual_chapter`（虚拟章节）：它不整章处理，而是前后各扩 500 行。

### 高亮分两层，缺一不可

| 层 | 位置 | 管什么 |
|---|---|---|
| 单行 | 前端 `highlightQuotesAndBrackets()` | 同一行内的引号、括号 |
| 跨行 | 后端 `highlight_crossline_brackets()` 的 `bracket_pairs` | `<br>` / 换行两侧的配对 |

符号与样式类（两版必须一致）：

| 符号 | 样式类 |
|---|---|
| `“ ”` `「 」` | `highlight-quote-double` |
| `‘ ’` `『 』` | `highlight-quote-single` |
| `（ ）` `( )` `｛ ｝` | `highlight-bracket` |
| `【 】` | `highlight-square-bracket` |
| `[ ]` `［ ］` `〔 〕` | `highlight-square-bracket-1` |
| `〖 〗` | `highlight-hollow-bracket` |
| `《 》` | `highlight-book` |

新增一组括号要改三处：前端一条规则、后端 `bracket_pairs` 加一项、**桌面版同步加**。
桌面版阅读页是 Docker 的对照面（同一份内容、同一套规则渲染），规则一分岔就失去校验能力。

### 高亮不会撕开标签

`highlightQuotesAndBrackets()` 开头把完整标签整体抽出占位（`\u0001序号\u0002`），
所有规则跑完再按序还原。所以 `alt="…（原版）"` 这类属性里的括号是安全的；
但**往文本节点里插的 HTML 仍会被高亮**——插块级组件时别在文本里留成对括号。

### 拖动翻页必须按下即锁选词

`is-drag-scrolling` 的 `user-select: none` 要等拖拽真正激活（按住 150ms 或移动超 5px）
才生效，太晚：Chromium 的选区在 `mousedown` 那一刻就开始铺，之后再加 `user-select: none`
**不会取消已有选区**（Firefox 遵守 `preventDefault()`，所以只有 Edge / Chrome 出问题）。

正确做法：`mousedown` 立刻给 `body` 加 `is-drag-holding`（只锁选词、不动光标）并
`removeAllRanges()` 清残留，`clearDragState()` 里无条件移除。
「允许圈选」模式下这条路径直接 return，不能加类。

### 配图画廊

连续 ≥ 阈值的媒体行折叠成网格：

- `galleryMediaKind()` 返回 `image` / `video` / `null`，**音频不参与**（音频会把组断开）
- 阈值：本版用 `user_prefs.gallery_min_images`（每用户，0 = 关），**按媒体总数算**而非图片数
- 视频进网格要做三件事：摘 `controls`、`preload` 改 `none`、把内联 `style` 一并暂存
  （它自带 12px 圆角和投影，会和网格的 3px 圆角打架）
- 展开/收起抽成 `applyStacked()`，toggle 与「点视频格」共用：点视频先展开本级，
  再 `scrollIntoView` + `play()`
- 分组只搬 `figure` 节点（不重建），原 `.content-line` 外壳整行删掉，不留空壳

桌面版这段代码**不是逐字相同**：本版按钮用 `icon()` sprite（`film` / `list` / `layout-grid`），
桌面版是纯文字，同步时别直接互相覆盖。

### 列表状态与「返回列表」

页码 / 筛选（`search` `author` `tag` `site`）/ 排序（`sort` `order`）必须**一路透传**：
首页卡片 → 详情页 → 阅读页（含目录抽屉、翻章）每一跳都要带上，少一环就回不到原样。
排序最容易被漏掉——漏了会按默认排序重排同一页，看着像「回不去」，其实内容全换了。

返回按钮统一调模板全局函数 `list_back_url()`：从 `request.args` 重建
（`list_page` 和 `page` 都认），由 `url_for` 负责编码；当前 URL 没有页码时借 `Referer`
兜底，所以从随机推荐、收藏夹进来也能回到刚才那页。

**别再手拼 `/?page=xx&search=yy`**：漏参数，而且中文和 `&` 不做编码会被截断。

随机推荐卡片这类「入口本身不带列表状态」的地方，用 `detail_url_with_state()` /
`read_url_with_state()` 生成链接（服务端模板和 `/api/random_novel` 共用同一对函数，
后者把页码转成 `list_page`）；前端「换一本」会把当前 `location.search` 一起发给接口，
所以换出来的卡片同样带着状态。

### 零碎

- `.content-line` 有 `text-indent: 2em`（特异性 0,5,0）→ 往里塞块级组件要显式 `text-indent: 0`
- 骨架屏是纯 CSS 实现的；早期那版转圈图已回退，**不要再加回来**

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

## 书名与章节数据

**书名以正文内的「书名：」行为准，不是文件名。** 全库有 1033 本书的内名与文件名不同，
内文那份更规范（文件名常被加进度后缀、站点前缀）。所以**不能改成文件名优先**。

改名时用 `title_from_filename()` 判断：只有「旧 title 正好等于旧文件名派生出来的值」
才跟着改，否则视为用户/内文指定的名字，保持不动。

**`chapters.media` 是三态字段**，别只看真假：

| 值 | 含义 |
|---|---|
| `NULL` | 没算过 |
| `'i'` / `'v'` / `'a'` 等组合 | 有对应媒体（图 / 视频 / 音频） |
| `''` | **算过了，确实没有媒体** |

写库时空值必须写 `''` 不能写 `NULL`，否则下次又会被当成「没算过」重算一遍。
两条取数路径都要带这个字段：索引路径 `load_details_from_index()` 和全文路径
`annotate_chapter_media()`——漏一条就会出现「详情页有徽章、阅读页没有」这类不一致。

**`work_id`** 取正文前 32 行的指纹：改名、追加章节、改几个错字都不变，
所以阅读进度按它存，不会因为 `【1-51】` 这类后缀变动而丢。

**已知问题（决定不修）**：带进度后缀的文件改名，扫描会当成「删一本 + 加一本」，
`renamed_count` 恒为 0。进度不受影响（按 `work_id` 存），只是提示里显示成新增。
提示文案用 `novel_title_stem()` 去掉后缀，避免看到两个几乎同名的书名。

---

## 自测方法

改完别只看代码，这几条能直接跑：

| 想验证 | 怎么做 |
|---|---|
| 视图渲染出的 HTML | `spec_from_file_location` 载入主程序 + `app.test_request_context()` 调视图函数；`/config` 需要先 `session['user_role'] = 'admin'` |
| 前端函数行为 | 无头 Edge：`--headless=new --allow-file-access-from-files --dump-dom`，从 DOM 里读结果。**必须 `--dump-dom`**，截图看不出结构 |
| 真实 HTTP 响应 | `curl` 带会话 cookie；静态文件直接比字节数和 `Last-Modified` |
| 容器内的数据 | `docker exec novel-manager python3 -c ...`；探针脚本用 base64 传进去，避免引号和中文被 shell 吃掉 |

注意：

- 容器内 `/novels` 是只读挂载，造测试书用 `NOVEL_DIR=/tmp`
- `docker exec` 单次执行约 3 分钟超时；镜像里没有 `ps`
- **交互类问题交给用户手动点**：合成事件会绕过 `mousedown` 监听器（浏览器级 drag 不触发它），
  无头测出来的结论可能是假的

---

## 简介与预览提取

`extract_intro_clean()`：从「简介：」行（没有就取元数据之后）到**第一个章节标题**为止。
空行保留（分段），图片行原样保留，纯符号行与元数据行剔除；整段超过 3000 字判为「无简介」
（说明截到正文了）。预览用 `extract_preview_clean()`，上限 6 行 / 300 字，只在无简介时展示。

⚠️ **详情页冷启动曾经走另一套逻辑**：`parse_novel_details_from_content()` 里用「前 100 行
凑 10 行长句」当简介 —— 既不是简介区，还会把首个章节（楔子 / 前言 / 引子）的正文吃进去。
详情页只校验这段里有没有「书名：/作者：/标签：/链接：」，没带这些词就放行、顶掉缓存里
正确的简介（2026-11-10 抽样 200 本命中 40 本）。现已统一改调 `extract_intro_clean()`，
部署后抽 200 本与缓存 100% 一致。

桌面版另有 `is_chapter_line_strict()` 做边界判定（比 `LEVEL*_PATTERN` 严：冒号式标题
≤30 字、不带句读；裸词短标签 ≤8 字），细节见桌面版仓库 `DEVELOPMENT.md`。

## 内置字体（全开源 + unicode-range 分包，2026-11-12）

原来 9 个内置字体里有 6 个是商业字体（方正大标宋/仿宋/楷体、汉仪文黑、兰亭羲之黑、仓耳今楷），
分享部署目录有授权风险。2026-11-12 全部换成 **SIL OFL 开源字体**（现 8 套可选），并按 unicode-range 分包：

| 家族（CSS 里的名字） | 上游 | 目录 | 用在 |
|---|---|---|---|
| `思源黑体内置` | Noto Sans SC（可变 100-900） | `static/fonts/noto-sans/` | 双引号、方括号、空心括号 |
| `思源宋体内置` | Noto Serif SC（可变 100-900） | `static/fonts/noto-serif/` | 括号、标题 |
| `霞鹜文楷等宽内置` | LXGW WenKai Mono 400 | `static/fonts/wenkai-mono/` | 正文 |
| `霞鹜文楷比例内置` | LXGW WenKai 400 | `static/fonts/wenkai/` | 单引号、书名号 |
| `未来圆内置` | WeiLaiYuan SC Medium（用户本地 TTF 自切） | `static/fonts/weilaiyuan/` | 空心括号 |
| `寒蝉圆体内置` | ChillRoundGothic ExtraLight（思源黑体圆角化） | `static/fonts/chillround/` | 可选：更细的圆体 |
| `得意黑内置` | Smiley Sans Oblique（倾斜黑，标题用） | `static/fonts/smiley/` | 可选：标题 |
| `朱雀仿宋内置` | Zhuque Fangsong v0.212（技术预览版，OFL） | `static/fonts/zhuque/` | 可选：引号/括号等装饰 |

### 字体配置要穿过 7 层，键名必须逐层对齐

9 个作用域（正文、标题、双/单引号、圆/方头/方/空心括号、书名号）在仓库里各有一份键名，
任何一层写错都表现为「配置页改了、阅读页没反应」：

| 层 | 位置 |
|---|---|
| 后端键 | `<scope>_font_family`（正文是 `font_family`），默认值在 `DEFAULT_CONFIG` |
| 允许保存 | `api_save_preferences` 的 `ALLOWED_KEYS` |
| 阅读页下发 | `read_chapter.html` 的 `data-xxx-font-family` |
| 阅读页抽屉 | `<scope>FontSelect` + `SCOPE_SELECT_IDS`（驼峰，不能靠「去下划线」推） |
| 配置页「管理员默认」 | `admin_font_field(标签, 键, …)`，加粗/斜体 id 必须同前缀 |
| 配置页「我的偏好」 | `pref_<键>` + `PREF_FIELDS.text` |
| 前端应用 | `SCOPE_APPKEY`、`FONT_PREF_KEYS` |

2026-11-12 踩的坑：配置页「标题字体」传的是 `book_font_family`（书名号的键），于是
① 配置页压根没有 `title_font_family` 下拉；② 保存时 `getElementById('title_font_family')`
取不到元素，`?? ''` 反而把已有的标题字体写成空串；③ 标题与书名号两个下拉共用同一个 id，
`getElementById` 只认第一个，书名号的改动被静默丢弃。加粗/斜体 id 同样串到 `book_bold`。

**空字符串的语义**：字体下拉的「跟随正文 / 跟随默认」就是空串，后端约定
「传空串 = 删除该键的个人覆盖」。前端收集偏好时不能因为「空值不发」而跳过字体键，
否则用户选回「跟随正文」永远清不掉旧设置（`FONT_PREF_KEYS` 就是为此单列的）。


每个目录 = `index.css`（带 unicode-range 的 @font-face）+ 97~106 个 woff2 分片（每片 50-100KB）。
未来圆 / 寒蝉圆体 / 得意黑 / 朱雀仿宋是自己切的（cn-font-split 在 Windows 跑不起来）：`fontTools.subset` 按码位
每 350 字切一片，106 片共 9.5MB。
浏览器只下页面实际用到的字所在分片，一页通常几百 KB，而不是原来的整包 8MB。

**`static/css/font.css` 是生成物**：把四份 `index.css` 拼起来，并把「同一批 URL 的三个字重块」
合并成一条 `font-weight: 100 900`（Google 的三档字重共用同一组分片，合并后 699 条 → 396 条）。
当前 432KB，gzip 后 126KB，随 `?v=mtime` 缓存 30 天。**别手改，改了要同步源码**。

**加载方式变了**：以前 `BUILTIN_FONTS` 里存单个 woff2 URL，用 `FontFace` 预载并显示进度；
分包后没有"单个文件"可预载，`BUILTIN_FONTS` 里只留 `{ chunked: true, label }`，
`common.js` 的预热和 `reader-ui.js` 的 `ensureBuiltinFont` 见到 `chunked` 直接放行，
交给 CSS 的 unicode-range 由浏览器按需取片。

**换字体的正确顺序**（漏一步就白干）：
1. 取上游分片（Google Fonts CSS2 + 现代 UA，或 jsDelivr 上的 `lxgw-wenkai-webfont`）
2. 分片落到 `static/fonts/<slug>/`，CSS 里的 URL 改成 `/static/fonts/<slug>/xxx.woff2`
3. 重新生成 `static/css/font.css`
4. 改四处清单：`templates/read_chapter.html`（`font_opts`）、`templates/config.html`
   （`font_list` + `font_opts`）、`static/js/config.js`（`FONT_NAME_MAP`）、`static/js/common.js`（`BUILTIN_FONTS`）
5. **迁移 `data/config.json`**：字体存的是整串 font stack，换了家族名旧值会全部回退到默认，
   按"旧家族名 → 新 stack"逐键映射（含 `users/*/preferences/*` 里的每用户偏好）

## 标签提取（关键词 → 派生 → 排序）

只读文件头 64KB，实际参与匹配的是 `header[:30000]`（约 1.5 万字）。

| 信号源 | 范围 | 用途 |
|---|---|---|
| 元数据「标签：」行 | 前 30 行 | 显式标签，排序时置顶 |
| 关键词 | 章节标题 + 头部前 30000 字符 | 命中即打标（`tag_rules.json` 的 655 条） |
| 章节标题 | 前 500 行内识别、最多 200 个 | 参与匹配，也用于打分 |
| 完结 | 文件名含「完」或「完结」 | 状态标签 |
| 配图 / 视频 / 音频 | 配图目录实际扫描 | 状态标签；**不参与文本匹配**（否则正文提到「视频」就打标） |
| 书名 / 文件名 | — | 只参与打分，不参与匹配 |

**排序三层**（`score_tags()`）：

1. 状态标签（完结 / 配图 / 视频 / 音频）
2. 「标签：」行的显式声明
3. 权重降序：文件名 6 / 章节 4 / 简介 2 / 正文 1，各自次数封顶（3 / 5 / 5 / 5）；
   派生标签 ×0.5；一个信号都没命中给 0.1；同分按标签名升序（保证可复现）

**否定上下文**（`_tag_negated_only()`，2026-11-08 加）：命中位置往前 8 个字符、
去掉空白后如果结尾是「不是 / 没有 / 并非 / 不算 / 不含 / 不涉 / 绝不是 / 杜绝 / 拒绝 /
无任何 / 没有任何」或单字「没 非 未 无 别」，就当这句是否定，跳过这次命中。
同一个关键词只要有一处没被否定，标签照样打上。

单字「不」**故意不收**：「不同性格」里的「同性」会被误杀（实测 120 本踩到 2 次），
而「不是 / 不算」这些短语已经能兜住真正的否定。

### 全库重扫实测（2026-11-08，5203 本）

| 指标 | 改前 | 改后 |
|---|---|---|
| 标签总数 | 232,927 | 231,884（−0.4%） |
| 平均每本 | 44.77 | 44.57 |
| 不同标签数 | 535 | 535（不变） |
| 标签完全没变的书 | — | 1,987 本（38.2%） |
| 前 3 个命中书名的比例 | 18.6% | 19.3% |
| 前 3 里噪音词占比 | 5.8% | 7.1% |

被删掉最多的标签：`处女` 128 本、`结婚` 56、`怀孕` 37、`绿帽` 30、`秘密` 30、`有绿` 26、
`出轨` 25、`真实` 25——基本都是「不是处女」「没有结婚」这类否定句，删对了。
没有新增标签（否定只做减法）。

噪音占比上升 1.3 个点，是「简介不再和正文重复计分」的副作用：分数被压平后同分变多，
同分按标签名排序，泛词偶尔挤进前 3。试过两种补救都无效——对数递减（噪音反而到 8.3%）、
同分时优先「命中来源更多」的标签（7.3% → 7.3%，没有区别），都没采用。

### 已知局限

- 简介信号以前取的是 `header[:30000]`，和正文完全同一段，等于正文命中双计分
  （2026-11-08 改成真正的简介区，但实测对前 3 名质量影响在 1% 以内）
- 次数封顶会让大量标签在上限处同分，同分再按标签名排 → 「生活」「真实」这类泛词
  偶尔会挤进前 3。要彻底压下去得在规则文件里给弱词打标，属于内容决策
- 单字 / 通用词（`父` 73%、`母` 85%、`生活` 81%）命中率极高，作为筛选维度区分度很低

### 改完要重扫才生效

标签存在 `novel_cache.db`，扫描时按 mtime + 文件哈希复用缓存，**改了提取规则不会
自动重算旧书**。要让全库生效只能删掉缓存库重扫（阅读进度不受影响，它按 `work_id` 存在别处）。

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
