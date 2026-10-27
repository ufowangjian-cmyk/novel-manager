import sys
import os
import json
import html
import secrets
import traceback
import gzip
import hashlib
import time
import threading
import contextlib
import re
import random
import chardet
import subprocess
import gc
import ctypes
import urllib.parse
from datetime import datetime, timedelta
from functools import wraps
from collections import OrderedDict
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, send_file
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash

# WebP MIME 注册：slim 基础镜像的 mimetypes 不认识 .webp，Flask 会把静态
# webp 下发成 application/octet-stream（浏览器靠嗅猜能显示，但严格代理/
# CDN/部分下载场景会出问题）。启动时补注册，一次生效。
import mimetypes
mimetypes.add_type('image/webp', '.webp')
# 字体 MIME：slim 镜像的 mimetypes 也不认识 .woff2，会把字体下发成
# application/octet-stream（Lucky 日志实测 8.6MB 霞鹜文楷即如此）。
mimetypes.add_type('font/woff2', '.woff2')
mimetypes.add_type('font/woff', '.woff')
mimetypes.add_type('font/ttf', '.ttf')
mimetypes.add_type('font/otf', '.otf')

try:  # Linux 文件锁
    import fcntl
except ImportError:  # Windows 等平台降级为进程内线程锁
    fcntl = None

# ===================== 日志系统配置 =====================
import logging

# 在模块加载时从环境变量读取 debug 模式
debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'

def setup_logging():
    """配置统一日志系统 - 仅输出到控制台"""
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 🔥 只保留控制台输出，不写入文件
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.DEBUG if debug_mode else logging.INFO)

    logger = logging.getLogger('novel_manager')
    logger.setLevel(logging.DEBUG)
    logger.addHandler(console_handler)

    return logger

logger = setup_logging()

# ===================== 缓存配置 =====================
MAX_TAG_PARSE_CACHE = 500
MAX_CHAPTER_CACHE = 40

# 配图文件夹检查缓存（用于 API 请求，非扫描）
_image_check_cache = OrderedDict()

# 配图文件夹「路径解析」缓存：filename -> 文件夹路径或 None。
# 与 _image_check_cache 不同，这里缓存的是「书名 → *_images/_配图 目录」的解析结果，
# 供扫描与媒体检测复用，避免同一文件在一轮扫描内被反复 os.path.isdir（NAS 上是网络 stat）。
# 每次扫描开始 / 目录变更后清空（见 _scan_core 与 invalidate 处）。
_image_folder_cache = {}

image_cache = OrderedDict()

# 全局缓存变量
_emoji_mapping_cache = None
_image_mapping_cache = None

# ===================== 数据目录配置 =====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
    print(f"✅ 已创建数据目录: {DATA_DIR}")

CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
TAG_RULES_FILE = os.path.join(DATA_DIR, 'tag_rules.json')
# 书籍缓存已迁移到 SQLite（见 storage/cache_store.py）：
#   CACHE_FILE     仅作为「迁移源」存在，迁移成功后会被改名成 .bak，不再读写
#   CACHE_DB_FILE  真正的缓存存储
CACHE_FILE = os.path.join(DATA_DIR, 'novel_cache.json')
CACHE_DB_FILE = os.path.join(DATA_DIR, 'novel_cache.db')
SECRET_KEY_FILE = os.path.join(DATA_DIR, 'secret_key')
SCAN_LOCK_FILE = os.path.join(DATA_DIR, 'scan.lock')
EMOJI_MAPPING_FILE = os.path.join(DATA_DIR, 'emoji_mapping.json')
IMAGE_MAPPING_FILE = os.path.join(DATA_DIR, 'image_mapping.json')

# ===================== 项目内模块 =====================
# 放在这里而不是文件顶部：要先算出 BASE_DIR 并确保它在 sys.path 上
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
from storage import cache_store
from app import create_app

# ===================== 通用 JSON 文件操作 =====================
# 所有写盘操作共用一把进程内写锁 + 原子替换，避免并发写/崩溃写坏 JSON
_write_lock = threading.RLock()

def load_json_file(file_path, default=None):
    """通用 JSON 文件加载（utf-8-sig 兼容带 BOM 的文件）"""
    if default is None:
        default = {}
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载文件失败 {file_path}: {e}")
            return default
    return default

#===================== 通用 JSON 文件保存（原子写）=====================
def save_json_file(file_path, data, indent=2):
    """通用 JSON 文件保存：先写临时文件再原子替换，避免半截文件。

    indent=None 时用紧凑格式（无空格、无换行）——缓存这类大文件能省 40% 体积和一半写出时间，
    配置文件仍用 indent=2 保持人类可读。
    """
    tmp_path = f"{file_path}.tmp.{os.getpid()}.{threading.get_ident()}"
    try:
        with _write_lock:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                if indent is None:
                    json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
                else:
                    json.dump(data, f, ensure_ascii=False, indent=indent)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, file_path)
        return True
    except Exception as e:
        logger.error(f"保存文件失败 {file_path}: {e}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False

@contextlib.contextmanager
def file_lock(lock_path, blocking=True):
    """跨进程文件锁；fcntl 不可用时退化为进程内写锁"""
    if fcntl is None:
        with _write_lock:
            yield
        return
    lock_f = open(lock_path, 'a+')
    try:
        flags = fcntl.LOCK_EX if blocking else (fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(lock_f, flags)
        yield
    finally:
        try:
            fcntl.flock(lock_f, fcntl.LOCK_UN)
        finally:
            lock_f.close()

# ===================== 配置加载 =====================
def load_config():
    """加载配置文件"""
    default_config = {
        "novel_dir": "/novels",
        "require_auth": True,
        "per_page": 100,
        "words_per_page": 8000,
        "max_tags_display": 3,
        "date_format": "YYYY-MM-DD",
        "scan_interval_hours": 0,
        "max_file_size_mb": 100,
        "auto_scan_on_start": True,
        "font_size": 16,
        "line_height": 1.8,
        "theme": "auto",
        "auto_save_progress": True,
        "show_word_count": True,
        "auto_tag_enabled": True,
        "enable_derived_tags": True,
        "custom_tags": [],
        # 段落排版（原先只在保存白名单里、代码从未读取，属半成品；
        # 这里补上默认值并在阅读页真正生效）
        "indent_paragraph": True,
        "paragraph_spacing": 0.8,
        "app_host": "0.0.0.0",
        "app_port": 5000,
        "default_sort_by": "title",
        "default_sort_order": "asc",
        # 用户表：{用户key: {role, user_id, password_hash, preferences}}
        # 用户 key 是随机不可猜的标识（u_xxx），不再用明文密码当 key
        "users": {}
    }

    config = load_json_file(CONFIG_FILE, default_config)

    for key in default_config:
        if key not in config or config[key] == "" or config[key] is None:
            config[key] = default_config[key]
            print(f"⚠️ 配置 {key} 缺失或为空，使用默认值")

    # 段落排版是后补的功能：早期版本的白名单里就有这两个键，但没有 UI 也没人读，
    # 有些 config.json 里残留着无意义的值（如 paragraph_spacing: true）。
    # 这里做一次类型校正，避免 True/字符串把 CSS 变量写成非法值。
    if not isinstance(config.get('indent_paragraph'), bool):
        config['indent_paragraph'] = bool(default_config['indent_paragraph'])
        print("⚠️ indent_paragraph 类型异常，已重置为默认值")
    try:
        spacing = float(config.get('paragraph_spacing'))
        # 允许 0（段落紧贴），但不允许负数或大得离谱的值
        config['paragraph_spacing'] = min(max(spacing, 0.0), 3.0)
    except (TypeError, ValueError):
        config['paragraph_spacing'] = default_config['paragraph_spacing']
        print("⚠️ paragraph_spacing 类型异常，已重置为默认值")

    if os.path.exists('/.dockerenv') or os.environ.get('DOCKER_ENV') == 'true':
        config['novel_dir'] = '/novels'
        print("🐳 Docker 环境检测到，强制设置 novel_dir = /novels")

    return config

CONFIG = load_config()

# 绝不通过 API 返回的配置项
SENSITIVE_CONFIG_KEYS = {'users'}

# 允许通过 /config/save 修改的配置项白名单
CONFIG_SAVE_WHITELIST = {
    'novel_dir', 'require_auth', 'per_page', 'words_per_page', 'max_tags_display',
    'date_format', 'scan_interval_hours', 'max_file_size_mb', 'auto_scan_on_start',
    'font_size', 'line_height', 'theme', 'auto_save_progress', 'show_word_count',
    'auto_tag_enabled', 'enable_derived_tags', 'custom_tags',
    'default_sort_by', 'default_sort_order',
    'indent_paragraph', 'paragraph_spacing',
    # 阅读默认值：字体设置（管理员设定的「新用户初始字体/排版」，经 resolve_reader_prefs 作为第一层默认值）
    'font_family', 'title_font_family', 'double_quote_font_family',
    'single_quote_font_family', 'bracket_font_family', 'square_bracket_font_family',
    'square_bracket_1_font_family', 'hollow_bracket_font_family', 'book_font_family',
    'body_bold', 'body_italic', 'title_bold', 'title_italic',
    'double_quote_bold', 'double_quote_italic', 'single_quote_bold', 'single_quote_italic',
    'bracket_bold', 'bracket_italic', 'square_bracket_bold', 'square_bracket_italic',
    'square_bracket_1_bold', 'square_bracket_1_italic', 'hollow_bracket_bold',
    'hollow_bracket_italic', 'book_bold', 'book_italic',
}

def load_or_create_secret_key():
    """SECRET_KEY：优先环境变量，其次 data/secret_key 文件，最后随机生成"""
    env_key = (os.environ.get('SECRET_KEY') or '').strip()
    if env_key:
        return env_key
    try:
        if os.path.exists(SECRET_KEY_FILE):
            with open(SECRET_KEY_FILE, 'r', encoding='utf-8') as f:
                key = f.read().strip()
            if key:
                return key
        key = secrets.token_hex(32)
        with open(SECRET_KEY_FILE, 'w', encoding='utf-8') as f:
            f.write(key)
        try:
            os.chmod(SECRET_KEY_FILE, 0o600)
        except OSError:
            pass
        logger.warning("⚠️ 未设置 SECRET_KEY 环境变量，已生成随机密钥并保存到 %s", SECRET_KEY_FILE)
        return key
    except Exception as e:
        logger.error(f"读取/生成 secret_key 失败，使用临时密钥（重启后需重新登录）: {e}")
        return secrets.token_hex(32)

# ===== 初始化 Flask 应用 =====
# 实例改由 app/create_app() 创建（阶段1：工厂只建实例，路由仍在本文件用
# @app.route 注册）。root_path 显式指向本文件所在目录，保证 templates/ 与
# static/ 的解析结果和原来 Flask(__name__) 完全一致。
app = create_app(root_path=BASE_DIR)
app.secret_key = load_or_create_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=(os.environ.get('SESSION_COOKIE_SECURE', '0') == '1'),
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    SEND_FILE_MAX_AGE_DEFAULT=timedelta(days=30),
)


@app.after_request
def add_static_cache_headers(response):
    """给静态资源加长缓存。

    Flask 默认给 static 资源发 `Cache-Control: no-cache`，意思是
    「每次都回服务器确认一下是否变了」—— 于是 CSS/JS/图片在弱网下
    每跳一次页面就重下一遍，50 张头部背景图共 11.7MB 全浪费在重复下载上。

    改成 max-age=30 天后，浏览器第一次下载后直接从本地磁盘读，不再请求网络。
    更新静态文件时靠版本号（见下）让浏览器重新拉取。

    安全前提：已确认 /static/images/*.webp 无需登录即可访问（HTTP 200），
    所以长缓存不会泄露任何受保护内容。
    """
    if response.mimetype in ('text/html', 'application/json'):
        # 页面与接口始终回源，避免改动不生效
        response.headers['Cache-Control'] = 'no-cache'
        return response

    # static 文件名不带 hash，改版后需要刷新缓存。
    # 用 mtime 作为附加标识，文件一变浏览器就会重新下载。
    # 注意按完整相对路径取文件——早先按 basename 取，不同子目录下同名文件
    # （如 js/common.js 与 js/reader/common.js）会取到错文件的 mtime。
    try:
        path = request.path
        if path == '/service-worker.js':
            rel = 'service-worker.js'  # SW 路由在根路径，文件在 static 下
        elif path.startswith('/static/'):
            rel = urllib.parse.unquote(path[len('/static/'):])
        else:
            rel = None
        if rel:
            static_dir = os.path.realpath(app.static_folder or os.path.join(BASE_DIR, 'static'))
            full = os.path.realpath(os.path.join(static_dir, rel))
            if os.path.isfile(full):
                mtime = int(os.path.getmtime(full))
                response.headers.setdefault('ETag', f'W/"{mtime:x}"')
    except OSError:
        pass

    # 不覆盖响应自己声明的缓存策略：典型如 /service-worker.js 路由设的
    # no-cache——SW 文件必须每次可重新获取，缓存 30 天会导致新版 SW
    # 永远下不达用户（SW 更新通道被断）。
    if 'Cache-Control' not in response.headers:
        response.headers['Cache-Control'] = 'public, max-age=2592000'
    return response


# 文本响应 gzip 压缩。gunicorn/Flask 默认原样吐字节，手机流量下
# CSS/JS/HTML 要多传 3-4 倍流量。只压文本类（woff2/webp 等已压缩内容跳过），
# 小响应不压（收益覆盖不了开销），压不动的放弃。
GZIP_MIMETYPES = ('text/', 'application/javascript', 'application/json',
                  'application/xml', 'application/xhtml+xml', 'image/svg+xml')


def _read_static_file():
    """按请求路径读 static 文件原文（gzip 兜底用）。

    send_file/send_from_directory 的响应是 direct_passthrough 流式对象，
    get_data() 拿不到 body。文件刚被 send_file 读过，在 OS 页缓存里，
    重复读几乎零成本。带路径穿越防护。
    """
    path = request.path
    if path == '/service-worker.js':
        rel = 'service-worker.js'  # SW 路由在根路径，文件在 static 下
    elif path.startswith('/static/'):
        rel = urllib.parse.unquote(path[len('/static/'):])
    else:
        return None
    static_dir = os.path.realpath(app.static_folder or os.path.join(BASE_DIR, 'static'))
    full = os.path.realpath(os.path.join(static_dir, rel))
    if not (full == static_dir or full.startswith(static_dir + os.sep)):
        return None
    if not os.path.isfile(full):
        return None
    try:
        with open(full, 'rb') as f:
            return f.read()
    except OSError:
        return None


@app.after_request
def gzip_response(response):
    if response.status_code >= 300:
        return response
    accept = request.headers.get('Accept-Encoding', '')
    if 'gzip' not in accept.lower():
        return response
    if response.headers.get('Content-Encoding'):
        return response
    mimetype = (response.mimetype or '').lower()
    if not mimetype.startswith(GZIP_MIMETYPES):
        return response
    try:
        body = response.get_data()
    except (RuntimeError, TypeError):
        body = None  # send_file 的流式响应拿不到 body，走下面的读盘兜底
    if not body and response.direct_passthrough:
        body = _read_static_file()
    if not body or len(body) < 512:
        return response
    try:
        compressed = gzip.compress(body, compresslevel=6)
    except Exception:
        return response
    if len(compressed) >= len(body):
        return response
    response.set_data(compressed)
    response.headers['Content-Encoding'] = 'gzip'
    response.headers['Content-Length'] = str(len(compressed))
    response.headers['Vary'] = 'Accept-Encoding'
    return response

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)


# ==================== 静态资源 URL 版本化 ====================
def versioned_url_for(endpoint, **values):
    """Jinja 模板里的 url_for：endpoint='static' 时追加 ?v=<mtime>。

    与 add_static_cache_headers 的 30 天 max-age 配套：
    文件没动 → URL 不变 → 浏览器命中本地缓存，零请求；
    文件一改 → mtime 变 → URL 变 → 浏览器当成新资源强制拉取。

    缺了这一层的后果：30 天缓存期内推送的 JS/CSS 修复，用户不硬刷新
    就永远看不到（今天修配图 bug 时赌对了用户会刷新，不能总赌）。
    仅影响模板渲染，Python 内部调用 flask.url_for 不受影响。
    """
    if endpoint == 'static' and values.get('filename'):
        try:
            full = os.path.join(app.static_folder or os.path.join(BASE_DIR, 'static'),
                                str(values['filename']))
            values['v'] = int(os.path.getmtime(full))
        except OSError:
            pass
    return url_for(endpoint, **values)


app.jinja_env.globals['url_for'] = versioned_url_for

NOVEL_DIR = CONFIG.get('novel_dir', '/novels')
PER_PAGE = CONFIG.get('per_page', 100)
WORDS_PER_PAGE = CONFIG.get('words_per_page', 8000)

# ==================== 用户阅读记录目录 ====================
READING_RECORD_DIR = os.path.join(DATA_DIR, 'reading_records')
if not os.path.exists(READING_RECORD_DIR):
    os.makedirs(READING_RECORD_DIR)
    print(f"✅ 已创建用户阅读记录目录: {READING_RECORD_DIR}")

# ==================== 用户模型（密码哈希 + 不可猜的用户 key）====================
USER_KEY_PREFIX = 'u_'

def get_user_record_file(user_key):
    """根据用户 key 获取对应的阅读记录文件路径"""
    user_hash = hashlib.md5(str(user_key).encode()).hexdigest()[:16]
    return os.path.join(READING_RECORD_DIR, f'records_{user_hash}.json')

def is_legacy_user_key(key):
    """旧版本用明文密码当 key，迁移时识别"""
    return not str(key).startswith(USER_KEY_PREFIX)

def new_user_key():
    return USER_KEY_PREFIX + secrets.token_hex(8)

def normalize_user_info(info, fallback_id):
    """兼容旧格式：值可能是纯角色字符串"""
    if isinstance(info, dict):
        out = dict(info)
    else:
        out = {'role': info if info else 'user'}
    out.setdefault('role', 'user')
    out.setdefault('user_id', fallback_id)
    return out


# ==================== 用户头像（Lucide 线稿 + 配色） ====================
# 不占图片资源：白底圆 + 彩色描边 + 一个 Lucide 线稿图标。
# 用项目已有的图标库（static/icons/*.svg → static/icons.svg，由 _sprite_build.py 打包），
# 所以头像和全站图标的描边粗细、圆角风格完全一致。
# 每个用户存一个 seed，图标与描边色都由 seed 确定性推出 —— 稳定、可复现。
AVATAR_ICONS = (
    'cat', 'dog', 'rabbit', 'bird', 'fish', 'turtle', 'squirrel', 'bug',
    'leaf', 'flower', 'sprout', 'tree-deciduous', 'clover',
    'moon', 'star', 'sun', 'snowflake', 'flame',
    'apple', 'cherry', 'coffee',
    'rocket', 'gift', 'heart',
)
AVATAR_COLORS = (
    '#7BA05B', '#5F8D6B', '#6B8E9F', '#8C7AA8',
    '#C08552', '#B5837A', '#8FA05B', '#A5806B',
)


def avatar_look(seed):
    """seed -> (Lucide 图标名, 描边色)。同一个 seed 永远得到同一个头像。"""
    try:
        seed = abs(int(seed))
    except (TypeError, ValueError):
        seed = 0
    icon_name = AVATAR_ICONS[seed % len(AVATAR_ICONS)]
    color = AVATAR_COLORS[(seed // len(AVATAR_ICONS)) % len(AVATAR_COLORS)]
    return icon_name, color


def ensure_avatar_seed(user_key, persist=True):
    """取用户的头像 seed；没有就随机生成一个并写回 config.json（老用户无感迁移）。"""
    users = CONFIG.get('users', {}) or {}
    info = users.get(user_key)
    if not isinstance(info, dict):
        return 0

    avatar = info.get('avatar')
    seed = avatar.get('seed') if isinstance(avatar, dict) else None
    if isinstance(seed, int) and seed > 0:
        return seed

    seed = random.randint(1, 999999)
    info['avatar'] = {'seed': seed}
    users[user_key] = info
    CONFIG['users'] = users
    if persist:
        try:
            save_json_file(CONFIG_FILE, CONFIG)
            logger.info(
                f"🎲 生成头像 seed={seed} 给用户「{info.get('user_id') or user_key}」"
            )
        except Exception as e:
            # 存不下来也不影响本次显示，下次访问会再试
            logger.warning(f"头像 seed 保存失败：{e}")
    return seed


def hash_password(password):
    return generate_password_hash(password)

def verify_user_password(password, user_info):
    """校验密码：优先 password_hash，兼容尚未迁移的明文"""
    if not password or not isinstance(user_info, dict):
        return False
    stored = user_info.get('password_hash')
    if stored:
        try:
            return check_password_hash(stored, password)
        except Exception:
            return False
    return False

def find_user_by_password(password):
    """按密码查找用户，返回 (user_key, user_info)"""
    if not password:
        return None, None
    users = CONFIG.get('users', {}) or {}
    for key, info in users.items():
        if not isinstance(info, dict):
            info = normalize_user_info(info, key)
            users[key] = info
        if verify_user_password(password, info):
            return key, info
    return None, None

def password_used_by_others(password, exclude_key=None):
    """检查密码是否已被其它用户占用（哈希不可逆，只能逐个校验）"""
    users = CONFIG.get('users', {}) or {}
    for key, info in users.items():
        if key == exclude_key:
            continue
        if verify_user_password(password, info):
            return True
    return False

def migrate_record_file(old_key, new_key):
    """把阅读记录文件从旧 key(md5) 迁移到新 key，避免升级后历史丢失"""
    if old_key == new_key:
        return
    old_file = get_user_record_file(old_key)
    new_file = get_user_record_file(new_key)
    if not os.path.exists(old_file):
        return
    try:
        old_records = load_json_file(old_file, {}) or {}
        if os.path.exists(new_file):
            merged = load_json_file(new_file, {}) or {}
            for k, v in old_records.items():
                cur = merged.get(k)
                if not cur or (isinstance(v, dict) and v.get('timestamp', 0) > cur.get('timestamp', 0)):
                    merged[k] = v
            save_json_file(new_file, merged)
        else:
            save_json_file(new_file, old_records)
        os.remove(old_file)
        logger.info(f"📦 已迁移阅读记录: {old_key[:4]}*** -> {new_key}")
    except Exception as e:
        logger.error(f"迁移阅读记录失败 {old_key[:4]}***: {e}")

def migrate_legacy_users(config):
    """把「明文密码当 key」的旧用户表迁移为「随机 key + password_hash」"""
    users = config.get('users') or {}
    if not users:
        return config, False

    migrated = False
    new_users = {}
    for key, info in users.items():
        if not is_legacy_user_key(key):
            new_users[key] = normalize_user_info(info, key)
            continue

        old_password = key
        new_key = new_user_key()
        while new_key in new_users:  # 极小概率碰撞
            new_key = new_user_key()
        entry = normalize_user_info(info, old_password)
        entry['password_hash'] = hash_password(old_password)
        new_users[new_key] = entry
        migrate_record_file(old_password, new_key)
        migrated = True
        logger.info(f"🔐 用户「{entry.get('user_id')}」已升级为哈希密码存储")

    if migrated:
        try:
            if os.path.exists(CONFIG_FILE):
                backup = f"{CONFIG_FILE}.bak-legacy"
                if not os.path.exists(backup):
                    with open(CONFIG_FILE, 'rb') as src, open(backup, 'wb') as dst:
                        dst.write(src.read())
                    logger.info(f"已备份旧配置: {backup}")
        except Exception as e:
            logger.warning(f"备份旧配置失败: {e}")
        config['users'] = new_users
        if not any(u.get('role') == 'admin' for u in new_users.values()):
            first_key = next(iter(new_users))
            new_users[first_key]['role'] = 'admin'
            logger.warning("⚠️ 迁移后没有管理员，已将第一个用户提升为管理员")
    return config, migrated

CONFIG, _users_migrated = migrate_legacy_users(CONFIG)
if _users_migrated:
    save_json_file(CONFIG_FILE, CONFIG)
    print("✅ 用户表已升级为「随机 key + 密码哈希」格式（旧配置已备份为 config.json.bak-legacy）")

def current_user_key():
    """当前会话的用户 key（不再在 cookie 里保存明文密码）"""
    return session.get('user_key')

def get_current_user_info():
    """返回 (user_key, user_info)，用户不存在时返回 (None, None)"""
    key = current_user_key()
    if not key:
        return None, None
    users = CONFIG.get('users', {}) or {}
    info = users.get(key)
    if not isinstance(info, dict):
        return None, None
    return key, info

# ===================== 阅读偏好（全局默认 + 用户覆盖） =====================
# 全局 config.json 里的这几项充当「新用户默认值」；
# 用户在自己的配置页/阅读页改过之后，以 users[key].preferences 为准。
READER_PREF_DEFAULTS = {
    'font_size': 16,
    'font_family': 'system-ui',
    'line_height': 1.8,
    'theme': 'auto',
    'auto_save_progress': True,
    'show_word_count': True,
    'indent_paragraph': True,
    'paragraph_spacing': 0.8,
    # —— 列表与显示（2026-10-19 起支持个人覆盖）——
    # 这几个原先是纯全局配置，普通用户改不了自己的排序/分页习惯。
    # 现在纳入偏好体系：CONFIG 里的值等于「新用户默认值」，用户在
    # 「我的阅读偏好」里设过的项覆盖它。index() / context_processor
    # 通过 resolve_reader_prefs() 取值，不再直接读 CONFIG。
    'default_sort_by': 'title',
    'default_sort_order': 'asc',
    'per_page': 100,
    'words_per_page': 8000,
    'max_tags_display': 3,
    'date_format': 'YYYY-MM-DD',
    # 阅读页背景主题（仅作用于阅读页，与全站明暗 theme 相互独立）
    'reader_theme': 'default',
    # 按住拖动翻页（抓手手势）：默认开启，可在阅读设置里关闭
    'drag_scroll': True,
    # 圈选文字（与按住拖动翻页互斥）：默认关闭，开启后允许自由选词/复制
    'text_select': False,
    # —— 分元素字体：标题 + reader-core 全部高亮类型各自可配，正文复用 font_family ——
    'title_font_family': "'Segoe UI', '微软雅黑', sans-serif",
    'double_quote_font_family': '',     # 空 = 跟随正文（双引号 "「」）
    'single_quote_font_family': '',     # 空 = 跟随正文（单引号 '『』）
    'bracket_font_family': '',          # 空 = 跟随正文（圆括号 （）()）
    'square_bracket_font_family': '',   # 空 = 跟随正文（方头括号 【】）
    'square_bracket_1_font_family': '', # 空 = 跟随正文（方括号 [] ［］）
    'hollow_bracket_font_family': '',   # 空 = 跟随正文（空心括号 〖〗）
    'book_font_family': '',             # 空 = 跟随正文（书名号 《》）
    # —— 分元素 加粗/斜体：默认跟随各作用域 CSS 现状（粗的保持粗），避免升级后改变外观 ——
    'body_bold': False,            'body_italic': False,
    'title_bold': True,            'title_italic': False,          # 标题默认就粗（保持）
    'double_quote_bold': False,    'double_quote_italic': False,
    'single_quote_bold': False,    'single_quote_italic': False,
    'bracket_bold': False,         'bracket_italic': False,        # 圆括号默认 normal
    'square_bracket_bold': True,   'square_bracket_italic': False,  # 方头括号默认粗
    'square_bracket_1_bold': False,'square_bracket_1_italic': False,# 方括号默认 normal
    'hollow_bracket_bold': True,   'hollow_bracket_italic': False,  # 空心括号默认 semibold→粗
    'book_bold': True,             'book_italic': False,           # 书名号默认 medium→粗
}

def resolve_reader_prefs(user_info=None):
    """把全局默认值与当前用户的覆盖值合并，返回最终生效的阅读偏好。

    user_info 为 None 时自动取当前登录用户；未登录则只返回全局默认。
    """
    prefs = {}
    for key, hard_default in READER_PREF_DEFAULTS.items():
        # 第一层：全局配置（管理员设定的新用户默认值）
        prefs[key] = CONFIG.get(key, hard_default)

    if user_info is None:
        _, user_info = get_current_user_info()

    if isinstance(user_info, dict):
        overrides = user_info.get('preferences') or {}
        if isinstance(overrides, dict):
            for key in READER_PREF_DEFAULTS:
                value = overrides.get(key)
                # 只接受有意义的覆盖值；空字符串/None 视为「未设置」
                if value is not None and value != '':
                    prefs[key] = value

    return prefs


# ===================== 首页页码记忆（Docker 版）=====================
# 记住用户最后一次停留的书架页码，下次打开首页直接落在那儿。
# 只记「纯浏览」状态：带筛选/搜索的请求既不记录也不恢复。
# 存在 users[key].preferences 里，跟其他偏好一起走 api_users_edit 的保留逻辑。
# 增删书会让总页数变化，所以同时记下当时的页数，恢复时按比例折算 ——
# 只记页码的话，删掉一批书后可能直接落到最后一页。
HOME_PAGE_KEY = 'home_page'
HOME_PAGE_PAGES_KEY = 'home_page_pages'


def get_saved_home_page(user_info):
    """返回 (页码, 记录时的总页数)。第 1 页视为「没记」，返回 (None, None)。"""
    if not isinstance(user_info, dict):
        return None, None
    prefs = user_info.get('preferences')
    if not isinstance(prefs, dict):
        return None, None

    try:
        page = int(prefs.get(HOME_PAGE_KEY))
    except (TypeError, ValueError):
        return None, None
    if page <= 1:
        return None, None

    try:
        pages = int(prefs.get(HOME_PAGE_PAGES_KEY))
    except (TypeError, ValueError):
        pages = None
    if pages is not None and pages <= 0:
        pages = None
    return page, pages


def resolve_home_page(page_arg, has_filter, user_info, total_pages):
    """决定这次显示第几页。

    - 显式带 page=  → 直接用它（夹到有效范围）
    - 没带 page 且没筛选 → 用记忆页，按「当时总页数 → 现在总页数」比例折算
    - 带筛选/搜索  → 一律第 1 页，不参与记忆
    """
    total_pages = max(1, int(total_pages or 1))

    if page_arg is None:
        return _saved_home_page_clamped(user_info, total_pages) if not has_filter else 1

    try:
        page = int(page_arg)
    except (TypeError, ValueError):
        page = 1
    return max(1, min(page, total_pages))


def _saved_home_page_clamped(user_info, total_pages):
    saved_page, saved_pages = get_saved_home_page(user_info)
    if not saved_page:
        return 1

    if saved_pages and saved_pages > 1:
        # 按 0 基数比例折算：第 50/100 页 ≈ 现在的第 15/30 页
        ratio = (saved_page - 1) / float(saved_pages)
        page = int(round(ratio * total_pages)) + 1
    else:
        page = saved_page

    return max(1, min(page, total_pages))


def remember_home_page(user_key, page, total_pages):
    """记住停留的页码；page<=1 表示回到第一页，顺手清掉记忆。

    只有值真的变了才写 config.json —— 每次翻页都写盘没必要。
    """
    if not user_key:
        return
    users = CONFIG.get('users', {}) or {}
    info = users.get(user_key)
    if not isinstance(info, dict):
        return

    prefs = info.get('preferences')
    if not isinstance(prefs, dict):
        prefs = {}
        info['preferences'] = prefs

    try:
        page = int(page or 1)
    except (TypeError, ValueError):
        return
    total_pages = max(1, int(total_pages or 1))

    if page <= 1:
        if HOME_PAGE_KEY not in prefs and HOME_PAGE_PAGES_KEY not in prefs:
            return
        prefs.pop(HOME_PAGE_KEY, None)
        prefs.pop(HOME_PAGE_PAGES_KEY, None)
    else:
        if (prefs.get(HOME_PAGE_KEY) == page
                and prefs.get(HOME_PAGE_PAGES_KEY) == total_pages):
            return
        prefs[HOME_PAGE_KEY] = page
        prefs[HOME_PAGE_PAGES_KEY] = total_pages

    users[user_key] = info
    CONFIG['users'] = users
    try:
        save_json_file(CONFIG_FILE, CONFIG)
    except Exception as e:
        # 记不住页码不影响这次访问
        logger.warning(f"保存首页页码失败：{e}")

# ===================== 缓存清理 =====================
def cleanup_cache():
    """每10分钟自动跑的温和清理"""
    result = aggressive_cache_cleanup(
        keep_tag=MAX_TAG_PARSE_CACHE - 100,   # 400
        keep_chapter=MAX_CHAPTER_CACHE - 20,  # 20
        keep_image=200,
        keep_work_id=MAX_WORK_ID_FILE_CACHE - 400,  # 1600
        keep_mapping=1,                        # 定时任务不丢映射表，避免频繁重载 JSON
        silent=True
    )

    total_removed = (result['tag'] + result['chapter'] + result['image']
                     + result['check'] + result['work_id_file'] + result['work_id_set'])
    if total_removed > 0:
        logger.info(
            f"自动缓存清理: 共移除 {total_removed} 条 "
            f"(tag={result['tag']}, chapter={result['chapter']}, "
            f"image={result['image']}, check={result['check']}, "
            f"work_id={result['work_id_file'] + result['work_id_set']})"
        )

    # 定时清理后同样归还碎片内存给 OS（之前只有手动 /force_cleanup 端点才做，
    # 导致每10分钟自动清理后 RSS 不降）。trim_memory() 成功时会自行打印 ✅ 日志。
    gc.collect()
    trim_memory()

def line_cache_bytes():
    """粗略估算 line_cache 占用的字节数（content + lines + 开销）

    这个缓存才是「释放内存」真正的大头（单文件上限 20MB），
    但页面上一直没有计数器，所以内存降了却看不出原因。
    """
    total = 0
    try:
        for entry in line_cache.values():
            if not isinstance(entry, dict):
                continue
            content = entry.get('content') or ''
            total += len(content) * 2  # Python str 中文场景近似
            lines = entry.get('lines') or []
            total += len(lines) * 56   # 每个 str 对象头 + 指针的粗略开销
    except Exception:
        return 0
    return total

def work_id_cache_kb():
    """粗略估算指纹缓存（_work_id_file_cache + _work_id_sets）占用的 KB

    这两个缓存过去既不清理也不统计，导致「清理后内存没降」很难解释。
    指纹集合每个元素是 16 位十六进制字符串，按每条约 64 字节 + set 开销估算。
    """
    total = 0
    try:
        for key, work_id in _work_id_file_cache.items():
            # key 是 (realpath, size, mtime)，realpath 字符串往往很长
            total += 120 + len(str(key[0])) * 2 + len(work_id or '')
        for work_id, hashes in _work_id_sets.items():
            total += 216 + len(hashes) * 80  # set 本体开销 + 每个 hash 字符串
    except Exception:
        return 0.0
    return total / 1024.0


def trim_memory():
    """尝试将 glibc 释放的空闲内存归还给操作系统（仅 Linux）"""
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
        logger.info("✅ malloc_trim 执行完成，内存已归还系统")
        return True
    except Exception as e:
        logger.debug(f"malloc_trim 不可用: {e}")
        return False

# ===================== 激进缓存清理 =====================
def aggressive_cache_cleanup(keep_tag=100, keep_chapter=30, keep_image=100,
                            keep_work_id=200, keep_mapping=0, silent=False):
    """激进缓存清理 - 原地修改，不重新赋值全局变量

    Args:
        keep_tag:      标签缓存保留条数（默认 100）
        keep_chapter:  章节缓存保留条数（默认 30）
        keep_image:    图片信息缓存保留条数（默认 100）
        keep_work_id:  文件指纹缓存保留条数（默认 200；映射表按 keep_mapping 处理）
        keep_mapping:  emoji/图片映射表保留份数（默认 0 = 手动清理时全丢，
                       下次用到会自动从 JSON 重新加载）
        silent:        是否静默（不打日志），用于自动定时清理

    Returns:
        dict: 各缓存移除的条目数
    """
    # 映射表需要整体置空，必须声明 global，否则赋值只作用于局部变量
    global _emoji_mapping_cache, _image_mapping_cache

    before = {
        'tag': len(tag_parse_cache),
        'chapter': len(chapter_cache),
        'image': len(image_cache),
        'image_check': len(_image_check_cache),
        'work_id_file': len(_work_id_file_cache),
        'work_id_set': len(_work_id_sets),
    }

    if not silent:
        logger.info(
            f"开始激进缓存清理 - 当前状态: {before} | "
            f"目标: tag={keep_tag}, chapter={keep_chapter}, image={keep_image}, "
            f"work_id_file={keep_work_id}"
        )

    def _trim(od, keep):
        """批量删除最旧的条目（比 while+popitem 快）"""
        extra = len(od) - keep
        if extra <= 0:
            return 0
        for key in list(od.keys())[:extra]:
            od.pop(key, None)
        return extra

    tag_removed = _trim(tag_parse_cache, keep_tag)
    chapter_removed = _trim(chapter_cache, keep_chapter)
    image_removed = _trim(image_cache, keep_image)

    check_removed = len(_image_check_cache)
    if check_removed > 0:
        _image_check_cache.clear()

    # 指纹缓存：去重扫描时每本书都会写一条，之前完全不在清理范围内，
    # 上限 2000 + 800 条常驻，是「清理后内存没降」的隐形大头之一。
    work_id_file_removed = _trim(_work_id_file_cache, keep_work_id)
    work_id_set_removed = _trim(_work_id_sets, min(keep_work_id, MAX_WORK_ID_SET_CACHE))

    # emoji / 图片映射表：手动清理时整份丢掉（keep_mapping=0），
    # 下次访问相关页面会自动重新加载，代价很小。
    mapping_removed = 0
    if keep_mapping <= 0:
        if _emoji_mapping_cache is not None:
            mapping_removed += 1
        if _image_mapping_cache is not None:
            mapping_removed += 1
        _emoji_mapping_cache = None
        _image_mapping_cache = None

    after = {
        'tag': len(tag_parse_cache),
        'chapter': len(chapter_cache),
        'image': len(image_cache),
        'image_check': len(_image_check_cache),
        'work_id_file': len(_work_id_file_cache),
        'work_id_set': len(_work_id_sets),
    }

    if not silent:
        logger.info(f"激进缓存清理完成: {before} → {after}")

    return {
        'tag': tag_removed,
        'chapter': chapter_removed,
        'image': image_removed,
        'check': check_removed,
        'work_id_file': work_id_file_removed,
        'work_id_set': work_id_set_removed,
        'mapping': mapping_removed,
        # 保留的下限：让前端能解释「为什么清完还有 N 条」
        'keep_tag': keep_tag,
        'keep_chapter': keep_chapter,
        'keep_image': keep_image,
        'keep_work_id': keep_work_id,
    }

# ===================== 缓存清理循环 =====================
def cache_cleanup_loop():
    """每10分钟清理一次缓存（更频繁）"""
    while True:
        time.sleep(10 * 60)  # 从30分钟改为10分钟
        try:
            cleanup_cache()
        except Exception as e:
            logger.error(f"缓存清理循环出错: {e}")
            # 不退出，继续下一轮

#===================== 定时扫描循环 =====================
_scheduler_lock_handle = None


def acquire_scheduler_lock(lock_file):
    """跨进程抢占「定时扫描」所有权；fcntl 不可用时退化为进程内唯一"""
    global _scheduler_lock_handle

    if fcntl is None:
        if _scheduler_lock_handle is not None:
            return False
        _scheduler_lock_handle = True
        return True

    try:
        lock_fd = open(lock_file, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # 锁一直持有，不释放，进程退出自动释放
        _scheduler_lock_handle = lock_fd
        return True
    except OSError:
        return False


def start_background_threads():
    """启动后台线程"""
    cleanup_thread = threading.Thread(target=cache_cleanup_loop, daemon=True)
    cleanup_thread.start()
    logger.info("✅ 缓存自动清理已启动（每10分钟清理一次）")

    # 用文件锁确保只有一个进程启动定时扫描
    lock_file = os.path.join(DATA_DIR, 'scheduler.lock')
    if not acquire_scheduler_lock(lock_file):
        logger.info("ℹ️ 另一个进程已启动定时扫描，本进程跳过")
        return

    scan_interval = CONFIG.get('scan_interval_hours', 0)
    if scan_interval > 0:
        schedule_thread = threading.Thread(target=scheduled_scan_loop, daemon=True)
        schedule_thread.start()
        logger.info(f"✅ 定时扫描已启动，间隔 {scan_interval} 小时（每30秒检查一次）")
    else:
        logger.info("ℹ️ 定时扫描未启用（scan_interval_hours = 0）")

# ===================== 强制清理缓存 API =====================
@app.route('/api/force_cleanup', methods=['POST'])
def force_cleanup():
    """强制清理缓存释放内存"""
    logger.info(
        f"force_cleanup 被调用: user_role={session.get('user_role')}, "
        f"authenticated={session.get('authenticated')}"
    )

    if not is_admin():
        logger.warning("force_cleanup 权限不足，拒绝执行")
        return jsonify({'success': False, 'message': '权限不足'}), 403

    # deep=true 时连热缓存一起丢（keep 全 0），用于「我就是要立刻把内存压下去」
    payload = request.get_json(silent=True) or {}
    deep = bool(payload.get('deep'))

    # 1) 清缓存（原地）
    if deep:
        result = aggressive_cache_cleanup(
            keep_tag=0, keep_chapter=0, keep_image=0,
            keep_work_id=0, keep_mapping=0
        )
    else:
        result = aggressive_cache_cleanup()

    # line_cache 才是真正的大头，单独统计后清空
    line_before = len(line_cache)
    line_mb_before = round(line_cache_bytes() / 1024 / 1024, 2)
    line_cache.clear()
    result['line'] = line_before
    result['line_mb'] = line_mb_before

    # 清理后各缓存「还剩多少」——前端用它来解释为什么没有归零
    result['remaining'] = {
        'tag': len(tag_parse_cache),
        'chapter': len(chapter_cache),
        'image': len(image_cache),
        'line': len(line_cache),
        'work_id_file': len(_work_id_file_cache),
        'work_id_set': len(_work_id_sets),
    }
    result['deep'] = deep

    # 2) 触发 GC，回收不可达对象
    collected = gc.collect()
    result['gc_collected'] = collected

    # 3) 关键：让 glibc 把空闲内存归还 OS
    trimmed = trim_memory()
    result['memory_trimmed'] = trimmed

    # 4) 获取当前内存信息
    try:
        import psutil
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024
        result['memory_mb'] = round(memory_mb, 1)
    except Exception:
        # 回退到 /proc
        try:
            with open('/proc/self/statm', 'r') as f:
                parts = f.read().split()
                if len(parts) >= 2:
                    result['memory_mb'] = round(int(parts[1]) * 4 / 1024, 1)
        except Exception:
            pass

    logger.info(f"force_cleanup 完成: {result}")
    return jsonify({'success': True, 'result': result})

# ===================== 认证和用户 =====================
def is_authenticated():
    return bool(session.get('authenticated')) and get_current_user_info()[0] is not None

def get_user_role():
    _, info = get_current_user_info()
    if info is None:
        return None
    return info.get('role', 'user')

def is_admin():
    return get_user_role() == 'admin'

# 永远允许匿名访问的路径
PUBLIC_PATHS = {
    '/login',
    '/logout',
    '/manifest.json',
    '/service-worker.js',
    '/favicon.ico',
    '/robots.txt',
}
# 必须管理员登录才能访问（无论 require_auth 开关如何）
# 注意：'/config' 页面本身**不在**这里——普通用户也能进配置页管理自己的
# 阅读偏好，页面内再用 {% if session.user_role == 'admin' %} 隐藏全局配置卡片。
# 但保存/重载全局配置的接口仍然是管理员专属。
ADMIN_EXACT_PATHS = {
    '/config/save',
    '/config/reload',
    '/tag_manager',
    '/clear_records',
    '/api/start_scan',
    '/api/force_cleanup',
    '/api/emoji/image-mapping/save',
}
ADMIN_PATH_PREFIXES = ('/admin/', '/api/tag/', '/api/users/')

def is_admin_path(path):
    return path in ADMIN_EXACT_PATHS or path.startswith(ADMIN_PATH_PREFIXES)

def _auth_denied(message, code):
    """API 返回 JSON，页面跳登录页"""
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'error': message, 'message': message}), code
    if code == 401:
        return redirect(url_for('auth.login', next=request.path))
    return message, code

#===================== 请求前认证检查 =====================
@app.before_request
def require_auth():
    path = request.path

    if path.startswith('/static') or path in PUBLIC_PATHS:
        return

    # 会话信息失效（用户被删除/旧版明文 cookie）→ 清理并要求重新登录
    if session.get('authenticated') and get_current_user_info()[0] is None:
        session.clear()

    if is_admin_path(path):
        if not is_admin():
            logger.warning(f"拒绝非管理员访问管理接口: {path}")
            return _auth_denied('权限不足，请联系管理员', 403 if is_authenticated() else 401)
        return

    # require_auth=False 时允许匿名浏览普通页面（管理页面仍受保护）
    if CONFIG.get('require_auth', True) is False:
        return

    if not is_authenticated():
        return _auth_denied('未登录', 401)

#==================== 用户阅读记录 =====================
# 存储结构（v2，以 work_id 为主键）：
# {
#   "version": 2,
#   "records": {
#       "<work_id>": {record...},          # record 内含 file_path（当前路径，可漂移）
#   },
#   "_path_index": {
#       "/novels/xxx.txt": "<work_id>",    # 归一化路径 -> work_id，仅用于加速解析
#   }
# }
# work_id 与文件名无关，所以改文件名/改内容都不会丢阅读记录。

READING_RECORD_SCHEMA_VERSION = 2
_PATH_INDEX_KEY = '_path_index'


def normalize_record_path(file_path):
    """把路径统一成索引用的形式：正斜杠 + 保证以 / 开头"""
    if not file_path:
        return ''
    normalized = str(file_path).replace('\\', '/')
    if not normalized.startswith('/'):
        normalized = '/' + normalized
    return normalized


def _empty_records_payload():
    return {
        'version': READING_RECORD_SCHEMA_VERSION,
        'records': {},
        _PATH_INDEX_KEY: {},
    }


def _coerce_records_payload(raw):
    """把磁盘上的数据统一成 v2 结构（含旧格式/脏数据的兜底转换）"""
    payload = _empty_records_payload()

    if not isinstance(raw, dict):
        return payload

    # 已经是 v2
    if isinstance(raw.get('records'), dict):
        payload['records'] = {
            k: v for k, v in raw['records'].items() if isinstance(v, dict)
        }
        path_index = raw.get(_PATH_INDEX_KEY)
        if isinstance(path_index, dict):
            payload[_PATH_INDEX_KEY] = {
                normalize_record_path(k): v for k, v in path_index.items()
            }
        # 补齐可能缺失的路径索引
        for work_id, record in payload['records'].items():
            record_path = record.get('file_path')
            if record_path:
                payload[_PATH_INDEX_KEY].setdefault(
                    normalize_record_path(record_path), work_id)
        return payload

    # 旧格式（路径为 key）兜底：以内容指纹为 work_id 重新整理
    legacy_records = {}
    legacy_index = {}
    for key, value in raw.items():
        if key in ('version', _PATH_INDEX_KEY):
            continue
        if not isinstance(value, dict):
            continue

        record = dict(value)
        record_path = record.get('file_path') or key
        file_path = record_path if os.path.isabs(str(record_path)) else os.path.join(
            NOVEL_DIR, os.path.basename(str(record_path)))

        work_id = record.get('work_id') or compute_work_id(file_path)
        if not work_id:
            # 文件已不存在且无历史指纹，退化为路径哈希，至少保证记录不丢
            work_id = hashlib.blake2b(
                normalize_record_path(record_path).encode('utf-8'),
                digest_size=WORK_ID_BYTES).hexdigest()

        record['work_id'] = work_id
        record['file_path'] = file_path
        legacy_records[work_id] = record
        legacy_index[normalize_record_path(record_path)] = work_id

    payload['records'] = legacy_records
    payload[_PATH_INDEX_KEY] = legacy_index
    return payload


def load_reading_records():
    """读取当前用户的阅读记录，返回 {work_id: record}"""
    if not is_authenticated():
        return {}
    user_key = current_user_key()
    if not user_key:
        return {}
    raw = load_json_file(get_user_record_file(user_key), {})
    return _coerce_records_payload(raw)['records']


def load_reading_payload():
    """读取完整的阅读记录载荷（records + path_index）"""
    if not is_authenticated():
        return _empty_records_payload()
    user_key = current_user_key()
    if not user_key:
        return _empty_records_payload()
    raw = load_json_file(get_user_record_file(user_key), {})
    return _coerce_records_payload(raw)


def save_reading_record(record):
    """保存/更新单条阅读记录（write_through，避免全量覆盖）

    record 必须含 work_id；file_path 会被同步写入路径索引。
    """
    work_id = record.get('work_id')
    if not work_id:
        logger.warning("保存阅读记录失败：缺少 work_id")
        return False

    if not is_authenticated():
        return False
    user_key = current_user_key()
    if not user_key:
        return False

    record_file = get_user_record_file(user_key)
    with file_lock(record_file + '.lock'):
        existing_raw = load_json_file(record_file, {})
        payload = _coerce_records_payload(existing_raw)
        payload['version'] = READING_RECORD_SCHEMA_VERSION
        payload['records'][work_id] = record

        record_path = record.get('file_path')
        if record_path:
            payload[_PATH_INDEX_KEY][normalize_record_path(record_path)] = work_id
        # 清掉指向同一条记录的历史路径，避免索引里堆积幽灵条目
        stale_paths = [p for p, wid in payload[_PATH_INDEX_KEY].items()
                       if wid == work_id and p != normalize_record_path(record_path)]
        for stale_path in stale_paths:
            del payload[_PATH_INDEX_KEY][stale_path]

        save_json_file(record_file, payload)
    return True


def resolve_record_by_path(file_path):
    """按路径解析阅读记录，返回 (work_id, record)；找不到返回 (None, None)

    解析顺序（从便宜到昂贵）：
      1. 路径索引（_path_index）—— O(1) 字典查找
      2. 扫描缓存中的 work_id —— 目录内按文件名查找
      3. 内容指纹 —— 需要读文件（有 size/mtime 缓存，文件没变不会重读）
      4. 指纹集合相似度匹配 —— 内容被大改时的兜底
    """
    if not file_path:
        return None, None

    payload = load_reading_payload()
    records = payload['records']
    if not records:
        return None, None

    record_key = normalize_record_path(file_path)

    # 1) 路径索引
    indexed_work_id = payload[_PATH_INDEX_KEY].get(record_key)
    if indexed_work_id and indexed_work_id in records:
        return indexed_work_id, records[indexed_work_id]

    # 2) 扫描缓存里的 work_id
    scan_work_id = get_work_id_from_cache(file_path)
    if scan_work_id and scan_work_id in records:
        return scan_work_id, records[scan_work_id]

    # 3) 内容指纹（compute_work_id 内部有 (size, mtime) 缓存，不会重复读全文）
    work_id = compute_work_id(file_path)
    if work_id and work_id in records:
        return work_id, records[work_id]

    # 4) 相似度匹配（改文件名 + 大量改内容的兜底）
    if work_id:
        known_hashes = _work_id_sets.get(work_id) or set()
        similar_id, score = find_similar_work_id(known_hashes, records.keys())
        if similar_id:
            logger.info(f"🔗 阅读记录相似度匹配成功 score={score:.2f} "
                        f"{os.path.basename(file_path)} -> {similar_id[:8]}")
            return similar_id, records[similar_id]

    return None, None


def get_work_id_from_cache(file_path):
    """从小说扫描缓存里取文件的 work_id（没有则返回 None）"""
    target_name = os.path.basename(file_path)
    for novel in novel_data:
        if os.path.basename(novel.get('file_path', '')) == target_name:
            return novel.get('work_id')
    return None


def compute_progress_ratio(chapter_index, total_chapters, page, total_pages):
    """按「章节序号 + 章内页序」估算整本阅读进度，返回 0.0~1.0 的浮点数。

    不用 line_number / 总行数：每本书切章粒度差异极大（实测有 line=5 的书，
    也有 line=25993 的书），直接相除会得出完全误导的百分比。

    返回 None 表示无法判断进度（例如整本被当成单一虚拟章节）。
    """
    try:
        total_chapters = int(total_chapters or 0)
        if total_chapters <= 0:
            return None

        chapter_index = int(chapter_index) if chapter_index is not None else -1
        if chapter_index < 0:
            return None

        page = int(page or 1)
        total_pages = int(total_pages or 1)
        total_pages = max(1, total_pages)
        page = max(1, min(page, total_pages))

        # 章内页序最多只占一章的宽度，避免单章多页的书进度虚高
        within_chapter = (page - 1) / total_pages
        ratio = (chapter_index + within_chapter) / total_chapters
        return round(max(0.0, min(1.0, ratio)), 4)
    except (TypeError, ValueError):
        return None


def humanize_timestamp(timestamp):
    """把时间戳转成「刚刚 / 12 分钟前 / 昨天 21:30 / 3 天前 / 06-12」"""
    try:
        ts = float(timestamp)
    except (TypeError, ValueError):
        return '未知时间'

    dt = datetime.fromtimestamp(ts)
    now = datetime.now()
    delta = now - dt
    seconds = delta.total_seconds()

    if seconds < 0:
        return dt.strftime('%m-%d %H:%M')
    if seconds < 60:
        return '刚刚'
    if seconds < 3600:
        return f'{int(seconds // 60)} 分钟前'

    today = now.date()
    record_day = dt.date()
    day_diff = (today - record_day).days

    if day_diff == 0:
        return f'今天 {dt.strftime("%H:%M")}'
    if day_diff == 1:
        return f'昨天 {dt.strftime("%H:%M")}'
    if day_diff < 7:
        return f'{day_diff} 天前'
    if dt.year == now.year:
        return dt.strftime('%m-%d')
    return dt.strftime('%Y-%m-%d')


def annotate_reading_status(novels, records):
    """给一批小说补上「已读完 / 阅读中 / 未读」状态（用于主页书名栏的标记）。

    只查传进来的这批（主页当前页 100 本），按 work_id / 文件名两次哈希命中，
    避免为每本书去遍历阅读记录或扫描缓存。

    写回字段：
      reading_status  'finished' | 'reading' | 'none'
      record_finished 该书的记录是否被标记为已读完
    """
    if not novels:
        return

    by_work_id = {}
    by_name = {}
    for rec in (records or {}).values():
        if not isinstance(rec, dict):
            continue
        wid = rec.get('work_id')
        if wid:
            by_work_id[wid] = rec
        name = rec.get('filename') or os.path.basename(str(rec.get('file_path') or ''))
        if name:
            by_name[name] = rec

    for novel in novels:
        rec = by_work_id.get(novel.get('work_id'))
        if rec is None:
            name = novel.get('filename') or os.path.basename(str(novel.get('file_path') or ''))
            rec = by_name.get(name) if name else None

        if rec is None:
            # 没有任何阅读记录 = 没读过
            novel['reading_status'] = 'none'
            novel['record_finished'] = False
        elif rec.get('finished'):
            novel['reading_status'] = 'finished'
            novel['record_finished'] = True
        else:
            # 有记录但没标已读完 = 阅读中
            novel['reading_status'] = 'reading'
            novel['record_finished'] = False


def recent_group_of(timestamp):
    """把记录归入 今天 / 昨天 / 更早 三组"""
    try:
        dt = datetime.fromtimestamp(float(timestamp))
    except (TypeError, ValueError):
        return 'earlier'
    day_diff = (datetime.now().date() - dt.date()).days
    if day_diff <= 0:
        return 'today'
    if day_diff == 1:
        return 'yesterday'
    return 'earlier'


def compute_recent_stats(records):
    """最近阅读概览：总数 / 今日 / 在读本数 / 已读完本数 / 平均进度"""
    records = records or []
    today_count = sum(1 for r in records if r.get('group') == 'today')
    finished_count = sum(1 for r in records if r.get('finished'))
    in_progress = [r for r in records
                   if not r.get('finished')
                   and r.get('progress_percent') is not None
                   and 0 < r['progress_percent'] < 100]
    ratios = [r['progress_ratio'] for r in records if r.get('progress_ratio') is not None]
    avg = int(round(sum(ratios) / len(ratios) * 100)) if ratios else 0
    return {
        'total': len(records),
        'today': today_count,
        'in_progress': len(in_progress),
        'finished': finished_count,
        'avg_progress': avg
    }


def group_recent_records(records):
    """按 今天 / 昨天 / 更早 分组，保持时间倒序，空组自动省略"""
    buckets = {'today': [], 'yesterday': [], 'earlier': []}
    for record in records or []:
        buckets.setdefault(record.get('group', 'earlier'), []).append(record)

    # 图标名与文字分开返回：模板负责渲染 SVG（与 main.js 的 GROUP_META 一致），
    # 这里不再拼 emoji，否则首屏会出现「emoji → 重渲染后变 SVG」的跳变。
    labels = {
        'today': ('今天', 'calendar'),
        'yesterday': ('昨天', 'moon'),
        'earlier': ('更早', 'library')
    }
    groups = []
    for key in ('today', 'yesterday', 'earlier'):
        if buckets.get(key):
            label, icon_name = labels[key]
            groups.append({
                'key': key,
                'slug': key,
                'label': label,
                'icon': icon_name,
                'records': buckets[key]
            })
    return groups


def build_recent_records(records, limit=None):
    """把原始阅读记录整理成首页可直接渲染的列表（已按时间倒序、已补全字段）。

    limit 为 None 表示全部返回（首页默认只渲染前若干条，其余由「加载更多」拉取）。
    """
    items = [r for r in (records or {}).values() if isinstance(r, dict)]
    items.sort(key=lambda x: x.get('timestamp', 0) or 0, reverse=True)

    enriched = []
    for record in items:
        # 首页卡片要能直接跳转，这里把失效的 file_path 用当前扫描缓存刷新一遍
        rec = dict(_refresh_record_path(record))

        # 「已读」标记优先：手动标记或读到最后一页都会置位，直接按 100% 处理
        if rec.get('finished'):
            rec['progress_ratio'] = 1.0
            rec['progress_percent'] = 100
            rec['progress_text'] = '已读完'
            rec['progress_known'] = True
            rec['finished'] = True
        else:
            ratio = rec.get('progress_ratio')
            if ratio is None:
                # 只有改造后写入的记录才带 progress_ratio/chapter_index。
                # 老记录没有章节序号，这里不猜：扫描缓存里的 chapter_count 实测恒为 1，
                # 拿它算会得出「0%，共 1 章」这种看起来精确、实际错误的进度，
                # 不如老实显示「进度未知」。用户重新打开一次书就会写入精确值。
                ratio = compute_progress_ratio(
                    rec.get('chapter_index'),
                    rec.get('total_chapters'),
                    rec.get('page'),
                    rec.get('total_pages')
                )
            try:
                ratio = float(ratio) if ratio is not None else None
            except (TypeError, ValueError):
                ratio = None

            if ratio is not None:
                ratio = max(0.0, min(1.0, ratio))
                rec['progress_ratio'] = ratio
                rec['progress_percent'] = int(round(ratio * 100))
                rec['progress_text'] = (f'{rec["progress_percent"]}%'
                                        if rec['progress_percent'] > 0 else '刚开始')
                rec['progress_known'] = True
            else:
                rec['progress_ratio'] = None
                rec['progress_percent'] = None
                # 老记录（升级前写入）没有章节数据，进度无法判断。
                # 明确区分「未知」和「0%」，避免界面显示成没读过。
                rec['progress_text'] = '进度待更新'
                rec['progress_known'] = False
            rec['finished'] = False

        author = (rec.get('author') or '').strip()
        # 「[不详]」「未知」这类占位作者不渲染，把槽位让给更有用的信息
        rec['author_display'] = '' if author in ('', '[不详]', '不详', '未知', '未知作者', '无') else author

        rec['time_display'] = humanize_timestamp(rec.get('timestamp'))
        rec['group'] = recent_group_of(rec.get('timestamp'))
        rec['missing_file'] = not (rec.get('file_path') and os.path.exists(rec['file_path']))
        rec['chapter_display'] = (rec.get('chapter_text') or '').strip() or '正文'
        enriched.append(rec)

    if limit is not None:
        return enriched[:limit]
    return enriched


def _refresh_record_path(record):
    """返回一份 file_path 指向「当前实际文件」的记录副本。

    记录里存的路径是上次阅读时的路径；文件改名后可能失效。
    这里用 work_id 到 novel_data（扫描缓存）里找回当前文件名。
    """
    if not isinstance(record, dict):
        return record

    record_path = record.get('file_path', '')
    if record_path and os.path.exists(record_path):
        return record

    work_id = record.get('work_id')
    if work_id:
        for novel in novel_data:
            if novel.get('work_id') == work_id:
                refreshed = dict(record)
                refreshed['file_path'] = novel.get('file_path', record_path)
                return refreshed

    # 退一步：按文件名在目录里找
    filename = record.get('filename') or os.path.basename(str(record_path))
    if filename:
        candidate = os.path.join(NOVEL_DIR, filename)
        if os.path.exists(candidate):
            refreshed = dict(record)
            refreshed['file_path'] = candidate
            return refreshed

    return record


def delete_reading_record_by_work_id(work_id):
    """在文件锁内删除单条记录（供 /api/delete_record 使用）"""
    if not work_id:
        return False
    if not is_authenticated():
        return False
    user_key = current_user_key()
    if not user_key:
        return False

    record_file = get_user_record_file(user_key)
    with file_lock(record_file + '.lock'):
        payload = _coerce_records_payload(load_json_file(record_file, {}))
        if work_id not in payload['records']:
            return False
        del payload['records'][work_id]
        payload[_PATH_INDEX_KEY] = {
            p: w for p, w in payload[_PATH_INDEX_KEY].items() if w != work_id
        }
        save_json_file(record_file, payload)
    return True

def set_reading_record_finished(work_id, finished=True, seed=None):
    """在文件锁内设置/取消单条记录的「已读」标记，返回 (是否成功, 记录或None)

    记录不存在时，如果传入了 seed（{title/author/file_path...}），
    会创建一条最小记录（line_number=1）——这样「没读过也想直接标记已读」
    也能工作，同时记录本身是完整的、能正常显示在首页。
    """
    if not work_id:
        return False, None
    if not is_authenticated():
        return False, None
    user_key = current_user_key()
    if not user_key:
        return False, None

    record_file = get_user_record_file(user_key)
    with file_lock(record_file + '.lock'):
        payload = _coerce_records_payload(load_json_file(record_file, {}))
        record = payload['records'].get(work_id)

        if not isinstance(record, dict):
            if not seed:
                return False, None
            # 新建一条最小记录：阅读位置从头开始，只带「已读」标记
            record = {
                'work_id': work_id,
                'title': seed.get('title', ''),
                'author': seed.get('author', ''),
                'line_number': 1,
                'chapter_text': seed.get('chapter_text') or '正文',
                'timestamp': time.time(),
                'file_path': seed.get('file_path', ''),
                'filename': os.path.basename(seed.get('file_path', '') or ''),
                'page': 1,
                'total_pages': 1,
                'is_virtual': False,
                'chapter_index': None,
                'total_chapters': None,
                'progress_ratio': None,
            }

        record['finished'] = bool(finished)
        if finished:
            record['finished_at'] = time.time()
        else:
            record.pop('finished_at', None)
        payload['records'][work_id] = record

        record_path = record.get('file_path')
        if record_path:
            payload[_PATH_INDEX_KEY][normalize_record_path(record_path)] = work_id

        save_json_file(record_file, payload)
    return True, record


# ==================== PWA 支持 ====================
@app.route('/manifest.json')
def pwa_manifest():
    theme = request.args.get('theme')
    if theme not in ('light', 'dark'):
        theme = CONFIG.get('theme', 'auto')
        if theme == 'auto':
            theme = 'dark'  # 服务端默认

    theme_color = '#ffffff' if theme == 'light' else '#131a12'

    manifest = {
        "name": "摸鱼读物",
        "short_name": "被窝阅读器",
        "description": "个人小说阅读管理器",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": theme_color,
        "theme_color": theme_color,
        "lang": "zh-CN",
        "dir": "ltr",
        "categories": ["books", "productivity"],
        "icons": [
            {"src": "/static/images/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/static/images/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": "/static/images/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}
        ],
        "shortcuts": [
            {
                "name": "继续阅读",
                "short_name": "继续",
                "url": "/",
                "icons": [{"src": "/static/images/icon-192.png", "sizes": "192x192"}]
            }
        ]
    }
    return jsonify(manifest)

@app.route('/service-worker.js')
def pwa_service_worker():
    """Service Worker - 必须从根路径访问，才能覆盖整个网站"""
    from flask import send_from_directory
    response = send_from_directory(
        os.path.join(BASE_DIR, 'static'),
        'service-worker.js',
        mimetype='application/javascript'
    )
    # 关键：告诉浏览器不要缓存 SW 本身
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    # 允许跨域（如果以后有子域）
    response.headers['Service-Worker-Allowed'] = '/'
    return response

# ==================== 加载标签规则 ====================
def load_tag_rules():
    DEFAULT_KEYWORDS = [
        "连载", "完结", "太监", "断更", "番外", "同人", "原创", "翻译", "改编",
        "都市", "校园", "职场", "官场", "仙侠", "玄幻", "奇幻", "武侠", "穿越",
        "末世", "无限流", "恐怖", "悬疑", "纯爱", "后宫", "出轨"
    ]
    DEFAULT_ALIASES = {
        "完结": ["完"],
        "连载": ["连载中", "更新中"],
        "太监": ["断更", "烂尾"]

    }
    DEFAULT_IMPLICATIONS = {
        "后宫": ["一男多女"],
        "百合": ["女同"],
        "催眠": ["精神控制"],
        "穿越": ["重生"],
        "重生": ["穿越"],
        "无限流": ["末世", "异界"],
        "异界": ["无限流", "末世"],
        "末世": ["无限流", "异界"],
        "恐怖": ["悬疑"],
        "悬疑": ["恐怖"]}

    default_rules = {
        "implications": DEFAULT_IMPLICATIONS,
        "aliases": DEFAULT_ALIASES,
        "keywords": DEFAULT_KEYWORDS,
        "negation_patterns": []
    }

    rules = load_json_file(TAG_RULES_FILE, default_rules)

    for key, default in default_rules.items():
        if key not in rules or not rules[key]:
            rules[key] = default
            print(f"⚠️ {key} 字段缺失，已使用默认值")

    print(f"✅ 从 {TAG_RULES_FILE} 加载标签规则")
    print(f"   🔑 识别关键词: {len(rules.get('keywords', []))} 个")
    print(f"   🔗 别名映射: {len(rules.get('aliases', {}))} 组")
    print(f"   📌 派生规则: {len(rules.get('implications', {}))} 条")
    return rules

TAG_RULES = load_tag_rules()
TAG_IMPLICATIONS = TAG_RULES.get('implications', {})
TAG_ALIASES = TAG_RULES.get('aliases', {})

def normalize_tag_keywords(keywords):
    """英文关键词统一小写，避免重载后大小写不一致"""
    if not isinstance(keywords, list):
        return []
    return [k.lower() if isinstance(k, str) and k.isalpha() else k for k in keywords if k]

TAG_KEYWORDS = normalize_tag_keywords(TAG_RULES.get('keywords', []))

# ==================== 预编译正则表达式 ====================
LEVEL1_PATTERN = re.compile(r'^\s*(?:第(?:\d+|[〇零一二三四五六七八九十百千万]+)[册集卷部]|[上下前后中终序][册集卷部])\s*[：:\s·]?\s*.*$')
LEVEL2_PATTERN = re.compile(r'^\s*(?:第(?:\d+|[〇零一二三四五六七八九十百千万]+)[篇章]|[上下前后中终序][篇章]|楔子|引子|引言|前言|序言|正文|番外|后记|尾声)\s*[：:\s·]?\s*.*$')
LEVEL3_PATTERN = re.compile(r'^\s*(?:第(?:\d+|[〇零一二三四五六七八九十百千万]+)[节回目幕])\s*[：:\s·]?\s*.{1,30}$')

# ===== 排序规则 =====
if sys.platform != 'win32':
    try:
        import locale
        locale.setlocale(locale.LC_ALL, 'zh_CN.UTF-8')
        print("✅ 已设置中文排序规则")
    except:
        try:
            locale.setlocale(locale.LC_ALL, 'C.UTF-8')
            print("✅ 已设置 C.UTF-8 排序规则")
        except:
            print("⚠️ 无法设置 locale，将使用默认排序规则")

# ==================== 全局变量 ====================
novel_data = []
chapter_cache = OrderedDict()      # 改为 OrderedDict 支持 LRU
tag_parse_cache = OrderedDict()    # 改为 OrderedDict 支持 LRU

scan_progress = {
    'total': 0,
    'current': 0,
    'status': 'idle',
    'message': '',
    'start_time': None,
    # 进度分两段：scan_dir（检查书目，增量扫描的主要耗时）→ parse（解析变化文件）
    # 百分比由接口按阶段加权，避免 total 切换导致的跳变
    'phase': '',
    'incremental': False,
}

cache = {
    'filter_options': None,
    'last_update': 0,
    'data_hash': None
}

# 阅读页行内容缓存（受限，避免把大文件常驻内存）
line_cache = OrderedDict()
MAX_LINE_CACHE_FILES = 1
MAX_LINE_CACHE_FILE_MB = 5

# 缓存版本号（对应 meta.revision），替代原来的「缓存文件 mtime」：
# 库里的 revision 一变说明有人写过缓存，需要重新加载
_last_cache_rev = 0
_scan_active = False

def invalidate_filter_cache():
    """标签/作者/站点发生变化后调用，让下拉筛选重新统计"""
    cache['filter_options'] = None
    cache['data_hash'] = None

# ==================== 缓存监控装饰器 ====================
def monitor_cache(func):
    """监控缓存操作的装饰器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        before_tag = len(tag_parse_cache)
        before_chapter = len(chapter_cache)

        try:
            result = func(*args, **kwargs)
        except Exception as e:
            logger.error(f"{func.__name__} 执行失败: {e}")
            raise

        elapsed = time.time() - start_time
        after_tag = len(tag_parse_cache)
        after_chapter = len(chapter_cache)

        logger.debug(
            f"{func.__name__} | 耗时:{elapsed:.3f}s | "
            f"tag缓存:{before_tag}→{after_tag}({after_tag-before_tag:+d}) | "
            f"chapter缓存:{before_chapter}→{after_chapter}({after_chapter-before_chapter:+d})"
        )

        if after_tag - before_tag > 10:
            logger.warning(f"{func.__name__} 导致 tag 缓存增长过快: +{after_tag-before_tag}")

        return result
    return wrapper

# ==================== 辅助函数 ====================
def get_file_hash(file_path):
    try:
        stat = os.stat(file_path)
        return f"{stat.st_size}_{stat.st_mtime}"
    except Exception as e:
        logger.warning(f"获取文件哈希失败：{e}")
        return None

#==================== 获取数据哈希 =====================
def get_data_hash(data):
    if not data:
        return None
    try:
        return f"{len(data)}_{os.path.getmtime(NOVEL_DIR) if os.path.exists(NOVEL_DIR) else 0}"
    except:
        return f"{len(data)}_{time.time()}"

#==================== 获取小说配图文件夹 =====================
def strip_txt_ext(filename):
    """去掉结尾的 .txt/.TXT（只去结尾，避免标题里的 .txt 被误伤）"""
    if not filename:
        return ''
    if filename.lower().endswith('.txt'):
        return filename[:-4]
    return filename

def _media_tags_from(item):
    """从条目里取出 tags 字段（可能是字符串或列表）"""
    tags = item.get('tags') or ''
    if isinstance(tags, str):
        return [t for t in re.split(r'[,，\s]+', tags) if t]
    return list(tags)


def _set_media_tags(item, media_types):
    """把 配图/视频/音频 三个标签按实际媒体情况写回条目。

    只增删这三类标签，其余标签原样保留，且尽量维持原有顺序，
    避免每次扫描把用户的标签顺序打乱（顺序影响首页展示的前 3 个）。
    """
    media_names = MEDIA_TAG_NAMES
    current = _media_tags_from(item)
    desired = []
    if media_types.get('image'):
        desired.append('配图')
    if media_types.get('video'):
        desired.append('视频')
    if media_types.get('audio'):
        desired.append('音频')

    # 先剔除旧的媒体标签，再把缺的补到末尾
    result = [t for t in current if t not in media_names]
    for t in desired:
        if t not in result:
            result.append(t)

    if result != current:
        item['tags'] = ','.join(result) if result else '无'
        return True
    return False


def _refresh_media_tags(item, folder_path):
    """按目录实际内容刷新 配图/视频/音频 标签，返回是否发生变化"""
    try:
        return _set_media_tags(item, scan_media_types(folder_path))
    except Exception as e:
        logger.warning(f"刷新媒体标签失败（已跳过）: {folder_path}: {e}")
        return False


def _strip_media_tags(item):
    """配图目录已不存在时，移除三类媒体标签，返回是否发生变化"""
    try:
        names = {'image': False, 'video': False, 'audio': False}
        return _set_media_tags(item, names)
    except Exception:
        return False


def get_image_folder_for_novel(filename, _use_cache=True):
    """获取小说对应的配图文件夹路径。

    ⚠️ 候选只认带后缀的 *_images / *_配图。
    历史上还有第三个候选「与书名同名的目录」，但把书按目录整理时
    （NOVEL_DIR/某本书/ 下放章节或正文），那个目录会被误判成配图文件夹，
    导致「配图」标签与前端找图路径双双出错，故移除。

    _use_cache：扫描时同一批会反复问同一个文件（增量扫描的未变化分支、
    以及 parse_file_content_fast 里的媒体检测各问一次），而每次询问是
    3 次 os.path.exists —— 在 NAS 挂载路径上就是 3 次网络 stat。
    这里用一个短命缓存（每次扫描开始时清空，见 _scan_core），
    避免重复往返；缓存键只用 filename，因为 NOVEL_DIR 在进程内不变。
    """
    if not filename:
        return None

    if _use_cache:
        try:
            return _image_folder_cache[filename]
        except KeyError:
            pass

    base_name = strip_txt_ext(os.path.basename(filename))

    possible_folders = [
        os.path.join(NOVEL_DIR, f"{base_name}_images"),
        os.path.join(NOVEL_DIR, f"{base_name}_配图"),
    ]

    result = None
    for folder in possible_folders:
        if os.path.isdir(folder):
            result = folder
            break

    if _use_cache:
        _image_folder_cache[filename] = result
    return result

# ==================== 媒体类型判定（单一定义源）====================
# 「配图 / 视频 / 音频」这三个标签是**文件系统存在性标记**，
# 只能由 scan_media_types() 按配图目录的实际内容生成，
# 绝不能参与正文关键词匹配（正文里提到「视频」二字太常见了，
# 会把大量纯文字小说误标成「视频」）。
# 同一组名字在多处用于「先剔除、再按实际情况补回」，集中定义避免拼写漂移。
MEDIA_TAG_NAMES = frozenset({'配图', '视频', '音频'})

# 之前扩展名列表在两处各写一份（parse_file_content_fast 内联元组、
# 文件末尾的 VIDEO_EXTENSIONS/AUDIO_EXTENSIONS 常量），两份会漂移；
# 这里统一成一处，扫描标签与播放接口共用。
IMAGE_EXTENSIONS_ALL = frozenset({
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.avif',
    '.tif', '.tiff', '.heic', '.heif',
})
VIDEO_EXTENSIONS_ALL = frozenset({
    '.mp4', '.webm', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.m4v',
    '.mpg', '.mpeg', '.ts', '.m2ts', '.3gp', '.ogv',
})
AUDIO_EXTENSIONS_ALL = frozenset({
    '.mp3', '.m4a', '.m4b', '.aac', '.wav', '.flac', '.ogg', '.oga',
    '.opus', '.wma', '.ape', '.alac', '.aiff', '.aif',
})


# ==================== 「每日推荐」卡片封面 ====================
# 来源优先级：配图目录里的本地图片 > 正文里出现的封面外链。
# 都没有时返回空串，模板退化成「书名首字」占位封（保证左右两栏布局稳定）。
_COVER_NAME_HINTS = ('cover', '封面', 'front', 'poster', 'folder', '001', '01')
_IMG_URL_RE = re.compile(
    r'''https?://[^\s"'<>]+?\.(?:jpe?g|png|webp|gif|bmp|avif)(?:\?[^\s"'<>]*)?''',
    re.I,
)


def _pick_cover_image(folder, max_depth=2, limit=60):
    """在配图目录里挑一张当封面，返回 (所在子目录, 文件名)；没有返回 None。

    配图常按章节分子目录（第1章/01.jpg），所以要在浅层递归里找。
    优先文件名带 cover/封面 的，其次按路径排序取第一张 —— 稳定、可预测，
    不会出现「每次刷新推荐封面都不一样」的随机感。
    """
    candidates = []
    base_depth = folder.rstrip(os.sep).count(os.sep)
    try:
        for root, dirs, files in os.walk(folder):
            if root.rstrip(os.sep).count(os.sep) - base_depth >= max_depth:
                dirs[:] = []
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for name in files:
                if name.startswith('.') or name.lower() in ('thumbs.db', 'desktop.ini'):
                    continue
                if os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS_ALL:
                    candidates.append((root, name))
            if len(candidates) >= limit:
                break
    except OSError:
        return None

    if not candidates:
        return None

    def rank(item):
        root, name = item
        low = name.lower()
        hinted = 0 if any(h in low for h in _COVER_NAME_HINTS) else 1
        return (hinted, len(root), low)

    return min(candidates, key=rank)


def find_cover_url(novel):
    """给「每日推荐」卡片找封面，返回可直接用于 <img src> 的地址；没有则空串。"""
    if not isinstance(novel, dict):
        return ''

    filename = novel.get('filename') or os.path.basename(str(novel.get('file_path') or ''))
    folder = get_image_folder_for_novel(filename) if filename else None
    if folder:
        picked = _pick_cover_image(folder)
        if picked:
            sub_folder, name = picked
            try:
                return url_for('serve_local_image', folder=sub_folder, name=name)
            except RuntimeError:
                # 非请求上下文（后台线程）调用时 url_for 不可用，直接放弃封面
                return ''

    # 外链：正文预览/简介里出现的第一张图（含「封面：http…」这种带标签的写法）
    for key in ('preview', 'intro'):
        match = _IMG_URL_RE.search(str(novel.get(key) or ''))
        if match:
            return match.group(0)
    return ''


def scan_media_types(folder_path, max_depth=3):
    """统计配图目录里实际存在的媒体类型。

    与旧实现（只看 os.listdir 第一层）的差异：
      1) 递归到 max_depth 层 —— 配图常按章节分子目录（第1章/01.jpg），
         旧实现会整批漏掉，导致「配图」标签缺失；
      2) 排除隐藏文件与系统垃圾文件（.DS_Store / Thumbs.db / desktop.ini）；
      3) 用统一的扩展名集合判定，不再两份常量漂移。

    返回 {'image': bool, 'video': bool, 'audio': bool}，
    目录不可读时全为 False（不抛异常，避免单本坏目录打断整次扫描）。
    """
    found = {'image': False, 'video': False, 'audio': False}
    if not folder_path:
        return found

    base_depth = folder_path.rstrip(os.sep).count(os.sep)
    try:
        for root, dirs, files in os.walk(folder_path):
            # 深度限制：避免某些人把整个书库塞进配图目录导致长遍历
            if root.rstrip(os.sep).count(os.sep) - base_depth >= max_depth:
                dirs[:] = []
            # 跳过隐藏目录，减少无谓 stat
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in files:
                if f.startswith('.') or f.lower() in ('thumbs.db', 'desktop.ini'):
                    continue
                ext = os.path.splitext(f)[1].lower()
                if ext in IMAGE_EXTENSIONS_ALL:
                    found['image'] = True
                elif ext in VIDEO_EXTENSIONS_ALL:
                    # 纯音频的 mp4（AAC 封装）在扩展名层无法区分，
                    # 这里按扩展名归为视频，与主流播放器习惯一致。
                    found['video'] = True
                elif ext in AUDIO_EXTENSIONS_ALL:
                    found['audio'] = True
            if all(found.values()):
                break   # 三类都齐了，没必要继续遍历
    except OSError as e:
        logger.warning(f"读取配图目录失败（已跳过）: {folder_path}: {e}")

    return found

#==================== 检查配图文件夹缓存 =====================
def check_image_folder_cached(folder_paths):
    """缓存配图文件夹检查结果（仅用于 API 请求）"""
    cache_key = str(folder_paths)

    if cache_key in _image_check_cache:
        return _image_check_cache[cache_key]

    for folder in folder_paths:
        if os.path.exists(folder) and os.path.isdir(folder):
            result = {'exists': True, 'path': folder}
            _image_check_cache[cache_key] = result
            return result

    result = {'exists': False, 'path': None}
    _image_check_cache[cache_key] = result
    return result

# ==================== 路径安全 ====================
def novel_dir_real():
    """NOVEL_DIR 的真实路径（解析符号链接），用于包含性校验"""
    try:
        return os.path.realpath(NOVEL_DIR)
    except Exception:
        return os.path.abspath(NOVEL_DIR)

def is_inside_novel_dir(path, base_real=None):
    """判断路径是否位于小说目录内（防止 ../ 与绝对路径穿越）"""
    if not path:
        return False
    base = base_real or novel_dir_real()
    try:
        real = os.path.realpath(path)
    except Exception:
        return False
    return real == base or real.startswith(base + os.sep)

def resolve_novel_path(raw_path):
    """把 URL/参数里的路径安全解析成小说目录内的 .txt 文件路径；非法返回 None

    实现要点：无论传来的是原样路径、还是被 quote() 过一次/两次的路径，
    都只取文件名再拼到 NOVEL_DIR 下，因此解码多少次都无法越出小说目录。
    """
    if not raw_path:
        return None

    value = str(raw_path).replace('\\', '/').strip()
    if not value:
        return None

    candidates = []
    for variant in (value, urllib.parse.unquote(value)):
        name = os.path.basename(variant)
        if not name:
            continue
        candidate = os.path.join(NOVEL_DIR, name)
        if candidate not in candidates:
            candidates.append(candidate)

    valid = [c for c in candidates
             if is_inside_novel_dir(c) and c.lower().endswith('.txt')]
    if not valid:
        logger.warning(f"拒绝非法路径访问: {raw_path}")
        return None

    for candidate in valid:
        if os.path.exists(candidate):
            return candidate
    return valid[0]

def resolve_media_path(folder, name, extensions):
    """解析媒体文件路径：folder 必须在小说目录内，name 只能是纯文件名"""
    if not folder or not name:
        return None
    name = str(name)
    if '/' in name or '\\' in name or name != os.path.basename(name) or name in ('.', '..'):
        logger.warning(f"拒绝非法媒体文件名: {name}")
        return None
    folder_real = os.path.realpath(folder)
    if not is_inside_novel_dir(folder_real):
        logger.warning(f"拒绝越界媒体目录: {folder}")
        return None
    for ext in extensions:
        candidate = os.path.join(folder_real, name + ext)
        if os.path.isfile(candidate):
            return candidate, ext
    # 兼容 name 已带扩展名的调用方式
    ext = os.path.splitext(name)[1].lower()
    if ext in extensions:
        candidate = os.path.join(folder_real, name)
        if os.path.isfile(candidate):
            return candidate, ext
    return None

#==================== 获取小说配图信息 =====================
def get_novel_image_info(file_path):
    """获取小说的配图信息"""

    filename = os.path.basename(file_path)
    base_name = strip_txt_ext(filename)

    if base_name in image_cache:
        image_cache.move_to_end(base_name)
        return image_cache[base_name]

    image_folder = get_image_folder_for_novel(filename)

    if not image_folder:
        image_cache[base_name] = None
        return None

    info = {
        'folder': image_folder,
        'files': []
    }

    try:
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg'}
        for f in os.listdir(image_folder):
            ext = os.path.splitext(f)[1].lower()
            if ext in image_extensions:
                info['files'].append(f)
    except Exception as e:
        logger.error(f"读取配图信息失败: {e}")

    image_cache[base_name] = info
    return info

def is_file_readable(file_path):
    try:
        with open(file_path, 'rb') as f:
            f.read(1)
        return True
    except:
        return False

#==================== 读取文件头部内容 =====================
def read_file_header(file_path, max_size=16384):
    try:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read(max_size)
                if content.startswith('\ufeff'):
                    content = content[1:]
                return content
        except UnicodeDecodeError:
            with open(file_path, 'rb') as f:
                raw_data = f.read(max_size)
            try:
                content = raw_data.decode('utf-8', errors='ignore')
            except:
                content = raw_data.decode('gbk', errors='ignore')
            if content.startswith('\ufeff'):
                content = content[1:]
            return content
    except Exception as e:
        logger.error(f"读取文件出错：{e}")
        return None

# ==================== 作品指纹（work_id）====================
# work_id 是「这本书」的稳定标识，与文件名无关，因此改文件名不会丢阅读记录。
#
# 算法：MinHash 风格的「最小行哈希集合」
#   1. 把正文按行归一化（去掉所有空白符），过滤掉过短的行（空行/纯序号）
#   2. 给每一行算一个固定的随机优先级（种子固定 → 跨进程/重启稳定）
#   3. 取优先级最小的 K 行，作为这本书的「指纹集合」
#   4. work_id = 指纹集合排序后整体哈希
#
# 为什么不用「全文 sha256」或「均匀抽样」：
#   * 全文哈希：改一个字就全变，记录会断
#   * 均匀抽样：按位置抽样，只要「追加/插入」都会整体错位，记录也会断
#   * 最小行哈希集合：对追加、插入、删除、局部修改都稳定，
#     只有大面积替换正文才会明显下降，这时用相似度兜底
#
# 匹配策略：
#   1. work_id 完全相等          → 同一本书（改名/改少量内容）
#   2. 指纹集合相似度 >= 阈值     → 同一本书（内容被大改）
#   3. 扫描缓存里的 work_id       → 兜底

WORK_ID_VERSION = 2
WORK_ID_BYTES = 16              # 16 字节 = 32 位十六进制
WORK_ID_FINGERPRINT_LINES = 32  # 指纹集合大小（行数）
WORK_ID_SEED = 20240512         # 固定种子，保证跨进程稳定
WORK_ID_MIN_LINE_LEN = 6        # 太短的行（空行/序号）不参与计算
WORK_ID_MATCH_THRESHOLD = 0.5   # 相似度 >= 该值视为同一本书
WORK_ID_SALT = b'novel-work-id-v2'

# work_id -> 指纹集合（进程内缓存，供相似度匹配用）
_work_id_sets = OrderedDict()
MAX_WORK_ID_SET_CACHE = 800

# (realpath, size, mtime) -> work_id（进程内缓存，避免反复读全文）
_work_id_file_cache = OrderedDict()
MAX_WORK_ID_FILE_CACHE = 2000


def _normalize_fingerprint_line(line):
    """归一化一行文本，让空格/空白符差异不影响指纹"""
    if not line:
        return ''
    return re.sub(r'\s+', '', line)


def _fingerprint_line_hash(text):
    """单行文本 → 短哈希（指纹集合的元素）"""
    return hashlib.blake2b(text.encode('utf-8', errors='ignore'),
                           digest_size=8).hexdigest()


def _line_priority(text):
    """给一行文本算一个稳定的随机优先级（用于取「最小 K 行」）"""
    digest = hashlib.blake2b(text.encode('utf-8', errors='ignore'),
                             digest_size=16).digest()
    keyed = hashlib.blake2b(digest, key=WORK_ID_SALT, digest_size=8).digest()
    return int.from_bytes(keyed, 'big')


def extract_work_id_set(text):
    """从正文文本中抽取「指纹集合」（行哈希集合）；无有效行返回空集合"""
    if not text:
        return set()

    candidates = []
    for raw_line in text.splitlines():
        line = _normalize_fingerprint_line(raw_line)
        if len(line) >= WORK_ID_MIN_LINE_LEN:
            candidates.append(line)

    if not candidates:
        # 极短文本：退化为整篇哈希，至少保证「改名不变指纹」
        whole = _normalize_fingerprint_line(text)
        return {_fingerprint_line_hash(whole)} if whole else set()

    # 按固定优先级取最小的 K 行 —— 插入/追加不会改变已选中行的优先级
    candidates.sort(key=_line_priority)
    picked = candidates[:WORK_ID_FINGERPRINT_LINES]
    return {_fingerprint_line_hash(p) for p in picked}


def work_id_from_set(hashes):
    """指纹集合 → work_id 字符串"""
    if not hashes:
        return None
    joined = ''.join(sorted(hashes))
    return hashlib.blake2b(joined.encode('utf-8'),
                           key=WORK_ID_SALT,
                           digest_size=WORK_ID_BYTES).hexdigest()



def read_text_for_fingerprint(file_path, max_bytes=None):
    """读取正文用于计算指纹。

    max_bytes 为 None 时按行流式读取全文（用于扫描建库，避免整本载入内存）；
    否则只读取指定字节数（用于阅读页的快路径）。
    """
    try:
        with open(file_path, 'rb') as f:
            head = f.read(3)
            f.seek(0)
            if head == b'\xef\xbb\xbf':
                raw = f.read()
                return raw[3:].decode('utf-8', errors='ignore')
            if head[:2] == b'\xff\xfe':
                raw = f.read()
                return raw[2:].decode('utf-16-le', errors='ignore')
            if head[:2] == b'\xfe\xff':
                raw = f.read()
                return raw[2:].decode('utf-16-be', errors='ignore')

            if max_bytes is None:
                raw = f.read()
            else:
                raw = f.read(max_bytes)

        for enc in ('utf-8', 'gbk', 'gb18030', 'big5'):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode('utf-8', errors='ignore')
    except Exception as e:
        logger.warning(f"读取指纹内容失败 {file_path}: {e}")
        return ''


def read_and_decode_novel(file_path):
    """一次性读取并解码整本小说，返回 (raw_bytes, text)。

    扫描流程里 work_id 与详情解析都需要全文。过去各自读一次，
    在 NAS 挂载路径上等于每本书多付一倍 I/O。这里抽出公共实现，
    让调用方读一次、两处复用。
    解码顺序与 parse_novel_details 保持一致，保证两条路径结果相同。
    """
    with open(file_path, 'rb') as f:
        raw_data = f.read()

    if raw_data[:3] == b'\xef\xbb\xbf':
        return raw_data, raw_data[3:].decode('utf-8')
    if raw_data[:2] == b'\xff\xfe':
        return raw_data, raw_data[2:].decode('utf-16-le')
    if raw_data[:2] == b'\xfe\xff':
        return raw_data, raw_data[2:].decode('utf-16-be')

    for enc in ('utf-8', 'gbk', 'gb18030', 'big5'):
        try:
            return raw_data, raw_data.decode(enc)
        except UnicodeDecodeError:
            continue

    try:
        detected = chardet.detect(raw_data[:65536]).get('encoding') or 'utf-8'
    except Exception:
        detected = 'utf-8'
    return raw_data, raw_data.decode(detected, errors='ignore')


def compute_work_id(file_path, _use_cache=True, text=None):
    """计算文件的 work_id（结果唯一，必须基于全文，不能用前缀近似）

    性能：
      1. 扫描缓存 novel_data 里已经存了 work_id（get_work_id_from_cache）
      2. 进程内按 (size, mtime) 缓存，文件没变就不重算
      3. text 参数：调用方若已经读过并解码了全文（例如扫描时紧接着要
         跑 parse_novel_details），可以直接传进来，避免同一文件被读第二遍。
         NAS 挂载路径上读一本 10MB 的书要几百毫秒，省掉这一次收益很实在。
    """
    if not file_path or not os.path.isfile(file_path):
        return None

    # 文件没变就直接复用上次算好的 work_id
    try:
        stat = os.stat(file_path)
        cache_key = (os.path.realpath(file_path), stat.st_size, stat.st_mtime)
    except OSError:
        return None

    if _use_cache and cache_key in _work_id_file_cache:
        _work_id_file_cache.move_to_end(cache_key)
        return _work_id_file_cache[cache_key]

    # 优先用调用方已读好的全文，省掉一次整本读取
    if text is None:
        text = read_text_for_fingerprint(file_path, max_bytes=None)
    hashes = extract_work_id_set(text)
    work_id = work_id_from_set(hashes)
    if work_id:
        cache_work_id_set(work_id, hashes)

    _work_id_file_cache[cache_key] = work_id
    _work_id_file_cache.move_to_end(cache_key)
    while len(_work_id_file_cache) > MAX_WORK_ID_FILE_CACHE:
        _work_id_file_cache.popitem(last=False)

    return work_id


def cache_work_id_set(work_id, hashes):
    """把 work_id -> 特征行集合放进 LRU 缓存"""
    if not work_id:
        return
    _work_id_sets[work_id] = hashes
    _work_id_sets.move_to_end(work_id)
    while len(_work_id_sets) > MAX_WORK_ID_SET_CACHE:
        _work_id_sets.popitem(last=False)


def work_id_similarity(set_a, set_b):
    """两个指纹集合的相似度（overlap 系数）；任一为空返回 0

    用 overlap 而不是 Jaccard：追加章节会让集合变大，
    Jaccard 会被分母拖低，overlap 只看交集占较大集合的比例，更贴近直觉。
    """
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    if not intersection:
        return 0.0
    return intersection / max(len(set_a), len(set_b))


def find_similar_work_id(hashes, candidates, threshold=WORK_ID_MATCH_THRESHOLD):
    """在已知 work_id 中查找最相似的一个；找不到或不够像返回 (None, 0.0)

    candidates 为 work_id 的可迭代集合；仅对缓存里有特征集合的条目做比较。
    相似度低于 threshold 时视为「不是同一本书」，避免误合并。
    """
    if not hashes:
        return None, 0.0
    best_id, best_score = None, 0.0
    for work_id in candidates:
        known = _work_id_sets.get(work_id)
        if not known:
            continue
        score = work_id_similarity(hashes, known)
        if score > best_score:
            best_id, best_score = work_id, score
    if best_score < threshold:
        return None, best_score
    return best_id, best_score


#==================== 名称标准化 =====================
def normalize_name(name, type='site'):
    if not name or name == '未知作者' or name == '未知网站' or name == '未知':
        return name
    if type == 'site':
        return name.strip().lower()
    if type == 'author':
        return name.lower()
    if type == 'tag':
        return name.lower()
    return name.strip()

#==================== 解析进度信息 =====================
def parse_progress(filename):
    progress_pattern = r"【([^】]+)】"
    match = re.search(progress_pattern, filename)
    if match:
        progress_text = match.group(1).strip()
        separators = r'[+\s/、]'

        parts = []
        if '完' in progress_text:
            if progress_text.endswith('完'):
                main_part = progress_text[:-1]
                if main_part:
                    subparts = re.split(separators, main_part)
                    parts.extend([p for p in subparts if p])
                parts.append('完')
            elif progress_text.startswith('完'):
                parts.append('完')
                main_part = progress_text[1:]
                if main_part:
                    subparts = re.split(separators, main_part)
                    parts.extend([p for p in subparts if p])
            else:
                temp_parts = progress_text.split('完')
                for i, part in enumerate(temp_parts):
                    if part:
                        subparts = re.split(separators, part)
                        parts.extend([p for p in subparts if p])
                    if i < len(temp_parts) - 1:
                        parts.append('完')
        else:
            parts = re.split(separators, progress_text)

        parts = [p.strip() for p in parts if p.strip()]

        seen = set()
        unique_parts = []
        for p in parts:
            if p not in seen:
                seen.add(p)
                unique_parts.append(p)

        if len(unique_parts) > 1:
            return ','.join(unique_parts)
        return unique_parts[0] if unique_parts else "未知"

    return "未知"

# ==================== 标签相关函数 ====================
def normalize_tag(tag):
    if not tag:
        return ''
    tag = tag.lower().strip()
    for main_tag, aliases in TAG_ALIASES.items():
        if tag == main_tag.lower() or tag in [a.lower() for a in aliases]:
            return main_tag
    return tag

# ==================== 标签清理和派生 =====================
def clean_tags(tags_list):
    if not tags_list:
        return []
    mapped = [normalize_tag(tag) for tag in tags_list if tag]
    seen = set()
    result = []
    for tag in mapped:
        tag = tag.strip()
        if tag and tag != '无' and len(tag) <= 12:
            if tag not in seen:
                seen.add(tag)
                result.append(tag)
    return result

# ==================== 派生标签 =====================
def derive_tags(original_tags_list):
    if not original_tags_list:
        return []
    result = set(original_tags_list)
    changed = True
    while changed:
        changed = False
        current_tags = list(result)
        for tag in current_tags:
            if tag in TAG_IMPLICATIONS:
                for implied_tag in TAG_IMPLICATIONS[tag]:
                    if implied_tag not in result:
                        result.add(implied_tag)
                        changed = True
    return list(result)

# ==================== 标签权重排序 =====================
# 标签都是「命中即打」的二元信号，一本书动辄 20~40 个标签，
# 前端只展示前 3 个，如果不排序就等于随机展示。
# 这里按「信号可信度 × 出现次数」算权重，让最相关的标签排前面。
#
# 权重来源（全部基于已读取的 64KB 头部，零额外 IO）：
#   * 显式声明（文件头「标签：」元数据行）—— 作者/发布者亲自标的，最可信
#   * 文件名/标题命中 —— 书名是对内容最强的概括
#   * 章节标题命中 —— 章节名是作者精选的内容概括
#   * 简介区命中 —— 简介是内容摘要
#   * 正文头部命中 —— 可能只是偶然提及
#   * 派生标签 —— 由其他标签推断而来，可信度打折

TAG_WEIGHT_FILENAME = 6
TAG_WEIGHT_CHAPTER = 4
TAG_WEIGHT_INTRO = 2
TAG_WEIGHT_BODY = 1
TAG_DERIVED_FACTOR = 0.5   # 派生标签权重折扣


def score_tags(tags, sources):
    """给标签列表排序，返回新的列表（不改原列表）

    排序策略分两层：
      第 1 层「置顶」：状态标签（完结/配图/视频/音频）和显式声明的标签。
                       它们是用户筛书的关键维度，不该被高频正文标签挤下去。
      第 2 层「按权重降序」：其余标签按「信号可信度 × 出现次数」排序。

    tags:    要排序的标签列表
    sources: {
        'meta':    显式声明的标签集合,
        'status':  确定状态标签集合（完结/配图/视频/音频）,
        'filename': 文件名+标题文本（小写）,
        'chapter': 章节标题文本（小写）,
        'intro':   简介区文本（小写）,
        'body':    正文头部文本（小写）,
        'derived': 派生出来的标签集合,
    }
    """
    if not tags:
        return []

    meta_tags = sources.get('meta') or set()
    status_tags = sources.get('status') or set()
    derived_tags = sources.get('derived') or set()
    filename_text = sources.get('filename') or ''
    chapter_text = sources.get('chapter') or ''
    intro_text = sources.get('intro') or ''
    body_text = sources.get('body') or ''

    pinned = []     # (固定顺序, 标签) —— 状态 / 显式声明
    scored = []     # (权重, 标签)

    for tag in tags:
        if not tag:
            continue

        # 置顶层：状态标签（完结/配图/视频/音频）最优先，其次显式声明
        if tag in status_tags:
            pinned.append((0, tag))
            continue
        if tag in meta_tags:
            pinned.append((1, tag))
            continue

        tag_lower = tag.lower()
        score = 0.0

        # 按出现次数累加（次数封顶，避免超长文本里高频词把权重撑爆）
        score += min(filename_text.count(tag_lower), 3) * TAG_WEIGHT_FILENAME
        score += min(chapter_text.count(tag_lower), 5) * TAG_WEIGHT_CHAPTER
        score += min(intro_text.count(tag_lower), 5) * TAG_WEIGHT_INTRO
        score += min(body_text.count(tag_lower), 5) * TAG_WEIGHT_BODY

        # 派生标签打折（它是推断出来的，不是文本直接命中的）
        if tag in derived_tags and score > 0:
            score *= TAG_DERIVED_FACTOR

        # 兜底：一个信号都没有的标签（例如规则联动产生）给最低分
        if score <= 0:
            score = 0.1

        scored.append((score, tag))

    # 置顶层按固定顺序；其余按权重降序，同分按标签名升序（保证结果可复现）
    pinned.sort(key=lambda x: (x[0], x[1]))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [tag for _, tag in pinned] + [tag for _, tag in scored]


# ==================== 快速解析文件头部获取元数据 =====================
def parse_file_content_fast(file_path):
    """快速解析TXT文件头部获取元数据（包含简介）"""
    current_hash = get_file_hash(file_path)
    if file_path in tag_parse_cache:
        cached_hash, cached_result = tag_parse_cache[file_path]
        if cached_hash == current_hash:
            return cached_result
    
    header = read_file_header(file_path, max_size=65536)
    
    if not header:
        result = {
            'title': '解析失败',
            'author': '未知作者',
            'site': '未知网站',
            'word_count': 0,
            'chapter_count': 1,
            'tags': '无',
            'publish_date': '未知',
            'file_path': file_path,
            'intro': '无简介'
        }
        tag_parse_cache[file_path] = (current_hash, result)
        return result
    
    lines = re.split(r'\r?\n|\r', header)
    
    title = strip_txt_ext(os.path.basename(file_path))
    author = "未知作者"
    site = "未知网站"
    link = ""
    publish_date = "未知"
    tags_from_meta = []
    
    meta_keywords = [
        '书名：', '作者：', '链接：', '标签：', '内容简介：', '说明：',
        '首发于：', '首发于', '发布于：', '发布于', '发表于：', '发表于',
        '发布：', '发布', '首发：', '首发', '发表：', '转发：', '独发于', '转发于'
    ]
    
    found_meta = False
    meta_ended = False
    
    for line in lines[:30]:
        line = line.replace('\ufeff', '').strip()
        if not line:
            if found_meta:
                meta_ended = True
            continue
        
        if meta_ended:
            break
        
        is_meta_line = any(line.startswith(kw) for kw in meta_keywords)
        
        date_match = re.search(r'(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?)', line)
        publish_keywords = ['首发于', '发布于', '发表于', '发布', '首发', '发表', '转发', '独发']
        has_date_and_publish = date_match and any(kw in line for kw in publish_keywords)
        is_date_only = re.match(r'^\s*\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?\s*$', line)
        is_meta_line = is_meta_line or has_date_and_publish or is_date_only
        
        if line.startswith('链接：') or line.startswith('链接:'):
            found_meta = True
            link = line[3:].strip()
            if not link.startswith('http'):
                link_match = re.search(r'(https?://[^\s）\)>]+)', line)
                if link_match:
                    link = link_match.group(1)
            continue
        
        if line.startswith('标签：'):
            found_meta = True
            tag_raw = line[3:].strip()
            tags_list = re.split(r'[ /＃#，,、；;|、\s]+', tag_raw)
            tags_from_meta = [t.strip() for t in tags_list if t.strip()]
            continue
        
        if is_meta_line:
            found_meta = True
            
            if line.startswith('书名：') and title == strip_txt_ext(os.path.basename(file_path)):
                title = line[3:].strip()
            elif line.startswith('作者：'):
                author_raw = line[3:].strip()
                if '＆' in author_raw or '&' in author_raw or '、' in author_raw:
                    author_parts = re.split(r'[＆&、]', author_raw)
                    author_parts = [normalize_name(p.strip(), 'author') for p in author_parts if p.strip()]
                    author = ','.join(author_parts)
                else:
                    author = normalize_name(author_raw, 'author')
            else:
                publish_keywords = ['首发于：', '首发于', '发布于：', '发布于', '发表于：', '发表于', '发布：', '发布', '首发：', '首发', '发表：', '转发：', '独发于', '转发于']
                
                found_site = False
                for keyword in publish_keywords:
                    pos = line.find(keyword)
                    if pos != -1:
                        if site == '未知网站' and not found_site:
                            after_keyword = line[pos + len(keyword):].strip()
                            after_keyword = re.sub(r'^[：:：\s]*', '', after_keyword)
                            after_keyword = re.sub(r'[。，、；：\s]+$', '', after_keyword)
                            if after_keyword and len(after_keyword) < 30:
                                if not re.search(r'第[0-9零一二三四五六七八九十百千万]+[篇部章节回目]', after_keyword):
                                    site = normalize_name(after_keyword, 'site')
                                    found_site = True
                        
                        if publish_date == '未知':
                            date_match = re.search(r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})[日]?', line)
                            if date_match:
                                year, month, day = date_match.groups()
                                month = month.zfill(2)
                                day = day.zfill(2)
                                publish_date = f"{year}-{month}-{day}"
                        
                        if found_site and publish_date != '未知':
                            break
        else:
            if found_meta:
                line_clean = line.strip()
                if len(line_clean) < 10 and not re.search(r'[，。！？；：、]', line_clean):
                    continue
                if (LEVEL1_PATTERN.match(line_clean) or 
                    LEVEL2_PATTERN.match(line_clean) or 
                    LEVEL3_PATTERN.match(line_clean)):
                    continue
                if len(line_clean) > 15 or re.search(r'[，。！？；：、]', line_clean):
                    meta_ended = True
    
    file_size = os.path.getsize(file_path)
    estimated_words = file_size // 2

    chapter_titles = set()
    title_count = 0
    for line in lines[:500]:
        line_clean = line.strip()
        if not line_clean or len(line_clean) > 100:
            continue
        if (LEVEL1_PATTERN.match(line_clean) or 
            LEVEL2_PATTERN.match(line_clean) or 
            LEVEL3_PATTERN.match(line_clean)):
            chapter_titles.add(line_clean.lower())
            title_count += 1
            if title_count >= 200:
                break
    
    titles_text = ' '.join(chapter_titles)
    intro_text = header[:30000].lower()
    combined_text_lower = titles_text + ' ' + intro_text

    # 标签权重用的信号源（都是小写文本，命中次数越多越相关）
    filename_text_lower = (os.path.basename(file_path) + ' ' + title).lower()
    body_text_lower = header[:30000].lower()

    tags_set = set()
    # 记录每个标签的来源，供 score_tags 计算权重
    tag_sources = {
        'meta': set(),
        'status': set(),
        'derived': set(),
        'filename': filename_text_lower,
        'chapter': titles_text,
        'intro': intro_text,
        'body': body_text_lower,
    }

    if tags_from_meta:
        for tag in tags_from_meta:
            tags_set.add(tag)
            tag_sources['meta'].add(tag)

    tag_keywords_lower = [kw.lower() for kw in TAG_KEYWORDS]
    if CONFIG.get('auto_tag_enabled', True):
        for idx, keyword_lower in enumerate(tag_keywords_lower):
            # ⚠️ 配图/视频/音频 是「文件系统存在性标记」，必须由磁盘检测决定，
            # 不能参与正文关键词匹配。
            # 曾经的 bug：这三个词在 TAG_KEYWORDS 里，而这里匹配的是正文前
            # 30000 字符 —— 小说里只要写到「视频」二字（极常见），就会被自动
            # 打上「视频」标签。实测磁盘上 656 个配图目录、0 个含视频/音频，
            # 缓存里却有 1976 本标「视频」、65 本标「音频」，全是这么来的。
            # 真正的媒体标签在下方 scan_media_types 里按目录内容生成。
            if keyword_lower in MEDIA_TAG_NAMES:
                continue
            if keyword_lower in combined_text_lower:
                tags_set.add(normalize_name(TAG_KEYWORDS[idx], 'tag'))

    # ===== 在 parse_file_content_fast 中 =====

    filename = os.path.basename(file_path)
    if '完' in filename or '完结' in filename:
        tags_set.add('完结')
        tag_sources['status'].add('完结')

    # ===== 检测配图文件夹中的媒体文件（递归，支持 _images / _配图）=====
    media_folder = get_image_folder_for_novel(filename)

    if media_folder:
        # scan_media_types 会递归子目录、跳过隐藏/垃圾文件、用统一扩展名集合判定。
        # 旧实现只看第一层 os.listdir，配图按章节分子目录时会整批漏掉。
        media_types = scan_media_types(media_folder)

        if media_types['image']:
            tags_set.add('配图')
            tag_sources['status'].add('配图')
        if media_types['video']:
            tags_set.add('视频')
            tag_sources['status'].add('视频')
        if media_types['audio']:
            tags_set.add('音频')
            tag_sources['status'].add('音频')
        
    tags = list(tags_set)

    if tags:
        if CONFIG.get('enable_derived_tags', True):
            direct_hits = set(tags)
            derived = derive_tags(tags)
            # 记录哪些是推断出来的（不在直接命中集合里），权重会打折
            tag_sources['derived'] = {t for t in derived if t not in direct_hits}
            tags = derived
        tags = clean_tags(tags)
        # 按权重排序：最相关的标签排前面，前 3 个（首页/卡片展示位）才有意义。
        # 同时解决了 set 顺序受哈希随机化影响、每次重启顺序都变的问题。
        tags = score_tags(tags, tag_sources)

    intro = "无简介"
    intro_pattern = re.compile(r'简介[：:]\s*(.*?)(?=\n\s*第|\n\s*$|\n\s*\[|$)', re.DOTALL)
    intro_match = intro_pattern.search(header[:10000])
    if intro_match:
        intro_raw = intro_match.group(1).strip()
        intro_lines = [line.strip() for line in intro_raw.split('\n') if line.strip()]
        intro = '\n'.join(intro_lines)
        if len(intro) > 2000:
            intro = intro[:2000] + '...'
    
    # 🔥 新增：没有简介时提取正文预览
    preview = None
    if intro == '无简介':
        preview = extract_preview_clean(lines)
    
    result = {
        'title': title[:50] + '...' if len(title) > 50 else title,
        'author': author,
        'site': site,
        'word_count': estimated_words,
        'chapter_count': 1,
        'tags': ','.join(tags) if tags else '无',
        'publish_date': publish_date,
        'link': link,
        'file_path': file_path,
        'intro': intro,
        'preview': preview   # 🔥 新增
    }
    
    tag_parse_cache[file_path] = (current_hash, result)
    return result

# ==================== 预览提取函数 ====================
def extract_preview_clean(lines, max_lines=12, max_chars=600):
    def _clean(s):
        return s.strip(' \t\r\n\u3000\u200b\ufeff')

    def is_meta_line(t):
        t = _clean(t)
        if not t:
            return False
        meta_prefixes = [
            '书名：', '书名:', '作者：', '作者:', '链接：', '链接:',
            '标签：', '标签:', '内容简介：', '内容简介:', '简介：', '简介:',
            '说明：', '说明:', '首发于', '发布于', '发表于',
            '发布：', '发布:', '首发：', '首发:', '发表：', '发表:',
            '转发：', '转发:', '独发于', '转发于',
            '分类：', '分类:', '状态：', '状态:', '字数：', '字数:',
            '更新时间', '更新：', '更新:',
            # 封面/配图标签行：内容是图片地址，不能当成正文预览
            '封面图：', '封面图:', '封面：', '封面:', '配图：', '配图:', '插图：', '插图:',
        ]
        for p in meta_prefixes:
            if t.startswith(p):
                return True
        # 纯日期行
        if re.match(r'^\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?$', t):
            return True
        # 🔥 日期 + 发表/发布/首发/转发 的复合行
        if re.search(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}', t) and \
           any(k in t for k in ['首发', '发布', '发表', '转发', '独发',
                                 '发表于', '首发于', '发布于']):
            return True
        # 纯 URL
        if t.startswith('http://') or t.startswith('https://'):
            return True
        return False

    def is_chapter_line(t):
        t = _clean(t)
        if not t:
            return False
        return bool(LEVEL1_PATTERN.match(t) or
                    LEVEL2_PATTERN.match(t) or
                    LEVEL3_PATTERN.match(t))

    def is_separator(t):
        return bool(re.match(r'^[\d\s\-/\.=_*#~·—○●◎＊※◇♦♢★☆♡♥✿❀]{3,}$', t))

    # 封面/配图行：裸 URL、[img:…] 标记，或「封面：url」这类带标签的行。
    # 这些行会被 is_meta_line 跳过（不当作正文），但要单独收集起来，
    # 以便在没有正文可预览时把封面图还给用户（前端会渲染成 <img>）。
    _COVER_LABELS = ('封面图', '封面', '配图', '插图', '图片')
    _IMG_MARK_RE = re.compile(r'\[\s*img\s*[:：]?[^\]]*\]', re.IGNORECASE)
    _URL_RE = re.compile(r'https?://\S+')

    def is_cover_line(t):
        t = _clean(t)
        if not t:
            return False
        if _IMG_MARK_RE.fullmatch(t):
            return True
        if t.startswith('http://') or t.startswith('https://'):
            return True
        for lbl in _COVER_LABELS:
            if t.startswith(lbl):
                rest = t[len(lbl):].lstrip(' \t：:；;，,-—')
                if rest.startswith(('http://', 'https://')):
                    return True
        return False

    # 1. 跳过开头的元数据行
    start = 0
    cover_lines = []
    for i in range(min(len(lines), 80)):
        t = _clean(lines[i])
        if not t:
            continue
        if is_cover_line(t):
            cover_lines.append(t)
            start = i + 1
            continue
        if is_meta_line(t):
            start = i + 1
            continue
        if is_chapter_line(t):
            start = i + 1  # 跳过章节标题本身
            break
        if len(t) > 3:
            start = i
            break

    # 2. 从 start 开始收集正文
    collected = []
    total_chars = 0

    for i in range(start, len(lines)):
        t = _clean(lines[i])

        if not t:
            if collected:
                break
            continue

        if is_meta_line(t):
            continue
        if is_separator(t):
            continue
        if len(t) <= 1:
            continue

        collected.append(t)
        total_chars += len(t)

        if len(collected) >= max_lines or total_chars >= max_chars:
            break

    if not collected:
        # 没有正文可预览，但有封面/配图 → 返回封面块
        if cover_lines:
            return '\n'.join(cover_lines)
        return None

    preview = '\n'.join(collected)
    if len(preview) > max_chars:
        preview = preview[:max_chars].rstrip() + '……'

    return preview

# ==================== 空章节判定 =====================
# 有些小说文件为了排版会插入「只有标题、没有正文」的章节。
# 这类章节在目录里仍然要显示，但不应该可点击（点进去是空白页）。
# 判定方式：一个章节从它的标题行之后，到下一个章节标题行之前，
# 如果没有任何一行含实际正文（非空白、非分隔线一类的装饰行），
# 就认为它是空章节。
_EMPTY_CHAPTER_IGNORE_PATTERN = re.compile(
    r'^[\s\-—–~=*＊·•.。…_#※☆★✦✧]+$'
)


def _is_meaningful_body_line(line):
    """判断一行是否算「正文内容」（排除空行与分隔线装饰行）"""
    stripped = line.strip()
    if not stripped:
        return False
    if _EMPTY_CHAPTER_IGNORE_PATTERN.match(stripped):
        return False
    return True


def mark_empty_chapters(all_chapters, lines):
    """给每个章节打上 is_empty 标记，返回被标记为空的章节数

    传入的 all_chapters 必须已按 line_number 升序排列。
    """
    if not all_chapters:
        return 0

    total_lines = len(lines)
    empty_count = 0

    for idx, chapter in enumerate(all_chapters):
        start = chapter.get('line_number', 1)  # 1-based，指向标题行本身
        if idx + 1 < len(all_chapters):
            # 下一个章节的标题行不计入本章正文
            end = all_chapters[idx + 1].get('line_number', start) - 1
        else:
            end = total_lines

        # 只截取标题行之后的部分
        body = lines[start:max(start, end)] if end >= start else []

        has_body = any(_is_meaningful_body_line(line) for line in body)
        chapter['is_empty'] = not has_body
        if not has_body:
            empty_count += 1

    return empty_count


# ==================== 解析章节信息 =====================
def parse_novel_details_from_content(content, lines):
    """从已读取的内容解析章节信息"""
    chapters_level1 = []
    chapters_level2 = []
    chapters_level3 = []
    all_chapters = []

    max_lines = min(len(lines), 50000)

    for i, line in enumerate(lines[:max_lines]):
        line_clean = line.strip()
        if not line_clean or len(line_clean) > 100:
            continue

        if LEVEL1_PATTERN.match(line_clean):
            chapter_info = {'text': line_clean, 'line_number': i + 1, 'level': 1}
            chapters_level1.append(chapter_info)
            all_chapters.append(chapter_info)
        elif LEVEL2_PATTERN.match(line_clean):
            chapter_info = {'text': line_clean, 'line_number': i + 1, 'level': 2}
            chapters_level2.append(chapter_info)
            all_chapters.append(chapter_info)
        elif LEVEL3_PATTERN.match(line_clean):
            chapter_info = {'text': line_clean, 'line_number': i + 1, 'level': 3}
            chapters_level3.append(chapter_info)
            all_chapters.append(chapter_info)

    intro_lines = []
    for line in lines[:100]:
        clean = line.strip()
        if clean and len(clean) > 10 and not any(p.match(clean) for p in [LEVEL1_PATTERN, LEVEL2_PATTERN, LEVEL3_PATTERN]):
            intro_lines.append(clean)
        if len(intro_lines) >= 10:
            break

    all_chapters = sorted(all_chapters, key=lambda x: x['line_number'])
    mark_empty_chapters(all_chapters, lines)

    return {
        'intro': '\n'.join(intro_lines) if intro_lines else '无简介',
        'chapters_level1': chapters_level1,
        'chapters_level2': chapters_level2,
        'chapters_level3': chapters_level3,
        'all_chapters': all_chapters,
        'encoding': 'utf-8',
        'file_hash': ''
    }

#==================== 解析小说详情（带缓存） =====================
def is_valid_intro(intro):
    """简介有效性校验：排除元数据误截、过短、无标点的内容"""
    if not intro or intro == '无简介':
        return False
    if any(kw in intro for kw in ['书名：', '作者：', '标签：', '链接：']):
        return False
    return len(intro) > 10 and bool(re.search(r'[，。！？；：、]', intro))

@monitor_cache
def parse_novel_details(file_path, prefetched=None):
    """解析详情（简介/章节等）。

    prefetched：可选，形如 (raw_bytes, content_text) 的预读结果。
    扫描流程里 compute_work_id 已经读过全文，交给本函数即可避免重复整本读取
    —— 在 NAS 上这是每本书最主要的耗时来源。
    传入 prefetched 时跳过缓存校验（调用方刚读过盘，数据即最新）。
    """
    current_hash = get_file_hash(file_path)
    
    # 缓存校验：hash 一致就复用；「无简介」不再是坏缓存（之前会导致整本反复重读）
    if prefetched is None and file_path in chapter_cache:
        cached_info = chapter_cache[file_path]
        if isinstance(cached_info, dict) and cached_info.get('file_hash') == current_hash:
            cached_intro = cached_info.get('intro', '') or ''
            invalid = (cached_intro and cached_intro != '无简介' and not is_valid_intro(cached_intro))
            if invalid:
                logger.warning(f"⚠️ 缓存 intro 无效，重新解析: {os.path.basename(file_path)}")
                del chapter_cache[file_path]
            else:
                chapter_cache.move_to_end(file_path)  # LRU：标记最近使用
                return cached_info

    image_info = get_novel_image_info(file_path)
    file_size = os.path.getsize(file_path)
    print(f"📖 开始解析: {os.path.basename(file_path)} ({file_size/1024/1024:.2f} MB)")

    t1 = time.time()
    if prefetched is not None:
        # 调用方（扫描流程）已经读过盘，这里不再重复读整本
        raw_data, content = prefetched
        print(f"   ⏱️ 复用预读内容（跳过重复读取）")
    else:
        with open(file_path, 'rb') as f:
            raw_data = f.read()
        content = None
    print(f"   ⏱️ 读取文件: {time.time()-t1:.3f}s")

    t2 = time.time()
    encoding = 'utf-8'

    if content is not None:
        # 预读路径：content 已解码，跳过下面的编码探测
        pass
    elif raw_data[:3] == b'\xef\xbb\xbf':
        content = raw_data[3:].decode('utf-8')
        encoding = 'utf-8-sig'
    elif raw_data[:2] == b'\xff\xfe':
        content = raw_data[2:].decode('utf-16-le')
        encoding = 'utf-16-le'
    elif raw_data[:2] == b'\xfe\xff':
        content = raw_data[2:].decode('utf-16-be')
        encoding = 'utf-16-be'
    else:
        for enc in ['utf-8', 'gbk', 'gb18030', 'big5']:
            try:
                content = raw_data.decode(enc)
                encoding = enc
                break
            except UnicodeDecodeError:
                continue

        if content is None:
            sample = raw_data[:65536]
            result = chardet.detect(sample)
            encoding = result['encoding'] or 'utf-8'
            content = raw_data.decode(encoding, errors='ignore')

    print(f"   ⏱️ 检测编码: {time.time()-t2:.3f}s, 编码={encoding}")

    if content.startswith('\ufeff'):
        content = content[1:]

    content = content.lstrip('\ufeff\u200b\u200c\u3000')
    lines = content.splitlines()

    # ========== 全新的简介提取逻辑 ==========
    intro = extract_intro_clean(lines)

    # 没有简介时，提取正文开头作为预览
    preview = None
    if intro == '无简介':
        preview = extract_preview_clean(lines)
        print(f"📝 无简介，提取预览: {len(preview) if preview else 0} 字")
    else:
        print(f"📝 提取简介: {intro[:50]}..." if len(intro) > 50 else f"📝 提取简介: {intro}")

    # 章节提取逻辑
    chapters_level1 = []
    chapters_level2 = []
    chapters_level3 = []
    all_chapters = []

    max_lines_to_scan = len(lines)
    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    if file_size_mb > 50:
        print(f"⚠️ 文件较大 ({file_size_mb:.1f} MB)，正在扫描全部 {len(lines)} 行...")

    for i, line in enumerate(lines[:max_lines_to_scan]):
        line_clean = line.strip()
        if not line_clean or len(line_clean) > 100:
            continue

        if LEVEL1_PATTERN.match(line_clean):
            chapter_info = {'text': line_clean, 'line_number': i + 1, 'level': 1}
            chapters_level1.append(chapter_info)
            all_chapters.append(chapter_info)
        elif LEVEL2_PATTERN.match(line_clean):
            chapter_info = {'text': line_clean, 'line_number': i + 1, 'level': 2}
            chapters_level2.append(chapter_info)
            all_chapters.append(chapter_info)
        elif LEVEL3_PATTERN.match(line_clean):
            chapter_info = {'text': line_clean, 'line_number': i + 1, 'level': 3}
            chapters_level3.append(chapter_info)
            all_chapters.append(chapter_info)

        if len(all_chapters) > 5000:
            print(f"⚠️ 已找到 {len(all_chapters)} 个章节，停止扫描")
            break

    print(f"📚 找到章节：一级 {len(chapters_level1)} 个，二级 {len(chapters_level2)} 个，三级 {len(chapters_level3)} 个")

    # 按行号排序后再判定空章节（判定依赖「相邻章节」关系）
    all_chapters = sorted(all_chapters, key=lambda x: x['line_number'])

    if not all_chapters:
        start_line = 1
        virtual_chapter = {
            'text': '全文阅读',
            'line_number': start_line,
            'level': 1
        }
        all_chapters = [virtual_chapter]
        chapters_level1 = [virtual_chapter]
        print(f"📖 无章节结构，自动添加虚拟章节，从第 {start_line} 行开始")
    else:
        empty_count = mark_empty_chapters(all_chapters, lines)
        if empty_count:
            print(f"📭 其中空章节（仅标题无正文）: {empty_count} 个，目录中将显示为不可点击")

    result = {
        'intro': intro if intro and intro != '无简介' else '无简介',
        'preview': preview,
        'chapters_level1': chapters_level1,
        'chapters_level2': chapters_level2,
        'chapters_level3': chapters_level3,
        'all_chapters': all_chapters,
        'empty_chapter_count': sum(1 for c in all_chapters if c.get('is_empty')),
        'encoding': encoding,
        'has_images': image_info is not None,
        'image_folder': image_info['folder'] if image_info else None,
        'image_files': image_info['files'] if image_info else [],
        'file_hash': current_hash
    }

    chapter_cache[file_path] = result

    if len(chapter_cache) > 200:
        old_keys = list(chapter_cache.keys())[:20]
        for key in old_keys:
            del chapter_cache[key]

    return result

#==================== 简介提取函数 =====================
# 这些 txt 的结构很简单，简介就是「元数据结束 → 第一个章节标题」之间那一段。
# 所以这里不做任何"这是不是配图小标题"的猜测，只做三件事：
#   1. 定位简介段的起止
#   2. 认出其中的图片行（外链图片 / 本地图片 / [img:…] 表情），原样保留，
#      由前端 convertImageLinks() 渲染成 <img>
#   3. 其余行原样当文字保留
# 这样「作者配图」「摄影师配图」或任何别的写法，都只是简介里的一行普通文字，
# 不需要维护任何关键字表。
def extract_intro_clean(lines):
    def _clean(s):
        return s.strip(' \t\r\n\u3000\u200b\ufeff')

    intro_markers = [
        '简介', '内容简介', '作品简介', '故事简介', '小说简介',
        '写在前面', '文案', '介绍', '故事介绍', '题记',
        '作者言', '作者语', '作者的话', '自序', '作者注', '作者按', '说明',
        '书籍简介', '本书简介', '文章简介',
    ]

    meta_prefixes = [
        '书名：', '书名:', '作者：', '作者:', '链接：', '链接:',
        '标签：', '标签:', '内容简介：', '内容简介:', '简介：', '简介:',
        '说明：', '说明:', '首发于', '发布于', '发表于',
        '发布：', '发布:', '首发：', '首发:', '发表：', '发表:',
        '转发：', '转发:', '独发于', '转发于',
        '分类：', '分类:', '状态：', '状态:', '字数：', '字数:',
        '更新时间', '更新：', '更新:',
    ]

    _IMG_MARK_RE = re.compile(r'\[\s*img\s*[:：]?[^\]]*\]', re.IGNORECASE)

    def is_image_line(t):
        """整行是否只是一张图片：外链图片 / 本地图片路径 / [img:…] 表情标记"""
        t = _clean(t)
        if not t:
            return False
        # [img:…] 表情 / 图片标记
        if _IMG_MARK_RE.search(t):
            return True
        # 外链图片：「封面：https://…」「封面https://…」等带标签写法。
        # 注意只允许「封面/配图/插图/图片/封面图」这类图片标签做前缀——
        # 否则「链接：https://…」「作者博客：https://…」也会被当成图片行。
        m = re.match(r'^(?:封面图|封面|配图|插图|图片)?\s*[：:]?\s*(https?://\S+)$', t)
        if m:
            return True
        # 本地图片路径：images/a.jpg、./图/01.png、D:\pics\a.jpg
        if re.match(r'^(?:[A-Za-z]:[\\/]|[./\\])?[^\s:*?"<>|]+\.'
                    r'(?:jpe?g|png|gif|webp|bmp|svg)$', t, re.IGNORECASE):
            return True
        return False

    def is_meta_line(t):
        """元数据行：书名/作者/链接等前缀、纯日期、日期+发表动词

        注意**不包含图片行**——在这个文件结构里，图片属于简介内容，
        要原样保留给前端渲染，不能当元数据丢掉。
        """
        t = _clean(t)
        if not t:
            return False
        for p in meta_prefixes:
            if t.startswith(p):
                return True
        if re.match(r'^\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?$', t):
            return True
        if re.search(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}', t) and \
           any(k in t for k in ['首发', '发布', '发表', '转发', '独发',
                                '发表于', '首发于', '发布于']):
            return True
        return False

    def is_intro_marker(t):
        """返回 (是否是简介标记, 冒号后的内容)"""
        t = _clean(t)
        for m in intro_markers:
            mt = re.match(rf'^{re.escape(m)}[：:]\s*(.*)$', t)
            if mt:
                return True, mt.group(1).strip()
        return False, ''

    def is_chapter_line(t):
        t = _clean(t)
        if not t:
            return False
        return bool(LEVEL1_PATTERN.match(t) or
                    LEVEL2_PATTERN.match(t) or
                    LEVEL3_PATTERN.match(t))

    # ========== 1. 定位简介段 ==========
    # 起点：跳过开头的元数据行；有「简介：」则从它下一行开始。
    start = 0
    intro_marker_content = ''
    for i in range(min(len(lines), 50)):
        t = _clean(lines[i])
        if not t:
            continue
        is_marker, content = is_intro_marker(t)
        if is_marker:
            intro_marker_content = content
            start = i + 1
            break
        if is_meta_line(t):
            start = i + 1
            continue
        # 章节标题或第一条普通正文 → 简介段从这里开始
        start = i
        break

    # 终点：第一个章节标题行（找不到就到文件末尾）
    end = len(lines)
    for i in range(start, len(lines)):
        if is_chapter_line(_clean(lines[i])):
            end = i
            break

    # ========== 2. 逐行收集 ==========
    # 空行保留（用于分段），图片行保留（前端渲染成图片），其余文字原样保留。
    collected = []
    total_chars = 0

    for line in lines[start:end]:
        t = _clean(line)

        if not t:
            if collected:
                collected.append('')
            continue

        # 图片行：原样保留，交给前端渲染
        if is_image_line(t):
            collected.append(t)
            continue

        # 纯符号分隔行
        if re.match(r'^[\d\s\-/\.=_*#~·—○●◎＊※◇♦♢★☆♡♥✿❀]{3,}$', t):
            continue

        # 其他元数据行（书名/作者/链接等）不属于简介
        if is_meta_line(t):
            continue

        total_chars += len(t)
        if total_chars > 3000:
            # 这一段太长，说明其实是正文而非简介
            return '无简介'

        collected.append(t)

    # 去掉首尾空行
    while collected and not collected[0]:
        collected.pop(0)
    while collected and not collected[-1]:
        collected.pop()

    intro = '\n'.join(collected).strip()

    # 「简介：内容」写在冒号后面的写法
    if intro_marker_content:
        intro = f"{intro_marker_content}\n{intro}".strip() if intro else intro_marker_content

    return intro if intro else '无简介'

# ==================== 缓存加载和保存 ====================
def load_cache():
    global novel_data, _last_cache_rev
    # 注意：不再需要 chapter_cache、image_cache

    # 冷启动自动迁移：库不存在 + 旧 JSON 还在 → 导入后把 JSON 改名 .bak。
    # 热启动直接返回 existing，不重复导入（migrate 内部幂等）。
    try:
        imported, state = cache_store.ensure_ready(CACHE_FILE, CACHE_DB_FILE)
        if imported:
            print(f"✅ 已将 {imported} 本小说从 novel_cache.json 迁移到 SQLite")
    except Exception as e:
        print(f"⚠️ 缓存库初始化失败：{e}")
        traceback.print_exc()
        return False

    if state == 'empty':
        print(f"⚠️ 缓存为空: {CACHE_DB_FILE}")
        return False

    try:
        loaded_novel_data = cache_store.list_books()
        if not loaded_novel_data:
            return False

        novel_data = []

        for novel in loaded_novel_data:
            novel_copy = novel.copy()
            if 'file_path' in novel_copy:
                filename = os.path.basename(novel_copy['file_path'])
                abs_path = os.path.join(NOVEL_DIR, filename)
                novel_copy['file_path'] = abs_path

                if 'has_images' not in novel_copy:
                    image_folder = get_image_folder_for_novel(filename)
                    novel_copy['has_images'] = image_folder is not None
                    novel_copy['image_folder'] = image_folder

                if 'intro' not in novel_copy:
                    novel_copy['intro'] = '无简介'
                if 'preview' not in novel_copy:
                    novel_copy['preview'] = None

            novel_data.append(novel_copy)

        # 🔥 chapter_cache 不加载（运行时缓存，重启后从空开始）
        # 记下当前版本号：本次加载之后由自己引起的写入不再触发重复重载
        _last_cache_rev = cache_store.get_revision()
        print(f"✅ 从缓存加载了 {len(novel_data)} 本小说")
        return True

    except Exception as e:
        print(f"⚠️ 缓存库加载失败：{e}")
        traceback.print_exc()
        return False

#==================== 缓存保存 =====================
def save_cache():
    """把内存里的 novel_data 增量同步进 SQLite。

    原来是「重建整份 JSON 再 dump」——5000 本要写 10MB，在 NAS 上这一步能占到
    整个扫描耗时的一半。现在交给 cache_store.sync_all 做 diff：只有内容真的变了的
    书才会写行，其余既不写也不重算，没变化时一次写入都不会发生。
    """
    global _last_cache_rev
    # 注意：不再需要 chapter_cache
    try:
        relative_novel_data = []
        for novel in novel_data:
            novel_copy = novel.copy()
            if 'file_path' in novel_copy:
                novel_copy['file_path'] = os.path.basename(novel_copy['file_path'])

            image_folder = get_image_folder_for_novel(novel_copy.get('file_path', ''))
            if image_folder:
                novel_copy['has_images'] = True
                novel_copy['image_folder'] = image_folder
            else:
                novel_copy['has_images'] = False
                novel_copy['image_folder'] = None

            if 'intro' not in novel_copy:
                novel_copy['intro'] = '无简介'
            if 'preview' not in novel_copy:
                novel_copy['preview'] = None

            relative_novel_data.append(novel_copy)

        # 🔥 chapter_cache 不再持久化（运行时缓存）
        result = cache_store.sync_all(relative_novel_data)
        # 自己写的不需要再触发一次重新加载（原实现靠 mtime 触发，属白读一遍）
        _last_cache_rev = cache_store.get_revision()

        print(
            f"✅ 已缓存 {len(novel_data)} 本小说"
            f"（新增 {result['inserted']} / 更新 {result['updated']} / "
            f"删除 {result['deleted']} / 未变跳过 {result['unchanged']}）"
        )
    except Exception as e:
        print(f"❌ 缓存保存失败：{e}")
        traceback.print_exc()

#==================== 检测缓存更新 =====================
def should_reload_cache():
    """库里的 revision 变了就说明缓存被写过，需要重新加载。

    原实现比对 novel_cache.json 的 mtime；迁到 SQLite 后没有这个文件了，
    改用 meta.revision（每次写入 +1），语义等价且不用 stat 文件。
    """
    global _last_cache_rev
    try:
        current_rev = cache_store.get_revision()
    except Exception as e:
        logger.error(f"读取缓存版本失败: {e}")
        return False
    if current_rev != _last_cache_rev:
        _last_cache_rev = current_rev
        return True
    return False

@app.before_request
def check_cache_update():
    if request.path.startswith('/api/scan'):
        return
    if _scan_active:
        return  # 扫描进行中不重载，避免读到写了一半的缓存
    if should_reload_cache():
        print("🔄 检测到缓存已更新，重新加载...")
        load_cache()

# ==================== 扫描函数 ====================
def scan_novel_files_background(full_scan=False):
    """扫描入口：跨进程锁保证同一时刻只有一个扫描任务"""
    global _scan_active

    if not os.path.exists(NOVEL_DIR):
        scan_progress['status'] = 'error'
        scan_progress['message'] = f'目录不存在：{NOVEL_DIR}'
        return

    logger.info(f"开始扫描 - full_scan={full_scan}, 当前小说数={len(novel_data)}")

    try:
        with file_lock(SCAN_LOCK_FILE, blocking=False):
            print("🔒 获取扫描锁成功，开始扫描...")
            _scan_active = True
            try:
                _scan_core(full_scan)
            finally:
                _scan_active = False
                print("🔓 释放扫描锁")
    except BlockingIOError:
        print("⚠️ 另一个进程正在扫描，跳过本次扫描")
        scan_progress['status'] = 'idle'
        scan_progress['message'] = '另一个扫描任务正在进行中'
    except Exception as e:
        logger.error(f"扫描任务异常: {e}")
        traceback.print_exc()
        scan_progress['status'] = 'error'
        scan_progress['message'] = f'扫描出错：{e}'

def _scan_core(full_scan=False):
    """实际扫描逻辑（调用方必须已持有扫描锁）"""
    global novel_data

    # 🔥 初始化，防止全量扫描时未定义
    unchanged_count = 0
    removed_files = []
    files_to_scan = []
    temp_data_map = {}
    skipped_files = []
    existing_map = {}       # 仅增量扫描时填充；全量扫描保持为空
    renamed_count = 0
    media_changed = False   # 未变化文件的配图/视频/音频标签是否被刷新过

    try:
        scan_progress['status'] = 'scanning'
        scan_progress['current'] = 0
        scan_progress['phase'] = 'scan_dir'
        scan_progress['incremental'] = not full_scan
        scan_progress['message'] = '正在扫描目录...'
        # 记录「扫描进行中」标记：正常结束会清除，进程若在扫描途中重启，
        # 下次启动时 check_interrupted_scan() 就能发现上次没跑完
        try:
            save_scan_stats({
                'scan_in_progress': {
                    'type': 'full' if full_scan else 'incremental',
                    'start_time': time.time(),
                }
            })
        except Exception as e:
            logger.warning(f"写入扫描进行中标记失败（不影响扫描）：{e}")
        scan_progress['start_time'] = time.time()

        _image_check_cache.clear()
        # 配图目录解析缓存必须每轮扫描前清空：用户可能刚新建/改名/删除了
        # *_images / *_配图 目录，沿用上一轮结果会让「配图」标签长期滞后。
        _image_folder_cache.clear()

        all_files = {}
        for filename in os.listdir(NOVEL_DIR):
            if filename.endswith(('.txt', '.TXT')):
                file_path = os.path.join(NOVEL_DIR, filename)
                all_files[filename] = file_path

        scan_progress['total'] = len(all_files)

        # ========== 🔥 核心优化：使用字典映射代替列表合并 ==========
        if not full_scan and novel_data:
            # 建立文件名到数据的映射（旧缓存可能缺 filename，跳过脏数据）
            existing_map = {}
            for item in novel_data:
                name = item.get('filename')
                if name:
                    existing_map[name] = item
            print(f"📊 现有小说数: {len(existing_map)}")
            
            # 🔥 找出被删除/重命名的文件（在 existing_map 中但不在 all_files 中）
            removed_files = [f for f in existing_map if f not in all_files]
            if removed_files:
                print(f"🗑️ 检测到 {len(removed_files)} 个文件已被删除或重命名: {removed_files[:5]}...")
                # 清理这些文件的缓存
                for filename in removed_files:
                    file_path = existing_map[filename].get('file_path', '')
                    if file_path:
                        chapter_cache.pop(file_path, None)
                        tag_parse_cache.pop(file_path, None)

            
            # 先把「已删除/已改名」的旧条目从 existing_map 移除，作为结果基座。
            # 必须在下面识别改名之前做，否则识别出的条目会被基座覆盖。
            for filename in removed_files:
                del existing_map[filename]
            temp_data_map = existing_map.copy()

            files_to_scan = []
            unchanged_count = 0
            renamed_count = 0

            # work_id -> 旧条目：用于识别「同一本书换了文件名」
            existing_by_work_id = {}
            for item in temp_data_map.values():
                wid = item.get('work_id')
                if wid:
                    existing_by_work_id.setdefault(wid, item)

            _check_total = len(all_files)
            _checked = 0
            for filename, file_path in all_files.items():
                _checked += 1
                # 每 50 个文件刷新一次进度：这是增量扫描最耗时的环节
                if _checked % 50 == 0:
                    scan_progress['current'] = _checked
                    scan_progress['total'] = _check_total
                    scan_progress['message'] = f'正在检查书目：{_checked}/{_check_total}'
                try:
                    current_mtime = os.path.getmtime(file_path)
                except OSError as e:
                    logger.warning(f"跳过无法访问的文件 {filename}: {e}")
                    skipped_files.append(filename)
                    continue

                if filename in existing_map:
                    old_item = existing_map[filename]
                    old_mtime = old_item.get('mtime')

                    # 文件未变化，保留旧数据
                    if old_mtime == current_mtime:
                        # 只更新配图信息（轻量级操作）
                        new_image_folder = get_image_folder_for_novel(filename)
                        old_item['has_images'] = new_image_folder is not None
                        old_item['image_folder'] = new_image_folder

                        # 🔥 修复「配图/视频/音频标签不更新」：
                        # 这三个标签原本只在 parse_file_content_fast 里生成，
                        # 而未变化的文件不会重跑该函数 —— 于是你后来往配图目录
                        # 里加了图/视频，标签永远停在首次扫描那一刻。
                        # 这里对未变化文件单独重算媒体标签：成本仅一次目录遍历
                        # （配图目录通常很小），远低于重解析整本小说。
                        if new_image_folder:
                            if _refresh_media_tags(old_item, new_image_folder):
                                media_changed = True
                        else:
                            if _strip_media_tags(old_item):
                                media_changed = True

                        unchanged_count += 1
                        continue
                    else:
                        # 文件变化，清除旧缓存
                        chapter_cache.pop(file_path, None)
                        tag_parse_cache.pop(file_path, None)
                        files_to_scan.append(filename)
                else:
                    # 新文件名：先看内容是否对应一本已知的书（重命名场景）
                    new_work_id = compute_work_id(file_path)
                    reused = existing_by_work_id.get(new_work_id) if new_work_id else None
                    if reused is not None:
                        # 内容是同一本书，只是改名了：继承旧条目，保留 work_id
                        adopted = dict(reused)
                        adopted['filename'] = filename
                        adopted['file_path'] = file_path
                        adopted['mtime'] = current_mtime
                        adopted['file_size'] = os.path.getsize(file_path) // 1024
                        adopted['progress'] = parse_progress(filename)
                        new_image_folder = get_image_folder_for_novel(filename)
                        adopted['has_images'] = new_image_folder is not None
                        adopted['image_folder'] = new_image_folder
                        temp_data_map[filename] = adopted
                        # 该 work_id 只能被认领一次
                        existing_by_work_id.pop(new_work_id, None)
                        renamed_count += 1
                        logger.info(f"🔁 识别为改名（work_id 沿用）: {reused.get('filename')} -> {filename}")
                        continue
                    # 真正的新文件
                    files_to_scan.append(filename)

            
            print(f"📊 未变化: {unchanged_count}, 需扫描: {len(files_to_scan)}, 已删除: {len(removed_files)}")
            # 检查阶段收尾，切到解析阶段（百分比由接口按阶段加权）
            scan_progress['phase'] = 'parse'
            scan_progress['current'] = 0
            scan_progress['total'] = len(files_to_scan)
            
            
        else:
            # 全量扫描：清空所有缓存
            chapter_cache.clear()
            tag_parse_cache.clear()
            image_cache.clear()
            _image_check_cache.clear()
            files_to_scan = list(all_files.keys())
            temp_data_map = {}
            # 全量扫描没有「检查书目」阶段，必须切到 parse。
            # 否则 phase 一直停在 scan_dir，接口按「检查阶段占 0-55%」计算，
            # 进度条最多只到 55%，然后扫描结束时瞬间跳到 100%。
            scan_progress['phase'] = 'parse'
            scan_progress['current'] = 0
            scan_progress['total'] = len(files_to_scan)
            print(f"📊 全量扫描，文件数: {len(files_to_scan)}")

        # ========== 批次解析 ==========
        batch_size = 20
        processed_count = 0
        
        for batch_start in range(0, len(files_to_scan), batch_size):
            batch = files_to_scan[batch_start:batch_start + batch_size]
            
            for filename in batch:
                scan_progress['current'] += 1
                processed_count += 1
                scan_progress['message'] = f'正在解析：{filename[:30]}... ({processed_count}/{len(files_to_scan)})'

                file_path = all_files[filename]

                if not is_file_readable(file_path):
                    skipped_files.append(filename)
                    continue

                # 单个文件出错不再中断整次扫描
                try:
                    # work_id：优先沿用旧条目（文件只改了少量内容时保持稳定），
                    # 否则按当前内容计算。改文件名不影响 work_id。
                    old_entry = existing_map.get(filename) if existing_map else None
                    work_id = old_entry.get('work_id') if old_entry else None

                    # 🔥 性能关键：整本只读一次。
                    # work_id 需要全文，parse_novel_details 也需要全文，
                    # 过去各读一次（NAS 上每本多付一次几百毫秒）。
                    # 这里先读一次，解码结果同时喂给两者。
                    # 只有在「真的需要重算 work_id」或「详情没缓存」时才读；
                    # 两者都不需要则完全不读盘。
                    details_cached = file_path in chapter_cache and \
                        isinstance(chapter_cache.get(file_path), dict) and \
                        chapter_cache[file_path].get('file_hash') == get_file_hash(file_path)

                    prefetched = None
                    if not work_id or not details_cached:
                        raw_data, text = read_and_decode_novel(file_path)
                        prefetched = (raw_data, text)

                    if not work_id:
                        work_id = compute_work_id(
                            file_path,
                            text=(prefetched[1] if prefetched else None))

                    base_info = {
                        'filename': filename,
                        'progress': parse_progress(filename),
                        'file_size': os.path.getsize(file_path) // 1024,
                        'file_hash': get_file_hash(file_path),
                        'mtime': os.path.getmtime(file_path),
                        'file_path': file_path,
                        'work_id': work_id
                    }

                    # 获取元数据
                    content_info = parse_file_content_fast(file_path)

                    # 获取章节详情（复用上面已读好的全文，避免二次整本读取）
                    detail_info = parse_novel_details(file_path, prefetched=prefetched)
                    if detail_info.get('intro') and detail_info.get('intro') != '无简介':
                        if not any(kw in detail_info['intro'] for kw in ['书名：', '作者：', '标签：', '链接：']):
                            content_info['intro'] = detail_info['intro']
                    elif 'intro' not in content_info:
                        content_info['intro'] = '无简介'

                    novel_info = {**base_info, **content_info}

                    # 🔥 修复：全量扫描/重新解析的条目必须补上配图目录字段。
                    # 过去只有「未变化」与「改名」两个分支会写 has_images /
                    # image_folder，走 parse 分支的条目（含全量扫描的全部书）
                    # 这两个字段一直是缺失的（has_images=False, image_folder=None），
                    # 于是详情页/筛选拿不到配图信息，即使 _images 目录确实存在。
                    _img_folder = get_image_folder_for_novel(filename)
                    novel_info['has_images'] = _img_folder is not None
                    novel_info['image_folder'] = _img_folder

                    # 存入字典
                    temp_data_map[filename] = novel_info
                except Exception as e:
                    logger.error(f"解析文件失败（已跳过）{filename}: {e}")
                    skipped_files.append(filename)
                    continue
                
                # 每处理5个文件检查一次缓存
                if processed_count % 5 == 0:
                    if len(tag_parse_cache) > MAX_TAG_PARSE_CACHE * 0.8:
                        cleanup_cache()

            # 每批次后强制清理
            if (batch_start // batch_size) % 10 == 0:
                cleanup_cache()
                gc.collect()
            
            # 原先这里是 time.sleep(0.05) —— 1000 本就白等 2.5 秒。
            # 本意应是「让出 CPU 给请求线程」，用 sleep(0) 达到同样目的且不拖慢。
            # （真正的瓶颈是磁盘 I/O，不是 CPU 抢占。）
            time.sleep(0)

        # ========== 直接替换数据，避免累积 ==========
        if temp_data_map:
            unique_names = set()
            duplicate_count = 0
            cleaned_data = []
            for novel in temp_data_map.values():
                name = novel.get('filename', '')
                if name not in unique_names:
                    unique_names.add(name)
                    cleaned_data.append(novel)
                else:
                    duplicate_count += 1

            if duplicate_count > 0:
                print(f"⚠️ 发现 {duplicate_count} 个重复条目，正在清理...")

            cleaned_data.sort(key=lambda x: x.get('filename', '').lower())
            novel_data = cleaned_data
            # 只有真的发生变化才重写缓存。全量扫描必然有 files_to_scan；
            # 增量扫描若全部未变化（最常见的情况），跳过可省下重写十几 MB 的开销
            # —— 在 NAS 上这一步原本占整个扫描耗时的一半。
            if files_to_scan or removed_files or renamed_count or media_changed:
                save_cache()
                print(f"✅ 扫描完成，最终小说数: {len(novel_data)}")
            else:
                print(f"✅ 扫描完成（无任何变化，跳过写盘），共 {len(novel_data)} 本")
        else:
            print("⚠️ 扫描完成，没有变化")

        # ========== 更新状态 ==========
        if not full_scan:
            message_parts = []
            if files_to_scan:
                message_parts.append(f"更新 {len(files_to_scan)} 本")
            if unchanged_count > 0:
                message_parts.append(f"保留 {unchanged_count} 本")
            if renamed_count > 0:
                message_parts.append(f"识别改名 {renamed_count} 本")
            if removed_files:
                message_parts.append(f"删除 {len(removed_files)} 本")
            if skipped_files:
                message_parts.append(f"跳过 {len(skipped_files)} 本")
            scan_progress['message'] = f"扫描完成！{', '.join(message_parts)}" if message_parts else '扫描完成，没有变化'
        else:
            message_parts = [f'共 {len(novel_data)} 本小说']
            if skipped_files:
                message_parts.append(f'跳过 {len(skipped_files)} 本')
            scan_progress['message'] = f"全量扫描完成！{', '.join(message_parts)}"

        scan_progress['status'] = 'completed'
        cache['filter_options'] = None
        # 进度计数收尾打印：用于核对 current 是否走到 total（排查进度条不到头的问题）
        print(f"📊 进度计数收尾: {scan_progress['current']}/{scan_progress['total']} "
              f"（{'全量' if full_scan else '增量'}，阶段 {scan_progress.get('phase')}）")

        # ========== 持久化本次扫描统计，供首页「扫描管理」区块展示「上次扫描」信息 ==========
        try:
            start_time = scan_progress.get('start_time') or time.time()
            duration = time.time() - start_time
            scan_stats = {
                'last_scan_time': time.time(),
                'last_scan_type': 'full' if full_scan else 'incremental',
                'last_scan_total': len(novel_data),
                'last_scan_scanned': len(files_to_scan),
                'last_scan_renamed': renamed_count,
                'last_scan_removed': len(removed_files),
                'last_scan_skipped': len(skipped_files),
                'last_scan_duration': round(duration, 1),
                # 本次正常结束：清掉进行中标记
                'scan_in_progress': None,
            }
            # 中断告警的清除要保守：启动时的自动增量扫描只要 2 秒，
            # 若无条件清除，用户还没打开页面告警就没了。
            # 规则：全量扫描成功 → 清除任何告警；增量扫描成功 → 只清除「增量被中断」的告警。
            prev = load_scan_stats()
            pending = prev.get('last_scan_interrupted') if isinstance(prev, dict) else None
            keep_warn = bool(pending) and not full_scan and pending.get('type') == 'full'
            scan_stats['last_scan_interrupted'] = pending if keep_warn else None
            # 全量扫描成功才更新，增量扫描不碰它（merge 写入会保留旧值）
            if full_scan:
                scan_stats['last_full_scan_time'] = scan_stats['last_scan_time']
            save_scan_stats(scan_stats)
        except Exception as e:
            print(f"⚠️ 保存扫描统计失败：{e}")

        print(f"✅ 扫描完成，共 {len(novel_data)} 本小说")

    except Exception as e:
        scan_progress['status'] = 'error'
        scan_progress['message'] = f'扫描出错：{str(e)}'
        print(f"❌ 扫描失败：{e}")
        traceback.print_exc()
        # 扫描出错：清掉进行中标记，并留下可展示的中断原因
        try:
            save_scan_stats({
                'scan_in_progress': None,
                'last_scan_interrupted': {
                    'type': 'full' if full_scan else 'incremental',
                    'start_time': scan_progress.get('start_time'),
                    'reason': f'扫描出错：{e}',
                },
            })
        except Exception:
            pass

    finally:
        # 兜底：任何未预期路径都不要留下「进行中」标记，否则下次启动会误报
        if scan_progress.get('status') != 'completed':
            try:
                save_scan_stats({'scan_in_progress': None})
            except Exception:
                pass
        # 扫描后温和清理：保留 50 本，避免用户立刻点进详情又要重解析
        aggressive_cache_cleanup(keep_tag=200, keep_chapter=50, keep_image=200)
        # line_cache 存的是扫描期解析出的正文行，通常是大头；
        # 不清的话扫描完 RSS 会长期停在峰值，看起来像内存泄漏
        line_cache.clear()
        gc.collect()
        # glibc 默认不把已 free 的内存还给 OS，必须显式 trim，容器里 RSS 才会降
        trim_memory()

#==================== 定时扫描循环 =====================
def scheduled_scan_loop():
    """定时扫描循环 - 每30秒检查一次，配置改了也能较快生效"""
    last_scan_time = time.time()
    logger.info("⏰ 定时扫描线程已启动")

    while True:
        try:
            interval_hours = CONFIG.get('scan_interval_hours', 0)

            if interval_hours <= 0:
                time.sleep(60)
                continue

            interval_seconds = interval_hours * 3600
            now = time.time()
            elapsed = now - last_scan_time

            if elapsed >= interval_seconds:
                if scan_progress['status'] != 'scanning':
                    logger.info(f"🔍 执行定时扫描... [{time.strftime('%Y-%m-%d %H:%M:%S')}]")
                    scan_novel_files_background(full_scan=False)
                    last_scan_time = time.time()
                else:
                    logger.info("⚠️ 定时扫描跳过：已有扫描任务进行中，30秒后重试")
                    time.sleep(30)
                    continue

            time.sleep(30)
        except Exception as e:
            logger.error(f"定时扫描循环出错: {e}")
            time.sleep(60)

# ==================== 路由 ====================

#==================== API 路由 =====================


#==================== 获取过滤选项（带缓存） =====================
def split_author_aliases(author):
    """把「主名（马甲1,马甲2）」拆成 (主名, [马甲...])。

    元数据里同一作者的马甲统一写成：金鳞庸人（uwkuk8k,财狼少年）
    主名是括号前的部分；括号内用 , ， 、 & ＆ / ｜ 分隔都认
    （实际数据里主要是英文逗号）。

    没有括号时返回 (原串, [])。
    """
    if not author:
        return '', []

    text = str(author).strip()
    match = re.match(r'^(.*?)[（(]([^）)]*)[）)]\s*(.*)$', text)
    if not match:
        return text, []

    main = match.group(1).strip()
    inner = match.group(2).strip()
    tail = match.group(3).strip()

    if not main or not inner:
        return text, []

    aliases = [a.strip() for a in re.split(r'[,，、&＆/／|]+', inner) if a.strip()]

    if tail:
        main = f'{main} {tail}'.strip()

    return main, aliases


def author_names_of(author):
    """返回这本书涉及的全部名号：[主名, 马甲1, 马甲2...]"""
    main, aliases = split_author_aliases(author)
    if not main:
        return []
    return [main] + aliases


def build_author_identity_map(novels=None):
    """建立「任一名号 -> 该作者的全部名号」映射，用于把马甲和主名视为同一个人。

    例：{'金鳞庸人': {'金鳞庸人','uwkuk8k','财狼少年'},
         '财狼少年': {'金鳞庸人','uwkuk8k','财狼少年'}}

    这样下拉里选主名或选马甲，都能列出这个人署名的全部书。
    """
    source = novel_data if novels is None else novels
    # 先按主名把马甲并起来（同一主名在不同书里可能只写了部分马甲）
    merged = {}
    for n in source or []:
        main, aliases = split_author_aliases((n.get('author') or ''))
        if not main:
            continue
        bucket = merged.setdefault(main, set())
        bucket.add(main)
        bucket.update(aliases)

    lookup = {}
    for names in merged.values():
        for name in names:
            # 同名冲突时保留已有的（先到先得，避免来回覆盖）
            lookup.setdefault(name, names)
    return lookup


# ==================== 相似书籍推荐 ====================
# 用途：详情页 + 阅读页最后一页的「相似书籍」区块。锦上添花的功能，
# 刻意保持简单：只用书名 / 作者 / 标签，不引第三方库、不落盘、不加配置项。
#
# 取舍：宁缺毋滥 —— 分数不到阈值就不返回，调用方据此整块不渲染，
# 不拿随机书或弱标签凑数。
#
# 书名解析（parse_title_meta）解决三件事：
#   1) 系列：「系列名 + 第几部」拆开，同系列排一起、按卷次
#   2) 关系：番外 / 同人 / 外传 / 前传 / 续 单独标出，不跟原书混为一谈
#   3) 噪声：番号（FC2PPV-3179361）、原名/又名、【征文】这类尾巴不参与计算
#
# ⚠️ 冒号/下划线截出来的「系列根名」默认不可信：「XX：YY」这种修辞副标题会截出
#    两个字的假系列。只有该根名在全库出现 >= 2 次才认，否则回退完整书名。
#    实测 5102 本可聚出 266 个真系列簇。

SIMILAR_LIMIT = 8              # 最多几条
SIMILAR_THRESHOLD = 22.0       # 低于此分不展示
SIMILAR_SERIES_CAP = 3         # 同一系列最多占几条
SIMILAR_TAGS_FOR_MATCH = 6     # 只吃前 6 个高权重标签（每本中位数 46 个，全量算人人相似）
SIMILAR_GRAM_HOT_RATIO = 0.05  # 覆盖超过 5% 的二元组算热词，不进候选
SIMILAR_MIN_GRAM_HITS = 3      # 书名二元组至少命中几个才算候选

_SIM_TAIL_BRACKET_RE = re.compile(r'[（(【\[《]([^（()）【】\[\]《》]*)[）)】\]》]\s*$')
_SIM_VOLUME_RE = re.compile(r'第\s*([0-9一二三四五六七八九十百零两〇]{1,4})\s*[部卷册集篇季]')
_SIM_TRAIL_NUM_RE = re.compile(r'(?<=[\u4e00-\u9fa5])[\s·]*([0-9]{1,2})\s*$')
_SIM_CODE_RE = re.compile(r'(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9]{1,9})[-_ ]?([0-9]{3,})(?![0-9])')
_SIM_ALIAS_RE = re.compile(r'(?:原名|又名)\s*[:：]?\s*(.+)$')
_SIM_SEP_RE = re.compile(r'[_＿]|[:：]|—{2,}')
_SIM_CN_DIGITS = {
    '零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
    '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
}
_SIM_RELATIONS = (
    ('番外', 'fanwai'), ('同人', 'tongren'), ('外传', 'waizhuan'),
    ('外篇', 'waizhuan'), ('前传', 'qianchuan'), ('后传', 'xuji'),
    ('续集', 'xuji'), ('续篇', 'xuji'),
)
_SIM_RELATION_LABEL = {
    'main': '', 'fanwai': '番外', 'tongren': '同人',
    'waizhuan': '外传', 'qianchuan': '前传', 'xuji': '续',
}
_SIM_CONTINUE_SKIP = '继续连持陆'
# 这些不是真作者，不能拿来做「同作者」匹配（否则 159 本 [不详] 会互相推荐）
_SIM_UNKNOWN_AUTHORS = {
    '', '[不详]', '【不详】', '不详', '未知作者', '未知', '匿名', '佚名', '-', '—', '无',
}


def _sim_cn_to_int(text):
    """一~九十九 的中文数字转整数；认不出返回 None。"""
    text = (text or '').strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if '十' in text:
        left, _, right = text.partition('十')
        if left and left not in _SIM_CN_DIGITS:
            return None
        if right and right not in _SIM_CN_DIGITS:
            return None
        tens = _SIM_CN_DIGITS.get(left, 1) if left else 1
        ones = _SIM_CN_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    return _SIM_CN_DIGITS.get(text)


def _sim_find_relation(text):
    """返回 (relation, 位置)，取最靠前的关系词；没找到返回 ('main', -1)。"""
    best_pos, best_rel = -1, 'main'
    for word, rel in _SIM_RELATIONS:
        pos = text.find(word)
        if pos >= 0 and (best_pos < 0 or pos < best_pos):
            best_pos, best_rel = pos, rel
    # 单字「续」：前面是 继/连/持/陆 的不算（继续、连续、持续、陆续）
    for pos, char in enumerate(text):
        if char != '续':
            continue
        prev = text[pos - 1] if pos else ''
        if prev and prev in _SIM_CONTINUE_SKIP:
            continue
        if best_pos < 0 or pos < best_pos:
            best_pos, best_rel = pos, 'xuji'
        break
    return best_rel, best_pos


def _sim_clean(text):
    """去掉空白与残留分隔符，用于书名归一化比较。"""
    return re.sub(r'[\s\u3000·・]+', '', text or '').strip('_＿-—:：')


def parse_title_meta(title):
    """把书名拆成：系列根名 / 卷次 / 关系（番外·同人·续·外传）/ 原名 / 番号。

    返回的 dict 字段始终齐全。base 只是「候选系列根名」，是否可信由调用方
    按全库频次判定（见 _build_similar_index），避免冒号截断出假系列。
    """
    raw = (title or '').strip()
    meta = {
        'raw': raw, 'base': '', 'base_full': '', 'volume': None,
        'relation': 'main', 'relation_label': '', 'aliases': [], 'code': '', 'note': '',
    }
    if not raw:
        return meta

    text = raw.replace('《', '').replace('》', '').strip()

    # 1) 尾部括号逐层剥离（最多两层）：卷次 / 原名 / 番号 / 关系词 / 题材标注
    for _ in range(2):
        match = _SIM_TAIL_BRACKET_RE.search(text)
        if not match:
            break
        inner = (match.group(1) or '').strip()
        if not inner:
            break

        consumed = False
        volume = _SIM_VOLUME_RE.search(inner)
        if volume:
            meta['volume'] = _sim_cn_to_int(volume.group(1))
            consumed = True
        elif re.fullmatch(r'[0-9]{1,2}', inner):
            meta['volume'] = int(inner)
            consumed = True
        elif inner in ('上', '中', '下'):
            meta['volume'] = {'上': 1, '中': 2, '下': 3}[inner]
            consumed = True

        if not consumed:
            alias = _SIM_ALIAS_RE.search(inner)
            if alias:
                meta['aliases'].append(alias.group(1).strip())
                consumed = True

        if not consumed and len(inner) <= 20:
            code = _SIM_CODE_RE.search(inner)
            if code:
                meta['code'] = f'{code.group(1).upper()}-{code.group(2)}'
                consumed = True

        if not consumed:
            relation, _pos = _sim_find_relation(inner)
            if relation != 'main':
                meta['relation'] = relation
                consumed = True

        if not consumed and not meta['note']:
            meta['note'] = inner

        text = text[:match.start()].strip()
        if not text:
            break

    # 2) 关系词：整段书名里再找一次（拆掉括号后可能才露出来）
    relation, _pos = _sim_find_relation(text)
    if meta['relation'] == 'main' and relation != 'main':
        meta['relation'] = relation

    # 3) 分隔符左侧 = 系列名候选
    head = text
    sep = _SIM_SEP_RE.search(text)
    if sep and sep.start() >= 2:
        head = text[:sep.start()].strip()

    # 4) 卷次：「第X部」或书名尾部裸数字
    volume = _SIM_VOLUME_RE.search(head)
    if volume and meta['volume'] is None:
        meta['volume'] = _sim_cn_to_int(volume.group(1))
    head = _SIM_VOLUME_RE.sub('', head)
    trailing = _SIM_TRAIL_NUM_RE.search(head)
    if trailing:
        if meta['volume'] is None:
            meta['volume'] = int(trailing.group(1))
        head = head[:trailing.start()].strip()

    meta['base'] = _sim_clean(head)
    meta['base_full'] = _sim_clean(text)
    meta['relation_label'] = _SIM_RELATION_LABEL.get(meta['relation'], '')
    if not meta['base']:
        meta['base'] = meta['base_full']
    return meta


def _sim_grams(text, size=2):
    """中文/字母数字二元组集合，用于抓「同格式书名同族」（如番号类长标题）。"""
    cleaned = re.sub(r'[^\u4e00-\u9fa5A-Za-z0-9]', '', text or '')
    if len(cleaned) < size:
        return set()
    return {cleaned[i:i + size] for i in range(len(cleaned) - size + 1)}


def _sim_split_tags(value):
    """标签兼容字符串（缓存里是逗号分隔）和 list（内存里可能是 list）。"""
    if isinstance(value, (list, tuple, set)):
        items = [str(tag).strip() for tag in value]
    else:
        items = [tag.strip() for tag in str(value or '').split(',')]
    return [tag for tag in items if tag and tag != '无']


_similar_index_cache = {'key': None, 'data': None}


def _build_similar_index():
    """建倒排索引：系列 / 作者身份组 / 书名二元组 / 标签。全库一次，约 70ms。"""
    novels = novel_data or []
    if not novels:
        return None

    identity = build_author_identity_map(novels)
    metas = []
    base_count = {}
    for novel in novels:
        meta = parse_title_meta(novel.get('title') or '')
        metas.append(meta)
        if meta['base']:
            base_count[meta['base']] = base_count.get(meta['base'], 0) + 1

    by_series, by_author, by_gram, by_tag = {}, {}, {}, {}
    tag_sets = []
    authors = []

    for idx, (novel, meta) in enumerate(zip(novels, metas)):
        # 系列根名必须全库 >= 2 次才算数，否则用完整书名当 key（防假系列）
        series_key = meta['base'] if base_count.get(meta['base'], 0) >= 2 else meta['base_full']
        meta['series_key'] = series_key
        if series_key:
            by_series.setdefault(series_key, []).append(idx)

        names = author_names_of(novel.get('author') or '')
        group = ''
        if names and names[0] not in _SIM_UNKNOWN_AUTHORS:
            group = sorted(identity.get(names[0]) or {names[0]})[0]
            by_author.setdefault(group, []).append(idx)
        meta['author_group'] = group
        authors.append((names[0] if names else '', max(0, len(names) - 1)))

        meta['grams'] = _sim_grams(meta['raw'])
        for gram in meta['grams']:
            by_gram.setdefault(gram, []).append(idx)

        tag_set = set(_sim_split_tags(novel.get('tags'))[:SIMILAR_TAGS_FOR_MATCH])
        tag_sets.append(tag_set)
        for tag in tag_set:
            by_tag.setdefault(tag, []).append(idx)

    return {
        'novels': novels, 'metas': metas, 'base_count': base_count,
        'alias_group': identity, 'by_series': by_series, 'by_author': by_author,
        'by_gram': by_gram, 'by_tag': by_tag, 'tag_sets': tag_sets,
        'authors': authors, 'total': len(novels),
    }


def _get_similar_index():
    """索引生命周期跟着 novel_data 这个列表对象走，不落盘。

    扫描/重载缓存都是整体替换 `novel_data = [...]`（load_cache 与扫描分支都是新列表），
    所以比较对象身份 + 长度就能准确判断要不要重建，比按目录 mtime 更可靠
    （扫描只读目录，mtime 不会变）。
    """
    cached = _similar_index_cache
    data = cached['data']
    if (data is not None and data['novels'] is novel_data
            and len(data['novels']) == len(novel_data or [])):
        return data
    data = _build_similar_index()
    cached['key'] = (id(novel_data), len(novel_data or []))
    cached['data'] = data
    return data


def find_similar_novels(title, author, tags, exclude_work_id='', exclude_path='',
                        limit=SIMILAR_LIMIT):
    """找相似书籍，返回按相关度排好的 list。

    打分：系列根名相同 60 / 作者身份组相同（含马甲）30 /
          书名二元组 Jaccard ×20 / 标签 Jaccard ×15，满分 125。
    不到 SIMILAR_THRESHOLD 直接丢弃；同系列最多 SIMILAR_SERIES_CAP 条。
    """
    index = _get_similar_index()
    if not index:
        return []

    novels = index['novels']
    metas = index['metas']
    total = index['total']
    base_count = index['base_count']
    hot_limit = max(1, int(total * SIMILAR_GRAM_HOT_RATIO))

    query_meta = parse_title_meta(title)
    query_base = query_meta['base']
    query_series = query_base if base_count.get(query_base, 0) >= 2 else query_meta['base_full']
    query_grams = _sim_grams(query_meta['raw'])
    query_tags = set(_sim_split_tags(tags)[:SIMILAR_TAGS_FOR_MATCH])

    query_group = ''
    names = author_names_of(author or '')
    if names and names[0] not in _SIM_UNKNOWN_AUTHORS:
        query_group = sorted(index['alias_group'].get(names[0]) or {names[0]})[0]

    # === 候选集：系列 + 作者 + 书名二元组 + 非热标签，上限通常两三百本 ===
    candidates = set()
    if query_series:
        candidates.update(index['by_series'].get(query_series, ()))
    if query_group:
        candidates.update(index['by_author'].get(query_group, ()))

    gram_hits = {}
    for gram in query_grams:
        posting = index['by_gram'].get(gram)
        if not posting or len(posting) > hot_limit:
            continue
        for idx in posting:
            gram_hits[idx] = gram_hits.get(idx, 0) + 1
    candidates.update(idx for idx, hits in gram_hits.items() if hits >= SIMILAR_MIN_GRAM_HITS)

    for tag in query_tags:
        posting = index['by_tag'].get(tag)
        if not posting or len(posting) > hot_limit:
            continue
        candidates.update(posting)

    exclude_name = os.path.basename(exclude_path or '')
    items = []
    for idx in candidates:
        novel = novels[idx]
        if exclude_work_id and novel.get('work_id') == exclude_work_id:
            continue
        if exclude_name and os.path.basename(novel.get('file_path') or '') == exclude_name:
            continue

        meta = metas[idx]
        matched = []
        score = 0.0
        is_series = bool(query_series) and meta.get('series_key') == query_series
        if is_series:
            score += 60.0
            matched.append('series')
        else:
            other_grams = meta.get('grams') or set()
            union = len(query_grams | other_grams)
            if union:
                score += 20.0 * len(query_grams & other_grams) / union
        if query_group and meta.get('author_group') == query_group:
            score += 30.0
            matched.append('author')

        other_tags = index['tag_sets'][idx]
        union = len(query_tags | other_tags)
        common_tags = len(query_tags & other_tags)
        if union:
            score += 15.0 * common_tags / union
        if score < SIMILAR_THRESHOLD:
            continue

        labels = []
        if is_series:
            labels.append('系列' + (f'·第{meta["volume"]}部' if meta.get('volume') else ''))
        if meta['relation'] != 'main':
            labels.append(meta['relation_label'])
        if not labels:
            labels.append('同作者' if 'author' in matched else '同标签')

        author_name, alias_count = index['authors'][idx]
        items.append({
            'title': novel.get('title') or meta['raw'],
            'author': author_name or '未知作者',
            'alias_count': alias_count,
            'reason': ' · '.join(label for label in labels if label),
            'score': round(score, 1),
            'volume': meta.get('volume') or 0,
            'is_series': is_series,
            'is_main': meta['relation'] == 'main',
            'series_key': meta.get('series_key') or '',
            'file_path': (novel.get('file_path') or '').lstrip('/'),
        })

    # 系列整体排前面；系列内部按「本篇 → 卷次」，避免番外/同人把原书挤出前 3 条
    items.sort(key=lambda item: (
        0 if item['is_series'] else 1,
        0 if item['is_main'] else 1,
        item['volume'],
        -item['score'],
        item['title'],
    ))

    picked = []
    series_used = {}
    for item in items:
        if item['is_series']:
            used = series_used.get(item['series_key'], 0)
            if used >= SIMILAR_SERIES_CAP:
                continue
            series_used[item['series_key']] = used + 1
        picked.append(item)
        if len(picked) >= limit:
            break
    return picked


def build_similar_urls(items, **query):
    """给相似项补详情页链接，并带上当前列表的筛选参数（返回列表不丢状态）。"""
    clean = {key: value for key, value in query.items() if value not in (None, '', 0)}
    for item in items:
        item['detail_url'] = url_for('library.novel_detail', file_path=item['file_path'], **clean)
    return items


def get_filter_options_cached():
    current_hash = get_data_hash(novel_data)

    if cache['filter_options'] and cache['data_hash'] == current_hash:
        return cache['filter_options']

    if not novel_data:
        result = [], [], []
    else:
        author_count = {}
        for n in novel_data:
            author = n.get('author') or '未知作者'
            if author == '未知作者':
                continue
            # 一本书可能同时挂多个名号（主名 + 马甲）。
            # 按「该名号名下的书数」计数，这样主名和马甲都能作为筛选项出现，
            # 且计数反映的是各自实际署名的数量。
            for name in author_names_of(author):
                author_count[name] = author_count.get(name, 0) + 1
        authors = sorted(author_count.keys(), key=lambda x: (-author_count[x], x))

        site_count = {}
        for n in novel_data:
            site = n.get('site') or '未知网站'
            if site != '未知网站':
                site_count[site] = site_count.get(site, 0) + 1
        sites = sorted(site_count.keys(), key=lambda x: (-site_count[x], x))

        tag_count = {}
        for n in novel_data:
            tags_value = n.get('tags') or ''
            if tags_value and tags_value != '无':
                for tag in tags_value.split(','):
                    tag = tag.strip()
                    if tag:
                        tag_count[tag] = tag_count.get(tag, 0) + 1
        tags = sorted(tag_count.keys(), key=lambda x: (-tag_count[x], x))

        result = authors, tags, sites

    cache['filter_options'] = result
    cache['data_hash'] = current_hash
    cache['last_update'] = time.time()

    return result

#==================== API 路由=====================







#==================== 保存排序偏好 =====================


def pick_random_novel(exclude_work_id=None, prefer_rich=True):
    """随机挑一本书用于「每日推荐」。

    prefer_rich=True 时优先从「有可用简介或预览」的书里挑，
    避免推荐出来的卡片是空的（实测约 41% 有简介、77% 有预览）。
    候选为空时退回全量，保证一定能推荐出东西。

    exclude_work_id：避免「换一本」时抽到同一本。
    """
    if not novel_data:
        return None

    def _has_text(value):
        text = (value or '').strip()
        return bool(text) and text != '无简介'

    def _build(novel):
        base_info = novel
        title = base_info.get('title') or os.path.basename(str(base_info.get('file_path') or ''))
        # 简介优先；没有就用正文预览（预览是截取的正文开头，更适合「试读」）
        intro = ''
        for key in ('intro', 'preview'):
            if is_valid_intro(base_info.get(key)):
                intro = base_info[key].strip()
                break
        if not intro:
            preview = (base_info.get('preview') or '').strip()
            intro = preview if preview and preview != '无简介' else ''

        raw_author = base_info.get('author') or ''
        main_author, aliases = split_author_aliases(raw_author)

        tags = [t.strip() for t in (base_info.get('tags') or '').split(',') if t.strip() and t.strip() != '无']

        return {
            'work_id': base_info.get('work_id', ''),
            'title': title,
            'author': main_author or raw_author or '未知作者',
            'author_full': raw_author,
            'author_aliases': aliases,
            'site': base_info.get('site') or '未知网站',
            'word_count': base_info.get('word_count', 0),
            'publish_date': base_info.get('publish_date') or '未知',
            'progress': base_info.get('progress') or '',
            'tags': tags,
            'intro': intro,
            'file_path': base_info.get('file_path', ''),
            'has_intro': bool(intro),
            # 封面：配图目录首图 > 正文封面外链；为空时卡片用书名首字占位
            'cover_url': find_cover_url(base_info),
        }

    candidates = novel_data
    if exclude_work_id:
        filtered = [n for n in novel_data if n.get('work_id') != exclude_work_id]
        # 只剩一本时就用它，否则「换一本」会没结果
        if filtered:
            candidates = filtered

    if prefer_rich:
        rich = [n for n in candidates
                if is_valid_intro(n.get('intro')) or _has_text(n.get('preview'))]
        if rich:
            candidates = rich

    return _build(random.choice(candidates))




#==================== 头部背景图清单 =====================
_header_bg_cache = None
_header_bg_cache_time = 0
HEADER_BG_CACHE_TTL = 60  # 秒：文件很少变动，不必每次请求都 listdir 一遍


def list_header_bg_images():
    """列出真实存在的头部背景图（只读文件系统，不发网络请求）。

    从前前端靠 new Image().onload 探测文件是否存在，对 50 张图并发下载
    再 await Promise.all(...) —— 等于**首屏强制下载全部 50 张（约 14MB）
    才能显示第一张**。局域网瞬间传完看不出问题，3 Mbps 移动网络要等约 37 秒。

    改成后端直接把清单交给前端，前端首屏只需等 1 张，其余后台慢慢预热。
    """
    global _header_bg_cache, _header_bg_cache_time

    now = time.time()
    if _header_bg_cache is not None and now - _header_bg_cache_time < HEADER_BG_CACHE_TTL:
        return _header_bg_cache

    images_dir = os.path.join(BASE_DIR, 'static', 'images')
    urls = []
    try:
        for name in sorted(os.listdir(images_dir)):
            if not (name.startswith('header-bg-') and name.endswith('.webp')):
                continue
            full = os.path.join(images_dir, name)
            if os.path.isfile(full):
                # 带 mtime 版本号：换图后 URL 变，浏览器立刻拉新图，
                # 不会被 30 天静态缓存卡住（common.js 的 localStorage
                # 已加载记录按 URL 记账，格式变化不影响）
                urls.append(f'/static/images/{name}?v={int(os.path.getmtime(full))}')
    except OSError as e:
        logger.warning(f"读取头部背景图目录失败: {e}")

    _header_bg_cache = urls
    _header_bg_cache_time = now
    logger.debug(f"头部背景图清单: {len(urls)} 张")  # 60s TTL 到期会重刷，别用 info 刷屏
    return urls


# 页面 CSS 的版本号：静态资源走浏览器 30 天强缓存，改样式后必须换 URL 才生效。
_css_version_cache = {'value': 0, 'ts': 0}


def get_css_version():
    """静态资源版本号：static/css 与 static/js 下的最新 mtime。

    名字沿用 css_version（模板里已经在用），但范围覆盖到 JS ——
    改 reader-core.js 这类脚本同样必须换 URL，否则浏览器按 30 天强缓存跑旧代码。
    """
    now = time.time()
    if _css_version_cache['value'] and now - _css_version_cache['ts'] < 300:
        return _css_version_cache['value']
    latest = 0
    for sub in ('css', 'js'):
        for root, _dirs, files in os.walk(os.path.join(BASE_DIR, 'static', sub)):
            for name in files:
                if name.endswith(('.css', '.js')):
                    try:
                        latest = max(latest, int(os.path.getmtime(os.path.join(root, name))))
                    except OSError:
                        continue
    _css_version_cache['value'] = latest
    _css_version_cache['ts'] = now
    return latest


# 头部背景图清单注入所有模板：详情页/配置页/标签页/缺失页同样有 .header，
# 以前只有首页路由传 header_bg_images，其它页面前端拿不到清单，只能退化成
# 「new Image() 逐张探测」——首屏先下 11.7MB 才显示第一张。
@app.context_processor
def inject_header_bg_images():
    # max_tags_display 已支持个人覆盖，取「全局默认 + 用户设置」的生效值
    prefs = resolve_reader_prefs()
    return {
        'header_bg_images': list_header_bg_images(),
        'max_tags_display': prefs.get('max_tags_display', 3),
        'css_version': get_css_version(),
    }


# 轻量兜底接口：个别页面漏输出清单时，前端一次请求拿到，不再逐张探测。
# 需要登录（与页面本身一致），不泄露额外信息。
@app.route('/api/header_bg_images')
def api_header_bg_images():
    return jsonify({'images': list_header_bg_images()})


# ==================== 扫描管理：缓存概览 / 上次扫描 统计 ====================
SCAN_STATS_FILE = os.path.join(DATA_DIR, 'scan_stats.json')


def load_scan_stats():
    """读取上次扫描的统计信息（不存在时返回空字典）。"""
    return load_json_file(SCAN_STATS_FILE, {})


def save_scan_stats(stats, merge=True):
    """持久化扫描统计到 data/scan_stats.json。

    merge=True（默认）时与现有内容合并：增量扫描只更新 last_scan_* 等字段，
    不会把 last_full_scan_time 冲掉。置 None 的键仍然会写入（表示显式清空）。
    """
    if merge:
        merged = load_scan_stats()
        if not isinstance(merged, dict):
            merged = {}
        merged.update(stats)
        stats = merged
    return save_json_file(SCAN_STATS_FILE, stats)


def check_interrupted_scan():
    """启动时检查上次扫描是否被中断（进程重启/被杀，扫描线程随之消失）。

    扫描开始时会在 scan_stats.json 写 scan_in_progress 标记，正常结束时清除。
    如果启动时还留着它，说明上一次扫描没能跑完 —— 统计数据不可信，且
    last_scan_type 可能停在「增量」，让用户误以为全量从未执行过。
    """
    try:
        stats = load_scan_stats()
        if not isinstance(stats, dict):
            return
        pending = stats.get('scan_in_progress')
        if not pending:
            return

        started = pending.get('start_time')
        scan_type = pending.get('type') or 'unknown'
        stats['scan_in_progress'] = None
        stats['last_scan_interrupted'] = {
            'type': scan_type,
            'start_time': started,
            'detected_at': time.time(),
        }
        save_scan_stats(stats, merge=False)

        from datetime import datetime
        when = datetime.fromtimestamp(started).strftime('%Y-%m-%d %H:%M:%S') if started else '未知时间'
        label = '全量扫描' if scan_type == 'full' else '增量扫描'
        logger.warning(f"⚠️ 检测到上次{label}未完成（开始于 {when}），进程可能在扫描过程中重启")
    except Exception as e:
        logger.warning(f"检查扫描中断状态失败（已跳过）：{e}")


def human_size(num_bytes):
    """把字节数格式化为易读字符串（B/KB/MB/GB/TB/PB）。"""
    try:
        num_bytes = float(num_bytes)
    except (TypeError, ValueError):
        return '0 B'
    if num_bytes < 1024:
        return f"{num_bytes:.0f} B"
    num_bytes /= 1024
    for unit in ('KB', 'MB', 'GB', 'TB'):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} PB"


def human_words(num):
    """把字数格式化为简略字符串：不足 1 万保留千分位，1 万以上按「万字」，1 亿以上按「亿字」。

    例：8888 → "8,888"；12345 → "1.2万字"；1234567 → "123万字"；1169930000 → "11.7亿字"。
    """
    try:
        num = int(num)
    except (TypeError, ValueError):
        return '0'
    if num < 10000:
        return f"{num:,}"
    yi = round(num / 100000000, 1)
    if yi >= 1:
        text = f"{yi:.1f}"
        if text.endswith('.0'):
            text = text[:-2]
        return f"{text}亿字"
    wan = round(num / 10000, 1)
    if wan >= 100:
        return f"{int(wan)}万字"
    text = f"{wan:.1f}"
    if text.endswith('.0'):
        text = text[:-2]
    return f"{text}万字"


def get_cache_overview():
    """首页「扫描管理」区块展示的缓存概览统计。

    注意：不与已有的 /api/cache/stats（运行时缓存调试）混淆，
    这里统计的是书架维度的概览数据。
    """
    global novel_data
    total_novels = len(novel_data)
    total_words = 0
    authors = set()
    tags = set()
    sites = set()
    image_novels = 0
    video_novels = 0
    audio_novels = 0
    for n in novel_data:
        try:
            total_words += int(n.get('word_count', 0) or 0)
        except (TypeError, ValueError):
            pass
        a = n.get('author')
        if a and a != '未知作者':
            authors.add(a)
        t = n.get('tags')
        if t:
            for tag in str(t).split(','):
                tag = tag.strip()
                if tag:
                    tags.add(tag)
                    if tag == '配图':
                        image_novels += 1
                    elif tag == '视频':
                        video_novels += 1
                    elif tag == '音频':
                        audio_novels += 1
        s = n.get('site')
        if s and s != '未知网站':
            sites.add(s)

    return {
        'total_novels': total_novels,
        'total_words': total_words,
        'total_words_text': human_words(total_words),
        'image_novels': image_novels,
        'video_novels': video_novels,
        'audio_novels': audio_novels,
        'authors': len(authors),
        'tags': len(tags),
        'sites': len(sites),
    }


#==================== 首页路由 =====================

# ==================== 详情/阅读页文件失效提示 ====================
def render_missing_page(file_path, reason):
    """渲染友好的文件失效提示页（模块级，多处可调用）"""
    reasons = {
        'deleted': {
            'title': '文件不存在或已被删除',
            'desc': '这本书的文件可能已被移除、重命名或移动了位置。<br>'
                    '如果文件确实还在，请点击下方按钮重新扫描目录以更新缓存。',
            'class': 'deleted',
            'text': '❌ 文件未找到'
        },
        'modified': {
            'title': '文件已更新',
            'desc': '这本书的文件已被修改，当前缓存数据已过期。<br>'
                    '请执行一次扫描以更新最新内容，然后重新打开。',
            'class': 'modified',
            'text': '⚠️ 缓存已过期'
        },
        'error': {
            'title': '文件读取失败',
            'desc': '读取文件时发生错误，可能是权限问题或文件损坏。<br>'
                    '请检查文件后重试，或执行扫描刷新缓存。',
            'class': 'error',
            'text': '⚠️ 读取异常'
        }
    }
    info = reasons.get(reason, reasons['error'])
    return render_template(
        'novel_missing.html',
        title=os.path.basename(file_path),
        file_path=file_path,
        page_title=info['title'],
        page_desc=info['desc'],
        reason_class=info['class'],
        reason_text=info['text'],
        back_url=url_for('library.index'),
        is_admin=is_admin()
    ), 404

#==================== 小说详情页 =====================
#==================== 阅读章节路由 =====================
def load_novel_content(file_path):
    """读取并解码小说文件；带受限行缓存，翻页时不再重复读整本

    返回 (content, lines, encoding)
    """
    current_hash = get_file_hash(file_path)
    cached = line_cache.get(file_path)
    if cached and cached.get('hash') == current_hash:
        line_cache.move_to_end(file_path)
        return cached['content'], cached['lines'], cached['encoding']

    with open(file_path, 'rb') as f:
        raw_data = f.read()

    encoding = 'utf-8'
    if raw_data[:3] == b'\xef\xbb\xbf':
        raw_data = raw_data[3:]
    elif raw_data[:2] == b'\xff\xfe':
        encoding = 'utf-16-le'
        raw_data = raw_data[2:]
    elif raw_data[:2] == b'\xfe\xff':
        encoding = 'utf-16-be'
        raw_data = raw_data[2:]

    try:
        content = raw_data.decode(encoding)
    except UnicodeDecodeError:
        content = None
        for enc in ['utf-8', 'gbk', 'gb18030', 'big5']:
            try:
                content = raw_data.decode(enc)
                encoding = enc
                break
            except UnicodeDecodeError:
                continue
        if content is None:
            result = chardet.detect(raw_data[:65536])
            encoding = result.get('encoding') or 'utf-8'
            content = raw_data.decode(encoding, errors='ignore')

    if content.startswith('\ufeff'):
        content = content[1:]

    lines = re.split(r'\r?\n|\r', content)

    # 只缓存中小文件，避免大文件把内存撑满
    if len(raw_data) <= MAX_LINE_CACHE_FILE_MB * 1024 * 1024:
        line_cache[file_path] = {
            'hash': current_hash,
            'content': content,
            'lines': lines,
            'encoding': encoding,
        }
        line_cache.move_to_end(file_path)
        while len(line_cache) > MAX_LINE_CACHE_FILES:
            line_cache.popitem(last=False)

    return content, lines, encoding

#==================== 判断当前页是否有正文 ====================
# 阅读页用「纯符号行」和「章节标题行」来判断本页是不是空页，
# 空页会显示「本章节无正文内容」占位图。
#
# ⚠️ 这里的判定规则**故意比 LEVEL1/2/3_PATTERN 宽松**，是对原模板逻辑的等价搬迁：
#   1) 标题判定用「以『第』开头 且 含 章/卷/篇/节/回/部/集」，而 LEVEL*_PATTERN 是严格正则。
#      因此「楔子」「序章」「正文」「第3节 出发」在这里算**正文**，在正则里算标题。
#   2) 分隔符只剔除符号、**不剔除数字**，因此纯数字行（页码/字数残留）算正文，
#      而 is_separator 的正则把 \d 也算分隔符。
# 这两点差异会影响实际渲染结果（实测约 19.5% 的页面结论相反），
# 所以不要为了「消除重复」把它合并到 LEVEL*_PATTERN / is_separator 上，
# 否则大量本来正常显示的页面会开始出现「无正文」占位图。
_SEPARATOR_CHARS = ('*', '＊', '—', '－', '~', '～', '…', '·', '•')
_TITLE_KEYWORDS = ('章', '卷', '篇', '节', '回', '部', '集')


def page_has_content(lines):
    """判断本页是否存在「真正的正文」（排除章节标题行与纯符号分隔行）

    Args:
        lines: 当前页的行列表（content_lines）

    Returns:
        bool: True 表示有正文，False 表示整页都是标题/分隔符/空行
    """
    if not lines:
        return False

    for line in lines:
        trimmed = (line or '').strip()
        if not trimmed:
            continue

        # 章节标题行：以「第」开头且含章节关键字
        if trimmed.startswith('第') and any(k in trimmed for k in _TITLE_KEYWORDS):
            continue

        # 纯符号分隔行：10 字以内且剔除符号后为空
        if len(trimmed) <= 10:
            chars = trimmed
            for ch in _SEPARATOR_CHARS:
                chars = chars.replace(ch, '')
            if not chars:
                continue

        # 只要有一行既不是标题也不是分隔符，就算有正文
        return True

    return False



#==================== 继续阅读路由 =====================

#==================== 模板过滤器 =====================
@app.template_filter('timestamp_to_date')
def timestamp_to_date(timestamp):
    dt = datetime.fromtimestamp(timestamp)
    now = datetime.now()
    if dt.date() == now.date():
        return f"今天 {dt.strftime('%H:%M')}"
    elif (now - dt).days == 1:
        return f"昨天 {dt.strftime('%H:%M')}"
    else:
        return dt.strftime('%m-%d %H:%M')


#==================== 最近阅读 API（加载更多 / 搜索 / 删除后就地刷新） =====================
def _recent_record_to_json(record):
    """把整理好的记录裁成前端需要的字段（不泄漏服务端内部路径）"""
    return {
        'work_id': record.get('work_id', ''),
        'title': record.get('title', ''),
        'author': record.get('author_display', ''),
        'chapter': record.get('chapter_display', ''),
        'time': record.get('time_display', ''),
        'group': record.get('group', 'earlier'),
        'progress_percent': record.get('progress_percent'),
        'progress_text': record.get('progress_text', ''),
        'progress_known': bool(record.get('progress_known', record.get('progress_percent') is not None)),
        'finished': bool(record.get('finished')),
        'missing_file': bool(record.get('missing_file')),
        'url': url_for('reader.continue_reading', file_path=(record.get('file_path') or '').lstrip('/')),
        # url_for 会对 path 参数做一次编码，这里不要再手动 quote，否则会二次编码
        'restart_url': url_for('reader.read_chapter',
                               file_path=(record.get('file_path') or '').lstrip('/'),
                               line_number=1),
        'file_path': record.get('file_path', '')
    }




def _recent_record_matches(record, keyword):
    haystack = ' '.join(str(record.get(field, '') or '') for field in
                        ('title', 'author_display', 'chapter_display', 'filename'))
    return keyword in haystack.lower()


#==================== 删除阅读记录 API =====================

#==================== 标记「已读 / 未读」API =====================
def _resolve_work_id_for_request(data):
    """把请求里的 work_id / file_path 解析成一个 work_id；解析不到返回 ''

    对「还没读过、因此还没有记录」的书也要能解析出 work_id，
    否则手动标记已读就没法用。解析顺序：
      1. 请求里直接给的 work_id
      2. 阅读记录里的路径索引 / 指纹解析
      3. 扫描缓存（novel_data）里的 work_id
      4. 用文件内容现算指纹
    """
    work_id = (data.get('work_id') or '').strip()
    if work_id:
        return work_id

    file_path = data.get('file_path') or ''
    if not file_path:
        return ''

    resolved = resolve_novel_path(file_path)
    if resolved:
        # 2) 已有记录：走正常的记录解析
        work_id, _ = resolve_record_by_path(resolved)
        if work_id:
            return work_id

        # 3) 还没读过：用扫描缓存里的 work_id
        work_id = get_work_id_from_cache(resolved)
        if work_id:
            return work_id

        # 4) 现算内容指纹
        work_id = compute_work_id(resolved)
        if work_id:
            return work_id

    # 兜底：直接用归一化路径在索引里找
    payload = load_reading_payload()
    return payload[_PATH_INDEX_KEY].get(normalize_record_path(file_path), '')




#==================== 获取缓存统计信息 API =====================
@app.route('/api/cache/stats')
def get_cache_stats():
    """获取缓存统计信息"""
    if not is_authenticated():
        return jsonify({'error': '未登录'}), 401

    memory_mb = None

    # 优先用 psutil（最准确）
    try:
        import psutil
        process = psutil.Process()
        memory_mb = round(process.memory_info().rss / 1024 / 1024, 1)
    except Exception:
        pass

    # psutil 不可用，回退到 /proc/self/statm
    if memory_mb is None or memory_mb == 0:
        try:
            with open('/proc/self/statm', 'r') as f:
                parts = f.read().split()
                if len(parts) >= 2:
                    # 第一列是总虚拟内存页数，第二列是常驻内存页数(RSS)
                    # 用第二列更准确
                    rss_pages = int(parts[1])
                    memory_mb = round(rss_pages * 4 / 1024, 1)
        except Exception:
            pass

    # 指纹缓存条数（前缀之和）+ 估算占用，前端「其他缓存」用
    work_id_count = len(_work_id_file_cache) + len(_work_id_sets)
    work_id_kb = round(work_id_cache_kb(), 1)

    return jsonify({
        'tag_cache': len(tag_parse_cache),
        'chapter_cache': len(chapter_cache),
        'image_cache': len(image_cache),
        'image_check_cache': len(_image_check_cache),
        'line_cache': len(line_cache),
        'line_cache_mb': round(line_cache_bytes() / 1024 / 1024, 2),
        'work_id_count': work_id_count,
        'work_id_kb': work_id_kb,
        'memory_mb': memory_mb
    })

# ==================== 当前书内搜索 API ====================

# ==================== 配置管理路由 ====================

#==================== 标签管理路由 ====================

#==================== 保存配置 API =====================
def apply_runtime_config():
    """配置变化后同步已缓存的模块级常量"""
    global NOVEL_DIR, PER_PAGE, WORDS_PER_PAGE
    NOVEL_DIR = CONFIG.get('novel_dir', NOVEL_DIR)
    PER_PAGE = CONFIG.get('per_page', 100)
    WORDS_PER_PAGE = CONFIG.get('words_per_page', 8000)
    invalidate_filter_cache()


#==================== 重载配置 API =====================

# ==================== 标签管理 API ====================

#==================== 标签列表 API ====================

#==================== 派生规则列表 API ====================

#==================== 添加标签 API ====================

#=================== 编辑标签 API ====================

#==================== 删除标签 API ====================

#==================== 添加派生规则 API ====================

#==================== 删除派生规则 API ====================

#==================== 导出标签 API ====================

#==================== 导入标签 API ====================

#==================== 重置标签 API ====================

#==================== 重新应用标签 API ====================

#=================== 保存标签规则 API ====================

#=================== 重载标签规则 API ====================

#=================== 获取标签规则 API ====================

#=================== 添加关键词 API ====================

#=================== 删除关键词 API ====================

#=================== 保存标签规则文件 ====================
def save_tag_rules_file():
    rules = {
        'keywords': TAG_KEYWORDS,
        'aliases': TAG_ALIASES,
        'implications': TAG_IMPLICATIONS
    }
    return save_json_file(TAG_RULES_FILE, rules)

#=================== 编辑关键词 API ====================

#=================== 添加别名 API ====================

#=================== 编辑别名 API ====================

#=================== 删除别名 API ====================

#=================== 更新别名 API ====================

#=================== 添加派生规则 API ====================

#=================== 删除派生规则 API ====================

#=================== 预览标签规则 API ====================

#=================== 导入标签规则 API ====================

# ==================== 本地媒体 API ====================
IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg']
VIDEO_EXTENSIONS = ['.mp4', '.webm', '.mov', '.avi', '.mkv', '.flv', '.wmv']
AUDIO_EXTENSIONS = ['.mp3', '.m4a', '.wav', '.flac', '.aac', '.ogg', '.wma', '.opus']
MIME_TYPES = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.gif': 'image/gif',
    '.bmp': 'image/bmp', '.webp': 'image/webp', '.svg': 'image/svg+xml',
    '.mp4': 'video/mp4', '.webm': 'video/webm', '.mov': 'video/quicktime',
    '.avi': 'video/x-msvideo', '.mkv': 'video/x-matroska', '.flv': 'video/x-flv',
    '.wmv': 'video/x-ms-wmv',
    '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.wav': 'audio/wav', '.flac': 'audio/flac',
    '.aac': 'audio/aac', '.ogg': 'audio/ogg', '.wma': 'audio/x-ms-wma', '.opus': 'audio/opus',
}

@app.route('/api/check_image_folder', methods=['POST'])
def check_image_folder():
    data = request.get_json(silent=True) or {}
    folders = data.get('folders', [])

    if not isinstance(folders, list):
        return jsonify({'exists': False, 'path': None}), 400

    # 只允许探测小说目录内的文件夹
    safe_folders = [str(f) for f in folders[:10] if f and is_inside_novel_dir(f)]
    if not safe_folders:
        return jsonify({'exists': False, 'path': None})

    return jsonify(check_image_folder_cached(safe_folders))

#=================== 读取本地图片 API ====================
@app.route('/api/local_image')
def serve_local_image():
    folder = request.args.get('folder', '')
    name = request.args.get('name', '')

    found = resolve_media_path(folder, name, IMAGE_EXTENSIONS)
    if not found:
        return '', 404

    img_path, ext = found
    resp = send_file(img_path, mimetype=MIME_TYPES.get(ext, 'application/octet-stream'))
    # send_file 默认吃 SEND_FILE_MAX_AGE_DEFAULT（30 天），配图文件夹里的图
    # 是被同名替换的高频对象——缓存 30 天会导致换了图浏览器不换。
    # no-cache + send_file 自带的 Last-Modified/ETag：每次带条件请求
    # 重新验证，没变回 304（几字节），变了立刻拿新图。
    resp.headers['Cache-Control'] = 'no-cache'
    return resp

#=================== 列出图片文件夹 API ====================
@app.route('/api/list_image_folder', methods=['POST'])
def list_image_folder():
    data = request.get_json(silent=True) or {}
    folder = data.get('folder', '')

    if not folder or not is_inside_novel_dir(folder) or not os.path.isdir(folder):
        return jsonify({'files': []})

    try:
        entries = os.listdir(folder)
    except OSError as e:
        logger.warning(f"列目录失败 {folder}: {e}")
        return jsonify({'files': []})

    files = [f for f in entries if os.path.splitext(f)[1].lower() in set(IMAGE_EXTENSIONS)]
    return jsonify({'files': files})

#=================== 打开文件夹 API ====================
@app.route('/api/open_folder', methods=['POST'])
def open_folder():
    data = request.get_json(silent=True) or {}
    path = data.get('path', '')

    # 只允许打开小说目录内的路径，避免被当成任意路径启动器
    if not path or not is_inside_novel_dir(path) or not os.path.exists(path):
        return jsonify({'success': False, 'message': '文件夹不存在或不在小说目录内'})

    try:
        if sys.platform == 'win32':
            os.startfile(path)  # noqa: S606 - 本机自用功能
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

#=================== 读取本地视频 API ====================
@app.route('/api/local_video')
def serve_local_video():
    folder = request.args.get('folder', '')
    name = request.args.get('name', '')

    found = resolve_media_path(folder, name, VIDEO_EXTENSIONS)
    if not found:
        return '', 404

    video_path, ext = found
    resp = send_file(video_path, mimetype=MIME_TYPES.get(ext, 'video/mp4'))
    # 同 local_image：媒体文件不参与 30 天静态缓存（见上注释）
    resp.headers['Cache-Control'] = 'no-cache'
    return resp

#=================== 读取本地音频 API ====================
@app.route('/api/local_audio')
def serve_local_audio():
    folder = request.args.get('folder', '')
    name = request.args.get('name', '')

    found = resolve_media_path(folder, name, AUDIO_EXTENSIONS)
    if not found:
        return '', 404

    audio_path, ext = found
    resp = send_file(audio_path, mimetype=MIME_TYPES.get(ext, 'audio/mpeg'))
    # 同 local_image：媒体文件不参与 30 天静态缓存（见上注释）
    resp.headers['Cache-Control'] = 'no-cache'
    return resp

# ==================== 表情映射 API ====================
def load_emoji_mapping_cached():
    global _emoji_mapping_cache

    if _emoji_mapping_cache is not None:
        return _emoji_mapping_cache

    default_mapping = {
        "微笑": "😊", "大笑": "😂", "偷笑": "😏", "得意": "😎",
        "调皮": "😜", "吐舌": "😝", "眨眼": "😉", "害羞": "😊",
        "尴尬": "😅", "冷汗": "😰", "惊讶": "😲", "惊恐": "😱",
        "流泪": "😢", "大哭": "😭", "伤心": "😔", "生气": "😠",
        "愤怒": "🤬", "抓狂": "🤯", "无语": "😑",
    }

    _emoji_mapping_cache = load_json_file(EMOJI_MAPPING_FILE, default_mapping)
    logger.info(f"加载表情映射: {len(_emoji_mapping_cache)} 个")
    return _emoji_mapping_cache

def load_image_mapping_cached():
    global _image_mapping_cache

    if _image_mapping_cache is not None:
        return _image_mapping_cache

    default_mapping = {
        "抠鼻": "/static/emojis/koubi.png",
        "狗头": "/static/emojis/doge.png",
        "旺柴": "/static/emojis/wangchai.png"
    }

    _image_mapping_cache = load_json_file(IMAGE_MAPPING_FILE, default_mapping)
    logger.info(f"加载图片表情映射: {len(_image_mapping_cache)} 个")
    return _image_mapping_cache

#=================== 获取图片映射 API ====================
@app.route('/api/emoji/image-mapping')
def get_image_mapping():
    return jsonify(load_image_mapping_cached())

#=================== 保存图片映射 API ====================
@app.route('/api/emoji/image-mapping/save', methods=['POST'])
def save_image_mapping():
    global _image_mapping_cache
    try:
        mapping = request.get_json(silent=True)
        if not isinstance(mapping, dict):
            return jsonify({'success': False, 'message': '数据格式错误'})
        save_json_file(IMAGE_MAPPING_FILE, mapping)
        _image_mapping_cache = mapping
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

#=================== 获取表情映射 API ====================
@app.route('/api/emoji/mapping')
def get_emoji_mapping():
    return jsonify(load_emoji_mapping_cached())

# ==================== 跨行括号高亮 ====================
_FULLWIDTH_SPACE = '\u3000'
_FW_INDENT_RE = re.compile(r'(?m)^[ \t\u3000]+')


def _collapse_fullwidth_indent(content):
    """把每行开头的连续全角/半角空白压成最多两个 &emsp;

    TXT 正文常用整串全角空格做缩进/居中排版。原实现把每个 U+3000 都换成
    &emsp;，行首出现几十个全角宽、又不允许断行的占位符，会把行撑出容器，
    移动端就表现为「这一章可以左右拖动」。这里只保留最多两个（约两字缩进）。
    """
    if not content:
        return content

    def _repl(match):
        return '&emsp;&emsp;' if match.group(0) else ''

    return _FW_INDENT_RE.sub(_repl, content)


def highlight_crossline_brackets(text):
    """给跨行的引号/括号加高亮 span

    注意：本函数会插入 HTML 标签，正文先做 HTML 转义，避免 TXT 里的
    <script>/<img onerror> 之类内容被浏览器当代码执行。
    """
    if not text:
        return text

    result = html.escape(text, quote=False)

    bracket_pairs = [
        ('“', '”', 'highlight-quote-double'),
        ('‘', '’', 'highlight-quote-single'),
        ('（', '）', 'highlight-bracket'),
        ('【', '】', 'highlight-square-bracket'),
        ('《', '》', 'highlight-book'),
        ('「', '」', 'highlight-quote-double'),
        ('『', '』', 'highlight-quote-single'),
        ('[', ']', 'highlight-square-bracket-1'),
        ('［', '］', 'highlight-square-bracket-1'),
        ('〖', '〗', 'highlight-hollow-bracket'),
    ]

    for left, right, css_class in bracket_pairs:
        pattern = re.compile(
            f'{re.escape(left)}([^{re.escape(left)}{re.escape(right)}]*?){re.escape(right)}',
            re.DOTALL
        )

        def repl(match, left=left, right=right, css_class=css_class):
            content = match.group(1)
            if '\n' not in content:
                return match.group(0)

            content = _collapse_fullwidth_indent(content)

            # 关键：不要用 <br> 把整段压成一行。
            # 调用方会把结果按 '\n' 重新切成多行，每行渲染成独立的
            # <div class="content-line">，这样跨行引号的每一行都能各自
            # 应用 text-indent（用 <br> 的话第 2 行起算「续行」，没有缩进）。
            #
            # 每一行都包一个完整、闭合的 <span>，保证切行后每段 HTML 都合法。
            parts = content.split('\n')
            wrapped = []
            for idx, part in enumerate(parts):
                head = left if idx == 0 else ''
                tail = right if idx == len(parts) - 1 else ''
                wrapped.append(f'<span class="{css_class}">{head}{part}{tail}</span>')
            return '\n'.join(wrapped)

        result = pattern.sub(repl, result)

    return result

#=================== 管理员清除所有用户的阅读记录 ====================

#=================== 管理员清除指定用户的阅读记录 ====================

#=================== 管理员查看所有用户的阅读记录（仅数量，不含内容） ====================

# ==================== 启动 ====================
_started_threads = False

def bootstrap():
    """启动后台线程 + 加载缓存（模块导入时执行一次）"""
    global _started_threads

    if not _started_threads:
        start_background_threads()
        _started_threads = True

    print("=" * 50)
    print("📚 小说管理系统启动中...")
    print("=" * 50)
    print(f"📁 扫描目录：{NOVEL_DIR}")
    print(f"💾 缓存库：{CACHE_DB_FILE}")
    print("=" * 50)

    if not any(normalize_user_info(v, k).get('role') == 'admin'
               for k, v in (CONFIG.get('users') or {}).items()):
        logger.warning("⚠️ 当前没有任何管理员账号，请检查 config.json 或设置 DEFAULT_ADMIN_PASSWORD")

    # 必须在任何自动扫描启动之前：判断上次扫描是否被中断
    check_interrupted_scan()

    if load_cache():
        print(f"✅ 缓存加载成功，共 {len(novel_data)} 本小说")
        print("🚀 使用缓存数据快速启动")

        if CONFIG.get('auto_scan_on_start', True):
            def check_updates():
                time.sleep(2)
                if novel_data:
                    print("🔍 启动时检查文件更新...")
                    scan_novel_files_background(full_scan=False)

            update_thread = threading.Thread(target=check_updates, daemon=True)
            update_thread.start()
            print("✅ 启动时自动扫描已启用")
        else:
            print("ℹ️ 启动时自动扫描已禁用")
    else:
        print("⚠️ 缓存加载失败")
        print("💡 提示：请登录后在网页中点击'扫描'按钮手动扫描")

        if CONFIG.get('auto_scan_on_start', True):
            thread = threading.Thread(target=scan_novel_files_background, args=(True,), daemon=True)
            thread.start()
            print("✅ 首次启动，执行全量扫描...")

# ===== 注册蓝图（阶段2 起）=====
# 放在这里而不是 create_app() 里：蓝图模块反向 import 本模块的共享函数
# （CONFIG / is_admin / save_json_file 等），只有本模块的全局名字全部就绪
# 之后 import 才不会拿到半成品。阶段6 全部路由搬完后可移回工厂。
from app import register_blueprints
register_blueprints(app)

bootstrap()

if __name__ == '__main__':
    app.run(
        debug=debug_mode,
        host=str(CONFIG.get('app_host', '0.0.0.0')),
        port=int(CONFIG.get('app_port', 5000)),
    )