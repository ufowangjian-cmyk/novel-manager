# -*- coding: utf-8 -*-
"""行为基线快照：状态码 / 重定向目标 / 响应体哈希。

用于模块化重构前后逐项比对。**必须在隔离副本里跑**（/tmp/modtest），
因为阅读页会写阅读进度，不能碰真实 data。

    python tests/snapshot_behavior.py --out /tmp/base.json      # 采集基线
    python tests/snapshot_behavior.py --diff /tmp/base.json     # 与基线比对

稳定性判定：每个 URL 连采两次，两次哈希相同才记为 stable；不稳定的（首页随机
推荐卡片之类）只比状态码和长度区间，不比哈希。
"""

import hashlib
import json
import os
import random
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

# 页面清单：(标签, 登录态, 路径)
PAGES = [
    ('login_anon', 'anon', '/login'),
    ('index_anon', 'anon', '/'),
    ('config_anon', 'anon', '/config'),
    ('api_tags_anon', 'anon', '/api/tag/list'),
    ('manifest', 'anon', '/manifest.json'),
    ('service_worker', 'anon', '/service-worker.js'),

    ('index', 'admin', '/'),
    ('index_sorted', 'admin', '/?sort=word_count&order=desc'),
    ('index_tagged', 'admin', '/?tag=%E4%BA%BA%E5%A6%BB'),
    ('config', 'admin', '/config'),
    ('tag_manager', 'admin', '/tag_manager'),
    ('get_all_authors', 'admin', '/get_all_authors'),
    ('get_all_tags', 'admin', '/get_all_tags'),
    ('get_all_sites', 'admin', '/get_all_sites'),
    ('get_first_tags', 'admin', '/get_first_tags'),
    ('config_get', 'admin', '/config/get'),
    ('api_tags', 'admin', '/api/tag/list'),
    ('api_tag_stats', 'admin', '/api/tag/stats'),
    ('api_tag_rules', 'admin', '/api/tag/rules/get'),
    ('api_users_list', 'admin', '/api/users/list'),
    ('api_avatar_options', 'admin', '/api/avatar/options'),
    ('api_cache_stats', 'admin', '/api/cache/stats'),
    ('api_scan_progress', 'admin', '/api/scan_progress'),
    ('api_recent_records', 'admin', '/api/recent_records'),
    ('api_preferences', 'admin', '/api/get_preferences'),
    ('api_header_bg', 'admin', '/api/header_bg_images'),
    ('api_image_mapping', 'admin', '/api/emoji/image-mapping'),
    ('api_emoji_mapping', 'admin', '/api/emoji/mapping'),
    ('detail', 'admin', None),       # 运行时按第一本书填
    ('read_first', 'admin', None),
    ('read_last_line', 'admin', None),
    ('continue', 'admin', None),
]


def _sha(text):
    return hashlib.sha256(text.encode('utf-8', 'replace')).hexdigest()[:16]


# 这些接口的响应天然带进程级动态值，只比状态码，不比哈希：
#   api_cache_stats -> 含 memory_mb（当前进程 RSS），每进程都不同
EXEMPT_HASH = {'api_cache_stats'}


def _reset_reading_records():
    """清空副本里的阅读记录。

    首页/详情页会渲染「最近阅读」卡片，API 也直接返回记录；上一篇采集
    自己就会写进记录，导致同一个副本第二次采集时哈希必变。每次采集前清空，
    基线才可能跨进程复现。

    ⚠️ 只在副本里用（/tmp/modtest）。真实 data 的阅读进度是用户数据，不能清。
    """
    directory = os.path.join(APP_DIR, 'data', 'reading_records')
    if not os.path.isdir(directory):
        return 0
    removed = 0
    for name in os.listdir(directory):
        if not name.endswith('.json'):
            continue
        try:
            os.remove(os.path.join(directory, name))
            removed += 1
        except OSError:
            pass
    return removed


def _admin_session(client, app, config):
    admin_key = admin_info = None
    for key, info in (config.get('users') or {}).items():
        if isinstance(info, dict) and info.get('role') == 'admin':
            admin_key, admin_info = key, info
            break
    if not admin_key:
        raise SystemExit('config.json 里没有管理员账号')
    with client.session_transaction() as sess:
        sess['authenticated'] = True
        sess['user_key'] = admin_key
        sess['user_role'] = 'admin'
        sess['user_id'] = admin_info.get('user_id', 'admin')
        sess['user_name'] = 'baseline'
    return admin_key


def _probe(client, path):
    # 首页含「随机推荐」卡片，用固定种子让它可复现，否则每次哈希都不同。
    # 只影响本次请求内的随机取值，不改变任何业务逻辑。
    random.seed(20261027)
    response = client.get(path)
    body = response.get_data()
    text = body.decode('utf-8', 'replace')
    return {
        'status': response.status_code,
        'location': response.headers.get('Location'),
        'len': len(body),
        'sha': _sha(text),
    }


def _redact(path):
    """落盘前抹掉 path 里的书名/标签值 —— 基线要进公开仓库，书单不能泄露。"""
    for prefix in ('/novel_detail/', '/read/', '/continue/'):
        if path.startswith(prefix):
            rest = path[len(prefix):]
            # read 后面还有 /<行号>
            if prefix == '/read/' and '/' in rest:
                return prefix + '<book>/<line>'
            return prefix + '<book>'
    if '?tag=' in path:
        head, _, _ = path.partition('?tag=')
        return head + '?tag=<tag>'
    return path


def collect():
    import novel_manager as nm

    config = nm.CONFIG
    books = nm.novel_data
    if not books:
        raise SystemExit('novel_data 为空，副本里没有书？')

    sample = books[0]
    filename = sample['filename']
    total = sample.get('word_count') or 5000
    last_line = max(2, int(total / 300))

    filled = []
    for label, who, path in PAGES:
        if path is None:
            if label == 'detail':
                path = f'/novel_detail/{filename}'
            elif label == 'read_first':
                path = f'/read/{filename}/1'
            elif label == 'read_last_line':
                path = f'/read/{filename}/{last_line}'
            elif label == 'continue':
                path = f'/continue/{filename}'
        filled.append((label, who, path))

    results = {}
    cleared = _reset_reading_records()
    if cleared:
        print(f'# 已清空副本阅读记录 {cleared} 个文件（保证跨进程可复现）')
    for who in ('anon', 'admin'):
        client = nm.app.test_client()
        if who == 'admin':
            _admin_session(client, nm.app, config)
        for label, session_kind, path in filled:
            if session_kind != who:
                continue
            first = _probe(client, path)
            second = _probe(client, path)
            entry = dict(first)
            entry['stable'] = first['sha'] == second['sha'] and first['len'] == second['len']
            if not entry['stable']:
                entry['len'] = 0  # 不稳定项不参与长度比较
            results[label] = {'path': _redact(path), 'session': who, **entry}
    return results


def compare(baseline, current):
    problems = []
    notes = []
    for label, base in baseline.items():
        cur = current.get(label)
        if cur is None:
            problems.append(f'{label}: 当前快照缺失')
            continue
        if base['status'] != cur['status']:
            problems.append(f"{label}: 状态码 {base['status']} -> {cur['status']} ({base['path']})")
        if (base.get('location') or '') != (cur.get('location') or ''):
            problems.append(f"{label}: Location {base.get('location')} -> {cur.get('location')}")
        if base.get('stable') and cur.get('stable'):
            if label in EXEMPT_HASH:
                continue
            if base['sha'] != cur['sha']:
                problems.append(
                    f"{label}: 响应体哈希变化 {base['sha']} -> {cur['sha']} ({base['path']})")
        elif base.get('stable') != cur.get('stable'):
            notes.append(f"{label}: 稳定性标记变化 {base.get('stable')} -> {cur.get('stable')}")
    for label in current:
        if label not in baseline:
            notes.append(f'{label}: 基线里没有（新增）')
    return problems, notes


def main():
    out_path = diff_path = None
    args = sys.argv[1:]
    for index, arg in enumerate(args):
        if arg == '--out':
            out_path = args[index + 1]
        elif arg == '--diff':
            diff_path = args[index + 1]

    current = collect()

    if diff_path:
        with open(diff_path, encoding='utf-8') as handle:
            baseline = json.load(handle)
        problems, notes = compare(baseline, current)
        stable_count = sum(1 for v in baseline.values() if v.get('stable'))
        print(f'比对 {len(baseline)} 项（其中 {stable_count} 项比哈希）')
        for note in notes:
            print(f'  ~ {note}')
        if problems:
            print(f'\n❌ {len(problems)} 项不一致：')
            for item in problems:
                print(f'  - {item}')
            return 1
        print('✅ 行为基线完全一致')
        return 0

    if out_path:
        with open(out_path, 'w', encoding='utf-8', newline='\n') as handle:
            json.dump(current, handle, ensure_ascii=False, indent=2, sort_keys=True)
        stable = sum(1 for v in current.values() if v['stable'])
        print(f'已写入 {out_path}：{len(current)} 项，其中 {stable} 项哈希稳定')
        for label, item in sorted(current.items()):
            flag = 'stable' if item['stable'] else 'DYNAMIC'
            print(f"  {label:22s} {item['status']}  {item['len']:7d}  {flag}  {item['path'][:60]}")
        return 0

    print(json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
