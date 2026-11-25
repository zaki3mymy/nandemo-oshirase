{
  description = "nandemo-oshirase の開発環境";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
        # C コンパイラ（gcc など）は使わないので、mkShellNoCC にする（CI でキャッシュする Nix ストアが小さくなる）
        devShells.default = pkgs.mkShellNoCC {
          packages = with pkgs; [
            # Python 本体は入れない。uv が .python-version を見て入れる（CI の setup-uv と同じ）
            # ruff などの Python のツールは、uv.lock で管理する（uv run で使う）
            uv
            pre-commit
            # scripts/build-docs.sh の npx（@redocly/cli で API のドキュメントをビルドする）
            nodejs
            # GitHub Actions のワークフローのチェック（nixpkgs の actionlint は shellcheck・pyflakes を同梱している）
            actionlint
            # terraform は unfree でビルド済みのものがなく、ソースからのビルドに時間がかかるので入れない（別に入れる）
          ];

          # 開発環境に入ったときに、pre-commit のフックを入れる（入っていれば何もしない）
          # pre-commit（nix の Python）の依存が PYTHONPATH に入り、uv run の venv より先に読み込まれてしまう。
          # 例えば venv の platformdirs が登録する pytest のプラグインを、nix の古い platformdirs から
          # 読もうとして pytest が起動できなくなる。pre-commit 自体は PYTHONPATH がなくても動く
          shellHook = ''
            unset PYTHONPATH
            pre-commit install
          '';
        };
      }
    );
}
