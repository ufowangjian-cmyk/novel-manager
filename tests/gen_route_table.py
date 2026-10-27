# -*- coding: utf-8 -*-
"""生成「路由 → 目标蓝图」映射表（任务书第 3 节交付物）。

从真实 url_map 读，保证 76 条一条不漏；分类规则写在 DOMAIN_BY_ENDPOINT。
未归类的端点会显式标成 UNCLASSIFIED，不允许静默漏掉。

    python tests/gen_route_table.py > docs/blueprint-roadmap.md
"""

import os
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

# import novel_manager 会打一堆启动日志到 stdout；本脚本的输出要能直接重定向成
# markdown 文件，所以加载期间把 stdout 临时接到 stderr。
_REAL_STDOUT = sys.stdout

# 端点名 → 目标蓝图。顺序无所谓，查表用。
DOMAIN_BY_ENDPOINT = {
    # ---------- auth：登录 / 登出 / 用户管理 / 个人偏好 ----------
    'login': 'auth',
    'logout': 'auth',
    'api_users_list': 'auth',
    'api_users_add': 'auth',
    'api_users_edit': 'auth',
    'api_users_delete': 'auth',
    'api_avatar_options': 'auth',
    'api_get_preferences': 'auth',
    'api_save_preferences': 'auth',

    # ---------- library：列表 / 详情 / 扫描 / 标签 / 站点级配置 ----------
    'index': 'library',
    'novel_detail': 'library',
    'tag_manager': 'library',
    'config_page': 'library',
    'save_config_api': 'library',
    'reload_config_api': 'library',
    'get_all_authors': 'library',
    'get_all_tags': 'library',
    'get_all_sites': 'library',
    'get_first_authors': 'library',
    'get_first_tags': 'library',
    'get_first_sites': 'library',
    'get_config_api': 'library',
    'save_sort_preference': 'library',
    'api_random_novel': 'library',
    'start_scan': 'library',
    'get_scan_progress': 'library',
    'api_tag_stats': 'library',
    'api_tag_list': 'library',
    'api_tag_derived_rules': 'library',
    'api_tag_add': 'library',
    'api_tag_edit': 'library',
    'api_tag_delete': 'library',
    'api_tag_add_derived_rule': 'library',
    'api_tag_delete_derived_rule': 'library',
    'api_tag_export': 'library',
    'api_tag_import': 'library',
    'api_tag_reset': 'library',
    'api_tag_reapply': 'library',
    'save_tag_rules': 'library',
    'reload_tag_rules': 'library',
    'get_tag_rules': 'library',
    'add_keyword': 'library',
    'delete_keyword': 'library',
    'edit_keyword': 'library',
    'add_alias': 'library',
    'edit_alias': 'library',
    'delete_alias': 'library',
    'update_alias': 'library',
    'add_derived_rule': 'library',
    'delete_derived_rule': 'library',
    'preview_tag_rules': 'library',
    'import_tag_rules': 'library',

    # ---------- reader：阅读页 / 进度 / 书内搜索 ----------
    'read_chapter': 'reader',
    'continue_reading': 'reader',
    'clear_records': 'reader',
    'api_recent_records': 'reader',
    'delete_reading_record': 'reader',
    'api_mark_read': 'reader',
    'api_search_in_novel': 'reader',
    'admin_clear_all_records': 'reader',
    'admin_clear_user_records': 'reader',
    'admin_user_records': 'reader',

    # ---------- media：配图 / 音视频 / 映射表 ----------
    'check_image_folder': 'media',
    'serve_local_image': 'media',
    'list_image_folder': 'media',
    'open_folder': 'media',
    'serve_local_video': 'media',
    'serve_local_audio': 'media',
    'get_image_mapping': 'media',
    'save_image_mapping': 'media',
    'get_emoji_mapping': 'media',
    'api_header_bg_images': 'media',

    # ---------- core：跨域的基础设施 ----------
    'pwa_manifest': 'core',
    'pwa_service_worker': 'core',
    'static': 'core',
    'get_cache_stats': 'core',
    'force_cleanup': 'core',
}

DOMAIN_NOTE = {
    'auth': '登录、登出、用户增删改、个人阅读偏好',
    'library': '列表 / 详情 / 扫描 / 标签体系 / 站点配置',
    'reader': '阅读页、阅读进度、书内搜索、记录清理',
    'media': '配图检测、音视频、映射表',
    'core': 'PWA、静态资源、缓存统计等跨域基础设施',
}


def load_app():
    sys.stdout = sys.stderr  # 启动日志别混进 markdown
    try:
        import novel_manager

        # 主模块里的模块级 app 才是真正注册了全部路由的那个实例；
        # create_app() 在阶段1只是个空壳（故意不注册路由）。
        # 所以永远优先取 novel_manager.app，取不到才退回工厂。
        instance = getattr(novel_manager, 'app', None)
        if instance is not None:
            return instance, novel_manager
        factory = getattr(novel_manager, 'create_app', None)
        if callable(factory):
            return factory(), novel_manager
        raise SystemExit('既没有 novel_manager.app 也没有 create_app')
    finally:
        sys.stdout = _REAL_STDOUT


def main():
    app, module = load_app()

    rows = []
    for rule in app.url_map.iter_rules():
        methods = ','.join(sorted(m for m in rule.methods if m not in ('HEAD', 'OPTIONS')))
        domain = DOMAIN_BY_ENDPOINT.get(rule.endpoint, 'UNCLASSIFIED')
        rows.append((domain, rule.rule, methods, rule.endpoint))
    rows.sort(key=lambda r: (r[0], r[1]))

    total = len(rows)
    unclassified = [r for r in rows if r[0] == 'UNCLASSIFIED']

    print('# 路由 → 目标蓝图 映射表')
    print()
    print(f'> 自动生成（`python tests/gen_route_table.py`），共 **{total}** 条路由。')
    print('> 分类依据是端点名的功能归属，不是行号；同一域的代码在源文件里可能分散。')
    print()
    print('| 原路由 | 方法 | 端点名 | 目标蓝图 |')
    print('|---|---|---|---|')
    for domain, rule, methods, endpoint in rows:
        flag = ' ⚠️' if domain == 'UNCLASSIFIED' else ''
        print(f'| `{rule}` | {methods} | `{endpoint}` | {domain}{flag} |')

    print()
    print('## 各域规模')
    print()
    print('| 蓝图 | 路由数 | 说明 |')
    print('|---|---|---|')
    counts = {}
    for domain, _, _, _ in rows:
        counts[domain] = counts.get(domain, 0) + 1
    for domain in sorted(counts, key=lambda d: -counts[d]):
        print(f'| {domain} | {counts[domain]} | {DOMAIN_NOTE.get(domain, "—")} |')

    if unclassified:
        print()
        print(f'## ⚠️ 未分类 {len(unclassified)} 条（必须补进 DOMAIN_BY_ENDPOINT）')
        for _, rule, methods, endpoint in unclassified:
            print(f'- `{rule}` {methods} `{endpoint}`')
    return 0


if __name__ == '__main__':
    sys.exit(main())
