# ceek.jp の RSS をページ送りで読み、件数・日付の範囲・サイトの内訳を調べる（試し用）
import re, time, urllib.request, xml.etree.ElementTree as ET, collections
Q = 'site%3Amantan-web.jp%2Cnatalie.mu%2Cwww.oricon.co.jp%2Cwww.animatetimes.com%2Canimeanime.jp'
UA = {'User-Agent': 'Mozilla/5.0 (compatible; anime-news-bot; +https://nzanke.github.io/anime-news/)'}
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read()
for page in (1, 2, 5, 20, 50, 100, 200, 400):
    u = f'https://news.ceek.jp/search.cgi?q={Q}&feed=1&page={page}'
    try:
        x = ET.fromstring(get(u)); its = x.findall('.//item')
        ds = [i.findtext('pubDate') for i in its]
        c = collections.Counter(re.sub(r'https?://([^/]+)/([^/]+).*', r'\1/\2', i.findtext('link')) for i in its)
        print(page, len(its), ds[0] if ds else '', '→', ds[-1] if ds else '', dict(c.most_common(8)))
    except Exception as e: print(page, 'エラー', e)
    time.sleep(2)
# 日付で絞れるか（HTML の検索窓のパラメータを探す）
h = get(f'https://news.ceek.jp/search.cgi?q={Q}').decode('utf-8', 'replace')
print('フォーム:', re.findall(r'<(?:input|select)[^>]+name="([^"]+)"', h)[:30])
print('ページ送り:', re.findall(r'href="([^"]*page=\d+[^"]*)"', h)[:5])
i = h.find('<li'); print(h[i:i+1500])
