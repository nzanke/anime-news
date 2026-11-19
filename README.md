# アニメ制作決定ニュース

https://nzanke.github.io/anime-news/

アニメ映画・テレビアニメ・その他のアニメ（OVA・配信アニメ・CM・動画）の制作決定と、放送日・放送局・公開日のニュースを30分ごとに集めて並べるサイト。

## データの流れ（`.github/workflows/pages.yml`、30分ごと）
1. `tools/rss_fetch.py`：ceek.jp のニュース検索の RSS（「アニメ」＋MANTANWEB・ナタリー・オリコン・アニメイトタイムズ・アニメ！アニメ！）の新しい記事の見出し・URL・日時を `data/rss/<年-月>.jsonl` に足す。RSS の要約（本文の冒頭）は残さない。過去の記事は `rss.yml` を手で動かして集める（`--until 日付`。ceek.jp でさかのぼれるのは約4か月）。
2. 非公開の anime-database が毎日 anime-world に置く `news_ev.json`（MANTANWEB・アニメイトタイムズの本文から判定した手がかり。本文は含まない）と `news_ref.json.gz`（データベースの番組名・開始日・人名）を取ってくる。
3. `tools/make_news.py`：RSS の見出しを `tools/news_tag.py` の規則で判定し（本文で判定した記事は除く）、手がかりを合わせて作品ごとにまとめ、`data/news.json`（リポジトリには入れない）を作る。
4. `build.py` で `_site/` に組み立てて公開する。

## 判定の規則
- 正本はこのリポジトリの `tools/news_tag.py`・`data/news_upcoming_fix.csv`（例外）・`data/news_tests.json`（確認用の一覧）。anime-database の毎日の収集は動かす前にここから取ってくる。
- 規則を変えたら `python3 tools/make_news.py && python3 tools/news_check.py data/news.json` を通す。
