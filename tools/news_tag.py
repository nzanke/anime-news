"""集めたニュース（news/*.jsonl）から、アニメの制作決定と日程（放送日・放送局・公開日）を取り出し、公開用の news.json を書き出す。

  python3 news_tag.py <出力先 news.json>        （例：../../anime-world/data/news.json）
  python3 news_check.py <news.json>            （確認用の一覧 news_tests.json と照らす。判定を変えたら必ず動かす）

5つの段を順に1回ずつ通す。
  1. 作品を決める（identify）  見出しから作品名を1つ（同じ記事で別々の時期の作品を発表していれば複数）決め、本文の正式名称にそろえる
       MANTANWEB の見出しの「：」の前は正式名称ではない（略称のことが多い）。本文の『』「」の名前と一致すればそのまま、一致しなければ、それを含む本文の名前・略称の表で正式名称にする
       A. 名前をそろえる（canon）：略称・前後の入れ替わった名前は本文の正式名称に、見出しが第N期の話なら「元の名前 第N期」、本文の「作品名称：『…』」を優先
  2. 記事の種類を決める（kind）  制作決定 a／日程 s／公開・放送後 post／そのほか（使わない）
  3. 事実を取る（facts）       媒体・時期・局。見出しから取り、本文からはその作品名が出てくる文（と次の文）からだけ取る
       B. その作品の文と認める条件：作品名か「決定」を含む文。同じシリーズの別の作品（前の期・旧作）の名前が出てくる文と、過去の節（放送された・最終回・上映されていましたが・…に続き）は除く
  4. 作品ごとにまとめる        同じ作品の記事を集め、媒体（映画とそれ以外）で分け、名前違い（Paradox Live／Paradox Live THE MOVIE）をまとめる。期の数が違うもの・一方の発表の時点でもう一方が放送・公開済みのものはまとめない
  5. 放送・公開前か決める       予定の時期が過ぎていない、かつ最新の発表より後に「始まった」手がかり（公開・放送後の記事、データベースの放送開始）がない
例外は news_upcoming_fix.csv（作品名,扱い,正しい作品名。扱いは「放送済み」「外す」「載せる」）に書く。本文は書き出さない。
"""
import csv, datetime, glob, json, os, re, sqlite3, sys, unicodedata
from collections import defaultdict, Counter

# 置き場所：正本は公開の anime-news（tools/news_tag.py・data/news_upcoming_fix.csv）。非公開の anime-database の毎日の収集は、動かす前にそれを articles/ に取ってくる
SD = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(SD, '..')
HERE = os.path.join(ROOT, 'data') if os.path.exists(os.path.join(ROOT, 'data', 'news_upcoming_fix.csv')) else SD   # anime-news は data/、anime-database は articles/
BODIES = os.environ.get('NEWS_BODIES') or os.path.join(SD, 'news')   # 本文つきの記事（非公開の anime-database だけ）
TODAY = datetime.date.today().isoformat()
def nf(s):   # NFKC ＋ カタカナの後ろの漢数字「一」を長音「ー」に（「乙女ゲ一ム」の取り違え）
    return re.sub(r'(?<=[ァ-ヶ])[一―‐－—─](?=[ァ-ヶ])', 'ー', re.sub(r'(?<=[ァ-ヶ])一', 'ー', unicodedata.normalize('NFKC', s or '')))   # 「ゲ―ム」（横棒）もカタカナにはさまれていれば長音

def norm(s):
    s = ''.join(c for c in unicodedata.normalize('NFKD', nf(s).lower()) if not unicodedata.combining(c))   # アクセント記号を外す（MURCIÉLAGO）
    s = unicodedata.normalize('NFKC', s)
    return re.sub(r'[\s・･!！?？:：~〜～\-－―‐/／\'"“”‘’.,、。☆★♪♡♥()（）\[\]「」『』【】<>《》〈〉＜＞]', '', s)

# ================================================================ 言葉の表（判定はこの表と下の5つの段だけで決まる）
N = r'[0-9０-９一二三四五六七八九十]'
# 制作決定：制作の言葉 ＋ 決定などの言葉
PRODUCE = r'アニメ化|映画化|制作|製作|続編|新作|新シリーズ|始動|プロジェクト|' + N + r'{1,2}期'
ANNOUNCE = re.compile(r'(' + PRODUCE + r'|劇場版|劇場アニメ)[^、。！!]{0,24}?(決定|発表|始動|進行中|制作中|製作中|決まる|決まった)|アニメ化|映画化|プロジェクト始動')
# 日程：放送・公開・配信・上映の日や局
SCHEDULE = re.compile(r'限定上映|上映決定|上映開始|放送日|放送開始|放送スタート|放送決定|放送局|放送時期|放送枠|(より|から)(放送|公開|配信|上映)|(放送|公開)へ|公開日|公開決定|劇場公開|配信開始|配信日|配信決定|'
                      r'(\d+年(\d{1,2}月|春|夏|秋|冬)|\d{1,2}月\d{1,2}日|\d{1,2}/\d{1,2})(\(.\))?(から|より|に)?.{0,8}(放送|公開|配信|上映|スタート)')
# 公開・放送が始まったあと（これがあれば「始まった」手がかり）
POST_MOVIE = re.compile(r'公開中|上映中|大ヒット|興収|興行収入|動員|公開御礼|(舞台あいさつ|舞台挨拶)(?!.{0,10}(決定|開催|実施))')
POST_TV = re.compile(r'放送中|配信中|最終回')
# 作品の発表・日程ではない記事（話題・催し・グッズ・音楽・反響・インタビューなど）
NOT_NEWS = re.compile(r'再上映|特典|入プレ|生放送|PPV|インタビュー|対談|鼎談|座談会|語る|レポート|記念|周年|上映会|リバイバル|4K|リマスター|Blu-ray|ブルーレイ|BD|DVD|グッズ|コラボ|主題歌|挿入歌|振り返り|あらすじ|候補|舞台あいさつ|舞台挨拶|大ヒット|初日|アフレコ|収録|泣いて|涙|なぜ|反響|予想|どうなる|'
                      r'(アニメ化|映画化|ドラマ化)[^。]{0,8}(も話題|で話題|の人気|された|した人気|も人気)')
# 日程として読まない話題（映像・催し・グッズ・音楽・各話など）
NOT_SCHED = re.compile(r'OST|デジタル配信|無料配信|見放題|一挙配信|初放送|地上波初|(予告|特報|PV).{0,12}上映|復活上映|上映期間|上映館|\d+タイトル|INFO|感謝祭|番組|プレミア公開|見学|発表会|生配信|主題歌|シングル|楽曲|サントラ|サウンドトラック|ラジオ|CD|特別エピソード|特別編|傑作選|特別上映|IMAX|4DX|MX4D|Dolby|リバイバル|再上映|応援上映|'
                       r'\d{4}年公開の|スペシャル|一挙|あらすじ|第\d+話|振り返り|再放送|特番|総集編|レビュー|ランキング|特典|入プレ|グッズ|コラボ|イベント|BD|Blu-ray|ブルーレイ|DVD')
PAST = re.compile(r'(アニメ化|映画化|ドラマ化)[^。]{0,8}(も話題|で話題|の人気|された|した人気|も人気)')   # 過去のアニメ化・映画化への言及
NOT_NEWS_CORE = re.compile(NOT_NEWS.pattern.replace('|(アニメ化|映画化|ドラマ化)[^。]{0,8}(も話題|で話題|の人気|された|した人気|も人気)', ''))
AWARD = re.compile(r'選出|受賞|ノミネート|映画祭|アワード|グランプリ')
KEEP = re.compile(r'化決定|(制作|製作|続編|新作|期)[^。]{0,4}決定')   # これがあれば NOT_NEWS の言葉があっても発表・日程として読む
NOT_ANIME = re.compile(r'ウェブトゥーン|WEBTOON|実写|ドラマ化|舞台化|ミュージカル化|ゲーム化|コミカライズ|小説化|ノベライズ')
ROUNDUP = re.compile(r'^(アニメ|マンガ|今週).{0,3}1週間')
# 媒体
MOVIE = re.compile(r'新作映画|劇場版|劇場アニメ|アニメ映画|アニメーション映画|映画化|劇場公開|長編アニメ|映画『|映画「|劇場作品|ロードショー|上映')
TVW = re.compile(r'TVアニメ|テレビアニメ|TVシリーズ|テレビシリーズ|' + N + r'{1,2}期|放送')
OTHER = [('OVA', re.compile(r'OVA|OAD')),
         ('配信', re.compile(r'配信アニメ|配信限定|独占配信|Netflix|ネットフリックス|Disney\+|ディズニープラス|Prime Video|プライムビデオ|ABEMA|Lemino|U-NEXT|WEBアニメ|ウェブアニメ|配信オリジナル|世界配信|\d+年.{0,6}配信')),
         ('CM', re.compile(r'CM|コマーシャル|広告アニメ')),
         ('動画', re.compile(r'YouTube|ユーチューブ|MV|ミュージックビデオ|ショートアニメ|ショートムービー|縦型アニメ|PVアニメ|アニメーションPV|TikTok'))]
SEQ = re.compile(r'第[2-9２-９二三四五六七八九十]' + N + r'?[期部]|[2-9２-９]期|続編|新シリーズ|シーズン ?[2-9２-９]|Season ?[2-9]|新章|完全新作|再アニメ化|リメイク|(?<!最)新作(?!アニメ化)|新プロジェクト|ファイナルシーズン|最終章')
# 作品名にしない名前（催し・グッズ・番組などの名前）
NOT_TITLE = re.compile(r'展|イベント|特番|上映会|コラボ|ダイジェスト|総集編|記念|フェス|Fest|キャンペーン|ストア|カフェ|グッズ|ポップアップ|分で分かる|祝|ステージ|舞台|感謝祭|20\d\d|園遊会|ラジオ|RADIO|生放送|配信番組|'
                       r'チャンネル|プロジェクト|画集|大全集|音楽祭|ツアー|主題歌集|^(?:ゲーム|Game)$|Blu-ray|BOX|巻|COMIC|コミック|御礼|WEB|マップ|×')
# 放送局・配信先・放送枠
STATIONS = ['TOKYO MX', 'テレビ東京', 'テレ東', 'フジテレビ', '日本テレビ', '日テレ', 'TBS', 'テレビ朝日', 'NHK総合', 'NHK Eテレ', 'Eテレ', 'NHK', 'BS11', 'BS日テレ', 'BSフジ', 'BS朝日', 'BS-TBS', 'BSテレ東', 'BS12', 'AT-X',
            'MBS', '毎日放送', 'ABCテレビ', '朝日放送', 'CBC', '読売テレビ', 'カンテレ', '関西テレビ', '中京テレビ', 'メ～テレ', 'テレビ愛知', 'テレビ大阪', 'サンテレビ', 'KBS京都', 'テレ玉', 'チバテレ', 'tvk', 'とちぎテレビ', '群馬テレビ', 'アニマックス', 'WOWOW',
            'Netflix', 'Prime Video', 'Amazonプライム・ビデオ', 'ディズニープラス', 'Disney+', 'ABEMA', 'U-NEXT', 'dアニメストア', 'Lemino', 'Crunchyroll', 'YouTube']
ST_RX = re.compile('|'.join(re.escape(x) for x in sorted(STATIONS, key=len, reverse=True)))
NOT_ON_AIR = r'ポッドキャスト|Spotify|PV|映像|特報|予告|ティザー|生配信|生放送|番組|チャンネル|ライブ|特番|動画|ラジオ|オーディオドラマ|ボイスドラマ|前作|過去|振り返り|一挙|連続配信|期間限定|無料|記念'
ST_SAME = {'テレ東': 'テレビ東京', '日テレ': '日本テレビ', 'Disney+': 'ディズニープラス', '関西テレビ': 'カンテレ', '毎日放送': 'MBS', '朝日放送': 'ABCテレビ'}
FRAMES = re.compile(r'ノイタミナ|アニメイズム|\+Ultra|IMAnimation|NUMAnimation|FRIDAY ANIME NIGHT|アガルアニメ|日5|木曜劇場|AnichU|ANiMAZiNG')
SEASON = {'冬': 1, '春': 4, '夏': 7, '秋': 10}
NEAR = re.compile(r'放送|公開|配信|上映|放映|スタート|始動|予定|ロードショー|開始|(テレビ|TV|劇場)?アニメ化|映画化')
_HEAD = [False]
def HEAD(b):   # いま通している記事が RSS の見出しと抜粋だけのもの（本文なし）
    return _HEAD[0] or not b

NEAR_BODY = re.compile(r'放送|公開|配信|上映|放映|ロードショー')   # 本文は「2026年に20周年」などがあるので、放送・公開などの言葉があるときだけ

# ================================================================ データベース・手直しの表
db_titles, db_starts = set(), defaultdict(list)   # 正規化した番組名 → [開始日]
dbp = os.environ.get('NEWS_DB') or os.path.join(ROOT, 'data', 'db', 'anime_credits.sqlite')
REF = os.path.join(HERE, 'news_ref.json.gz')   # データベースから書き出した番組名・開始日・人名（公開の anime-news 用。--export で作る）
_ref_persons = None
_ref_alias = {}
if os.path.exists(dbp):
    for t, sd in sqlite3.connect(f'file:{dbp}?mode=ro', uri=True).execute('SELECT title, start_date FROM works'):
        k = norm(re.sub(r'\s*[（(][^）)]*[）)]\s*$', '', t))
        if len(k) >= 3: db_titles.add(k)
        if sd: db_starts[k].append(sd)
elif os.path.exists(REF):
    import gzip
    _r = json.load(gzip.open(REF, 'rt', encoding='utf-8'))
    db_titles = set(_r['titles']); db_starts = defaultdict(list, _r['starts']); _ref_persons = set(_r['persons']); _ref_alias = _r.get('alias', {})
FIX, RENAME = {}, {}
if os.path.exists(os.path.join(HERE, 'news_upcoming_fix.csv')):
    for row in csv.DictReader(open(os.path.join(HERE, 'news_upcoming_fix.csv'), encoding='utf-8-sig')):
        if not row.get('作品名'): continue
        if (row.get('正しい作品名') or '').strip(): RENAME[norm(row['作品名'])] = row['正しい作品名'].strip()
        if (row.get('扱い') or '').strip(): FIX[norm(RENAME.get(norm(row['作品名']), row['作品名']))] = row['扱い'].strip()

# ================================================================ 時期・局を読む部品
def plan(s, base='', body=False):
    """文の中の放送・公開時期 → (表示, 鍵 'YYYY-MM-DD')。月・季節までなら日を 99、年だけなら 12-99。なければ ('', '')。
    年のない日付・月は記事の日付から補う（見出しは先の日付、本文は記事と同じ年）。記事より前の月・範囲の後ろ側（10～12月）・「された」は読まない"""
    by = int(base[:4]) if base[:4].isdigit() else int(TODAY[:4]); bm = int(base[5:7]) if base[5:7].isdigit() else 1
    s = re.sub(r'(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])', r'\1月\2日', s)
    for m in re.finditer(r'(?:(20)?(\d\d)年)?(\d{1,2})月(\d{1,2})日', s):
        mo, d = int(m.group(3)), int(m.group(4))
        if not (NEAR.search(s[m.end():m.end() + 24]) or re.search(r'(放送|公開|配信|上映)(開始)?日(は|が)\s*$', s[max(0, m.start() - 12):m.start()])) or not (1 <= mo <= 12 and 1 <= d <= 31): continue   # 「初回放送日は4月10日」も
        y = 2000 + int(m.group(2)) if m.group(2) else (by if body else (by + 1 if mo < bm - 1 else by))
        if y > by + 3 or (base and f'{y}-{mo:02d}' < base[:7]): continue
        return f'{y}年{mo}月{d}日', f'{y}-{mo:02d}-{d:02d}'
    s = re.sub(r'今年(?=(?:中|内)?に?(?:公開|放送|配信|上映|スタート))|(今|来)(春|夏|秋|冬)|来年', lambda m: f"{by + (m.group(0).startswith('来'))}年" + (m.group(2) or ''), s)   # 今秋・来春・来年も年に（記事の日付から）。「今年4月の放送開始時」のような過去は読まない   # 今秋・来春なども年に（記事の日付から）
    best = None
    for m in re.finditer(r'(20)?(\d\d)年の?(?:(\d{1,2})月|(春|夏|秋|冬)|度)?', s):
        if not m.group(1) and not (m.group(3) or m.group(4)): continue
        win = re.sub(r'Netflix|Prime ?Video|Amazon|Disney\+|ディズニープラス|U-NEXT|ABEMA|Hulu|にて|世界|独占|先行', '', s[m.end():m.end() + 40])[:14]   # 「2026年8月Netflixにて世界独占配信」も
        if not (NEAR_BODY if body else NEAR).search(win) or re.search(r'され|した', s[m.end():m.end() + 12]): continue
        y = 2000 + int(m.group(2))
        if y < by or y > by + 5: continue
        if m.group(3): return f'{y}年{int(m.group(3))}月', f'{y}-{int(m.group(3)):02d}-99'
        if m.group(4): return f'{y}年{m.group(4)}', f'{y}-{SEASON[m.group(4)]:02d}-99'
        best = best or (f'{y}年', f'{y}-12-99')
    if best: return best
    for m in re.finditer(r'(?<![\d年~〜～\-－])(\d{1,2})月(?!\d)', s):
        mo = int(m.group(1))
        if not (NEAR_BODY if body else NEAR).search(s[m.end():m.end() + 10]) or re.search(r'され|した', s[m.end():m.end() + 12]) or not 1 <= mo <= 12: continue
        y = by + 1 if mo < bm - 1 else by
        return f'{y}年{mo}月', f'{y}-{mo:02d}-99'
    return '', ''

def rank(k): return 0 if not k else (1 if k.endswith('12-99') else 2 if k.endswith('99') else 3)   # 時期の細かさ：年＜月・季節＜日

def stations(txt):
    """局名・放送枠と、そのすぐ後ろの放送日時 → [[局名, 日時], …]"""
    out = {}
    for m in sorted(list(FRAMES.finditer(txt)) + list(ST_RX.finditer(txt)), key=lambda m: m.start()):
        v = ST_SAME.get(m.group(0), m.group(0))
        # 放送・配信先でないもの：「PVをYouTubeで公開」「公式YouTubeチャンネル」「生配信番組」「前作を連続配信」「ラジオの過去回」。
        # 動画サイト（YouTube・ABEMA）はその文全体で、ほかの局は局名の後ろ30字で見る
        after = re.split(r'[。\n]', txt[m.end():m.end() + 30])[0]
        sent = re.split(r'[。\n]', txt[:m.start()])[-1] + re.split(r'[。\n]', txt[m.end():])[0]
        if re.search(r'公式$', txt[max(0, m.start() - 4):m.start()]) or re.search(NOT_ON_AIR, sent if v in ('YouTube', 'ABEMA') else after): continue
        if v == 'NHK' and any(x.startswith('NHK') and x != 'NHK' for x in out): continue
        w = re.match(r'^[\s:：・／/、,（(）)]*(?:系列?|ほか|他|にて|で|では|[\s、,])*((?:(?:(?:20\d\d|\d\d)年)?\d{1,2}月\d{1,2}日(?:\([^)]{1,3}\))?)?(?:(?:から|より|〜|~|～)\s*)?(?:毎週)?'
                     r'(?:[月火水木金土日](?:曜日?|曜)?)?\s*(?:(?:午前|午後|深夜|夜|朝|夕方)?\d{1,2}(?::\d{2}|時(?:\d{1,2}分|半)?)\s*(?:〜|~|～|から|より)?)?)', txt[m.end():m.end() + 50])
        w = w.group(1).strip() if w and re.search(r'\d', w.group(1)) else ''
        if v not in out or (w and not out[v]): out[v] = w
    return [[k, w] for k, w in list(out.items())[:6]]

def merge_tv(a, b):
    d = {k: w for k, w in a}
    for k, w in b:
        if not d.get(k): d[k] = w
    return [[k, w] for k, w in d.items()]

def medium(s):
    """(媒体, その他の種類)。テレビの言葉と放送があればテレビ（劇場版をもとにしたテレビアニメ）。なければ (None, '')"""
    s = re.sub(r'実写(映画|ドラマ|版)?(化)?|(アニメーション|アニメ)?映画(祭|賞)', '', s)   # 「実写映画化も話題」の映画は媒体ではない
    if re.search(r'(TV|テレビ)アニメ', s) and ('放送' in s or re.search(r'(TV|テレビ)アニメ化', s)): return 'テレビ', ''
    if MOVIE.search(s): return '映画', ''
    if re.search(r'TVアニメ|テレビアニメ|TVシリーズ|テレビシリーズ|' + N + r'{1,2}期', s): return 'テレビ', ''
    if re.search(r'公開(決定|日|開始)|(から|より|に)公開|\d{1,2}日公開|劇場', s) and not re.search(r'放送|配信|公開メディア|短編', s): return '映画', ''
    if '放送' in s and not re.search(r'独占(配信|放送)|配信限定|配信のみ', s): return 'テレビ', ''   # 「2027年1月に放送、配信」はテレビ
    for name, rx in OTHER:
        if rx.search(s): return 'その他', name
    if TVW.search(s): return 'テレビ', ''
    return None, ''

# ================================================================ 1. 作品を決める
def bracketed(name, b): return bool(name) and bool(re.search('[『「]' + re.escape(name) + r'(?:[』」\s(（:：~〜\-]|$)', b))   # 「天野喜孝の世界を…」のような引用は数えない

def expand(name, b, t=''):
    """見出しの作品名を本文の正式名称にそろえる。本文にその名前だけで書かれていればそのまま。
    そうでなければ、本文の『』「」のうち、その名前で始まる名前（頭に劇場版・映画が付くものも）か、略称なら頭の字が同じで字を順に含む名前"""
    if not name: return name
    nn = norm(name)
    alone = bool(re.search('[『「]' + re.escape(name) + '[』」]', b))
    cands = [(f[0] or f[1]).strip() for f in re.findall(r'『([^』]{3,70})』|「([^」]{3,70})」', b[:1500])]
    if '『' in t and '『' in b[:1500]: cands = [x.strip() for x in re.findall(r'『([^』]{3,70})』', b[:1500])]   # 『』で作品名を書く記事では「」は特番・曲名・催し
    first = cands[0] if cands else None   # 本文で最初に出てくる名前（記事の主題）
    nt = norm(t)
    prev = re.findall(r'[「『]([^」』]{2,40})[」』](?:編)?に(?:続き|引き続き)', t)
    for raw in sorted(cands, key=lambda f: 0 if norm(f).startswith(nn) and len(norm(f)) > len(nn) and norm(f)[len(nn):] in nt else 1):   # 残りの部分が見出しにもある名前を先に
        full = re.sub(r'^(TV|テレビ)?アニメ\s*', '', raw)
        full = re.sub(r'\s*[(（]([^)）]{1,40})[)）]$', lambda m: '' if norm(m.group(1)) == nn or len(m.group(1)) <= 6 or re.match(r'^([ぁ-んァ-ヶー・!！\s]+|読み|英題)', m.group(1)) else m.group(0), full)
        k = norm(full)
        if any(k.endswith(norm(x)) for x in prev): continue   # 見出しで「…に続き」と書かれた前の作品（本好きの下剋上 領主の養女）
        if len(k) <= len(nn) or re.search(r'[。、]$|[『』「」]', full) or (raw != first and re.search(r'[！？!?]$', full)) or NOT_TITLE.search(full): continue   # 「？」「！」で終わる名前は本文の最初の名前なら作品名（ごきげんよう、一局いかが？）
        if nn in k and k.replace(nn, '', 1) in nt: return full                                     # 残りの部分も見出しにある名前（名探偵コナン＋ハイウェイの堕天使）
        if not alone and raw == first and (k.startswith(nn) or (re.match(r'(劇場版|映画|新作)', k) and nn in k[:len(nn) + 4])): return full   # 頭で一致するだけなら最初の名前のときだけ
        ab = re.sub(r'アニメ$', '', nn)
        if raw == first and nn in k and not k.startswith(nn): return full   # 最初の名前の途中・後ろの部分（器用貧乏 → 勇者パーティを追い出された器用貧乏、おっさん剣聖 → 片田舎のおっさん、剣聖になる）
        if raw == first and nn in [norm(x) for x in re.split(r'\s*[-－―‐]\s*', full) if x.strip()]: return full   # 部分の名前（戦車椅子 → TANK CHAIR-戦車椅子-）
        if raw == first and (len(ab) >= 4 or len(ab) == 3 and ab[0] == k[0]) and nn not in k and all(ch in iter(k) for ch in ab): return full   # 3文字の略称は頭の字も同じとき（キミ戦）   # 最初の名前の略称は頭の字を問わない（おっさん剣聖II）
        if full[0] == name[0] and nn not in norm(k) and len(ab) >= 2 and all(ch in iter(k) for ch in ab) and (nn not in norm(b) or ab != nn): return full   # 略称（デモクレ、うち弟アニメ）
    if len(norm(name.split()[0])) <= 8 and not alone:   # 見出しの略称が本文にまったく出てこない（かのかり、まとスレ）→ 本文でいちばん多い名前（2回以上）
        tails = [norm(x) for x in name.split()[1:] if x.strip()]
        cnt = Counter(x for x in (re.sub(r'\s*[(（][^)）]*[)）]$', '', x).strip() for x in re.findall(r'『([^』]{3,60})』', b[:2500])) if all(tl in norm(x) for tl in tails))
        top = sorted(cnt.items(), key=lambda x: (x[1], len(x[0])), reverse=True)[:1]
        if top and (top[0][1] >= 2 or tails and len(norm(top[0][0])) > len(nn)) and not NOT_TITLE.search(top[0][0]): return top[0][0]   # 副題があれば1回でよい（いちばん長い名前）
    return name

ALIAS = dict(_ref_alias)   # 略称 → 正式名称。どの記事の本文でも「正式名称（略称）」「『正式名称』（通称、略称）」と書かれたもの
ALIAS_RX = [re.compile(r'[『「]([^』」（(]{3,80}?)\s*[（(](?:通称[、,]?\s*|以下[、,]?\s*)?([^）)』」]{2,12})[）)][』」]'),
            re.compile(r'[『「]([^』」]{3,80})[』」]\s*[（(](?:通称|以下)[、,]?\s*([^）)]{2,12})[）)]')]
def learn_alias(b):
    for rx in ALIAS_RX:
        for full, ab in rx.findall(b[:3000]):
            full, ab = full.strip(), ab.strip()
            if re.fullmatch(r'[ぁ-ん・\s]+', ab) and '・' in ab or len(norm(ab)) * 2 > len(norm(full)) or re.search(r'[。「」『』]|色紙|カード|グッズ|アクリル|ポスター|ファイル|ブロマイド|しおり|特典|Blu-ray|BOX', full) or \
               re.search(r'\d|種|ver|本作|仮題|仮称|原題|前編|後編|初日|主人公|抜粋', ab, re.I): continue   # 読みがな・グッズ・言葉の注
            ALIAS.setdefault(norm(ab), full)
ALIAS_RX2 = [re.compile(r'「((?:[^「」『』（()]|『[^』]{1,40}』){3,90}?)\s*[（(]([^）)」]{2,12})[）)]」'),   # 中に『』のある名前：「99回…『超絶愛されモード』ですって!?(くくルプ)」
             re.compile(r'『((?:[^『』「」]|「[^」]{1,40}」){3,90})』\s*[（(]([^）)]{2,12})[）)]')]           # 『99回…「超絶愛されモード」ですって!?』(くくルプ)
def learn_alias2(b):   # RSS の抜粋から（中に別のかぎかっこのある長い名前の略称）
    for rx in ALIAS_RX2:
        for full, ab in rx.findall(b or ''):
            full, ab = full.strip(), ab.strip()
            if '。' in full or norm(full).startswith(norm(ab)) or len(norm(ab)) * 2 > len(norm(full)) or re.search(r'\d|種|ver|本作|仮題|仮称|原題|読み', ab, re.I): continue
            ALIAS.setdefault(norm(ab), full)
def alias(name, b):
    """略称を正式名称に（その記事の本文にも正式名称が出てくるときだけ）。略称＋数字（このすば4）は「正式名称 第N期」"""
    if norm(name) in ALIAS and norm(ALIAS[norm(name)])[:6] in norm(b): return ALIAS[norm(name)]
    m = re.fullmatch(r'(.+?)\s*([2-9])', name)
    if m and norm(m.group(1)) in ALIAS and norm(ALIAS[norm(m.group(1))])[:6] in norm(b): return ALIAS[norm(m.group(1))] + f' 第{m.group(2)}期'
    return ''

_persons = None
def is_person(name):
    """人の名前か（「…監督」「…さん」、データベースのスタッフ、声優一覧）"""
    global _persons
    if re.search(r'(監督|さん|氏|先生|作者|社長|プロデューサー)$', name): return True
    if _persons is None:
        _persons = set(_ref_persons or ())
        if os.path.exists(dbp): _persons = {norm(p_) for (p_,) in sqlite3.connect(f'file:{dbp}?mode=ro', uri=True).execute("SELECT DISTINCT person FROM v_staff_credits")}
        if os.path.exists(os.path.join(SD, '声優一覧.txt')): _persons |= {norm(x) for x in open(os.path.join(SD, '声優一覧.txt'), encoding='utf-8').read().split()}
    return norm(name) in _persons and norm(name) not in db_titles

def identify(r, t, b):
    """記事の作品名を決める。
    見出しの頭の「名前：」（MANTANWEB）は、本文でも『』「」で書かれている名前か番組名のときだけ作品名にする（人名・会社名・「解説」などは書かれない）。
    そうでなければ見出しの『』、次に「」の名前。どれもなければ作品の記事ではない"""
    raw = r.get('title') or ''
    name = ''
    m = re.match(r'([^:]{0,59}(?:[^:\d]|(?<![\d:])\d)):', t) if r.get('site') == 'MANTANWEB' else None   # 「サンダー3：」も（「12:00」は除く）
    if m:
        name = m.group(1).strip()
        seg = raw.split('　')[0]   # 「SEKIRO：NO DEFEAT：全8話の…」のように名前に「：」があるもの
        mid = seg[seg.index('：') + 1:seg.rindex('：')] if seg.count('：') >= 2 else ''
        if mid and not re.search(r'[「『]|^\s*[\d第]|ぶり|新作|劇場|アニメ', mid): name = nf(seg[:seg.rindex('：')]).strip()
        # 本文で『』「」に入れて書かれる名前か番組名だけを作品名にする（人名・会社名・「解説」などは書かれない）。
        # ただし見出しに「」の作品名がなく、アニメ化・新作アニメの発表なら、頭の名前が作品名
        if HEAD(b) and r.get('site') == 'MANTANWEB':
            if re.search(r'週間$|さん$|^ドラマ|^映画|^話題|^解説|^朝ドラ', name) or is_person(name): name = ''
        elif not (bracketed(name, b) or norm(name) in db_titles or RENAME.get(norm(name)) or
                (re.search(r'アニメ化|新作アニメ|劇場版アニメ|オリジナル(テレビ)?アニメ|(テレビ|TV)アニメ', t) and norm(name) in norm(b) and not is_person(name))): name = ''
    head = name
    if not name and HEAD(b) and len(re.findall(r'[「『]', t)) >= 2:   # 見出しだけ（RSS）で名前が2つ以上：「A」「B」の作者が描く「C」TVアニメ化 → C、完全オリジナル『X』→ X
        m = re.search(r'(?:新作|新)[^「『]{0,15}アニメ[^「『]{0,30}[「『]([^」』]{2,60})[」』]', t) or \
            re.search(r'[「『]([^」』]{2,60})[」』](?=\s*(?:が|の)?\s*(?:(?:TV|テレビ)?アニメ化|新作アニメ|劇場アニメ化|アニメ映画化|映画化))', t) or \
            re.search(r'(?:描く|原作の|完全オリジナル|劇場アニメ|劇場版アニメ|新作映画|アニメ映画化)\s*[「『]([^」』]{2,60})[」』]', t)
        if m: name = m.group(1)
        if not name:   # 『ONE PIECE』新作映画…『ONE PIECE FILM GOD VALLEY』2027年夏公開 → 後ろの長い名前
            qs = re.findall(r'[「『]([^」』]{2,60})[」』]', t)
            longer = [x for x in qs[1:] if norm(x).startswith(norm(qs[0])) and norm(x) != norm(qs[0])]
            if longer: name = longer[0]
            elif len(qs) >= 2 and re.match(r'FILM\s', qs[1]): name = qs[0] + ' ' + qs[1]   # 「ONE PIECE」新作映画…「FILM GOD VALLEY」
    if not name and HEAD(b):   # 見出しだけ：放送枠の名前（フジ「B8station」枠）を除き、2文字の名前（「尚善」）も取る
        m = re.search(r'『([^』]{1,60})』', t) or re.search(r'「([^」]{2,40})」(?!\s*枠)', t)
        name = m.group(1) if m else ''
    if not name:
        m = (re.search(r'(?:新作|新)(?:テレビ|TV)?(?:アニメ|劇場版|映画)(?:シリーズ)?\s*『([^』]{1,60})』', t) if t.count('『') >= 2 else None) or re.search(r'『([^』]{1,60})』', t) or re.search(r'「([^」]{2,40}?[^』」。―…!?！？])」', t)
        name = m.group(1) if m else ''
    name = re.sub(r'^(TVアニメ|テレビアニメ|劇場版|劇場アニメ|映画|アニメ)\s*', '', name).strip()
    if HEAD(b) and (re.search(r'(する|した|される|れる|ている|てる|しい|ぜ|よ|ね|は|に|を|だろ)[?？!！]?$|展$', name) or name in ('解説', '話題')): return ''   # 言葉の引用・展覧会   # 見出しだけのとき、言葉の引用（「日常が一変する」）は作品名ではない
    if not name or ST_RX.fullmatch(name) or FRAMES.fullmatch(name): return ''
    if not RENAME.get(norm(name)):
        base = SEASON_MARK.sub('', name).strip() or name   # 「暗殺貴族 第2期」は期を除いて正式名称を探す（期は canon で付け直す）
        x = alias(base, b) if HEAD(b) else ''   # RSS の抜粋は短く名前の切れ端も多いので、略称の表を先に
        if x: name = x
        else:
            x = expand(base, b, t)
            name = x if x != base else (alias(base, b) or name)   # 本文から正式名称が取れなければ、略称の表
    if head and not re.search(r'[「『]', head) and not RENAME.get(norm(name)):   # MANTANWEB の見出しの「：」の前は正式名称ではない。本文に同じ名前が『』「」で書かれているときだけ使い、なければ本文の名前
        bq = []
        for mm in re.finditer(r'『([^』]{2,60})』|「([^」]{2,60})」', b[:800]):
            x = (mm.group(1) or mm.group(2)).strip()
            if re.search(r'(誌|サイト|レーベル|文庫|アプリ|サービス|枠|番組|イベント|劇場|系)$', b[max(0, mm.start() - 6):mm.start()]) or NOT_TITLE.search(x) or re.search(r'[、。!?！？]', x) or is_person(x): continue   # 雑誌・投稿サイト・放送枠などの名前は除く
            bq.append(x)
        plain = [re.sub(r'[(（][^)）]{1,10}[)）]', '', x).strip() for x in bq]   # 「ペンと手錠（ワッパ）と事実婚」の読みがなを除く
        if norm(name) == norm(head) and norm(name) not in [norm(x) for x in plain] and not re.search(r'「[^」]+」(編|篇|章)', t):   # 見出しに「…」編があれば新しい部分の話なのでシリーズの名前にしない（本好きの下剋上）   # 頭の名前が本文の名前と一致しなければ、頭の名前を含む本文の名前（なければそのまま）
            hit = [x for x, y in zip(bq, plain) if norm(head) in norm(y) and norm(y) != norm(head)]
            if hit: name = hit[0]
    name = re.sub(r'^映画[『「](.+)[』」]$', r'\1', name)
    m = re.search(r'新作(?:テレビ|TV)?アニメ(?:シリーズ)?[「『]([^」』]{2,40})[」』]', t)
    if m and norm(m.group(1)) not in norm(name): name = name + ' ' + m.group(1) if len(norm(m.group(1))) <= 4 or re.search(r'篇|編|シリーズ|続編|期', m.group(1)) else m.group(1)   # 「特別篇」のような副題は元の名前に付ける   # 「ポケモン：新作アニメ『ネギガナイトとピチューの冒険』」は新作の名前（サイボーグ009 ネメシスのように含んでいればそのまま）
    return canon(RENAME.get(norm(name), name), t, b)

# ---- A. 名前をそろえる（1か所で）
KANSU = {'二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
SEASON_MARK = re.compile(r'\s*(?:第\s*\d+\s*期|\d+期|(?:season\s*)?(?:II|III|IV|V|VI|Ⅱ|Ⅲ|Ⅳ)|\d+(?:st|nd|rd|th)\s*season|season\s*\d+|シーズン\s*\d+|其[のノ][二三四五六])(?=\s*(?:[~〜～(（][^~〜～]*[~〜～)）]?)?$)', re.I)   # 後ろに「~副題~」があってもよい（無職転生III ~異世界行ったら本気だす~）
def season_no(s):
    """名前の中の期の数（なければ 1）。II・第2期・2nd season など"""
    m = SEASON_MARK.search(s or '')
    if not m: return 1
    x = re.sub(r'(?i)^season\s*', '', m.group(0).strip())
    r = {'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6, 'Ⅱ': 2, 'Ⅲ': 3, 'Ⅳ': 4}.get(x) or (KANSU.get(x[-1]) if x.startswith('其') else None)
    return r or int(re.search(r'\d+', x).group(0))
_swap = {}
def canon(name, t, b):
    """本文の「作品名称：『…』」を優先し、見出しが第N期の話なら「元の名前 第N期」にし、
    「A-B」と「B-A」のような前後が入れ替わっただけの名前は先に出た書き方にそろえる"""
    m = re.search(r'作品名称\s*[:：]\s*『([^』]{2,60})』', b)
    if m and norm(name) and norm(m.group(1)).startswith(norm(re.sub(r'\s*[(（][^)）]*[)）]$', '', name))[:4]): name = m.group(1).strip()
    m = re.search(r'第?\s*([2-9二三四五六七八九十]|1[0-9])\s*期(?!生|間)|(?:Season|シーズン)\s*([2-9]|1[0-9]|II|III|IV|VI|V)(?![\dIV])|([2-9])(?:nd|rd|th)\s*Season', t, re.I)   # 見出しが第N期の話（制作決定・放送時期）
    if m and not re.search(r'劇場版|映画', t[:m.start()] + t[m.end():m.end() + 8]):   # 「劇場版アニメ制作 テレビアニメ第2期のその後」は劇場版
        g_ = m.group(1) or m.group(2) or m.group(3)
        n_ = int(g_) if g_.isdigit() else {'II': 2, 'III': 3, 'IV': 4, 'V': 5, 'VI': 6}.get(g_) or KANSU[g_]
        if season_no(name) != n_ and not re.search(rf'(?:season|シーズン)\s*{n_}(?!\d)|第\s*{n_}\s*期', name, re.I):
            base_ = SEASON_MARK.sub('', name).strip()
            inb = [x for x in re.findall(r'[『「]([^』」]{2,80})[』」]', b) if norm(x).startswith(norm(base_)) and season_no(x) == n_]   # 本文に期つきの正式名称があればそれ（キミと僕の最後の戦場、あるいは世界が始まる聖戦 Season III）
            name = inb[0].strip() if inb else base_ + f' 第{n_}期'
    if re.search(r'映画化|劇場(版)?アニメ化|劇場版(制作|製作)', t): name = re.sub(r'\s*(THE ANIMATION|ジ・アニメーション)$', '', name, flags=re.I)   # テレビアニメ（パラアニ＝Paradox Live THE ANIMATION）の映画化は、シリーズ名の劇場版（Paradox Live THE MOVIE）
    m = re.search(r'第\s*([2-9二三四五六七八九])\s*部】?[^。]{0,6}?(?:制作|製作)(?:が|も)?(?:決定|始動)', t)   # 「劇場版シリーズ第2部制作決定」は「シリーズ名 第2部」（第1部の副題は付けない）
    if m:
        n_ = int(m.group(1)) if m.group(1).isdigit() else KANSU[m.group(1)]
        name = name.split()[0] + f' 第{n_}部'
    parts = [norm(x) for x in re.split(r'\s*[-－―‐]\s*', name) if x.strip()]
    if len(parts) >= 2:
        key = '|'.join(sorted(parts)); name = _swap.setdefault(key, name)
    return name

def title_works(t, b, name):
    """1本の記事で別々の時期の作品を発表したもの（『ONE PIECE FILM GOD VALLEY』2027年夏・『ONE PIECE FILM BAAD』2029年）→ [(名前, 時期の文)]。1作品なら []
    分けるのは見出しの作品名（略称も）を含む名前だけ。本文の名前は『』「」の両方を見る。
    名前のない劇場版を同じ見出しで発表したもの（SPY×FAMILY シーズン4 2027年放送・劇場版第2弾も2027年公開）は「劇場版 元の名前 第N弾」を分ける"""
    m = re.search(r'劇場版(?:アニメ)?\s*(第\d+弾)?[^。、]{0,8}?((?:20)?\d\d年(?:の)?(?:\d{1,2}月(?:\d{1,2}日)?|春|夏|秋|冬)?)[^。、]{0,6}?公開', t)
    if m and re.search(r'(テレビ|TV)アニメ|シーズン|Season|第\d+期', t[:m.start()], re.I) and not re.search(r'[『「]劇場版', t):
        base = SEASON_MARK.sub('', name).strip()
        return [(name, t[:m.start()]), ('劇場版 ' + base + (' ' + m.group(1) if m.group(1) else ''), '劇場版 ' + m.group(2) + '公開')]
    tt = [x for x in (norm(y) for y in re.findall(r'『([^』]{2,60})』', t)) if len(x) >= 4]   # 見出しの『』の名前（本文の名前がこれを含めばよい）
    tn = tt + ([norm(name)] if len(norm(name)) >= 4 else [])                                 # ＋作品名（本文の名前がこれで始まればよい）
    out = []
    for n_ in dict.fromkeys(a or c for a, c in re.findall(r'『([^』]{2,60})』|「([^」]{2,60})」', t + b[:900])):
        n_ = re.sub(r'\s*[(（][^)）]{1,30}[)）]$', '', n_).strip(); k = norm(n_)
        if len(k) < 4 or FRAMES.search(n_) or ST_RX.fullmatch(n_) or not (any(x in k for x in tt) or any(k.startswith(x) or (x[:1] == k[:1] and all(ch in iter(k) for ch in x)) for x in tn)): continue
        m = re.search('[『「]' + re.escape(n_) + r'(?:[(（][^)）]{1,30}[)）])?[』」][^。『]{0,40}?((20)?\d\d年の?(\d{1,2}月(\d{1,2}日)?|春|夏|秋|冬)?)[^。]{0,60}?(公開|放送|配信|上映)', b[:1500])
        if m and NOT_TITLE.search(n_): m = None
        if m and not any(norm(o) == k for o, _ in out): out.append((RENAME.get(k, n_), m.group(1) + m.group(5)))   # 時期の文は「2027年夏公開」の形にして読む
    out = [(n_, s) for n_, s in out if plan(s.replace('年の', '年'))[1] and not any(n_ != o and norm(o).startswith(norm(n_)) for o, _ in out)]   # 時期が読めるものだけ
    return out if len({plan(s.replace('年の', '年'))[1] for _, s in out}) >= 2 else []

# ================================================================ 2. 記事の種類を決める
# 見出しの型（入口）。制作決定・日程はこの型に合う見出しだけを使う。型に合わないが広い言葉には当たる見出しは「保留」に書き出す
MEDIA_W = r'(?:(?:TV|テレビ|新作|劇場|オリジナル|配信|ショート|WEB|新)?アニメ(?:ーション)?(?:シリーズ)?|劇場版(?:アニメ)?|映画|OVA|OAD)'
ANN_TYPE = re.compile(
    r'(?:TV|テレビ|劇場)?アニメ化(?!記念|作品|の原作|も話題|で話題|された|され|の人気)'                                   # 『○○』TVアニメ化（決定）
    r'|映画化(?:が|も)?決定'
    r'|(?:第\s*' + N + r'{1,2}\s*期|' + N + r'期|続編|新シリーズ|シーズン\s*\d|Season\s*\d|\d+(?:st|nd|rd|th)\s*(?:season|Season)|第\d+クール|新章|最終章|完全新作|新プロジェクト|新作|'
    + MEDIA_W + r')[^。]{0,16}?(?:の)?(?:制作|製作)(?:が|も)?(?:決定|始動|進行中|中|開始)'                            # 第2期制作決定・新作アニメ制作中
    r'|(?:制作|製作)(?:が|も)?決定|新作[^。]{0,20}?始動|プロジェクト(?:が)?始動'                     # 『○○』制作決定・第4弾新作始動・REBOOTプロジェクト始動
    r'|(?:第\s*' + N + r'{1,2}\s*期|続編|新シリーズ|完全新作|新プロジェクト|新作[^。]{0,8}?' + MEDIA_W + r')[^。]{0,16}?(?:決定|始動|発表)'   # 続編決定・新作ショートアニメ劇場公開決定
    r'|' + MEDIA_W + r'(?:プロジェクト|化)[^。]{0,16}?(?<!公開|放送|配信|上映)(?:決定|始動|発表)'   # 媒体だけなら公開・放送の決定は日程
    r'|(?:タイトル|副題)(?:が)?決定'   # 続編決定・新作アニメ始動
)
WHEN_W = r'(?:(?:来|今)(?:年|春|夏|秋|冬)|(?:20)?\d\d年(?:の)?(?:\d{1,2}月(?:\d{1,2}日)?|春|夏|秋|冬|内|度)?|\d{1,2}月\d{1,2}日|\d{1,2}/\d{1,2}|\d{1,2}月)(?:\(.\))?'
SCH_TYPE = re.compile(
    WHEN_W + r'[^。]{0,10}?(?:から|より|に)?[^。]{0,8}?(?:放送|公開|配信|上映|放映|スタート|ロードショー)'                    # 2027年1月より放送開始・4月10日公開
    r'|(?:放送|公開|配信|上映)(?:日|時期|局|枠|開始日)(?:が|も)?(?:決定|発表)'                                             # 放送日決定
    r'|(?:限定上映|限定公開|劇場公開|上映)(?:が|も)?(?:決定|予定)'
    r'|(?:初回)?(?:放送|公開|配信|上映)(?:・配信)?(?:開始)?(?:日|時期)(?:が|は)' + WHEN_W +                       # 初回放送日は1/4・公開日が11月20日に決定
    r'|放送(?:が|も)?決定|放送へ|配信(?:が|も)?決定'                                                              # TOKYO MXで放送決定・第2クール放送決定（特番・再放送などは除外の言葉で落とす）
)

def kind(t, pending=None, b=''):
    """記事の種類：post（公開・放送後）／a（制作決定）／s（日程）／None。
    1. 型（ANN_TYPE・SCH_TYPE）に合う見出しだけを入口にする
    2. 型に合っても、除外の言葉（受賞・インタビュー・記念・特典など）のある見出しは使わない（安全弁）
    3. 型に合わないが広い言葉（ANNOUNCE・SCHEDULE）に当たる見出しは pending に入れる（型を足すための取りこぼし候補）"""
    if ROUNDUP.match(t) or re.search(r'決定記念|化記念', t): return None   # 「制作決定記念の上映会」は催し
    if POST_MOVIE.search(t) or POST_TV.search(t): return 'post'
    a, sc = bool(ANN_TYPE.search(t)), bool(SCH_TYPE.search(t))
    if not (a or sc) and b:   # 見出しは話題（KV・PV・声優など）でも、本文1文目が日付つきの「より放送決定」なら日程
        s1 = re.split(r'[。\n]', b, maxsplit=1)[0]
        if re.search(WHEN_W + r'[^。]{0,8}?(?:から|より)[^。]{0,6}?(?:放送|公開|配信|上映)(?:開始)?(?:が|も)?決定', s1) and not NOT_SCHED.search(s1) and not NOT_NEWS_CORE.search(t) and not AWARD.search(t): return 's'
    if not (a or sc):
        if pending is not None and (ANNOUNCE.search(t) or SCHEDULE.search(t)) and not NOT_NEWS.search(t): pending.append(t)
        return None
    if AWARD.search(t) and not KEEP.search(t) and not (sc and plan(t)[0]): return None
    if NOT_NEWS.search(t) and not KEEP.search(t) and not (PAST.search(t) and not NOT_NEWS_CORE.search(t) and plan(t)[0]): return None
    if re.search(r'「[^」]*[ぁ-ん][^」]{8,}」\s*$', t) and not plan(t)[0] and not KEEP.search(t): return None   # 出演者などの言葉の引用で終わる見出し
    if a: return 'a'
    if sc and not NOT_SCHED.search(t): return 's'
    return None

B_NOT = re.compile(r'第\d+話|スペシャル|SP|一挙|再放送|再配信|再上映|上映会|特番|傑作選|コラボ|グッズ|最終巻|発売|イベント|ステージ|展|カフェ|パレード|解説|1週間|ランキング|振り返|まとめ|新刊|キャンペーン|タイアップ|4DX|MX4D|先行上映|回数')   # 本文の日付を日程にしない記事（各話・再放送・催し・グッズなど）
BODY_DATE = re.compile(r'\d{1,2}月\d{1,2}日[^。]{0,12}?(?:に|から|より)?(?:全国)?(?:で)?(?:劇場)?(?:公開|放送|上映|配信)(?:される|開始|スタート|予定|が決定|することが)')   # 本文の「9月25日に公開される」
# ================================================================ 3. 事実を取る（本文はその作品の文だけ）
def work_text(name, short, b):
    """本文のうち、その作品名（見出しの書き方でも）が出てくる文と、別の作品名を含まない次の文"""
    keys = {norm(name), norm(short)} - {''}
    keys |= set(K_TITLE)   # 見出しの「」の名前（名探偵コナンの「30号殺人事件」）
    nk = norm(name); nkb = norm(SEASON_MARK.sub('', re.sub(r'\s*[(（][^)）]*[)）]$', '', name)))   # 作品名（（仮）・期を含む）と、その元の名前
    nkf = norm(name.split()[0]) if name.split() else nkb   # シリーズの名前（「チェンソーマン 刺客篇」の「チェンソーマン」）
    def other(s):   # 文の中の『』「」の名前が同じシリーズの別の作品（前の期・旧作）：元の名前を含むか頭が同じで、この作品名の頭でもこの作品名で始まる名前でもない
        for a_, c_ in re.findall(r'『([^』]{2,60})』|「([^」]{2,60})」', s):
            k = norm(re.sub(r'\s*[(（][^)）]*[)）]$', '', a_ or c_))
            if len(k) >= 2 and (nkb in k or len(nkf) >= 3 and nkf != nkb and nkf in k) and not (nk.startswith(k) or k.startswith(nk)): return True
        return False
    b2 = re.sub(r'[『「][^』」\n]{0,60}[』」]', lambda m: m.group(0).replace('。', '\ue000'), b[:2500])   # 名前の中の「。」（死亡遊戯で飯を食う。）で文を切らない
    sents = [x.replace('\ue000', '。') for x in re.split(r'(?<=[。\n])', b2)]; out = []
    for i, s in enumerate(sents):
        if any(k in norm(s) for k in keys) and not other(s):
            if s not in out: out.append(s)
            if i + 1 < len(sents) and '『' not in sents[i + 1] and '「' not in sents[i + 1]: out.append(sents[i + 1])
    return ''.join(out)

PAST_CLAUSE = re.compile(r'[^、。!！?？]*?に(?:引き)?続き(?=、)|[^、。!！?？]*?(最終回を迎え|放送を開始し|放送を終え|放送終了|(上映|公開|放送|配信)されていましたが)[^、。!！?？]*|[^、。!！?？]*?(放送|公開|上映|配信)(され|し)(た|て|、)|[^、。!！?？]*?(放送|公開|上映|配信)されるなど|(これまで|前作|累計|以来|その後|今なお)[^、。!！?？]*')   # 「2024年にテレビアニメが放送された」まで、「前作の…」はその句だけ
def past(s): return PAST_CLAUSE.sub('', re.sub(r'(放送|配信|公開|上映)、(?=放送|配信|公開|上映)', r'\1・', s))   # 過去の節を取り除く（「放送、配信された」も）
def body_medium(wt):
    """本文から媒体を決める。発表の文（決定・制作・始動・予定・○月から など）を順に見て、
    文の中の過去の部分（「2024年に放送された」「前作の劇場版は」「累計」）だけを取り除いてから媒体の言葉を探す。
    「2024年に放送された●●の続編が4月から放送される」は後ろの部分でテレビと読める"""
    for sent in [x for x in re.split(r'(?<=[。\n])', wt) if re.search(r'決定|制作|製作|始動|予定|発表|開始|スタート|(より|から)(放送|公開|配信|上映)|される', x)][:4]:   # 発表の文のうち前のほう（リード）だけ。後ろは会社の紹介・旧作の説明が多い
        if re.search(r'TVシリーズ|テレビシリーズ|TVアニメ|テレビアニメ', sent) and re.search(r'劇場版|映画', sent) and not re.search(r'決定|制作|製作|される|予定', sent): continue   # テレビと劇場版の両方を挙げた文（旧作の紹介）は決めない
        c, x = medium(past(sent))
        if c: return c, x
    return None, ''

K_TITLE = []
def facts(name, short, t, b, d, kd, when=''):
    K_TITLE[:] = [norm(x) for x in re.findall(r'(?:SP|スペシャル|特番|特別編|短編アニメ|新作アニメ)「([^」]{3,30})」', t)]   # 特番・新作の名前（名探偵コナン 2時間SP「30号殺人事件」）
    wt = work_text(name, short, b)
    tm = t if re.match(r'劇場版|映画', name) else t.replace(name, '').replace(short or '\x00', '')   # 作品名の中の言葉（「可哀想に!劇場」の劇場）は媒体に数えない
    c, x = medium(when) if when.startswith('劇場版') or (when and HEAD(b) and medium(when)[0]) else medium(tm); ct = bool(c)   # 見出しだけで2作品を分けたものは、その部分の言葉で（Season 4が放送、劇場版第2弾も公開）   # 名前のない劇場版を分けたものは、その部分の言葉で
    if not c and when: c, x = medium(when); ct = bool(c)
    if not c: c, x = body_medium(wt)
    p, pk = plan(when.replace('年の', '年') if when else t, d)
    if rank(pk) < 3 and not when:
        p2, pk2 = plan(past(wt), d, body=True)
        if rank(pk2) > rank(pk) and (not pk or pk2.startswith(pk[:4])) and not (HEAD(b) and rank(pk) == 2 and pk2[:7] != pk[:7]) and not (kd == 'a' and rank(pk2) == 3 and d[:10] <= pk2 <= (datetime.date.fromisoformat(d[:10]) + datetime.timedelta(days=7)).isoformat()): p, pk = p2, pk2   # 発表の記事で記事から1週間以内の日付は前作の公開日や催し・CDの日
    tv = stations(t + '。' + ''.join(past(s) for s in re.split(r'(?<=[。\n])', wt) if re.search(r'放送|配信|毎週', s))) if (kd == 's' or p) else []
    rel = any(re.search(r'(上映|公開)されていましたが|(上映|公開)されていた', s) and not re.search(r'劇場版|映画[『「]|[『「]', s) for s in re.split(r'(?<=[。\n])', wt))   # この作品はもう上映・公開された（死亡遊戯 44）
    seq = bool(SEQ.search(t)) or any(sd < (d or '9999') for sd in db_starts.get(norm(name), [])) or ('劇場版' in t and bool(re.search(r'TVアニメ|テレビアニメ|シリーズ', b[:400])))
    return {'c': c or '未定', 'x': x, 'ct': ct, 'p': p, 'pk': pk, 'tv': tv, 'q': 1 if seq else 0, 'rel': rel}

NOT_RSS = re.compile(r'アニメ化してほしい|どこで見(れ|られ)|見る方法|配信サイト(まとめ|一覧)|無料放送|一挙(放送|配信)|再放送|再配信|ランキング|死去|逝去|追悼|訃報|最新話|(公開|放送|上映)された[『「]|同時視聴|\d位|といえば[?？]|アニメ化の壁|\d{4}年(公開|放送)の?[『「]|限定(上映|公開)|リバイバル|再上映|セレクション放送|アンコール放送|アニメ劇場|ムビチケ|SNS企画|オールナイトニッポン|ラジオ|野外上映|上映会')   # 作品の発表ではない記事（見出しで分かるもの）
def is_anime(r, name, t, b):
    if HEAD(b):   # 見出しだけのとき：まとめ・再放送・ゲームや本の発売・実写（「アニメイト」はアニメに数えない）
        ta = bool(re.search(r'アニメ(?!イト)', t))
        if NOT_RSS.search(t) or (re.search(r'ゲーム|刊行|コミックス|単行本|\d+巻|最終回|連載', t) and not ta) or (re.search(r'ドラマ|実写', t) and not ta): return False
        if not ta and not re.search(r'OVA|OAD|劇場版|アニメ(?!イト)', b) and not re.search(r'OVA|OAD|劇場版', t) and norm(name) not in db_titles and not r.get('anime'): return False   # 見出しになくても抜粋に「アニメ」があればよい
    if '実写' in b[:200] and not re.search(r'アニメ', t): return False   # 本文の冒頭が実写（Netflix 映画『シティーハンター2』）
    if re.search(r'ミュージカル|上演|舞台(?!あいさつ|挨拶)', t) and 'アニメ' not in t: return False   # 舞台
    if (NOT_ANIME.search(t) or re.search(r'仮面ライダー|戦隊|ウルトラマン|アギト|特撮', t)) and 'アニメ' not in t: return False   # 実写・特撮
    return bool(r.get('anime')) or norm(name) in db_titles or bool(re.search(r'アニメ|OVA|OAD|劇場版', t)) or bool(re.search(r'アニメ(ーション)?(映画|化|制作)|劇場アニメ|TVアニメ', b[:800]))

# ---------------------------------------------------------------- 記事を通す
def extract(records, ev, pending):
    """記事（title・body・date・url・site）を1本ずつ1〜3の段に通し、手がかり（記事×作品）を ev に足す。本文は手がかりに残さない"""
    for r in records:
        _HEAD[0] = bool(r.get('rss'))
        t, b, d = nf(r.get('title') or r.get('list_title')), nf(r.get('body')), r.get('date', '')
        kd = kind(t, pending, b)
        if not kd:   # 型に合わない記事（声優・PVの記事など）でも、本文にその作品の日付つきの公開・放送日があれば日程の候補（初めて出た日付なら日程のニュース：縁の手紙）
            if NOT_NEWS_CORE.search(t) or AWARD.search(t) or B_NOT.search(t) or not BODY_DATE.search(b[:2500]): continue
            kd = 'b'
        name = identify(r, t, b)
        if _HEAD[0] and name and re.search(r'[」』]\s*(?:の)?新作映画', t) and not re.match(r'劇場版|映画', name) and len(re.findall(r'[「『]', t)) == 1: name = '劇場版' + name   # 『ポケモン』新作映画（名前の出ていない新しい映画）はシリーズの名前にしない
        if not name or not is_anime(r, name, t, b): continue
        short = (re.search(r'『([^』]{1,60})』', t) or re.match(r'([^:]{1,60}):', t) or [None, ''])[1]
        works = title_works(t, b, name) if kd != 'post' else []
        for n_, when in (works or [(name, '')]):
            e = {'n': n_, 'k': kd, 'd': d, 't': t, 'u': r['url'], 's': r.get('site', '')}
            e.update(facts(n_, short if not works else n_, t, b, d, 's' if kd == 'b' else kd, when))
            if _HEAD[0] and not works and len(set(re.findall(r'[「『]([^」』]+)[」』]', t))) >= 2 and len(set(re.findall(r'(\d{1,2})月', t))) >= 2:
                e['p'], e['pk'] = '', ''   # 見出しだけで、2つの作品と2つの時期が並ぶもの（「転スラ」4期第3クールは7月、4月には「クレイマンREVENGE」）は、どちらの時期か分からないので取らない
            if kd == 'b':
                if not e['pk'] and not works:   # 作品名のない文（「日本では、9月25日に公開される。」）でも、日付の文から読む
                    m_ = BODY_DATE.search(b[:2500])
                    sent = b[b.rfind('。', 0, m_.start()) + 1:b.find('。', m_.end()) + 1]
                    if re.search(r'日本では|(本作|同作|劇場版|映画|アニメ)(は|が|も)', sent): e['p'], e['pk'] = plan(past(sent), d, body=True)   # 主語がその作品の文だけ
                if not e['pk'] or rank(e['pk']) < 3 or e['pk'] < (datetime.date.fromisoformat(d[:10]) + datetime.timedelta(days=3)).isoformat(): continue   # 本文に日付まで決まった先の公開・放送日がない（記事の3日以内は催しの日が多い）
            ev.append(e)

def aggregate(ev):
    """手がかりを4〜5の段に通し、ニュース欄の行・放送・公開前・放送・公開済みを返す"""
    ev = list(ev)
    # 本文から拾った日程の候補（k='b'）：制作決定・日程の記事がすでにある作品で、それまで日付（何日まで）が出ていなかったときだけ、
    # 初めて日付を伝えた記事として日程のニュース（k='s'）にする。それ以外は捨てる
    _seen, _ann = {}, {}
    for e in sorted(ev, key=lambda e: e['d'] or ''):
        k_ = norm(e['n'])
        if e['k'] == 'b':
            e['k'] = 's' if k_ in _ann and not _seen.get(k_) else 'x'
        if e['k'] in ('a', 's'): _ann[k_] = 1
        if e['k'] != 'x' and e.get('pk') and rank(e['pk']) == 3: _seen[k_] = 1
    ev = [e for e in ev if e['k'] != 'x']

    # ================================================================ 4. 作品ごとにまとめる
    # 4-1 ニュース欄：同じ発表を複数のサイトが書いたもの（作品・媒体・種類が同じで10日以内）を1行に
    def day(s):
        try: return datetime.date.fromisoformat(s[:10])
        except Exception: return None
    items, last, lastn = [], {}, {}
    def _join(g, e):   # 同じ発表を伝えた別の記事を g にまとめる（別のサイトの記事は見出しごと o に残し、一覧で広げて見られるようにする）
        if e['s'] != g['s'] and all(o[0] != e['s'] for o in g['o']): g['o'].append([e['s'], e['u'], e['t'], e['d']])
        g['q'] = g['q'] or e['q']; g['x'] = g['x'] or e['x']; g['tv'] = merge_tv(g['tv'], e['tv'])
        if rank(e['pk']) > rank(g['pk']): g['p'], g['pk'] = e['p'], e['pk']
        if g['c'] == '未定' and e['c'] != '未定': g['c'] = e['c']
        if e['k'] == 's': g['k'] = 's'
    for e in sorted((e for e in ev if e['k'] in ('a', 's')), key=lambda e: (e['d'] or '9999', e['u'])):
        k = (norm(e['n']), e['c'], e['k']); g = last.get(k)
        if g and day(e['d']) and day(g['d']) and (day(e['d']) - day(g['d'])).days <= 10:
            _join(g, e); continue
        g2 = lastn.get(norm(e['n']))   # 同じ作品を別のサイトが前後1日で伝えたもの（制作決定と日程、媒体の書き方が違っても同じ発表）
        if g2 and e['s'] != g2['s'] and all(o[0] != e['s'] for o in g2['o']) and day(e['d']) and day(g2['d']) and abs((day(e['d']) - day(g2['d'])).days) <= 1:
            _join(g2, e); last[k] = g2; continue
        g = {**e, 'o': []}; items.append(g); last[k] = g; lastn[norm(e['n'])] = g

    # 4-2 作品：名前ごとに集め、見出しで映画とそれ以外の両方が出てくる名前は2つに分ける（SEKIRO の劇場版とテレビアニメ）
    byname = defaultdict(list)
    for e in ev: byname[norm(e['n'])].append(e)
    works = {}
    for nk, es in byname.items():
        es.sort(key=lambda e: e['d'] or '')
        sides = {('映画' if e['c'] == '映画' else 'TV') for e in es if e['ct'] and (e['k'] == 'a' or (e['k'] == 's' and e['pk'] >= TODAY))}   # 発表か、これからの日程がある側だけ
        for side in (sides if len(sides) == 2 else {None}):
            mine = [e for e in es if side is None or ('映画' if e['c'] == '映画' else 'TV') == side or (not e['ct'] and side == 'TV' and e['c'] != '映画') or (not e['ct'] and side == '映画' and e['c'] == '映画')]
            if not mine: continue
            titled = [e for e in mine if e['ct'] and e['k'] != 'post'] or [e for e in mine if e['k'] != 'post' and e['c'] != '未定'] or [e for e in mine if e['k'] != 'post'] or mine
            w = {'n': mine[-1]['n'] if any(x['k'] != 'post' for x in mine) else mine[0]['n'], 'c': titled[-1]['c'], 'x': next((e['x'] for e in reversed(titled) if e['x']), ''), 'ev': mine}
            for e in reversed(mine):
                if e['k'] != 'post': w['n'] = e['n']; break
            works[(nk, side)] = w

    # 4-3 名前違いをまとめる：同じ側で、短い名前が長い名前の頭にあり、残りが THE MOVIE などか、短いほうに時期がないか、時期が同じとき
    def aired_pk(w, day_):
        """いちばん新しい記事の時期が、その日より前（その時点で放送・公開が始まっていた）"""
        la = max((e['d'] for e in w['ev'] if e['k'] == 'a'), default='')
        pk_ = next((e['pk'] for e in sorted(w['ev'], key=lambda e: e['d'] or '', reverse=True) if e['k'] != 'post' and e['pk'] and (e['d'] or '') >= la), '')   # 最新の発表から後の記事の時期
        return bool(pk_) and (pk_[:10] <= day_ if rank(pk_) == 3 else pk_[:7] < day_[:7])
    def best_pk(w): return next((e['pk'] for e in sorted(w['ev'], key=lambda e: e['d'] or '', reverse=True) if e['k'] != 'post' and e['pk']), '')   # いちばん新しい記事の時期
    def bk(k): return norm(re.sub(r'^(劇場版|映画)\s*', '', SEASON_MARK.sub('', works[k]['n']).strip()))   # 期の印と頭の「劇場版」を除いた名前（期の数は別に比べる）
    for k in sorted(works, key=lambda k: (len(bk(k)), len(k[0]))):
        if k not in works: continue
        b1 = bk(k)
        def same_season(k2):   # 期の数が同じ。片方に期の印がなくても、日付まで同じ時期なら同じ作品（『真・侍伝 YAIBA』宇宙プロジェクト始動）
            a, b = season_no(works[k]['n']), season_no(works[k2]['n'])
            return a == b or (1 in (a, b) and best_pk(works[k]) == best_pk(works[k2]) and rank(best_pk(works[k])) == 3)
        for k2 in [k2 for k2 in works if k2 != k and k2[1] == k[1] and same_season(k2) and
                   (bk(k2) == b1 and len(k2[0]) >= len(k[0]) or len(bk(k2)) > len(b1) and (bk(k2).startswith(b1) or (len(b1) >= 4 and b1 in bk(k2) and best_pk(works[k]) == best_pk(works[k2]) and rank(best_pk(works[k])) == 3)))]:   # 期が同じで、頭で一致（または日付まで同じで名前を含む：YAIBA／真・侍伝 YAIBA）
            a_, b_ = works[k], works[k2]
            firsta = min((e['d'] for e in a_['ev']), default=''); firstb = min((e['d'] for e in b_['ev']), default='')
            if a_['c'] != b_['c'] and '未定' not in (a_['c'], b_['c']): continue   # 媒体が違えば別の作品（転スラ／転スラ 蒼海の涙編）
            la = max((e['d'] for e in a_['ev'] if e['k'] == 'a'), default='')
            la = la or max((e['d'] for e in a_['ev'] if e['k'] != 'post'), default='')
            lb = max((e['d'] for e in b_['ev'] if e['k'] == 'a'), default='') or max((e['d'] for e in b_['ev'] if e['k'] != 'post'), default='')
            if (la and aired_pk(b_, la)) or (lb and aired_pk(a_, lb)): continue
            if a_['c'] == '未定' and la and any((e['k'] == 's' and rank(e['pk']) == 3 and e['pk'] <= la) or (e['k'] == 'post' and (e['d'] or '') <= la) for e in b_['ev']): continue   # 種類未定の新プロジェクトは、その発表より前に公開・放送日を迎えた作品にまとめない（モノノ怪の新プロジェクトと劇場版モノノ怪 第三章）   # どちらかが、もう一方の発表の時点で放送・公開済み（攻殻機動隊の新作、剣聖の第2期と第3期）
            newer_a = max((e['d'] for e in a_['ev'] if e['k'] == 'a'), default='') > max((e['d'] for e in b_['ev'] if e['k'] != 'post'), default='')   # 長いほうの発表・日程より新しい発表（公開後の記事は数えない）
            pa_, pb_ = best_pk(a_), best_pk(b_)
            if (pa_ and pb_ and pa_[:4] == pb_[:4] and 1 in (rank(pa_), rank(pb_))) or \
               bk(k2) == b1 or re.fullmatch(r'(themovie|movie|劇場版|映画|thefilm)', bk(k2)[len(b1):]) or best_pk(a_) == best_pk(b_) or \
               (not best_pk(a_) and not newer_a) or not best_pk(b_):   # 時期が同じか、どちらかに時期がない（短いほうの発表が新しければ新しい作品なので分けたまま：攻殻機動隊の新作）
                b_['ev'] = sorted(b_['ev'] + a_['ev'], key=lambda e: e['d'] or ''); del works[k]; break

    # 4-4 名前の語がほぼ同じ（BanG Dream! It's MyGO!!!!! / Ave Mujica と BanG Dream! MyGO!!!!! // Ave Mujica）で、媒体と時期の月が同じものをまとめる。新しい記事の名前を使う
    def toks(n): return set(re.findall(r'[a-z0-9]+|[ぁ-んァ-ヶー一-龥]+', nf(n).lower()))
    for k in sorted(works, key=lambda k: max(e['d'] or '' for e in works[k]['ev']), reverse=True):
        if k not in works: continue
        for k2 in [k2 for k2 in works if k2 != k and k2[1] == k[1]]:
            a_, b_ = works[k], works[k2]; ta, tb = toks(a_['n']), toks(b_['n']); pa, pb = best_pk(a_), best_pk(b_)
            if a_['c'] == b_['c'] and len(ta) >= 3 and len(ta & tb) / len(ta | tb) >= 0.7 and pa and pb and pa[:7] == pb[:7] and season_no(a_['n']) == season_no(b_['n']):
                a_['ev'] = sorted(a_['ev'] + b_['ev'], key=lambda e: e['d'] or ''); del works[k2]

    # 4-5 ニュース欄の仕上げ：名前の書き方が違っても（ぼっち・ざ・ろっく！／映画ぼっち・ざ・ろっく！ 星のあしあと）、
    # 上で同じ作品にまとまった記事を別のサイトが前後1日で伝えていれば1行にまとめる
    _wk = {}
    for key, w in works.items():
        for e in w['ev']: _wk.setdefault(e['u'], key)
    _prev, _drop, _recent, _log = {}, set(), [], []
    for g in sorted(items, key=lambda e: (e['d'] or '9999', e['u'])):
        key = _wk.get(g['u'])
        if not key: continue
        h = _prev.get(key)
        if not h:   # 作品としては別にまとまっていても、名前の頭（劇場版・期の印を除いて5文字）が同じなら同じ発表とみる（DARK MACHINE／DARK MACHINE THE ANIMATION）
            b5 = norm(re.sub(r'^(劇場版|映画)\s*', '', SEASON_MARK.sub('', g['n'])))[:5]
            h = next((x for x in _recent if x['s'] != g['s'] and len(b5) == 5 and norm(re.sub(r'^(劇場版|映画)\s*', '', SEASON_MARK.sub('', x['n'])))[:5] == b5
                      and day(g['d']) and day(x['d']) and abs((day(g['d']) - day(x['d'])).days) <= 1 and all(o[0] != g['s'] for o in x['o'])), None)
            if h: _join(h, g); _drop.add(id(g)); _log.append((h['t'], g['t'])); continue
        if h and g['s'] != h['s'] and all(o[0] != g['s'] for o in h['o']) and day(g['d']) and day(h['d']) and abs((day(g['d']) - day(h['d'])).days) <= 1:
            _join(h, g); h['o'] += [o for o in g['o'] if all(o[0] != x[0] for x in h['o'])]; _drop.add(id(g)); continue
        _prev[key] = g; _recent.append(g); _recent[:] = _recent[-60:]
    items = [g for g in items if id(g) not in _drop]

    # ================================================================ 5. 放送・公開前か決める
    upcoming = []; released = []   # 放送・公開前／一覧から外れた放送・公開済みの作品
    for (nk, side), w in works.items():
        es = w['ev']; c = w['c']
        news = [e for e in es if e['k'] != 'post']
        if not news: continue
        ann = [e for e in news if e['k'] == 'a']
        last_ann = news[-1]['d'] or ''   # 最新の発表・日程の記事の日付（これより後に始まったかを見る。日程だけの続編も含む）
        sched = [e for e in news if e['k'] == 's']
        p, pk = '', ''
        def pick(es_):   # いちばん新しい記事の時期（同じ日の記事どうしなら細かいほう）。新しい発表は前の日程より優先
            es_ = [e for e in es_ if e['pk']]
            if not es_: return '', ''
            last = max(e['d'] or '' for e in es_)
            e = max((e for e in es_ if (e['d'] or '') == last), key=lambda e: rank(e['pk']))
            return e['p'], e['pk']
        # 最新の発表から後の記事の時期を使う。なければ、それより前の記事の時期のうちまだ来ていないもの（過ぎた時期は前の期・前作のもの）
        p, pk = pick([e for e in news if (e['d'] or '') >= last_ann])
        la_a = ann[-1]['d'] if ann else ''
        if not pk: p, pk = pick([e for e in news if (e['d'] or '') >= la_a])   # 最新の記事に時期がなければ、最新の発表から後で時期のある記事（公開日の後の宣伝記事：ケロロ軍曹）
        if not pk: p, pk = pick([e for e in news if e['pk'] >= TODAY])
        if not pk and not SEQ.search(news[-1]['t']): p, pk = pick(news)   # 最新の記事が続編・新作の発表でなければ（予告編・PVの記事）、それまでの記事の時期（ペリリュー -楽園のゲルニカ-）
        tv = []
        for e in reversed(news): tv = merge_tv(tv, e['tv'])   # 新しい記事の日時を優先
        q = any(e['q'] for e in news)
        f = FIX.get(nk, '')
        head = (ann or news)[-1]
        def done(rk, rp):   # 放送・公開済みとして外す。rk は並べる日付、rp は表に出す日付
            u = {'n': w['n'], 'c': c, 'x': w['x'] if c == 'その他' else '', 'q': 1 if any(e['q'] for e in news) else 0, 'p': rp, 'pk': rk, 'd': head['d'], 't': head['t'], 'u': head['u'], 's': head['s']}
            released.append({k: v for k, v in u.items() if v})
        if f == '外す': continue
        if f == '放送済み': done(pk or last_ann, p); continue
        if f != '載せる':
            if pk and pk < TODAY: done(pk, p); continue
            tease = [re.search(r'(\d{1,2})月(\d{1,2})日', e['t']) for e in news if re.search(r'(発表|解禁|お披露目)(へ|予定)|カウントダウン|特番|生配信', e['t'])]
            if len(tease) == len(news) and all(tease) and max(f"{e['d'][:4]}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" for e, m in zip(news, tease)) < TODAY: continue   # 新作情報を発表する特番・発表会の告知だけで、その日が過ぎた（ガンダム：新作アニメ情報 7月24日発表へ）。ニュースには残す                                     # 予定の時期が過ぎた
            if any(e.get('rel') and e['d'] >= last_ann for e in news): done(pk or last_ann, p); continue   # 最新の記事が「上映されていましたが」（もう公開された作品のテレビ放送・配信）
            started = [sd for k2, v in db_starts.items() if k2 == nk or (len(nk) >= 4 and len(k2) >= 4 and (k2.startswith(nk) or nk.startswith(k2))) for sd in v] if c in ('テレビ', '未定') else []
            st_ = [sd[:10] for sd in started if last_ann <= sd[:10] <= TODAY]
            if st_: sd_ = min(st_); done(sd_, f'{int(sd_[:4])}年{int(sd_[5:7])}月{int(sd_[8:10])}日'); continue   # 最新の発表より後にデータベースで放送が始まった
            if rank(pk) < 3 and any(e['d'] > last_ann and (bool(POST_MOVIE.search(e['t'])) if c == '映画' else (bool(POST_TV.search(e['t'])) and not q)) for e in es if e['k'] == 'post'):
                done(pk or last_ann, p); continue                                # 最新の発表より後に、公開・放送が始まったあとの記事がある
        u = {'n': w['n'], 'c': c, 'x': w['x'] if c == 'その他' else '', 'q': 1 if q else 0, 'p': p, 'pk': pk, 'tv': tv, 'd': head['d'], 't': head['t'], 'u': head['u'], 's': head['s']}
        if sched: u['su'], u['ss'] = sched[-1]['u'], sched[-1]['s']
        upcoming.append({k: v for k, v in u.items() if v})
    def _order(u):   # 季節だけのものは、その季節の3か月の後ろに並べる（見出しは「2027年夏」。冬は1～3月、春は4～6月…）
        k = u.get('pk') or '9999'
        if re.search(r'[春夏秋冬]$', u.get('p', '')): k = f'{k[:5]}{int(k[5:7]) + 2:02d}-99z'
        return (k, u['n'])
    upcoming.sort(key=_order)
    released.sort(key=lambda u: ((u.get('pk') or '0')[:8] + '00' if re.search(r'[春夏秋冬]$', u.get('p', '')) else (u.get('pk') or '0'), u['n']), reverse=True)   # 新しい順（季節だけのものはその季節の最初の月の後ろに）
    items.sort(key=lambda e: e['d'] or '0000', reverse=True)
    out_items = []
    for g in items:
        o = {'d': g['d'], 't': g['t'], 'u': g['u'], 's': g['s'], 'c': g['c'], 'x': g['x'], 'n': g['n'], 'p': g['p'], 'pk': g['pk'], 'tv': g['tv'], 'o': g['o'], 'q': g['q']}
        if g['k'] == 's': o['k'] = 's'
        out_items.append({k: v for k, v in o.items() if v})
    return out_items, upcoming, released, ev

# ================================================================ 書き出す（非公開の anime-database から動かすとき：news/*.jsonl の記事を全部通す）
if __name__ == '__main__':
    OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'news.json')
    recs = []
    for path in sorted(glob.glob(os.path.join(BODIES, '*.jsonl'))):
        for line in open(path, encoding='utf-8'):
            try: recs.append(json.loads(line))
            except Exception: pass
    for r in recs: learn_alias(nf(r.get('body')))
    ev, pending = [], []
    extract(recs, ev, pending)
    if '--export' in sys.argv:   # 公開の anime-news に渡すもの：手がかり（本文なし）・通した記事の URL・データベースの番組名・開始日・人名
        import gzip
        xd = sys.argv[sys.argv.index('--export') + 1]
        json.dump({'ev': ev, 'urls': sorted({r['url'] for r in recs})}, open(os.path.join(xd, 'news_ev.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        is_person('x')
        with gzip.open(os.path.join(xd, 'news_ref.json.gz'), 'wt', encoding='utf-8') as f:
            json.dump({'titles': sorted(db_titles), 'starts': dict(db_starts), 'persons': sorted(_persons), 'alias': ALIAS}, f, ensure_ascii=False, separators=(',', ':'))
    out_items, upcoming, released, ev = aggregate(ev)
    json.dump({'items': out_items, 'upcoming': upcoming, 'released': released}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    json.dump(sorted(set(pending)), open(os.path.join(BODIES, 'pending.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=0)   # 型に合わなかった見出し（型を足すときに見る）
    print(f'保留（型に合わない見出し） {len(set(pending))}件・手がかり {len(ev)}件 → ニュース {len(out_items)}件（うち日程 {sum(1 for g in out_items if g.get("k") == "s")}件）・放送・公開前 {len(upcoming)}作品・放送・公開済み {len(released)}作品', dict(Counter(g['c'] for g in out_items)))
