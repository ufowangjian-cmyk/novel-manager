════════════════════════════════════════════════════════════════════════════
 小说管理器 (Docker 版) —— 构建与运维速查
════════════════════════════════════════════════════════════════════════════

 详细说明见同目录 README.md。本文件只放命令，照着敲即可。

 项目目录（换成你自己的实际路径）：
     /path/to/novel-manager

────────────────────────────────────────────────────────────────────────────
 〇、登入 NAS
────────────────────────────────────────────────────────────────────────────

 用 SSH 客户端（Windows 可用 PowerShell 自带的 ssh）登录：

     ssh 你的用户名@NAS的IP

 登入后先进入项目目录（后面所有命令都在这个目录下执行）：

     cd /path/to/novel-manager

 确认一下路径对不对，应该能看到这些文件：

     ls

     Dockerfile            docker-compose.yml    novel_manager.py
     requirements.txt      templates/            static/


────────────────────────────────────────────────────────────────────────────
 一、首次部署（或换机重建）
────────────────────────────────────────────────────────────────────────────

 一条命令搞定：构建镜像 + 启动容器

     docker compose up -d --build

 看启动日志（Ctrl+C 退出，不会停容器）：

     docker compose logs -f

 确认状态（正常应显示 Up / healthy）：

     docker compose ps

 然后浏览器访问：

     http://NAS的IP:5000


────────────────────────────────────────────────────────────────────────────
 二、日常：改了什么 → 敲什么
────────────────────────────────────────────────────────────────────────────

 ┌─ 只改了 Python 代码 (novel_manager.py) ────────────────────────────┐
 │                                                                    │
 │   docker restart novel-manager                                     │
 │                                                                    │
 │   ⚠️ 不需要重建镜像。源码是靠 volume 挂载进去的，不在镜像里。      │
 └────────────────────────────────────────────────────────────────────┘

 ┌─ 只改了模板或静态文件 (templates/ 或 static/) ─────────────────────┐
 │                                                                    │
 │   docker restart novel-manager                                     │
 │                                                                    │
 └────────────────────────────────────────────────────────────────────┘

 ┌─ 改了依赖 (requirements.txt) ──────────────────────────────────────┐
 │                                                                    │
 │   docker compose up -d --build                                     │
 │                                                                    │
 │   必须重建镜像，因为依赖是装在镜像层里的。                          │
 └────────────────────────────────────────────────────────────────────┘

 ┌─ 改了 docker-compose.yml ──────────────────────────────────────────┐
 │                                                                    │
 │   docker compose up -d                                             │
 │                                                                    │
 │   compose 会自动检测配置变化并重建容器。                            │
 └────────────────────────────────────────────────────────────────────┘

 ┌─ 改了 Dockerfile ──────────────────────────────────────────────────┐
 │                                                                    │
 │   docker compose up -d --build                                     │
 │                                                                    │
 └────────────────────────────────────────────────────────────────────┘


 记忆口诀：
     代码、模板  →  restart
     依赖、Dockerfile  →  --build
     纯 compose 配置  →  直接 up -d


────────────────────────────────────────────────────────────────────────────
 三、看日志 / 排查问题
────────────────────────────────────────────────────────────────────────────

 实时跟踪日志（最常用）：

     docker compose logs -f

 只看最近 100 行：

     docker logs novel-manager --tail 100

 应用自己的日志文件（更详细，含扫描进度）：

     tail -f data/novel_manager.log

 容器起不来时，先看这个：

     docker logs novel-manager --tail 100

 进容器里看看（排查挂载、依赖问题）：

     docker exec -it novel-manager bash

     进去后可以检查：
         ls /novels          # 书库有没有挂上
         ls /app             # 代码有没有挂上
         python -c "import flask, chardet, psutil; print('依赖 OK')"


────────────────────────────────────────────────────────────────────────────
 四、停止 / 启动 / 重启
────────────────────────────────────────────────────────────────────────────

     docker compose stop            # 停止（容器保留）
     docker compose start           # 启动已停止的容器
     docker restart novel-manager   # 重启
     docker compose down            # 停止并删除容器（数据保留在 data/）
     docker compose ps              # 查看状态


────────────────────────────────────────────────────────────────────────────
 五、彻底重建（出问题时用）
────────────────────────────────────────────────────────────────────────────

 ★ 最省事的方式：直接跑脚本

     ./run-container.sh

   它会依次做：构建 → 停旧容器 → 启动 → 等就绪 → 报结果。
   ✅ 构建失败时旧容器仍在运行，服务不会中断
   ✅ 结尾会真检查服务是否可用，成功才打印 ✅

 情况 A：手动分步做（想看清楚每步输出时）

     docker compose build            # 先构建（失败就停下，旧容器还在跑）
     docker compose down             # 构建成功后再停旧容器
     docker compose up -d            # 启动

 ⚠️ 不要反过来先 down 再 build：
    一旦 build 失败，就成了「旧容器已删、新容器没起」，服务直接中断。

 情况 B：强制重新构建，不用缓存

     docker compose build --no-cache
     docker compose up -d

 情况 C：全部推倒重来（数据仍在 data/ 里，不会丢）

     docker compose down
     docker rmi novel-manager
     docker compose up -d --build

 情况 D：检查最终生效的 compose 配置（排查配置写错时很有用）

     docker compose config


────────────────────────────────────────────────────────────────────────────
 六、数据备份
────────────────────────────────────────────────────────────────────────────

 全部状态都在 data/ 目录下。书籍缓存是 SQLite 库 novel_cache.db，
 其余（配置、阅读记录、标签规则）仍是 JSON。

 完整备份（缓存也带上 —— 需要先停机，见下方说明）：

     docker stop novel-manager
     tar czf ~/novel-data-$(date +%Y%m%d).tar.gz data/
     docker start novel-manager

 备份但排除大缓存（推荐，缓存扫描一次就能重建，不用停机）：

     tar czf ~/novel-data-$(date +%Y%m%d).tar.gz \
         --exclude='data/novel_cache.db*' \
         --exclude='data/novel_cache.json*' \
         data/

 ⚠️ novel_cache.db 是 SQLite 库，运行中直接 tar 可能拷到未提交的事务
    （得到损坏/回退的库）。要连缓存一起备份就先 stop 容器，或者干脆排除它。

 ⚠️ 注意：data/config.json 含用户表和密码哈希，
    data/secret_key 丢了会导致所有人重新登录。这两个务必带上。


────────────────────────────────────────────────────────────────────────────
 七、首次部署要设的两个环境变量
────────────────────────────────────────────────────────────────────────────

 编辑 docker-compose.yml，找到 environment 段，
 把这两行的注释（#）去掉并填上自己的值：

     - SECRET_KEY=一串随机字符串
     - DEFAULT_ADMIN_PASSWORD=你的强密码

 说明：
   DEFAULT_ADMIN_PASSWORD
       仅在用户表为空时用于初始化 admin 账号。
       ⚠️ 本程序没有内置默认密码，不设这个变量就无法登录！
       账号建好后建议再把这一行注释掉。

   SECRET_KEY
       会话签名密钥。不设也能跑（会自动生成到 data/secret_key），
       但显式设置更稳妥。

 改完后执行：

     docker compose up -d


────────────────────────────────────────────────────────────────────────────
 八、常见问题
────────────────────────────────────────────────────────────────────────────

 问题：登录页提示「系统未配置任何用户」
 原因：没有设置 DEFAULT_ADMIN_PASSWORD
 解决：见上面第七节，设好变量后 docker compose up -d

 问题：端口 5000 被占用
 解决：改 docker-compose.yml 的 ports 映射，例如 "5001:5000"
       然后 docker compose up -d，访问时用新端口

 问题：容器一直重启
 解决：docker logs novel-manager --tail 100 看具体报错

 问题：扫描不出小说
 解决：docker exec novel-manager ls /novels
       确认书库挂载正确、文件是 .txt/.TXT、大小没超过 max_file_size_mb

 问题：想换书库目录
 解决：改 docker-compose.yml 里 /novels 前面的宿主机路径，
       然后 docker compose up -d
       ⚠️ 不要改 data/config.json 里的 novel_dir，
          容器环境会强制覆盖它为 /novels

 问题：容器启动后立刻退出，日志没有明显报错
 排查：确认 compose 里的 init: true 还在。
       它负责提供 PID 1（回收僵尸进程）。
       对应地，Dockerfile 里已不再安装 tini、也没有 ENTRYPOINT，
       两者是配套的，不要只改一边。

 问题：改了 Dockerfile 或依赖后想生效
 解决：docker compose up -d --build
       （只改 novel_manager.py 的话 docker restart 就够）


────────────────────────────────────────────────────────────────────────────
 附：进程模型说明（改 Dockerfile / compose 前先看）
────────────────────────────────────────────────────────────────────────────

 容器的进程树：

     PID 1  docker-init（由 compose 的 init: true 提供）
       └─ gunicorn -w 1 --threads 4 -b 0.0.0.0:5000
            └─ 工作线程处理请求

 两个要点：

   init: true
       提供 PID 1 负责回收僵尸进程。
       注意：它和 Dockerfile 里的 tini 是**二选一**的关系，
       同时用会造成两层 init 嵌套。本项目选择用 init: true。

   -w 1（单 worker）
       应用的扫描进度、缓存等状态存在进程内存里，
       多 worker 会导致各进程状态不一致。
       并发靠 --threads 4 处理，家庭规模够用。
       ⚠️ 不要为了"提速"把 -w 改成 2 或更多。


────────────────────────────────────────────────────────────────────────────
 九、命令速查表
────────────────────────────────────────────────────────────────────────────

     cd /path/to/novel-manager             进入项目目录
     docker compose ps                     看状态
     docker compose logs -f                看日志
     docker compose up -d                  启动（配置改动后）
     docker compose up -d --build          重建镜像并启动
     docker restart novel-manager          改代码后重启
     docker compose down                   停止并删除容器
     docker compose config                 检查生效的配置
     docker exec -it novel-manager bash    进容器

════════════════════════════════════════════════════════════════════════════
