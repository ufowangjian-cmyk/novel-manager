# 小说管理器 · Docker 版

把 NAS 上的 TXT 小说变成一个网页书库，**多用户、带登录鉴权**，局域网里家人各看各的，阅读进度互不干扰。

代码通过 volume 挂载运行，改完 `docker restart` 就生效，不需要重新构建镜像。

![Docker](https://img.shields.io/badge/Docker-Compose-blue)
![License](https://img.shields.io/badge/License-MIT-green)

<!-- 建议在这里插一张首页截图 -->

---

## 和桌面版的区别

| | Docker 版（本项目） | [桌面版](https://github.com/ufowangjian-cmyk/novel-manager-desktop) |
|---|---|---|
| 部署方式 | NAS / 服务器，容器常驻 | Windows 本机，双击启动 |
| 用户 | **多用户，独立账号与阅读进度** | 单人 |
| 登录鉴权 | **有** | 无 |
| 访问方式 | 局域网内任意设备（手机、平板、电视） | 仅本机 |
| 系统托盘 | 无 | 有 |
| 适用场景 | 全家共用、手机看小说 | 自己电脑上用 |

两边代码是独立分支，配置格式不完全通用。

---

## 特色

### 标点分区排版

中文小说里，不同类型的文字承担着不同的角色：对话、内心独白、系统提示、书名、章节标题。
普通阅读器只能给全部文字套一种字体，读起来是一整片。

这个工具把正文拆成 **9 个独立的排版位**，每一类可以单独指定字体、加粗、斜体：

| 排版位 | 对应内容 |
|---|---|
| 正文 | 普通叙述文字 |
| 标题 | 章节标题 |
| 双引号 | `「」` `""` |
| 单引号 | `''` `''` |
| 括号 | `（）` |
| 方头括号 | `【】` |
| 方括号 | `[]` `［］` |
| 空心括号 | `〖〗` |
| 书名号 | `《》` |

举个例子，可以这样配：

```
正文       霞鹜文楷等宽
双引号「」  仓耳今楷 + 常规
方头括号【】汉仪文黑 + 加粗     ← 系统提示一眼可辨
书名号《》  方正大标宋
标题       方正大标宋 + 加粗
```

对话、系统提示、书名用不同字体呈现，长文阅读时层次清晰，不容易串行。

字体放在 `static/fonts/`（woff2 格式），或用系统已安装的字体名。
**每个用户的排版偏好单独保存**，一家人用不同设置互不干扰。

### 多媒体关联

小说旁边的配图、视频、音频会被自动识别，不用手工登记。

**目录约定**：在书库目录下建与书同名的文件夹，后缀 `_images` 或 `_配图`：

```
书库/
├── 某本书.txt
├── 某本书_images/          ← 认这个
│   ├── 01.jpg
│   └── 02.jpg
└── 另一本书_配图/          ← 或这个
    ├── 第1章/
    │   ├── 01.jpg          ← 按章节分子目录也支持
    │   └── 02.jpg
    └── 第2章/
        └── 01.jpg
```

**识别方式**：递归扫描目录内容，按扩展名判断是图片、视频还是音频，
然后自动给这本书打上 `配图` / `视频` / `音频` 标签。

这几个标签是**文件系统存在性标记**，不参与关键词匹配 —— 书里恰好写到"配图"两个字，
不会让这本书被错误打标。目录挪走或删掉，标签也会自动消失。

**阅读页会内嵌显示配图**，点开有图片查看器（支持缩放、切换）。

**媒体检测页面**（`/media-detect`）用来查漏补缺，分为三类：

- 缺失：书里有引用但目录里找不到文件
- 多余：目录里有文件但书里没引用
- 重复：同一张图出现在多个位置

### 三级自动分章

不需要在 txt 里做任何标记，靠正则识别常见的中文章节标题格式，分三级：

| 级别 | 匹配示例 |
|---|---|
| 一级 | `第一卷` `第2册` `第三部` `上卷` |
| 二级 | `第一章` `第12篇` `楔子` `引子` `前言` `序言` `正文` `番外` `后记` `尾声` |
| 三级 | `第一节` `第5回` `第二幕` `第3目` |

数字同时支持阿拉伯数字和中文数字（`〇零一二三四五六七八九十百千万`）。
三级标题限制在 30 字以内，避免把正文句子误判成标题。

对 `楔子` `番外` 这类不带序号的裸词单独做了严格判定：整行只有这个词、或者后面接短标签才算标题，
像"正文第一行，这是小说开头的内容。"这种带句读的整句不会被误切。

分章结果会标出空章节（只有标题没有正文），方便发现文件本身的问题。

---

## 功能

**书库管理**

- 扫描挂载目录下的 `.txt` / `.TXT`，自动识别编码（UTF-8 / GBK / GB18030 / Big5 / UTF-16）
- 从文件头部解析书名、作者、站点、标签、简介、章节数、字数
- 按书名、作者、标签、站点、字数、日期排序筛选
- 增量扫描，定时自动重扫

**多用户**

- 每个账号独立密码（scrypt 哈希存储）、独立阅读进度、独立阅读偏好（字号、字体、主题、行距）
- 管理员可在网页里添加 / 删除用户、重置密码

**阅读**

- 网页内分章阅读，自动切分章节
- 进度自动保存，换设备也能接着看
- 字号、字体、行距、主题、段首缩进、标点字体分别可调

**标签**

- 关键词规则、别名映射、派生规则，支持导入导出

**其他**

- 缓存健康检查、缺失文件检查、运行日志

---

## 快速开始

### 1. 准备

- NAS 或服务器上已安装 Docker 与 Docker Compose
- 小说文件放在某个目录下（容器内是**只读**挂载，不会修改你的文件）

### 2. 获取代码

```bash
git clone https://github.com/ufowangjian-cmyk/novel-manager.git
cd novel-manager
```

### 3. 生成配置文件

```bash
cp docker-compose.example.yml docker-compose.yml
cp .env.example .env
```

编辑 `.env`，至少填两个路径和一个密码：

```bash
# 宿主机上的小说目录（绝对路径）
NOVEL_DIR=/volume1/books

# 本项目在宿主机上的绝对路径
APP_DIR=/volume1/docker/novel-manager

# 首次启动用，用来创建 admin 账号
DEFAULT_ADMIN_PASSWORD=你的强密码
```

> 容器内固定把书库挂到 `/novels`，想换目录改 `.env` 里的 `NOVEL_DIR`，
> **不是**改 `config.json`。

### 4. 启动

```bash
docker compose config    # 先确认变量解析正确
docker compose up -d --build
docker compose logs -f   # 看启动日志，Ctrl+C 退出查看
```

访问 `http://<你的NAS地址>:5000`，用 `admin` 和刚才设的密码登录。

> 登录成功后建议把 `.env` 里的 `DEFAULT_ADMIN_PASSWORD` 清空——
> 它只在用户表为空时生效，留着只是明文密码停在文件里。

---

## 首次登录

本程序**没有内置默认密码，也没有后门账号**。

当 `users` 为空时，程序只通过环境变量 `DEFAULT_ADMIN_PASSWORD` 初始化管理员。
没设这个变量，登录页会直接提示"系统未配置任何用户"——也就是说，不设密码你就进不去。

初始化完成后该变量即失效，改它不会再创建账号。

---

## 环境变量

| 变量 | 作用 | 必需 |
|---|---|---|
| `DOCKER_ENV=true` | 告诉程序运行在容器里，强制 `novel_dir` 为 `/novels` | 是 |
| `DEFAULT_ADMIN_PASSWORD` | 用户表为空时初始化管理员密码 | 首次需要 |
| `SECRET_KEY` | 会话签名密钥，留空则自动生成到 `data/secret_key` | 可选 |
| `TZ` | 时区，影响日志时间与定时任务 | 建议 `Asia/Shanghai` |
| `PYTHONUNBUFFERED=1` | 日志实时输出 | 建议 |

> `DOCKER_ENV=true` 会**覆盖** `config.json` 里的 `novel_dir`。
> 想换书库位置，改的是 compose 的挂载，不是配置文件。

---

## 配置项

`data/config.json` 的主要配置项，绝大多数也能在网页「设置」里改：

| 键 | 默认值 | 说明 |
|---|---|---|
| `require_auth` | `true` | 是否要求登录（关掉就没有任何保护了） |
| `users` | `{}` | 用户表，含密码哈希与各人偏好 |
| `app_port` | `5000` | 监听端口 |
| `per_page` | `100` | 列表每页条数 |
| `words_per_page` | `8000` | 阅读页每页字数 |
| `scan_interval_hours` | `24` | 定时扫描间隔，`0` 关闭 |
| `max_file_size_mb` | `50` | 超过此大小的文件跳过 |
| `auto_scan_on_start` | `false` | 启动时是否立即扫描 |
| `indent_paragraph` | `true` | 段落首行缩进 |
| `paragraph_spacing` | `0.8` | 段间距 |
| `auto_backup_enabled` | `true` | 自动备份 |
| `backup_interval_days` | `7` | 备份间隔 |
| `debug_mode` | `false` | DEBUG 级日志 |

---

## 关于素材

本仓库**不包含** `static/fonts/`、`static/images/`、`static/emojis/`：

- 中文字体多为商业授权（方正、汉仪、仓耳今楷、兰亭羲之黑、未来圆等），公开分发有版权风险
- 头图与表情包来源网络，授权不明

缺了不影响使用：程序照常启动、扫描、检索、阅读，只是排版回退到系统字体，头图和表情不显示。

想恢复原貌，把文件放进对应目录即可：

```
static/fonts/     .woff2 字体，文件名需与 templates/ 里的 font-family 对应
static/images/    header-bg-*.webp 头图
static/emojis/    表情 gif/png
```

可以自由分发的替代字体：**霞鹜文楷**（SIL OFL）、**HarmonyOS Sans**（华为免费商用）、**思源黑体/宋体**（SIL OFL）。

---

## 常见问题

**容器起不来 / 一直重启？**

```bash
docker logs novel-manager --tail 100
```

常见原因：端口被占用（改 compose 的 `ports`）、挂载路径不存在（检查 `.env`）、
依赖装不上（检查能否访问 PyPI）。

**登录页提示"系统未配置任何用户"？**
`users` 为空且没设 `DEFAULT_ADMIN_PASSWORD`。在环境变量里加上它然后重启，程序会自动创建 `admin` 账号。
这个初始化只在用户表为空时执行。

**忘记管理员密码？**
密码用 scrypt 哈希存储，无法反推。只能手工重置：备份 `data/config.json` → 删掉整个 `users` 字段 →
重新设置 `DEFAULT_ADMIN_PASSWORD` → 重启。注意这会丢失所有账号和偏好。

**扫描不出小说？**

```bash
docker exec novel-manager ls /novels | head
```

能看到文件才说明挂载正常。再确认文件是 `.txt`、大小没超过 `max_file_size_mb`。

**扫描很慢？**
首次全量扫描要读每个文件开头并计算指纹，与文件数量成正比。之后是增量。
`scan.lock` 存在说明已有扫描在进行，不会重复启动。

**数据怎么备份？**
打包整个 `data/` 目录即可，里面是全部状态。书籍缓存可以排除，扫描一次就能重建：

```bash
tar czf backup.tar.gz \
  --exclude='data/novel_cache.db*' \
  --exclude='data/novel_cache.json*' \
  data/
```

⚠️ 缓存现在是 SQLite 库（`novel_cache.db`），不像 JSON 那样能随便拷：如果要把库一起打包，
先 `docker stop novel-manager` 再 tar —— 运行中拷贝可能拿到未提交的事务。
只备份账号与阅读记录的话，上面排除掉缓存就够了，不需要停机。

**外网访问很慢、要卡几秒？**
容器同时监听 IPv4 和 IPv6。如果你的网络 IPv6 不通，客户端会在两条路线上竞争，
表现为"连上了但要等几秒"。这是客户端 Happy Eyeballs 行为，不是服务端故障。

**改了代码怎么生效？**

| 改了什么 | 做什么 |
|---|---|
| `.py` / `storage/` / 模板 / 静态文件 | `docker restart novel-manager` |
| `requirements.txt` | `docker compose build && docker compose up -d` |

代码是挂载进容器的，不在镜像里，所以绝大多数改动重启就够，不必重建。

---

## 目录结构

```
novel-manager/
├── novel_manager.py              # 主程序（注意是下划线）
├── migrate_cache.py              # 独立迁移脚本（novel_cache.json → SQLite）
├── storage/                      # 存储层：所有 SQL 只允许写在这里
│   └── cache_store.py
├── tests/                        # 自测脚本（存储层 / 应用级 / 线上探针）
├── Dockerfile
├── docker-compose.example.yml    # 配置模板，复制为 docker-compose.yml 后修改
├── .env.example                  # 环境变量模板
├── requirements.txt
├── run-container.sh              # 一键重建脚本
├── DOCKER-NOTES.md               # 常用命令速查
├── templates/                    # 网页模板
├── static/                       # CSS / JS / 素材
└── data/                         # 运行时数据（自动创建，不进版本库）
    └── novel_cache.db            # 书籍缓存（SQLite）
```

部署细节、容器内部结构、二次开发注意事项见 **[DEVELOPMENT.md](DEVELOPMENT.md)**。

---

## 相关项目

- **[novel-manager-desktop](https://github.com/ufowangjian-cmyk/novel-manager-desktop)** ——
  同一套功能的 Windows 桌面版，单人使用、带系统托盘、无需 Docker

---

## 许可

[MIT](LICENSE)
