# -*- coding: utf-8 -*-
"""比对两份 url_map 快照，**允许端点带蓝图前缀**。

模块化的硬要求是「外部行为不变」，即：URL 规则、HTTP 方法必须逐字一致。
但 Flask 注册蓝图时会给端点强制加 `<蓝图>.` 前缀（login → auth.login），
这是框架行为不是行为变更，所以验收口径定为：

  1. (方法, 规则) 集合必须完全一致        —— 禁止增删路由 / 改方法 / 改 URL
  2. 端点剥掉 `<蓝图>.` 前缀后集合必须一致 —— 禁止端点重命名或张冠李戴

    python tests/diff_url_map.py docs/url_map_before.txt /tmp/urlmap_after.txt
"""

import sys


def parse(path):
    rows = []
    prefixes = set()
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = [p.strip() for p in line.split('|')]
            if len(parts) != 3:
                raise SystemExit(f'无法解析的行: {line!r}')
            methods, rule, endpoint = parts
            bare = endpoint
            if '.' in endpoint:
                head, _, tail = endpoint.partition('.')
                prefixes.add(head)
                bare = tail
            rows.append({'methods': methods, 'rule': rule,
                         'endpoint': endpoint, 'bare': bare})
    return rows, prefixes


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    before_path, after_path = sys.argv[1], sys.argv[2]

    before, _ = parse(before_path)
    after, prefixes = parse(after_path)

    before_keys = {(r['methods'], r['rule']) for r in before}
    after_keys = {(r['methods'], r['rule']) for r in after}

    missing = sorted(before_keys - after_keys)
    added = sorted(after_keys - before_keys)

    before_eps = {r['bare'] for r in before}
    after_eps = {r['bare'] for r in after}
    ep_missing = sorted(before_eps - after_eps)
    ep_added = sorted(after_eps - before_eps)

    # 端点是否错配：同一 (方法, 规则) 对应的 bare 端点是否一致
    before_map = {(r['methods'], r['rule']): r['bare'] for r in before}
    after_map = {(r['methods'], r['rule']): r['bare'] for r in after}
    mismatched = [
        (key, before_map[key], after_map[key])
        for key in sorted(set(before_map) & set(after_map))
        if before_map[key] != after_map[key]
    ]

    print(f'拆分前 {len(before)} 条 / 拆分后 {len(after)} 条')
    print(f'检测到的蓝图前缀: {sorted(prefixes) or ["（无）"]}')

    ok = True
    if missing:
        ok = False
        print(f'\n❌ 丢失的路由 {len(missing)} 条：')
        for methods, rule in missing:
            print(f'   - {methods:10s} {rule}')
    if added:
        ok = False
        print(f'\n❌ 新增的路由 {len(added)} 条：')
        for methods, rule in added:
            print(f'   + {methods:10s} {rule}')
    if ep_missing or ep_added:
        ok = False
        print('\n❌ 端点集合变化：')
        for ep in ep_missing:
            print(f'   - {ep}')
        for ep in ep_added:
            print(f'   + {ep}')
    if mismatched:
        ok = False
        print('\n❌ 端点错配（同一 URL 换了处理函数）：')
        for key, old, new in mismatched:
            print(f'   {key[1]}: {old} -> {new}')

    if not ok:
        return 1

    print('\n✅ (方法, 规则) 逐条一致，端点剥前缀后一致')
    if prefixes:
        print(f'   端点加前缀属框架行为：{", ".join(sorted(prefixes))}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
