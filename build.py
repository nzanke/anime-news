"""アニメ制作決定ニュース（https://nzanke.github.io/anime-news/）を組み立てる。
データは data/news.json（非公開の anime-database の articles/news_tag.py が書き出し、公開の anime-world を経由して届く）。
記事の本文は持たず、見出し・リンク・作品名・時期・局だけを載せる。"""
import hashlib, html, json, os, shutil
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
D = lambda *p: os.path.join(HERE, *p)
OUT = D('_site')
SITE = 'アニメ制作決定ニュース'
esc = lambda s: html.escape(str(s or ''))
if os.path.exists(OUT): shutil.rmtree(OUT)
os.makedirs(OUT)
for f in ('style.css', 'news.js'): shutil.copy(D('static', f), OUT)
open(os.path.join(OUT, '.nojekyll'), 'w').close()
NEWS = json.load(open(D('data', 'news.json'), encoding='utf-8'))
nj = json.dumps(NEWS, ensure_ascii=False, separators=(',', ':'))
open(os.path.join(OUT, 'news.json'), 'w', encoding='utf-8').write(nj)
V = lambda b: hashlib.sha1(b).hexdigest()[:8]
CSS_V, NJS_V, NEWS_V = V(open(D('static', 'style.css'), 'rb').read()), V(open(D('static', 'news.js'), 'rb').read()), V(nj.encode())

NAV = [('index.html', 'ニュース'), ('upcoming.html', '放送・公開前'), ('released.html', '放送・公開済み')]
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=BIZ+UDPGothic:wght@400;700&display=swap">'
         # 半角の数字・英字・記号だけ BIZ UDゴシック（text= でその文字だけの字体にし、日本語は BIZ UDPゴシック に落ちる）
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=BIZ+UDGothic:wght@400;700&display=swap&text=%21%22%23%24%25%26%27%28%29%2A%2B%2C-.%2F0123456789%3A%3B%3C%3D%3E%3F%40ABCDEFGHIJKLMNOPQRSTUVWXYZ%5B%5C%5D%5E_%60abcdefghijklmnopqrstuvwxyz%7B%7C%7D~">')

ICONS = '<span class="ic" style="--h:25">映</span>映画 <span class="ic" style="--h:250">TV</span>テレビ <span class="ic" style="--h:150">配</span>配信・OVA・CM・動画 <span class="ic" style="--h:70">?</span>媒体未発表 <span class="sq">続</span>続編・新作'
ABOUT = {
    'index.html': ('ニュース', 'アニメ映画・テレビアニメ・その他のアニメ（OVA・配信アニメ・CM・動画）の制作決定（新規のアニメ化、続編・新作・劇場版の発表）と、その放送日・放送局・公開日のニュースの一覧です。同じ発表を複数のサイトが伝えたものは1行にまとめています。<span class="sq">日程</span>は放送日・放送局・公開日のニュースです。'),
    'upcoming.html': ('放送・公開前', '制作が決まり、まだ放送・公開されていない作品を1作品1行にまとめ、最新の記事で発表された時期の早い順に並べています。局名に指を置くと全局の日時が出ます。1か月以内のものには、日付の横に「あと○日」を薄く添えています。'),
    'released.html': ('放送・公開済み', '放送・公開前の一覧に載っていて、放送・公開が始まったので一覧から外れた作品です（放送・公開の新しい順）。日付は記事で発表された放送・公開日です。'),
}
def about(cur):
    order = [cur] + [k for k in ABOUT if k != cur]
    tabs = ''.join(f'<p><b>{esc(ABOUT[k][0])}</b>：{ABOUT[k][1]}</p>' for k in order)
    return f'''<details class="about"><summary><span class="qi">?</span>このサイトについて</summary><div class="aboutbox"><p class="abh">このサイトについて</p>
{tabs}
<p><b>アイコン</b>：{ICONS}</p>
<p><b>種類</b>：映画（アニメ映画）、テレビ（テレビアニメ）、その他（配信アニメ・OVA・CM・動画）、媒体未発表（テレビか映画かなどがまだ発表されていないもの）。</p>
<p><b>検索と絞り込み</b>：検索欄はスペースで区切ると、すべての語を含むものだけを出します。「日程も出す」は放送日・放送局・公開日のニュースも一覧に入れます。「新規だけ」は続編・新作を除き、新しくアニメ化が決まった作品だけを出します。</p>
<p><b>集めている記事</b>：MANTANWEB と アニメイトタイムズ のアニメの記事。毎日夕方に新着を集めます（記事の解禁がだいたい16〜17時のため）。過去の記事は2025年11月から集めています。</p>
<p><b>載せているもの</b>：記事の日付・見出し・リンクと、記事から読み取った作品名・種類・放送や公開の時期・放送局。記事の本文は載せていません。読み取りは決まった規則で機械的に行っているため、誤りが混じることがあります。</p>
</div></details>'''

def page(path, title, body, current, script=''):
    nav = ''.join(f'<a href="{u}"{" class=on" if u == current else ""}>{esc(t)}</a>' for u, t in NAV)
    full = esc(SITE) if title == SITE else f'{esc(title)}｜{esc(SITE)}'
    doc = f'''<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{full}</title><meta name="description" content="アニメ映画・テレビアニメ・配信アニメなどの制作決定と放送日・公開日のニュースを毎日集めた一覧">
{FONTS}<link rel="stylesheet" href="style.css?v={CSS_V}"></head>
<body><div class="wrap">
<h1 class="sitename"><a href="index.html">{esc(SITE)}</a></h1>
<nav class="nav" aria-label="サイト内">{nav}</nav>
<main>
{body.replace('{ABOUT}', about(current))}
</main>
<footer class="site"><p>MANTANWEB・アニメイトタイムズの記事の見出しとリンクを毎日集めて並べています（記事の本文は載せていません）。アニメの記事を探すなら <a href="https://nzanke.github.io/anime-world/">アニメインタビュー検索</a>。</p></footer>
</div>{script}<script data-goatcounter="https://nzanke.goatcounter.com/count" async src="//gc.zgo.at/count.js"></script></body></html>
'''
    open(os.path.join(OUT, path), 'w', encoding='utf-8').write(doc)

nsites = [x for x, _ in Counter(s_ for e in NEWS['items'] for s_ in [e['s']] + [o[0] for o in e.get('o', [])]).most_common()]
NCATS = [('', 'すべて', 250), ('映画', '映画', 25), ('テレビ', 'テレビ', 250), ('その他', 'その他', 150), ('未定', '媒体未発表', 70)]
UCATS = NCATS
btns = lambda cats: ''.join(f'<button type="button" data-c="{c}" style="--h:{h}"{" class=on" if not c else ""}>{esc(t)}<span class="n"></span></button>' for c, t, h in cats)
SCRIPT = lambda mode: f'<script>window.NEWS="news.json?v={NEWS_V}";window.MODE="{mode}"</script><script src="news.js?v={NJS_V}"></script>'
page('index.html', SITE, f'''<div class="seg" id="seg">{btns(NCATS)}</div>
<div class="sbar"><input type="search" id="q" placeholder="作品名・題名で検索">
<select id="site"><option value="">すべてのサイト</option>{"".join(f'<option>{esc(x)}</option>' for x in nsites)}</select></div>
<div class="opts"><label><input type="checkbox" id="sched" checked> 日程も出す</label><label><input type="checkbox" id="newonly"> 新規だけ</label><label><input type="checkbox" id="old"> 古い順</label></div>
<div class="cbar"><p class="count" id="count"></p>{{ABOUT}}</div>
<ul class="ulist" id="list"></ul>
<button class="more" id="more" hidden>さらに表示</button>''', 'index.html', SCRIPT('news'))
page('upcoming.html', '放送・公開前のアニメ', f'''<div class="seg" id="seg">{btns(UCATS)}</div>
<div class="sbar"><input type="search" id="q" placeholder="作品名・局名で検索"></div>
<div class="opts"><label><input type="checkbox" id="newonly"> 新規だけ</label></div>
<div class="cbar"><p class="count" id="count"></p>{{ABOUT}}</div>
<ul class="ulist" id="list"></ul>
<button class="more" id="more" hidden>さらに表示</button>''', 'upcoming.html', SCRIPT('upcoming'))
page('released.html', '放送・公開済みになったアニメ', f'''<div class="seg" id="seg">{btns(UCATS)}</div>
<div class="sbar"><input type="search" id="q" placeholder="作品名で検索"></div>
<div class="opts"><label><input type="checkbox" id="newonly"> 新規だけ</label></div>
<div class="cbar"><p class="count" id="count"></p>{{ABOUT}}</div>
<ul class="ulist" id="list"></ul>
<button class="more" id="more" hidden>さらに表示</button>''', 'released.html', SCRIPT('released'))
open(os.path.join(OUT, 'about.html'), 'w', encoding='utf-8').write('<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=index.html"><title>アニメ制作決定ニュース</title></head><body><p><a href="index.html">アニメ制作決定ニュース</a></p></body></html>')
print('組み立て', len(NEWS['items']), 'ニュース', len(NEWS.get('upcoming', [])), '放送・公開前', len(NEWS.get('released', [])), '放送・公開済み')
