"""news.json を確認用の一覧（news_tests.json）と照らす。判定を変えたら必ず動かす。

  python3 news_check.py <news.json>
"""
import json, os, re, sys, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
def norm(s):
    s = unicodedata.normalize('NFKC', s or '').lower()
    return re.sub(r'[\s・･!！?？:：~〜～\-－―‐/／\'"“”‘’.,、。☆★♪♡♥()（）\[\]「」『』【】<>《》]', '', s)

up = json.load(open(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'news.json'), encoding='utf-8'))['upcoming']
T = json.load(open(next(p_ for p_ in (os.path.join(HERE, 'news_tests.json'), os.path.join(HERE, '..', 'data', 'news_tests.json')) if os.path.exists(p_)), encoding='utf-8'))   # anime-database は articles/、anime-news は data/
def rows(name, contains=False):
    k = norm(name)
    return [u for u in up if (k in norm(u['n']) if contains else norm(u['n']) == k)]
ng = []
for a in T['absent']:
    hit = rows(a['name'], a.get('contains'))
    if hit: ng.append(f"出てはいけない：{a['name']} → {[(u['n'], u.get('p')) for u in hit]}（{a['why']}）")
for e in T['present']:
    hit = rows(e['name'], e.get('contains'))
    if not hit: ng.append(f"出ていない：{e['name']}"); continue
    if e.get('only_one') and len(hit) > 1: ng.append(f"行が複数：{e['name']} → {[(u['n'], u['c'], u.get('p')) for u in hit]}")
    u = hit[0]
    for f in ('c', 'x', 'p'):
        if f in e and u.get(f) != e[f]: ng.append(f"{e['name']} の {f} が {u.get(f)!r}（正しくは {e[f]!r}）")
    if e.get('no_p') and u.get('p'): ng.append(f"{e['name']} の時期が {u.get('p')!r}（時期は未発表のはず）")
    if e.get('p_not') and e['p_not'] in (u.get('p') or ''): ng.append(f"{e['name']} の時期が {u.get('p')!r}")
    if e.get('tv_not') and any(e['tv_not'] == t[0] for t in u.get('tv') or []): ng.append(f"{e['name']} の局に {e['tv_not']} がある（{u.get('tv')}）")
    if e.get('tv_has') and not any(e['tv_has'] == t[0] for t in u.get('tv') or []): ng.append(f"{e['name']} の局に {e['tv_has']} がない（{u.get('tv')}）")
# 見出しの例文で記事の種類の判定を確かめる（集めた記事にまだ例がない型のため）
_src = open(os.path.join(HERE, 'news_tag.py'), encoding='utf-8').read().split('# ---------------------------------------------------------------- 記事を通す')[0]
_g = {'__file__': os.path.join(HERE, 'news_tag.py')}; _argv = sys.argv; sys.argv = ['news_tag.py', os.devnull]; exec(_src, _g); sys.argv = _argv
for c in T.get('kind_cases', []):
    got = _g['kind'](_g['nf'](c['t']))
    if got != c['k']: ng.append(f"見出しの判定：{c['t']} → {got!r}（正しくは {c['k']!r}。{c['why']}）")
for c in T.get('medium_cases', []):   # 本文の文から媒体を決める判定
    got = _g['body_medium'](_g['nf'](c['s']))[0]
    if got != c['c']: ng.append(f"本文の媒体：{c['s']} → {got!r}（正しくは {c['c']!r}。{c['why']}）")
n = len(T['absent']) + len(T['present']) + len(T.get('kind_cases', [])) + len(T.get('medium_cases', []))
print(f'確認 {n}件のうち 食い違い {len(ng)}件' if ng else f'確認 {n}件 すべてよし')
for x in ng: print(' ✗', x)
sys.exit(1 if ng else 0)
