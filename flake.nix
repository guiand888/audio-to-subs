{
  description = "Dev environment for audio-to-subs (replaces Dockerfile.dev)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python311;
      in
      {
        devShells.default = pkgs.mkShell {
          name = "audio-to-subs-dev";

          packages = with pkgs; [
            # Backend runtime (pip is bootstrapped into the venv via `python -m venv`,
            # deliberately not taken from nixpkgs: python311Packages.pip currently
            # pulls in a sphinx build that's broken for the 3.11 interpreter)
            python

            # Native deps pulled in by the Python dependency set
            # (argon2-cffi, aiosqlite, etc. build/link against these)
            gcc
            pkg-config
            libffi
            openssl
            sqlite

            # Media processing (used at runtime by ffmpeg-python)
            ffmpeg

            # Backend service dependency (mirrors docker-compose redis service)
            redis

            # Frontend toolchain (mirrors node:24-alpine used in Makefile)
            nodejs_24

            # Misc
            git
            cacert
          ];

          env = {
            # Keep venv + caches inside the repo, out of $HOME.
            PIP_DISABLE_PIP_VERSION_CHECK = "1";

            # greenlet (SQLAlchemy / argon2-cffi dep) loads libstdc++.so.6 at
            # import time; nixpkgs' gcc does not put it on the default library
            # search path, so expose it explicitly. Without this, every test
            # that touches SQLAlchemy async raises:
            #   "the greenlet library is required to use this function.
            #    libstdc++.so.6: cannot open shared object file"
            LD_LIBRARY_PATH = "${pkgs.gcc.cc.lib}/lib";
          };

          shellHook = ''
            set -e

            export SSL_CERT_FILE="${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
            export REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

            VENV_DIR="$REPO_ROOT/.venv"
            if [ ! -d "$VENV_DIR" ]; then
              echo "[nix develop] creating Python venv at .venv"
              ${python}/bin/python -m venv "$VENV_DIR"
            fi
            # shellcheck disable=SC1091
            source "$VENV_DIR/bin/activate"

            REQ_HASH_FILE="$VENV_DIR/.deps.sha256"
            CURRENT_HASH="$(cat "$REPO_ROOT/requirements.txt" "$REPO_ROOT/requirements-dev.txt" "$REPO_ROOT/pyproject.toml" 2>/dev/null | sha256sum | cut -d' ' -f1)"
            if [ ! -f "$REQ_HASH_FILE" ] || [ "$(cat "$REQ_HASH_FILE")" != "$CURRENT_HASH" ]; then
              echo "[nix develop] installing/updating Python dependencies (requirements-dev.txt + editable package)"
              pip install --quiet --upgrade pip
              pip install --quiet -r "$REPO_ROOT/requirements-dev.txt"
              pip install --quiet -e "$REPO_ROOT"
              echo "$CURRENT_HASH" > "$REQ_HASH_FILE"
            fi

            set +e

            echo ""
            echo "audio-to-subs dev shell ready:"
            echo "  python  $(python --version 2>&1)   ($(command -v python))"
            echo "  node    $(node --version)   ($(command -v node))"
            echo "  ffmpeg  $(ffmpeg -version | head -n1 | cut -d' ' -f1-3)"
            echo "  redis   $(redis-server --version)"
            echo ""
            echo "Backend:   pytest | black audio_to_subs/ tests/ | ruff check audio_to_subs/ tests/ | mypy audio_to_subs/"
            echo "Frontend:  (cd frontend && npm install && npm run dev|test|build)"
            echo "Redis:     redis-server --daemonize yes   (or podman-compose up redis)"
            echo ""
          '';
        };
      });
}
