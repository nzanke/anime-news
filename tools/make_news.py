"""一覧のデータ data/news.json を作る。

  手がかり1：非公開の anime-database の毎日の収集（MANTANWEB・アニメイトタイムズの本文から判定したもの。本文は含まない）→ data/news_ev.json
  手がかり2：ceek.jp の RSS（5サイト）の見出し → data/rss/*.jsonl。見出しだけで判定する（手がかり1で通した記事は除く）
両方を合わせて、作品ごとにまとめ（同じ発表を伝えた複数のサイトの記事は1行に）、放送・公開前・放送・公開済みを決める。
"""
import glob, json, os, sys
sys.argv = sys.argv[:1]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import news_tag as T

D = os.path.join(T.ROOT, 'data')
prv = json.load(open(os.path.join(D, 'news_ev.json'), encoding='utf-8')) if os.path.exists(os.path.join(D, 'news_ev.json')) else {'ev': [], 'urls': []}
done = set(prv['urls'])
recs = []
for p in sorted(glob.glob(os.path.join(D, 'rss', '*.jsonl'))):
    for l in open(p, encoding='utf-8'):
        try: r = json.loads(l)
        except Exception: continue
        if r['url'] in done: continue
        done.add(r['url'])
        r['body'] = ''
        recs.append(r)
ev, pending = list(prv['ev']), []
n0 = len(ev)
T.extract(recs, ev, pending)

# 見出しだけの手がかりを、本文から判定した手がかりにそろえる（3日以内の同じ作品）
#  名前：同じ名前なら本文側の名前、片方がもう片方を含み、本文側の候補が1つだけならその名前（「星のあしあと」→「映画ぼっち・ざ・ろっく! 星のあしあと」）
#  種類：本文側の種類。本文側がなければ、見出しの手がかりどうしの多数決（「劇場版に新規カットを追加」でTV版を映画と読んだもの）
from collections import Counter, defaultdict
def dn(e):
    try: return T.datetime.date.fromisoformat(e['d'][:10]).toordinal()
    except Exception: return 0
body, head = ev[:n0], ev[n0:]
bidx = defaultdict(list)
for e in body: bidx[T.norm(e['n'])].append(e)
for e in head:
    k, dd = T.norm(e['n']), dn(e)
    near = [x for x in bidx.get(k, []) if abs(dn(x) - dd) <= 3]
    if not near and len(k) >= 4:
        cand = {T.norm(x['n']): x for k2, xs in bidx.items() if len(k2) >= 4 and (k in k2 or k2 in k) for x in xs if abs(dn(x) - dd) <= 3}
        if len(cand) == 1: near = list(cand.values())
    if near:
        x = max(near, key=lambda x: len(x['n']))
        e['n'] = x['n']
        cs = Counter(x['c'] for x in near if x['c'] != '未定')
        if cs: e['c'] = cs.most_common(1)[0][0]
by = defaultdict(list)
for e in head: by[T.norm(e['n'])].append(e)
for k, es in by.items():
    for e in es:
        if any(T.norm(x['n']) == k and abs(dn(x) - dn(e)) <= 3 for x in body): continue
        cs = Counter(x['c'] for x in es if x['c'] != '未定' and abs(dn(x) - dn(e)) <= 3)
        if cs and cs.most_common(1)[0][1] > cs.get(e['c'], 0): e['c'] = cs.most_common(1)[0][0]
items, upcoming, released, ev = T.aggregate(ev)
json.dump({'items': items, 'upcoming': upcoming, 'released': released}, open(os.path.join(D, 'news.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print(f'RSS の記事 {len(recs)}本（本文から判定した記事を除く）→ 手がかり {len(ev)}件（RSS から {len(ev) - n0 if len(ev) > n0 else "?"}）→ ニュース {len(items)}件・放送・公開前 {len(upcoming)}・放送・公開済み {len(released)}')
