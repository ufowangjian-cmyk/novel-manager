# 路由 → 目标蓝图 映射表

> 自动生成（`python tests/gen_route_table.py`），共 **77** 条路由。
> 分类依据是端点名的功能归属，不是行号；同一域的代码在源文件里可能分散。

| 原路由 | 方法 | 端点名 | 目标蓝图 |
|---|---|---|---|
| `/api/avatar/options` | GET | `api_avatar_options` | auth |
| `/api/get_preferences` | GET | `api_get_preferences` | auth |
| `/api/save_preferences` | POST | `api_save_preferences` | auth |
| `/api/users/add` | POST | `api_users_add` | auth |
| `/api/users/delete` | POST | `api_users_delete` | auth |
| `/api/users/edit` | POST | `api_users_edit` | auth |
| `/api/users/list` | GET | `api_users_list` | auth |
| `/login` | GET,POST | `login` | auth |
| `/logout` | GET | `logout` | auth |
| `/api/cache/stats` | GET | `get_cache_stats` | core |
| `/api/force_cleanup` | POST | `force_cleanup` | core |
| `/manifest.json` | GET | `pwa_manifest` | core |
| `/service-worker.js` | GET | `pwa_service_worker` | core |
| `/static/<path:filename>` | GET | `static` | core |
| `/` | GET,POST | `index` | library |
| `/api/random_novel` | GET | `api_random_novel` | library |
| `/api/scan_progress` | GET | `get_scan_progress` | library |
| `/api/start_scan` | GET | `start_scan` | library |
| `/api/tag/add` | POST | `api_tag_add` | library |
| `/api/tag/add-derived-rule` | POST | `api_tag_add_derived_rule` | library |
| `/api/tag/alias/add` | POST | `add_alias` | library |
| `/api/tag/alias/delete` | POST | `delete_alias` | library |
| `/api/tag/alias/edit` | POST | `edit_alias` | library |
| `/api/tag/alias/update` | POST | `update_alias` | library |
| `/api/tag/delete` | POST | `api_tag_delete` | library |
| `/api/tag/delete-derived-rule` | POST | `api_tag_delete_derived_rule` | library |
| `/api/tag/derived-rules` | GET | `api_tag_derived_rules` | library |
| `/api/tag/edit` | POST | `api_tag_edit` | library |
| `/api/tag/export` | GET | `api_tag_export` | library |
| `/api/tag/import` | POST | `api_tag_import` | library |
| `/api/tag/keyword/add` | POST | `add_keyword` | library |
| `/api/tag/keyword/delete` | POST | `delete_keyword` | library |
| `/api/tag/keyword/edit` | POST | `edit_keyword` | library |
| `/api/tag/list` | GET | `api_tag_list` | library |
| `/api/tag/reapply` | POST | `api_tag_reapply` | library |
| `/api/tag/reset` | POST | `api_tag_reset` | library |
| `/api/tag/rule/add` | POST | `add_derived_rule` | library |
| `/api/tag/rule/delete` | POST | `delete_derived_rule` | library |
| `/api/tag/rules/get` | GET | `get_tag_rules` | library |
| `/api/tag/rules/import` | POST | `import_tag_rules` | library |
| `/api/tag/rules/preview` | GET | `preview_tag_rules` | library |
| `/api/tag/rules/reload` | POST | `reload_tag_rules` | library |
| `/api/tag/rules/save` | POST | `save_tag_rules` | library |
| `/api/tag/stats` | GET | `api_tag_stats` | library |
| `/config` | GET | `config_page` | library |
| `/config/get` | GET | `get_config_api` | library |
| `/config/reload` | POST | `reload_config_api` | library |
| `/config/save` | POST | `save_config_api` | library |
| `/config/save_sort` | POST | `save_sort_preference` | library |
| `/get_all_authors` | GET | `get_all_authors` | library |
| `/get_all_sites` | GET | `get_all_sites` | library |
| `/get_all_tags` | GET | `get_all_tags` | library |
| `/get_first_authors` | GET | `get_first_authors` | library |
| `/get_first_sites` | GET | `get_first_sites` | library |
| `/get_first_tags` | GET | `get_first_tags` | library |
| `/novel_detail/<path:file_path>` | GET | `novel_detail` | library |
| `/tag_manager` | GET | `tag_manager` | library |
| `/api/check_image_folder` | POST | `check_image_folder` | media |
| `/api/emoji/image-mapping` | GET | `get_image_mapping` | media |
| `/api/emoji/image-mapping/save` | POST | `save_image_mapping` | media |
| `/api/emoji/mapping` | GET | `get_emoji_mapping` | media |
| `/api/header_bg_images` | GET | `api_header_bg_images` | media |
| `/api/list_image_folder` | POST | `list_image_folder` | media |
| `/api/local_audio` | GET | `serve_local_audio` | media |
| `/api/local_image` | GET | `serve_local_image` | media |
| `/api/local_video` | GET | `serve_local_video` | media |
| `/api/open_folder` | POST | `open_folder` | media |
| `/admin/clear_all_records` | POST | `admin_clear_all_records` | reader |
| `/admin/clear_user_records` | POST | `admin_clear_user_records` | reader |
| `/admin/user_records` | GET | `admin_user_records` | reader |
| `/api/delete_record` | POST | `delete_reading_record` | reader |
| `/api/mark_read` | POST | `api_mark_read` | reader |
| `/api/recent_records` | GET | `api_recent_records` | reader |
| `/api/search_in_novel` | GET | `api_search_in_novel` | reader |
| `/clear_records` | POST | `clear_records` | reader |
| `/continue/<path:file_path>` | GET | `continue_reading` | reader |
| `/read/<path:file_path>/<int:line_number>` | GET | `read_chapter` | reader |

## 各域规模

| 蓝图 | 路由数 | 说明 |
|---|---|---|
| library | 43 | 列表 / 详情 / 扫描 / 标签体系 / 站点配置 |
| media | 10 | 配图检测、音视频、映射表 |
| reader | 10 | 阅读页、阅读进度、书内搜索、记录清理 |
| auth | 9 | 登录、登出、用户增删改、个人阅读偏好 |
| core | 5 | PWA、静态资源、缓存统计等跨域基础设施 |
