# novel_cache.json → SQLite 迁移记录

> 范围：仅 Docker 版（NAS 上的源码目录，下文用 `$APP_DIR` 代指）。桌面版未改动。
> `config.json`、`reading_records/`、用户数据未改动。

- 执行日期：2026-10-27
- 基线 tag：`pre-sqlite-migration`
- 数据规模：5123 本，`novel_cache.json` 10.53MB → `novel_cache.db` 15.83MB

---

## 1. 结果摘要

| 指标 | 迁移前（JSON） | 迁移后（SQLite） |
|---|---|---|
| 启动耗时（5123 本） | 1.40s | 1.44s |
| 启动后 RSS | 94.2MB | **64.9MB**（-29MB） |
| 单本改动的落盘量 | 全量重写约 11MB | **1 行** |
| 无任何变化时的保存 | 全量重写约 11MB | **0 行**（只有一次 SELECT） |
| 迁移导入耗时 | — | 0.73s（临时目录）/ 生产启动内一次完成 |
| 并发读 + 写 | — | 无 `database is locked` |

启动耗时基本持平——解析 11MB JSON 只占启动的一小部分（大头是 Flask/模板导入），
真正的收益在**写放大**和**常驻内存**。

---

## 2. 交付物

| 交付物 | 状态 | 位置 |
|---|---|---|
| 存储层模块 | ✅ | `storage/cache_store.py`、`storage/__init__.py` |
| 独立迁移脚本 | ✅ | `migrate_cache.py`（`--check` 只体检） |
| 启动时自动迁移 | ✅ | `load_cache()` → `cache_store.ensure_ready()` |
| 调用点替换 | ✅ | 两个 commit：`9dbd431`（读）、`37ef2ec`（写） |
| `novel_cache.json.bak` | ✅ | `data/novel_cache.json.bak`（另有一份 `.pre-sqlite` 兜底） |
| `DEVELOPMENT.md` 存储层说明 | ✅ | 新增「存储层（SQLite）」小节 |
| 测试记录 | ✅ | 本文第 3 节 |
| 回滚演练记录 | ✅ | 本文第 4 节 |
| `EXPLAIN QUERY PLAN` 示例 | ✅ | 本文第 5 节 |

自测脚本（随代码保留，可重跑）：

| 脚本 | 覆盖 |
|---|---|
| `tests/sqlite_selftest.py` | 存储层单元级，34 项（迁移/幂等/级联/并发/回滚/查询计划） |
| `tests/app_integration_test.py` | 应用级，28 项（冷热启动/页面/增量/真实扫描），在隔离副本跑 |
| `tests/live_probe.py` | 线上探针，11 项（真实会话 HTTP，只读） |
| `tests/measure_rss.py` | 启动耗时与 RSS 对比 |
| `tests/prepare_apptest.sh` | 准备隔离副本 |

---

## 3. 测试清单（任务书第 7 节逐项）

| # | 项目 | 结果 | 证据 |
|---|---|---|---|
| 1 | 冷启动：db 不存在 + JSON 存在 → 自动迁移，服务正常启动 | ✅ | 生产重启日志：`✅ 已将 5123 本小说从 novel_cache.json 迁移到 SQLite` → `✅ 从缓存加载了 5123 本小说`；隔离副本冷启动 7/7 通过 |
| 2 | 热启动：db 存在 → 跳过迁移，不重复导入 | ✅ | 同副本二次运行 `冷启动=False`，25/25 通过，`migrate_from_json` 返回 0 |
| 3 | 书籍列表页：条目数、标题、作者、标签与迁移前一致 | ✅ | 迁移前后**逐字段比对 19 个键 0 处不一致**（`sqlite_selftest` [3]）；线上列表页 200 且渲染出书名 |
| 4 | 书籍详情页：章节列表、字数、顺序正确 | ✅ | 线上 `/novel_detail/<书>` 200 且含作者；字数/章节数来自 `word_count`/`chapter_count` 字段（随 extra 原样往返）；章节列表由正文实时解析，缓存未参与 |
| 5 | 阅读进度保存后重启 → 进度不丢 | ✅ | 副本进程 A 写入 42 行进度 → 进程 B（新进程=重启）读回一致；`reading_records/` 完全未改动 |
| 6 | 新增一本小说 → 扫描后可见，db 增量写入 | ✅ | `sync_all` 返回 `inserted=1, updated=0, deleted=0`；真实增量扫描 1.1s、库本数 == 内存本数 |
| 7 | 删除一本小说 → 缓存同步删除，章节级联删除 | ✅ | `deleted=1` 且 `get_book` 返回 `None`；`foreign_keys=ON` 下手动删 books 后 `LEFT JOIN` 孤儿章节数 = 0 |
| 8 | 并发：两个请求同时读 + 一个写 → 无 `database is locked` | ✅ | 3 个读线程 + 1 个写线程（5 次 upsert + 5 次 delete），异常列表为空 |
| 9 | 内存：迁移后进程 RSS 增量 < 20MB | ✅ | 同数据同环境：94.2MB → 64.9MB（**-29.3MB**，三次测量一致） |
| 10 | 回滚：`.bak` 改回 `.json` + 删 db → 旧版本代码可正常启动 | ✅ | 见第 4 节，旧代码启动后加载 5123 本 |

另：写入中途抛错时整体回滚（行数不变）也已验证。

---

## 4. 回滚演练记录

按任务书要求，在**阶段 3 完成、阶段 4 上线前**演练。为不影响正在对外的服务，
演练在容器内的隔离副本 `/tmp/rollback_test` 上进行（代码、数据、库文件都是真实副本）。

```
# 1) 代码回到 tag 之前的状态（旧主程序，无 storage 依赖）
rm -rf /tmp/rollback_test/storage
git show pre-sqlite-migration:novel_manager.py > /tmp/rollback_test/novel_manager.py

# 2) 数据回到迁移前形态
cd /tmp/rollback_test/data
mv novel_cache.json.bak novel_cache.json
rm -f novel_cache.db novel_cache.db-journal

# 3) 启动
python /tmp/measure_rss.py /tmp/rollback_test
```

输出：

```
--- 回滚后 data 目录 ---
-rwx------ 1 root root 11043709 novel_cache.json
=== 回滚演练：用旧代码启动（读恢复后的 JSON）===
✅ 缓存加载成功，共 5123 本小说
🚀 使用缓存数据快速启动
rollback_test: 启动 1.41s | RSS 94.1MB | 书籍 5123 本
```

结论：**回滚路径可用**，旧代码能直接吃恢复后的 JSON，数据无损失。

线上回滚命令（三行，见 `DEVELOPMENT.md`）：`git checkout pre-sqlite-migration` →
`data/` 里把 `.bak` 改回 `.json` → 删 `novel_cache.db*` → `docker restart novel-manager`。

---

## 5. EXPLAIN QUERY PLAN（生产库实测）

```
按路径查单本   -> SEARCH books USING INDEX sqlite_autoindex_books_1 (path=?)
按 mtime 排序  -> SCAN books USING INDEX idx_books_mtime
章节连表       -> SEARCH b USING COVERING INDEX sqlite_autoindex_books_1 (path=?)
                | SEARCH c USING COVERING INDEX sqlite_autoindex_chapters_1 (book_id=?)
全量加载       -> SCAN books
按作者筛选     -> SCAN books          ← 故意不建索引，见下
```

- `path` 走的是 `UNIQUE` 约束自带的 `sqlite_autoindex_books_1`。`idx_books_path` 与之
  功能重叠，但任务书要求显式建，保留（开销可忽略：只多一棵小索引）。
- **作者/标签不建索引**：程序从不按作者查库——所有筛选都在内存的 `novel_data` 上做，
  建索引只会增加写入成本。真要下推到 SQL，再加也不迟。
- `journal_mode=delete` 已确认生效（按任务书要求本次不切 WAL）；`mmap_size=0` 同样生效。

---

## 6. 与任务书不一致的地方（都是实测发现，记录原因）

1. **`novel_manager.py` 实际 7906 行，不是任务书写的 383 行。**
   缓存读写仍然集中（只有 `load_cache` / `save_cache` / `should_reload_cache` 三处），
   所以「按调用点逐个替换」依然成立，只是文件比预期大得多。

2. **`tags` 是逗号分隔字符串，不是 JSON 数组。**
   真实数据 5123 本全是 `"甲,乙,丙"` 这种形式，代码里也是 `.split(',')`。
   任务书建议「先 `json.dumps` 成字符串」——照做会让 `list_books()` 返回
   `"\"甲,乙,丙\""`，破坏逐字段兼容。因此**按原样存 TEXT**。

3. **schema 多了两处：`books.extra` 列 + `meta` 表。**
   原 JSON 每本 19 个字段，任务书的 schema 只覆盖 6 个。要满足「返回值逐字段兼容、
   调用方不改逻辑」，其余 13 个字段必须存下来——整体序列化成 JSON 放在 `extra`，
   没有拆表。`meta.revision` 用来替代原「缓存文件 mtime」做热重载判断，
   否则迁完之后「缓存被改写」这件事就没有信号了。

4. **`chapters` 表建了，但通常是空的。**
   程序里章节切分结果只存在内存 `chapter_cache`（`save_cache` 早就不持久化它）。
   表结构、`upsert_book(book, chapters)` 接口、级联删除都已实现并测过，
   等将来真要持久化章节索引时直接可用，本次不改变现有行为。

5. **阶段 3 单独不可部署。**
   只切读不切写会导致「读库、写 JSON」的数据分叉。两个 commit 分开提交（便于 review），
   但**一次上线**，commit message 里已注明。

6. **数据库放在 `data/`（NAS 本地卷 `/vol2`），不是网络盘。**
   `/app` 是 NAS 本地目录挂载进容器，走的是本地文件系统；
   任务书禁止的是 SMB/NFS 这类网络路径，这里不涉及。

7. **库比 JSON 大（15.8MB vs 10.5MB）。**
   SQLite 有页开销，`extra` 里的 JSON 还多带了一层引号/转义。
   换来的是写放大从「11MB×每次」降到「变化行数」——这才是本次要解决的问题。
   想再压体积可以调大 `page_size`，但收益（几 MB）不值得增加复杂度。

8. **回滚演练在隔离副本做，没有让线上真实回滚一次。**
   线上回滚意味着对用户停机一次、且要回退到旧版本代码再上回来，风险大于收益。
   副本演练用的是同一份代码和同一份数据，结论可信。

---

## 7. 后续可做（不在本次范围）

- 章节索引持久化（`chapters` 表已就绪，缺的是调用方）
- 标签拆表 + 全文检索（当前 `tags` 是字符串，`LIKE` 查询会误匹配，真要查得拆表）
- 大书库下把 `list_books()` 改成分页（现在 5123 本全量进内存没问题，2 万本再看）
