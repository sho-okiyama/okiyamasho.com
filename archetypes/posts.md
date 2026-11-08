+++
title = ""
date = {{ .Date }}
slug = "{{ .Date | time.Format "20060102" }}"  # URL = /posts/<初回投稿日>/。同じ日の 2 本目は "yyyymmdd-2"
draft = true
+++

ここに本文を Markdown で書きます。冒頭の数段落のあとに次の 1 行を入れると、トップページではそこまでが表示され「続きを読む」が付きます。

<!--more-->

画像は static/images/ に置き、`![説明](/images/ファイル名.png)` で貼ります。
数式は $$ ... $$（別行）か \( ... \)（文中）で書けます。
