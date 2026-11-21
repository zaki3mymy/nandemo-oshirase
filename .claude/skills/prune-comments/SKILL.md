---
name: prune-comments
description: コードコメントと docstring を Tautology / Excuse / Stale / Decision Record に分類し、Tautology と Stale を削除する。ユーザーに頼まれなくても、コードを書いた・直したあと（コミットの前）に、変更したファイルに対して自分から使う。「コメントを整理して」「無駄なコメントを消して」「comment audit」と頼まれたときは、リポジトリ全体に使う。Use proactively after writing or editing code and before committing, to remove comments that restate the code or no longer match it.
---

# コメントの整理（prune-comments）

コメントは「コードからは読み取れないこと」だけを残す。分類して、Tautology と Stale を消す。

## いつ使うか

- **実装モード（既定・指示がなくても行う）**: コードを書いた・直したあと、コミットの前に、
  `git diff` に含まれるファイルを対象にする。自分が足したコメントだけでなく、変更した処理の近くにある
  既存のコメントが Stale になっていないかも見る。報告は最後に1〜2行で十分。
- **監査モード（頼まれたとき）**: リポジトリ全体を対象にし、分類の一覧と削除する行数を先に示してから消す。

そもそも Tautology のコメントは書かない。迷ったら書かずに、名前や型で表す。

## 分類

| 分類 | 判断の基準 | 扱い |
|---|---|---|
| **Tautology** | コード（名前・型・値・直後の1行）を読めば分かることを言い換えているだけ | 削除 |
| **Stale** | 今のコードや設定と合っていない（存在しない関数・使われていない用途・逆の設定・置き換わったライブラリ） | 削除（直す価値があれば書き直す） |
| **Excuse** | 既知の欠点・手作業の同期・テストの抜けを、直さずに受け入れている | 消さない。報告して、直すか残すかを人に委ねる |
| **Decision Record** | なぜそうしたか、外部の制約、非自明な仕様、ほかのファイルとの対応 | 残す |

### Tautology の典型

- 関数名・クラス名を言い換えただけの docstring（`def split_into_batches` に `"""Split messages into batches."""`）
- テストのクラス名を繰り返す docstring（`class TestParseRequestBase64:` に `"""Test parsing base64 encoded body."""`）
- `Tests for X function.` だけのモジュール docstring
- リソースの見出し（`# Lambda Function` の直後に `resource "aws_lambda_function"`）
- `# argparse` のような区切りバナー
- 直後の assert・ログ文・設定値をそのまま日本語にしたもの

### Tautology ではないもの（残す）

- SHA やダイジェストで固定したものに付ける、人が読めるバージョン（`@<sha> # v7.0.1`、`# mockoon/cli:9.8.0`）。
  Dependabot も使う
- 「なぜ」を含む文。見出しの後半に理由があるなら、その部分は Decision Record
  （`# POST /webhook (APIキー不要 - LINEプラットフォームから送信される)`）
- 値の意味が名前から分からない定数の説明、ほかのファイルと一致させる必要があるという注意、外部ドキュメントへのリンク
- 公開 API・ライブラリの docstring で、引数・戻り値・例外の仕様を書いているもの
- 型だけでは中身が分からない戻り値の説明（`-> tuple[int, int]` に「(hour, minute)」）。
  `tuple` や `dict` の各要素の意味は型から読めないので、自明ではない

### 消すと情報が減るときは、名前や型に移してから消す

docstring が名前や型に足りない情報を補っているなら、消すだけにしない。次のどちらかにする。

- **名前に移す**: `build_expression` の docstring が「cron 式を作る」なら、`build_cron_expression` に改名して消す
  （呼び出し元とテストも直す）
- **型に移す**: `-> tuple[int, int]` で「(hour, minute)」と説明しているなら、
  `class TimeOfDay(NamedTuple): hour: int; minute: int` を返すようにして消す
  （NamedTuple はタプルとして分割代入・比較できるので、呼び出し元は変えずに済む）

移せないなら、そのコメントは Decision Record として残す。

### Stale の確かめ方（推測で決めない）

コメントが主張していることを、必ずコードで確かめる。

- 「〜でも使う」「〜から呼ぶ」: `grep` で呼び出し元を探す
- 設定の説明: 直下の実際の値と比べる（例: 「SIGTERM を受け取る」の下が `stop_signal: SIGKILL`）
- ライブラリ・ツール名: 今使っているものを確かめる。`git log -S'<語>' --oneline` で、いつ変わったかを見る
- 確かめられない外部の事実（別リポジトリのワークフローの中身など）は、Stale にしない

## 手順

1. **対象のコメントを集める**: 実装モードなら `git diff --name-only`（未コミットとステージ済み）、監査モードなら
   `git ls-files` から、lock ファイル・生成物・`.json`・`.md` を除く。`#` `//` `/* */` と docstring を対象にする。
   行番号は**ファイルごとに**取る（複数ファイルを連結した `cat -n` の番号を使わない）。
2. **分類する**: 1行ずつ上の基準で決める。Stale の候補は上の方法で確かめる。
3. **（監査モードのみ）先に報告する**: 分類ごとの一覧（`path:line` とコメント）と、消す行数を示す。
4. **削除する**: `scripts/delete_lines.py` に「消す行と、その行に含まれるはずの文字列」を渡す。
   すべての行を照合してから書き込むので、行番号がずれていれば何も変えずに止まる。

   ```json
   {
     "delete": {"src/app.py": {"12": "Return a cached client", "40": "# argparse"}},
     "replace_with_pass": {"src/app.py": {"55": "Raised when"}}
   }
   ```

   ```bash
   python3 .claude/skills/prune-comments/scripts/delete_lines.py spec.json
   ```

   - spec の JSON はスクラッチパッドなど、リポジトリの外に置く
   - 本体が docstring だけのクラス（例外クラスなど）は `replace_with_pass` で `pass` に置き換える
   - docstring を消したあと、ファイルの先頭や `def` / `class` の直後に残った空行はスクリプトが詰める
5. **整える・確かめる**: プロジェクトのフォーマッターとテストを動かす（このリポジトリなら
   `uv run ruff format`、`uv run ruff check`、`uv run ty check src/ tests/`、`uv run pytest`、`terraform fmt -check -recursive tf/`）。
   区切りバナーを消したあとの余分な空行はフォーマッターが直す。
6. **報告する**: 消した行数（Tautology / Stale の内訳）と、残した Excuse の一覧。Stale のうち、コメントではなく
   実装のほうを直すべきに見えるもの（コメントが本来の意図を表していそうなもの）は、消したうえで別に知らせる。

## 注意

- 消すのはコメントだけ。コードの動作が変わる編集はしない（上の「名前や型に移す」は、動作を変えない改名と型の変更に限る）。
- 迷ったものは Decision Record として残す。消しすぎより残しすぎのほうが害が小さい。
- Excuse は勝手に消さない。欠点を隠すことになる。
- ユーザーが書いたばかりのコメントを、実装モードで大量に消すときは、消す前に一言伝える。
