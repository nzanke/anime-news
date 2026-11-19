"""ceek.jp のニュース検索の RSS（5サイト・「アニメ」を含む記事）を読み、新しい記事の見出し・URL・日時・サイトを data/rss/<年-月>.jsonl に足す。
RSS の要約（本文の冒頭）は公開のリポジトリに残さない。

  python3 tools/rss_fetch.py               30分ごと：1ページ目から、もう持っている記事が出てくるまで読む（最大20ページ）
  python3 tools/rss_fetch.py --until 2025-10-21   過去の記事を集める：その日付より古い記事が出るまでページを送る
"""
import email.utils, glob, json, os, re, sys, time, urllib.request, xml.etree.ElementTree as ET
from datetime import timezone, timedelta

Q = '%E3%82%A2%E3%83%8B%E3%83%A1%20site%3Amantan-web.jp%2Cnatalie.mu%2Cwww.oricon.co.jp%2Cwww.animatetimes.com%2Canimeanime.jp'   # 「アニメ」で絞った5サイト
URL = 'https://news.ceek.jp/search.cgi?q=' + Q + '&feed=1&page={}'
UA = {'User-Agent': 'Mozilla/5.0 (compatible; anime-news-bot; +https://nzanke.github.io/anime-news/)'}
SITES = {'mantan-web.jp': 'MANTANWEB', 'natalie.mu': 'ナタリー', 'www.oricon.co.jp': 'オリコン', 'oricon.co.jp': 'オリコン',
         'www.animatetimes.com': 'アニメイトタイムズ', 'animeanime.jp': 'アニメ！アニメ！'}
DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'rss')
JST = timezone(timedelta(hours=9))

def norm_url(u):
    u = u.strip().split('#')[0]
    if 'oricon.co.jp' in u or 'natalie.mu' in u or 'animeanime.jp' in u: u = u.split('?')[0]
    return u.rstrip('/') if u.count('/') > 3 else u

def page(n):
    for i in range(3):
        try:
            x = ET.fromstring(urllib.request.urlopen(urllib.request.Request(URL.format(n), headers=UA), timeout=40).read())
            break
        except Exception as e:
            print('読めない', n, e); time.sleep(10)
    else: return None
    out = []
    for it in x.findall('.//item'):
        u = norm_url(it.findtext('link') or '')
        host = re.sub(r'^https?://([^/]+).*', r'\1', u)
        if host not in SITES: continue
        t = re.sub(r'\s*[(（][^()（）]{1,20}[)）]\s*$', '', (it.findtext('title') or '').strip())   # 末尾の「(ナタリー)」などを外す
        try: dt = email.utils.parsedate_to_datetime(it.findtext('pubDate')).astimezone(JST)
        except Exception: continue
        out.append({'url': u, 'title': t, 'date': dt.strftime('%Y-%m-%d'), 'time': dt.strftime('%H:%M'), 'site': SITES[host], 'cat': (it.findtext('category') or '').strip()})
    return out

def main():
    until = sys.argv[sys.argv.index('--until') + 1] if '--until' in sys.argv else None
    start = int(sys.argv[sys.argv.index('--from') + 1]) if '--from' in sys.argv else 1
    os.makedirs(DIR, exist_ok=True)
    seen = set()
    for p in glob.glob(os.path.join(DIR, '*.jsonl')):
        for l in open(p, encoding='utf-8'):
            try: seen.add(json.loads(l)['url'])
            except Exception: pass
    new, n = [], start
    while True:
        rs = page(n)
        if not rs: print('ページが空・読めない', n); break
        fresh = [r for r in rs if r['url'] not in seen]
        for r in fresh: seen.add(r['url'])
        new += fresh
        print(n, rs[0]['date'], '→', rs[-1]['date'], '新しい', len(fresh), flush=True)
        if until:
            if rs[-1]['date'] < until: break
        elif len(fresh) < len(rs) or n >= start + 19: break   # 持っている記事が出てきた
        n += 1; time.sleep(2)
    by = {}
    for r in new: by.setdefault(r['date'][:7], []).append(r)
    for m, rs in by.items():
        with open(os.path.join(DIR, f'{m}.jsonl'), 'a', encoding='utf-8') as f:
            for r in sorted(rs, key=lambda r: (r['date'], r['time'])): f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print('足した記事', len(new))

if __name__ == '__main__': main()
