{
  description = "なんでもお知らせくん 開発環境";

  # github: 入力は Claude Code のクラウド環境の GitHub プロキシで拒否されるため、
  # channels.nixos.org の tarball を使う
  inputs.nixpkgs.url = "https://channels.nixos.org/nixos-26.05/nixexprs.tar.xz";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});

      # CI (hashicorp/setup-terraform の ~1.9.0) と揃えるため、nixpkgs の terraform ではなく
      # 公式バイナリを固定する。nixpkgs の terraform は unfree でバイナリキャッシュに無く、
      # ソースからのビルドになるのも避けたい。
      terraformVersion = "1.9.8";
      terraformHashes = {
        x86_64-linux = "sha256-GG4BRfXl8uuXy9eFvHjyG65O8VEZNJ9q1PpTW4OxDfg=";
        aarch64-linux = "sha256-+FhoeYg0VYI59hSINIhACPJyJUj4QDTJsPYpNLLXPrs=";
        x86_64-darwin = "sha256-vlkejFnEnQz7x2ZNJJEKS0OEC4nQpLvKZiFJu/A5fpE=";
        aarch64-darwin = "sha256-hz17kl0IV4+2u5wSx82SrnPiieB8Ng8v3Wn5A2t7qqs=";
      };
      terraformPlatforms = {
        x86_64-linux = "linux_amd64";
        aarch64-linux = "linux_arm64";
        x86_64-darwin = "darwin_amd64";
        aarch64-darwin = "darwin_arm64";
      };

      mkTerraform =
        pkgs:
        let
          system = pkgs.stdenv.hostPlatform.system;
        in
        pkgs.stdenvNoCC.mkDerivation {
          pname = "terraform";
          version = terraformVersion;
          src = pkgs.fetchurl {
            url = "https://releases.hashicorp.com/terraform/${terraformVersion}/terraform_${terraformVersion}_${terraformPlatforms.${system}}.zip";
            hash = terraformHashes.${system};
          };
          nativeBuildInputs = [ pkgs.unzip ];
          sourceRoot = ".";
          installPhase = ''
            install -Dm755 terraform $out/bin/terraform
          '';
          # Terraform は BUSL-1.1。meta.license に書くと allowUnfree が必要になるため書いていない
        };

      # devShell と、Claude Code のクラウドセッションの SessionStart フック
      # (.claude/hooks/session-start.sh) の両方で使うツール一式
      devTools = pkgs: [
        pkgs.python313
        pkgs.uv
        pkgs.nodejs # openapi.yaml から docs.html を生成する npx @redocly/cli 用
        (mkTerraform pkgs)
      ];
    in
    {
      packages = forAllSystems (pkgs: {
        terraform = mkTerraform pkgs;
        dev-tools = pkgs.buildEnv {
          name = "nandemo-oshirase-dev-tools";
          paths = devTools pkgs;
        };
      });

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShellNoCC {
          packages = devTools pkgs;

          # uv には Nix の Python を使わせ、Python 本体のダウンロードはさせない
          env = {
            UV_PYTHON = "${pkgs.python313}/bin/python3";
            UV_PYTHON_DOWNLOADS = "never";
          };

          # Nix の Python の site-packages が PYTHONPATH に入ると .venv のパッケージと
          # ぶつかるので外す (pre-commit などは uv の dev 依存から使う)
          shellHook = ''
            unset PYTHONPATH
          '';
        };
      });
    };
}
