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
        r['body'] = r.get('desc') or ''   # RSS の抜粋（本文の冒頭）
        r['rss'] = 1
        recs.append(r)
for r in recs: T.learn_alias(T.nf(r['body'])); T.learn_alias2(T.nf(r['body']))   # 抜粋の「正式名称（略称）」も略称の表に
ev, pending = [e for e in prv['ev'] if not T.FIGURE.search(e['t'])], []   # 本文側の手がかりにも同じ除外（毎日の収集が新しい規則で作り直すまでの分）
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

# 同じ日に同じ作品を伝えた行を1行に（期の印・（仮題）・副題の有無だけが違う名前：ブラッククローバー／ブラッククローバー 第10期、無職転生III／無職転生III ~異世界行ったら本気だす~）
import re
def bkey(n): return T.norm(re.sub(r'[(（]仮[題称][)）]', '', T.SEASON_MARK.sub('', re.sub(r'\s*[~〜～][^~〜～]+[~〜～]\s*$', '', n))))
T.is_person('x')
_pc = {}
def names(t):   # 見出しに出てくる人名（データベース・声優一覧にある3字以上の名前）
    if t not in _pc:
        k = T.norm(t)
        _pc[t] = {k[i:j] for i in range(len(k)) for j in range(i + 3, min(len(k), i + 7) + 1) if k[i:j] in T._persons and not k[i:j].isascii()}
    return _pc[t]
# 抜粋の重なり：同じ発表の記事は、同じコメント・同じ説明文を引いている（「ゆうかわ、アニメ2期制作決定、ありがとうございます!」）
DESC = {}
for p in sorted(glob.glob(os.path.join(D, 'rss', '*.jsonl'))):
    for l in open(p, encoding='utf-8'):
        try: r = json.loads(l)
        except Exception: continue
        if r.get('desc'): DESC[r['url']] = T.norm(re.sub(r'^\.\.\.|\.\.\.$', '', r['desc']))
SH = 20
_iu = {u for e in items for u in [e['u']] + [o[1] for o in e.get('o', [])]}   # 一覧に出る記事だけ
_sh = {u: {DESC[u][i:i + SH] for i in range(max(0, len(DESC[u]) - SH + 1))} for u in _iu if u in DESC}
_cnt = Counter(g for x in _sh.values() for g in x)
def shingles(u):
    return {g for g in _sh.get(u, ()) if _cnt[g] <= 6}   # どの記事にもある決まり文句（サイトの案内）は除く
def desc_overlap(a_, b_):
    sa = set().union(*[shingles(u) for u in [a_['u']] + [o[1] for o in a_.get('o', [])]])
    sb = set().union(*[shingles(u) for u in [b_['u']] + [o[1] for o in b_.get('o', [])]])
    return len(sa & sb) >= 15   # 20字の切れ端が15以上重なる（＝34字以上同じ文）
def titles(e): return [e['t']] + [o[2] for o in e.get('o', [])]
def cross(a_, b_):   # 一方の作品名が、もう一方の見出しに出てくる（『ゆうかわ』TVアニメ第2期 ↔ 勇者パーティーにかわいい子がいたので、告白してみた。 第2期）
    ka, kb = bkey(a_['n']), bkey(b_['n'])
    return T.season_no(a_["n"]) == T.season_no(b_["n"]) and ((len(ka) >= 4 and any(ka in T.norm(t) for t in titles(b_))) or (len(kb) >= 4 and any(kb in T.norm(t) for t in titles(a_))))
def distinct(a_, b_):   # 見出しのかぎかっこの名前がまったく重ならない（同じ催しで発表された別の作品：デルタとガンマ／終末停滞委員会）
    qa = {T.norm(x) for t in titles(a_) for x in re.findall(r'[「『]([^」』]{2,60})[」』]', t)}
    qb = {T.norm(x) for t in titles(b_) for x in re.findall(r'[「『]([^」』]{2,60})[」』]', t)}
    return bool(qa) and bool(qb) and not (qa & qb)
merged, rows = set(), {}
for i, e in enumerate(items):
    rows.setdefault(e['d'], []).append(i)
for d, idx in rows.items():
    for x in idx:
        if x in merged: continue
        for y in idx:
            if y == x or y in merged: continue
            a_, b_ = items[x], items[y]
            ka, kb = bkey(a_['n']), bkey(b_['n'])
            same = len(ka) >= 3 and len(kb) >= 3 and (ka in kb or kb in ka)
            if not same and not (len(names(a_['t']) & names(b_['t'])) >= 2 and (a_.get('p') or '') [:4] == (b_.get('p') or '')[:4]) and not cross(a_, b_) and not (T.season_no(a_['n']) == T.season_no(b_['n']) and not distinct(a_, b_) and desc_overlap(a_, b_)): continue   # 名前が違っても、同じ日の見出しに同じ人（声優・監督）が2人以上出ていれば同じ発表（くくルプ／99回断罪された…）
            if a_.get('c') not in (None, '未定') and b_.get('c') not in (None, '未定') and a_['c'] != b_['c']: continue
            us = {a_['u']} | {o[1] for o in a_.get('o', [])}
            for o in [[b_['s'], b_['u'], b_['t'], b_['d']]] + b_.get('o', []):
                if o[1] not in us: a_.setdefault('o', []).append(o); us.add(o[1])
            if T.rank(b_.get('pk', '')) > T.rank(a_.get('pk', '')): a_['p'], a_['pk'] = b_.get('p', ''), b_.get('pk', '')
            if a_.get('c') in (None, '未定') and b_.get('c'): a_['c'] = b_['c']
            if b_.get('k') != 's': a_.pop('k', None)   # どちらかが制作決定なら制作決定の行
            merged.add(y)
items = [e for i, e in enumerate(items) if i not in merged]
json.dump({'items': items, 'upcoming': upcoming, 'released': released}, open(os.path.join(D, 'news.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print(f'RSS の記事 {len(recs)}本（本文から判定した記事を除く）→ 手がかり {len(ev)}件（RSS から {len(ev) - n0 if len(ev) > n0 else "?"}）→ ニュース {len(items)}件・放送・公開前 {len(upcoming)}・放送・公開済み {len(released)}')
