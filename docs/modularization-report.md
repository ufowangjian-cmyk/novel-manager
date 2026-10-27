# novel_manager.py 模块化（Blueprint 拆分）记录

> 纯重构：不改业务逻辑、不动存储层、不改 URL / 响应格式 / 模板结构（仅端点名加蓝图前缀）。
> 存储层的 SQLite 迁移已经结束，本次只移动 `storage/cache_store.py` 的调用位置。

- 执行日期：2026-10-27
- 基线 tag：`pre-modularization`（= SQLite 完成后的 `0a98925`）
- 规模：**7943 行的单文件、77 条路由、5 个全局钩子**

---

## 1. 进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| 0 | 采集基线（路由表 / url_map / 实例属性 / 行为快照） | ✅ |
| 1 | `create_app()` 工厂骨架，零行为变更 | ✅ 已上线 |
| 2 | 拆 `auth` 蓝图（9 条路由） | ✅ 已上线 |
| 3 | 拆 `library` 蓝图（43 条） | ✅ 已上线 |
| 4 | 拆 `reader` 蓝图（10 条） | ✅ 已上线 |
| 5 | 拆 `media`（10 条） | ⏸ 未开始 |
| 6 | 清理，`novel_manager.py` 收敛到入口 | ⏸ 未开始 |

`novel_manager.py`：7943 → 5785 行，`@app.route` 76 → 14。

library 内部按风险分三批搬，每批都跑了同一套快照：

| 批次 | 内容 | 条数 | 关键风险 |
|---|---|---|---|
| 1 | 筛选取数（`get_all_*`/`get_first_*`）、`/config/get`、`/config/save_sort`、随机推荐、扫描触发与进度、配置页/标签页壳 | 13 | 依赖 10 个共享名字，较干净 |
| 2 | 标签体系全套（增删改查、规则、别名、派生规则、导入导出） | 26 | 6 个函数有 `global CONFIG/TAG_*` 写操作 |
| 3 | `index`、`novel_detail`、`save_config`、`reload_config` | 4（534 行） | `global CONFIG` 整体替换 + `apply_runtime_config` 联动 |

---

## 2. 与任务书不一致的地方

**① 文件规模差了 20 倍。** 任务书写 383 行，实际 7943 行、77 条路由、5 个全局钩子（2 个
`before_request`、2 个 `after_request`、1 个 `context_processor`）。这不是「拆 5 个蓝图」的
量级，所以本轮只做到 auth。

**② 端点名要加蓝图前缀，「url_map diff 为空」不可能成立。** Flask 注册蓝图时强制给端点加
`<蓝图>.` 前缀，没有开关。经确认，验收口径改为：

- `rule` + `methods` **逐条 diff 必须为空**
- `endpoint` 剥掉 `<蓝图>.` 前缀后**必须完全一致**
- 用 `tests/diff_url_map.py` 自动执行这个判定，而不是裸 `diff`

**③ 共享逻辑没有下沉到 `app/core/`。** 任务书要求 `core/` 承载共享逻辑，但这个文件里
`CONFIG` / `novel_data` / `is_admin` / `save_json_file` 被 200+ 处引用，`CONFIG` 还有两处
`global CONFIG; CONFIG = 新dict`。真下沉会牵动全文件。经确认走「蓝图反向 import 主模块」：
路由搬走、共享物原地不动，靠「主模块末尾才 import 蓝图」保证初始化顺序。

**④ 改了一处模板。** `templates/index.html:125` 的 `url_for('logout')` 必须改成
`url_for('auth.logout')`，否则运行时 BuildError。这是端点改名的必然结果，不是「改模板结构」。

**⑤ 阶段 1 的 `create_app()` 不注册蓝图。** 蓝图要反向 import 主模块，只能在主模块初始化
完成后 import，所以注册放在 `novel_manager.py` 末尾（`register_blueprints(app)`）。
等阶段 6 全部搬完、共享物下沉后，这个调用可以移回工厂。

---

## 3. 回归测试记录（任务书第 5 节逐项）

| # | 项目 | 结果 | 证据 |
|---|---|---|---|
| 1 | `url_map` 与基线逐条 diff | ✅ | 77/77 条；(方法,规则) 逐条一致，端点剥 `auth.` 后一致（`diff_url_map.py`） |
| 2 | 关键页面状态码与响应哈希 | ✅ | 32/32 一致（首页/首页排序/首页标签筛选/配置页/标签管理/详情/阅读/continue + 11 个 API + PWA + SW） |
| 3 | 登录/登出/未登录重定向 | ✅ | auth 专项 27/27：未登录 302→/login、错误密码 200+提示、成功 302→/、登出 302→/login 且 session 清空 |
| 4 | 书籍列表、详情、标签筛选 | ✅ | `index` / `index_sorted` / `index_tagged` / `detail` 哈希一致 |
| 5 | 阅读页渲染、章节切换 | ✅ | `read_first`（第1行）/`read_last_line`（第40行）哈希一致 |
| 6 | 进度保存后重启，进度不丢 | ✅ | 阅读记录链路未改；阅读页 GET 仍走 `save_reading_record`，副本跨进程读回一致 |
| 7 | 配图检测与映射 | ✅ | `/api/emoji/image-mapping`(31KB) / `/api/emoji/mapping`(8.7KB) / `/api/header_bg_images` 哈希一致 |
| 8 | 静态资源路径可访问 | ✅ | `/service-worker.js`、`/manifest.json`、`/static/*` 哈希一致（`?v=` 指纹也一致） |
| 9 | 无新增 500 | ✅ | 启动日志无异常；探针 15/15；auth 专项无失败项 |
| 10 | 无 `url_for` 构建失败 | ✅ | 全部页面渲染成功；`url_for('auth.login')`/`('auth.logout')` 显式断言返回 `/login`/`/logout` |

另：**Flask 实例属性 46 行 diff**，只有 `blueprints: [] → ['auth']` 一行变化，其余
（钩子清单与顺序、jinja searchpath、session 配置、ProxyFix、view_functions 数量）完全一致。

线上探针 15/15 通过（含 4 项 auth 蓝图路由）。

---

## 4. 回滚演练记录

按任务书要求，阶段 2 完成后、上线前演练一次。在容器内副本 `/tmp/rollback2` 上进行
（代码/数据都是真实副本，不碰线上）：

```
1. 宿主机 git show pre-modularization:novel_manager.py > /tmp/old_nm.py   (7943 行)
2. cp -a /tmp/modtest /tmp/rollback2；替换主程序；删掉 app/ 目录
3. python tests/snapshot_url_map.py > /tmp/rollback_routes.txt
4. diff docs/url_map_before.txt /tmp/rollback_routes.txt
```

结果：

```
ROLLBACK_ROUTES_IDENTICAL
GET,POST     | /                                                            | index
```

**旧代码启动正常，路由表与拆分前逐字节一致**（端点回到无前缀形态 `login`/`index`…）。

线上回滚命令：`git checkout pre-modularization` → `docker restart novel-manager`。

---

## 5. 过程中踩到的坑（都已固化进脚本）

1. **容器内 `/tmp` 与宿主机 `/tmp` 不是一回事。** 第一次把文件 push 到宿主机 `/tmp/modtest`，
   容器里看不到，导致「旧代码 vs 旧代码」的空 diff 假通过。改成经挂载目录中转。
2. **`cp -r` 会毁掉静态资源指纹。** `?v=` 取的是文件 mtime，`cp -r` 让副本里所有静态文件
   变成「刚刚修改」，全部页面哈希集体误报。改 `cp -a`。
3. **基线自己会污染自己。** `/read/` 会写阅读记录，首页和详情页渲染「最近阅读」卡片，
   于是同副本第二次采集哈希必变。改成采集前清空副本的 `reading_records/`。
4. **`api_cache_stats` 含进程 RSS**，跨进程必然不同；列为豁免项，只比状态码。
5. **`novel_manager` 有了 `create_app` 属性后**，快照脚本的「有工厂就用工厂」逻辑误取了空壳实例
   （1 条路由），导致一次假的「完全一致」。改成永远优先取模块级 `app`。
6. **`threading` / `time` / `session` 漏 import**（library 批次 3 上线后才发现）。依赖分析器当
   初只找「主模块自己定义的名字」，而 `threading` 是 `import threading` 进来的，被当成已满足。
   `start_scan` 一被调用就 `NameError` → 500。为此写了 `tests/check_missing_imports.py`，
   现在每次搬完都跑，能一次列出所有「用了但没定义也没 import」的名字。
7. **代码与模板必须同批改**。搬到 `library` 后 `url_for('index')` / `url_for('novel_detail')`
   全要加前缀：代码 6 处（含 `app/auth/routes.py` 里 login 的跳转）+ 模板 7 处
   （`index.html` / `read_chapter.html` / `_random_card.html`）。只改一边，阅读页和首页立刻 500。
8. **数据一变，旧的行为基线就失效**。拆 library 期间书库真实新增了一本（5123 → 5124），
   `index` / `get_all_*` / `api_tags` / `api_users_list` 的哈希全变 —— 看着像代码坏了，其实是
   数据变了。正确做法：用「旧代码 + 旧模板」在**当前数据**上重采基线再比对，这一步做完后
   本轮是 32/32 完全一致。

---

## 6. 下一步（未做）

- 阶段 3 `library`（43 条）：最大的一块，`index` 依赖大量全局状态，需要在同样的
  快照机制下分小批搬，建议拆成 3～4 个 commit。
- 阶段 6 收敛时再决定是否把共享物下沉 `app/core/`（届时可用 `core/config.py` 持有 CONFIG，
  把两处 `global CONFIG` 改成原地更新，避免分叉）。
