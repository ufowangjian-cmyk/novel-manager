# 小说管理器 - Docker 版（NAS 部署）

在 NAS 上以 Docker 容器方式运行的小说库管理服务。**多用户、带登录鉴权**，
可局域网访问，供家人各自使用。

## ⚠️ 仓库不含字体与图片素材

本仓库**故意不包含** `static/fonts/`、`static/images/`、`static/emojis/`：

- 中文字体多为商业授权（方正、汉仪、仓耳今楷、兰亭羲之黑、未来圆等），
  公开分发有版权风险
- 头图与表情包来源网络，授权不明

代码不依赖它们，**缺了也能正常启动**，只是排版会回退到系统字体、
头图与表情不显示。

想让界面恢复原样，自己准备素材放进去即可：

```
static/fonts/    放 .woff2 字体文件，文件名需与 templates/ 里 font-family 对应
static/images/   放 header-bg-*.webp 头图
static/emojis/   放表情包 gif/png
```

可自由分发的替代字体推荐：**霞鹜文楷**（LXGW WenKai，SIL OFL）、
**HarmonyOS Sans**（华为免费商用）、**思源黑体/宋体**（SIL OFL）。

---

## 快速开始

### 前置条件

- NAS 上已安装 Docker 与 Docker Compose
- 已开启 SSH（或用 NAS 的终端应用）
- 小说文件已放在 NAS 的某个目录下

### 目录约定

| 用途 | 宿主机路径 | 容器内路径 |
|---|---|---|
| 项目目录 | `/path/to/novel-manager/` | `/app` |
| 小说书库 | `/path/to/your/novels/` | `/novels`（**只读**） |

两个宿主机路径在 `.env` 里配置（见 `.env.example`），**不要**直接写进
`docker-compose.yml`，否则换机器就得改代码。

### 首次部署

```bash
# 1. 进入项目目录
cd /path/to/novel-manager

# 2. 从模板生成自己的配方文件
cp docker-compose.example.yml docker-compose.yml
cp .env.example .env

# 3. 编辑 .env，填入小说目录、项目目录、管理员密码
vi .env

# 4. 确认 compose 能正确解析变量
docker compose config

# 5. 构建镜像并启动
docker compose up -d --build

# 6. 查看启动日志
docker compose logs -f
```

> `.env` 和 `docker-compose.yml` 已被 `.gitignore` 排除 ——
> 里面是本机真实路径，不该进仓库。

启动后访问：`http://<NAS的IP>:5000`

### 首次登录（重要）

> ⚠️ **本程序没有内置的默认密码，也不存在"后门账号"。**
>
> 当 `config.json` 里的 `users` 为空时，程序**只**通过环境变量
> `DEFAULT_ADMIN_PASSWORD` 初始化管理员。如果该变量没设置，
> 登录页会直接提示：
>
> > 系统未配置任何用户，请设置 DEFAULT_ADMIN_PASSWORD 环境变量后重启
>
> 也就是说：**不设这个变量，你将无法登录。**

**所以首次部署请务必在 `docker-compose.yml` 里显式设置：**

```yaml
environment:
  - DEFAULT_ADMIN_PASSWORD=你的强密码
  - SECRET_KEY=一串随机字符串
```

设置后 `docker compose up -d`，程序会自动创建用户名为 `admin` 的管理员账号
（密码用 scrypt 哈希存储），随后**建议把该环境变量注释掉**，
避免密码明文留在 compose 文件里。

关于 `SECRET_KEY`（会话签名密钥）：

- 不设置也能运行 —— 会自动生成并保存到 `data/secret_key`
- 该文件丢失会导致**所有用户需要重新登录**
- 迁移 NAS 时记得一起带走

---

## 架构说明

### 代码通过 volume 挂载，不在镜像里

这是本项目最重要的设计特点：

```
Dockerfile 只做三件事：
  1. 装 Python 3.9 运行时依赖（tini、tzdata）
  2. COPY requirements.txt 并 pip install
  3. 创建目录骨架 /app/data /app/templates /app/static /novels

它**不 COPY 源码**。源码由 docker-compose.yml 挂载进去：
  <项目目录>  →  /app
```

**好处：改代码后只需 `docker restart`，不用重建镜像。**
**代价：镜像不能单独分发**（脱离这个挂载目录就只是个空壳）。

### compose 里的 build 段

`docker-compose.yml` 中保留了 `build:` 段：

```yaml
build:
  context: .              # 以 compose 文件所在目录为构建上下文
  dockerfile: Dockerfile
image: novel-manager      # 构建出的镜像名
```

有了它，**`docker compose build` 和 `docker compose up -d --build` 才能正常工作**。
如果只有 `image:` 没有 `build:`，compose 会报 "no build context" 错误，
那时就只能手工执行 `docker build -t novel-manager .` 了。

### 容器启动流程

```
PID 1  docker-init（由 compose 的 init: true 提供，负责回收僵尸进程）
  └─ gunicorn -w 1 --threads 4 -b 0.0.0.0:5000 --timeout 120 novel_manager:app
```

- **PID 1 由 compose 的 `init: true` 提供**（即 Docker 内置的 docker-init）。
  Dockerfile 里因此**不再安装 tini、也没有 ENTRYPOINT** ——
  两者同时使用会造成两层 init 嵌套，且一旦 apt 装 tini 失败，
  ENTRYPOINT 指向不存在的路径会让容器无法启动。
  改动其一时请同步另一处。
- **worker 数固定为 1**：应用状态（扫描进度、缓存）保存在进程内存里，
  多 worker 会导致状态不一致。**不要为了提速把它改成 2 或更多。**
- **用 4 个线程处理并发**：足以应付家庭规模的访问量。
- `--timeout 120`：单次请求最长 120 秒（首次全量扫描可能较久）。

### 数据存储

**纯 JSON 文件，无数据库。** 全部在 `data/` 目录下：

| 文件 | 用途 |
|---|---|
| `config.json` | 全局配置 + **用户表**（含密码哈希、各人偏好） |
| `secret_key` | 会话签名密钥（权限 600） |
| `novel_cache.json` | 小说扫描缓存（较大，9MB+） |
| `tag_rules.json` | 标签规则 |
| `image_mapping.json` | 配图映射 |
| `emoji_mapping.json` | 表情映射 |
| `reading_records/` | **每用户一个阅读记录文件** |
| `scan.lock` | 扫描互斥锁（防止并发扫描） |
| `scheduler.lock` | 定时任务锁（单实例调度） |

> `reading_records/` 是多用户设计的体现：每个用户一个
> `records_<hash>.json`，各自独立，互不影响。

### 环境变量

| 变量 | 作用 | 必需 |
|---|---|---|
| `DOCKER_ENV=true` | **告诉程序运行在容器里，强制把 `novel_dir` 设为 `/novels`** | 是 |
| `TZ=Asia/Shanghai` | 时区，影响日志时间和定时任务 | 建议 |
| `PYTHONUNBUFFERED=1` | 日志实时输出（否则 `docker logs` 有延迟） | 建议 |
| `PYTHONDONTWRITEBYTECODE=1` | 不生成 `.pyc`（避免污染宿主机目录） | 建议 |
| `SECRET_KEY` | 会话签名密钥 | 可选 |
| `DEFAULT_ADMIN_PASSWORD` | 初始化管理员密码 | 首次建议 |

> **注意 `DOCKER_ENV=true`**：程序检测到它（或发现 `/.dockerenv` 存在）后，
> 会**忽略 config.json 里配置的 `novel_dir`，强制使用 `/novels`**。
> 所以想换书库目录，改的是 compose 里的挂载，不是 config.json。

### 配置项参考

`data/config.json` 的主要配置项（**本版特有或易混淆的已标注**）：

| 键 | 默认值 | 说明 |
|---|---|---|
| `novel_dir` | `/novels` | 书库路径，**被 `DOCKER_ENV=true` 强制覆盖** |
| `require_auth` | `true` | **本版特有**：是否要求登录 |
| `users` | `{}` | **本版特有**：用户表（含密码哈希与各人偏好） |
| `app_host` | `0.0.0.0` | 监听地址（桌面版是 `127.0.0.1`） |
| `app_port` | `5000` | 监听端口 |
| `per_page` | `100` | 列表每页条数 |
| `words_per_page` | `8000` | 阅读页每页字数 |
| `max_tags_display` | `3` | 列表页显示标签数 |
| `date_format` | `YYYY-MM-DD` | 日期格式 |
| `scan_interval_hours` | `0` | 定时扫描间隔（0 = 关闭） |
| `max_file_size_mb` | `100` | 超过此大小的文件跳过 |
| `auto_scan_on_start` | `true` | 启动时自动扫描 |
| `font_size` | `16` | 全局字号（用户可各自覆盖） |
| `line_height` | `1.8` | 行高 |
| `theme` | `auto` | 主题 |
| `indent_paragraph` | `true` | **本版特有**：段落首行缩进 |
| `paragraph_spacing` | `0.8` | **本版特有**：段间距 |
| `auto_save_progress` | `true` | 自动保存阅读进度 |
| `show_word_count` | `true` | 显示字数 |
| `auto_tag_enabled` | `true` | 启用自动打标签 |
| `enable_derived_tags` | `true` | 启用标签派生 |
| `custom_tags` | `[]` | 自定义标签 |
| `default_sort_by` | `title` | 默认排序字段 |
| `default_sort_order` | `asc` | 默认排序方向 |

> **关于两个分支的配置差异**
>
> 完整配置约 28 个键（含运行中新增的 `auto_backup_enabled`、
> `backup_interval_days`、`max_backups`、`debug_mode`）。
>
> 上表只列主要项。**桌面版专有的 `exclude_patterns`、`editor_path`
> 在本版不存在**；反过来 `require_auth`、`users`、`indent_paragraph`、
> `paragraph_spacing` 是**本版专有**。两个分支的配置格式并不完全通用。

---

## 日常操作

### 改了 Python 代码后

```bash
docker restart novel-manager

# 确认启动正常
docker logs -f novel-manager --tail 50
```

**不需要重建镜像** —— 因为源码是挂载进去的。

### 改了模板 / 静态文件（templates/ 或 static/）后

```bash
docker restart novel-manager
```

模板是每次请求时读取的，但静态文件有缓存，重启最稳妥。

### 改了依赖（requirements.txt）后

```bash
docker compose build
docker compose up -d
```

**必须重建镜像** —— 依赖装在镜像层里。

### 改了 docker-compose.yml 后

```bash
docker compose up -d
```

Compose 会自动检测配置变化并重建容器。

### 查看日志

```bash
# 实时跟踪
docker compose logs -f

# 最近 50 行
docker logs novel-manager --tail 50

# 容器内应用日志（更详细）
cat data/novel_manager.log
```

### 重启 / 停止 / 启动

```bash
docker restart novel-manager    # 重启
docker compose stop             # 停止
docker compose start            # 启动
docker compose down             # 停止并删除容器（数据保留）
```

### 一键重建（脚本）

```bash
./run-container.sh
```

该脚本会：停止旧容器 → 重建镜像 → 启动 → 显示状态和日志。

---

## 常见问题

### 容器起不来 / 一直重启

```bash
docker logs novel-manager --tail 100
```

常见原因：

- **端口 5000 被占用**：改 compose 里的 `ports` 映射，例如 `"5001:5000"`
- **挂载路径不存在**：确认 `.env` 里的 `NOVEL_DIR` 和 `APP_DIR` 都指向真实存在的目录
- **依赖装失败**：检查 NAS 能否访问 PyPI（可能需要配置镜像源）

### 访问页面提示"系统未配置任何用户"

登录页出现这个提示，说明 `users` 为空**且没有设置 `DEFAULT_ADMIN_PASSWORD`**。

**解决：** 在 `docker-compose.yml` 的 `environment` 里加上：

```yaml
- DEFAULT_ADMIN_PASSWORD=你的强密码
```

然后 `docker compose up -d`。程序会自动创建 `admin` 账号。

> 注意：这个初始化**只在用户表为空时执行**。如果已有账号，改这个变量不会有任何效果。

### 忘记密码 / 想加用户

用户管理在网页界面里（用管理员账号登录后进入设置页）。

密码用 **scrypt** 哈希存储，**无法从 `config.json` 反推明文**。
如果管理员密码彻底丢失，只能手工重置：

```bash
# 1. 备份
cp data/config.json data/config.json.bak

# 2. 编辑 data/config.json，删掉整个 "users" 字段（注意保持 JSON 合法）

# 3. 在 compose 里设置 DEFAULT_ADMIN_PASSWORD，然后重启
docker compose up -d
```

> 同时建议清理 `data/reading_records/` 下遗留的记录文件。
> **注意：这会丢失所有用户的账号和偏好设置**，请先备份。

### 扫描不出小说

1. 确认书库目录挂载正确：
   ```bash
   docker exec novel-manager ls /novels | head
   ```
2. 确认文件是 `.txt` / `.TXT`
3. 确认文件大小没超过 `max_file_size_mb`（当前配置是 50MB）
4. 查看 `data/novel_manager.log` 里的扫描记录

> 注意：NAS 版**没有** `exclude_patterns` 排除规则（那是桌面版的功能）。
> 想排除某些文件，只能把它们移出书库目录。

### 扫描很慢 / 卡住

- 首次全量扫描需读每个文件开头并计算内容指纹，与文件数成正比
- `scan.lock` 存在说明已有扫描在进行，不会重复启动
- 查看进度：`data/novel_manager.log`

### 想改书库目录

改 `docker-compose.yml` 的挂载，**不是** config.json：

```yaml
volumes:
  - "/你的/新书库路径:/novels:ro"
```

改完 `docker compose up -d`。

### 定时扫描

当前配置 `scan_interval_hours: 24.0`，即每 24 小时自动扫描一次。
设为 `0` 可关闭。由 `scheduler.lock` 保证只有一个调度器在跑。

### 数据怎么备份

**直接备份整个 `data/` 目录即可**，里面是全部状态：

```bash
tar czf novel-manager-data-$(date +%Y%m%d).tar.gz data/
```

建议排除体积大的缓存（可重建）：

```bash
tar czf backup.tar.gz --exclude='data/novel_cache.json*' data/
```

---

## 重建镜像 / 迁移

### 从零重建（换机器或误删镜像）

```bash
cd /path/to/novel-manager

# 1. 确认代码文件齐全
ls novel_manager.py templates/ static/ requirements.txt Dockerfile docker-compose.yml

# 2. 重建
docker compose build --no-cache
docker compose up -d

# 3. 验证
docker compose ps
docker logs novel-manager --tail 30
```

> `--no-cache` 确保完全重新构建，排除缓存干扰。
> 首次构建需下载 Python 基础镜像和依赖，视网络情况可能需要几分钟。

### 需要哪些文件才能重建

**必需：**

```
novel_manager.py        # 主程序（NAS 版，注意是下划线命名）
Dockerfile
docker-compose.yml
requirements.txt
templates/              # 11 个 HTML 模板（含登录页 login.html）
static/                 # 前端资源
```

**不需要（可重新生成）：**

```
data/                   # 运行时数据，但含用户表和阅读记录，迁移时应该带上
```

**可选：**

```
.dockerignore
run-container.sh
DOCKER-NOTES.md         # 构建与运维命令速查
config.example.json     # 首次启动的配置模板
```

### 迁移到新 NAS

1. 复制整个项目目录（**含 `data/`**，用户和阅读记录在里面）
2. 修改 `docker-compose.yml` 里的两处挂载路径为新机器的实际路径
3. `docker compose build && docker compose up -d`

> **注意**：`data/secret_key` 要一起带走，否则所有用户需要重新登录。

---

## 给 AI 助手的说明

如果你是 AI 助手，正在帮用户维护这个 Docker 部署，请注意以下要点：

**这个项目的特殊性：**

1. **源码不在镜像里，靠 volume 挂载。**
   镜像只含 Python 运行时和依赖。改代码后 `docker restart` 即可，
   **不要**习惯性地执行 `docker compose build`（除非改了 `requirements.txt`）。

2. **`novel_manager.py` 是 NAS 专用版本，与桌面版是不同分支。**
   桌面版是 `novel-manager.py`（连字符命名，约 5800 行，无鉴权）。
   本版是 `novel_manager.py`（下划线命名，6247 行，多用户带登录）。
   **两者不可互换**，修改前务必确认操作的是哪一份。

3. **文件命名有讲究**：本版必须是 `novel_manager.py`（下划线），
   因为 gunicorn 用 `novel_manager:app` 导入，Python 模块名不能含连字符。

4. **`DOCKER_ENV=true` 会强制覆盖 `novel_dir`**：
   程序检测到容器环境后，忽略 `config.json` 里的 `novel_dir`，强制用 `/novels`。
   要改书库位置，改 `docker-compose.yml` 的挂载。

**常见操作对应表：**

| 用户说 | 该执行 |
|---|---|
| 改了代码 | `docker restart novel-manager` |
| 改了模板/静态文件 | `docker restart novel-manager` |
| 改了 requirements.txt | `docker compose build && docker compose up -d` |
| 改了 docker-compose.yml | `docker compose up -d` |
| 看日志 | `docker logs novel-manager --tail 100` |
| 数据备份 | 打包 `data/` 目录（建议排除 `novel_cache.json*`） |

**注意事项：**

- 所有状态在 `data/` 下（纯 JSON，无数据库）。
- `data/config.json` 含**用户表和密码哈希**，是对外分享或截图时必须隐去的内容。
- `data/reading_records/` 每个用户一个文件。
- 容器内是 `gunicorn -w 1`（单 worker），因为应用状态在进程内存里，多 worker 会导致不一致。
  **不要建议用户提高 worker 数来"提速"。**
- **PID 1 由 compose 的 `init: true` 提供，Dockerfile 里没有 tini 也没有 ENTRYPOINT。**
  这两处是配套的：若要改回在 Dockerfile 里用 tini，必须同时移除 compose 的 `init: true`，
  否则会形成两层 init 嵌套。
- `run-container.sh` 的顺序是**先 build 成功、再 down 旧容器**，这是刻意的设计：
  若反过来（先 down 再 build），构建失败就会导致服务中断。
  修改该脚本时请保持这个顺序。
