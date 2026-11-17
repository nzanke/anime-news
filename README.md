# アニメ制作決定ニュース

https://nzanke.github.io/anime-news/

アニメ映画・テレビアニメ・その他のアニメ（OVA・配信アニメ・CM・動画）の制作決定と、放送日・放送局・公開日のニュースを毎日集めて並べるサイト。

- 一覧のデータ `data/news.json` は、毎日の収集（非公開の anime-database の `articles/news_tag.py`）が公開の anime-world に置くものを、3時間ごとに取ってきて組み立てる（`.github/workflows/pages.yml`）。
- `python3 build.py` で `_site/` に組み立てる。記事の本文は持たない。
