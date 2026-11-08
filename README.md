# okiyamasho.com

沖山翔のブログ（https://okiyamasho.com/）のソース。2026-11 に WordPress（さくらのレンタルサーバ）から静的サイトへ移行した。

- 生成: [Hugo](https://gohugo.io/) v0.168.0（版と SHA256 を固定）
- 公開: GitHub Pages（`main` に push すると GitHub Actions がビルド → 検査 → 配備）
- 公開側に動的な仕組み（ログイン画面・PHP・DB・フォーム・解析タグ）は一切ない

## 記事を書く・直す

Claude に「この内容で記事を追加して公開して」と頼めば、以下を代行する。

1. `content/posts/<英字スラッグ>.md` を作る（ひな形: `archetypes/posts.md`）
   - 本文は Markdown。生の HTML は書いても表示されない（安全のため無効化している）
   - `<!--more-->` の行より前がトップページに表示される
   - 数式は `$$ ... $$`（別行）、`\( ... \)`（文中）。ビルド時に MathML へ変換される
   - 画像は `static/images/` に置き、`![説明](/images/ファイル名.png)` で参照
2. `draft = true` を消して commit → `main` に push
3. 1〜2 分で公開。GitHub の Actions タブで結果を確認できる

URL は `/posts/<スラッグ>/`。一度公開したスラッグは変えない（リンク切れになる）。

## 手元で確認する

```bash
cd ~/ClaudeCode/02_projects/89_okiyamasho-website && ~/ClaudeCode/tools/hugo/0.168.0/hugo --gc --minify --cleanDestinationDir --environment production && python3 -I scripts/check_site.py public && python3 -I scripts/test_check_site.py public
```

`~/ClaudeCode/tools/hugo/0.168.0/hugo` は公式配布の macOS 用 pkg から取り出した同じ版（署名・SHA256 確認済み）。

## 構成

| パス | 内容 |
|---|---|
| `content/posts/*.html` | WordPress から移した 2017 年の記事 12 本（`tools/import_wp.py` で許可リスト変換済み。手で HTML を足さない） |
| `content/posts/*.md` | 移行後に書く記事 |
| `content/profile.html` | プロフィール（2017 年時点の内容のまま） |
| `layouts/` | 自作テーマ（旧サイトの見た目を踏襲） |
| `layouts/partials/render-math.html` | 数式をビルド時に MathML へ変換 |
| `assets/js/legacy-redirect.js` | 旧 URL（`/?p=473` など）→ 新 URL の転送。サイト唯一の JavaScript |
| `static/wp-content/uploads/` `static/uploads/` | 旧サイトと同じパスに置いた画像・PDF（外部からのリンクを切らさないため） |
| `scripts/check_site.py` | ビルド後の安全検査（CI で配備前に必ず実行） |
| `scripts/test_check_site.py` | 安全検査そのものの回帰テスト（危険な変更 25 種を注入し、すべて検出されることを確認） |
| `tools/import_wp.py` | 移行時に 1 回だけ使った変換スクリプト（記録として保存） |
| `.github/workflows/deploy.yml` | ビルド・検査・配備 |

## セキュリティ上の決まり

- **CSP**: 全ページの `<head>` 先頭に `<meta http-equiv="Content-Security-Policy">`。画像・CSS は自サイトのみ、スクリプトはトップページの転送用 1 本だけ（SRI 付き）。外部の埋め込み・解析タグ・CDN を追加しない
- **検査**: `scripts/check_site.py` が、スクリプト・イベント属性・外部読み込み・iframe・フォーム・`javascript:` リンク・リンク切れ・想定外のファイル種別（.php など）を見つけたら CI が止まり、配備されない
- **CI**: Actions は commit SHA で固定。ジョブ権限はビルド＝読み取りのみ、配備＝Pages 書込＋OIDC のみ。`main` への push 以外では配備しない
- **リポジトリは公開**: バックアップ、DB、調査報告書、鍵、パスワードは絶対に入れない（`.gitignore` でも除外）

## 定期作業

- Dependabot が月 1 回、Actions の更新 PR を出す → PR 上で `check.yml` がビルドと検査を自動実行するので、緑なら内容を確認してマージ
- Hugo の版上げ（年数回・任意）: `deploy.yml` の `HUGO_VERSION` と `HUGO_SHA256`（公式 `hugo_<版>_checksums.txt` の `linux-amd64.tar.gz` 行）を更新。公開から 2 週間以上経った版を使う。手元用バイナリも同じ版に揃える

## 緊急時

- サイトがおかしい: 直前のコミットを `git revert` して push すれば、前の状態で再配備される
- DNS（さくらのネームサーバ）: A `185.199.108-111.153`、AAAA `2606:50c0:8000-8003::153`、`www` CNAME `sho-okiyama.github.io.`、GitHub ドメイン認証用 TXT `_github-pages-challenge-sho-okiyama`（消さない）
