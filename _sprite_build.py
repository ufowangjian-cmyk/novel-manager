# -*- coding: utf-8 -*-
"""重建 static/icons.svg（合并 static/icons/*.svg）。
用法: python _sprite_build.py
"""
import io, os, re, sys, glob

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, 'static', 'icons')
OUT = os.path.join(ROOT, 'static', 'icons.svg')

files = sorted(glob.glob(os.path.join(SRC, '*.svg')))
symbols, names = [], []
for path in files:
    name = os.path.splitext(os.path.basename(path))[0]
    raw = open(path, encoding='utf-8').read()
    m = re.search(r'<svg[^>]*>(.*?)</svg>', raw, re.S)
    if not m:
        print('  [skip] %s' % name); continue
    inner = re.sub(r'<!--.*?-->', '', m.group(1), flags=re.S)
    inner = re.sub(r'\s+', ' ', inner).strip()
    vb = re.search(r'viewBox="([^"]+)"', raw)
    symbols.append('  <symbol id="ic-%s" viewBox="%s">%s</symbol>' % (
        name, vb.group(1) if vb else '0 0 24 24', inner))
    names.append(name)

header = '''<!--
  Lucide icon sprite - generated from static/icons/*.svg, do not edit by hand.
  Rebuild: python _sprite_build.py
  Source: https://lucide.dev  (ISC License)
  Usage: <svg class="ic" aria-hidden="true"><use href="/static/icons.svg#ic-search"></use></svg>
-->
'''
open(OUT, 'w', encoding='utf-8').write(
    header + '<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true">\n'
    + '\n'.join(symbols) + '\n</svg>\n')

print('rebuilt %s' % OUT)
print('  icons: %d' % len(names))
print('  size : %.1f KB' % (os.path.getsize(OUT) / 1024))
