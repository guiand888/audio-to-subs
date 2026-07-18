{
  description = "parolesub dev environment: `nix develop` drives local dev (backend + frontend) and CI alike";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python311;

        # Native deps needed to build the Python dependency set from source
        # (argon2-cffi's _cffi_backend, plus uvloop/httptools from
        # uvicorn[standard]). python311 itself is already built against its
        # own openssl/sqlite for the stdlib ssl/sqlite3 modules (verified via
        # `python311.buildInputs`), and doesn't propagate them to consumers
        # (`python311.propagatedBuildInputs` is empty) -- so only libffi
        # needs to be supplied fresh here for cffi to link against.
        pythonNativePkgs = with pkgs; [ python gcc pkg-config libffi ];

        nodePkgs = with pkgs; [ nodejs_24 ];

        # Common to every shell: git (shellHook uses it to find REPO_ROOT)
        # and cacert (TLS root certs for pip/npm network access).
        commonPkgs = with pkgs; [ git cacert ];

        pythonVenvShellHook = ''
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
        '';

        pythonEnv = {
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
      in
      {
        devShells = {
          # Full environment: backend + frontend + service deps. Used for
          # local dev and by CI's backend test job.
          default = pkgs.mkShell {
            name = "parolesub-dev";

            packages = commonPkgs ++ pythonNativePkgs ++ nodePkgs ++ (with pkgs; [
              # Media processing (used at runtime by ffmpeg-python)
              ffmpeg

              # Backend service dependency (mirrors docker-compose redis service)
              redis

              # Linters/type-checkers. The venv (requirements-dev.txt) also
              # installs pinned ruff/mypy, which take PATH precedence once the
              # shellHook activates it - these native copies guarantee `ruff`
              # and `mypy` are runnable under `nix develop` even before the
              # venv is bootstrapped, matching CI's `make lint`/`make typecheck`.
              ruff
              mypy
            ]);

            env = pythonEnv;

            shellHook = pythonVenvShellHook + ''
              echo ""
              echo "parolesub dev shell ready:"
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

          # Lean, node-only shell for frontend-only work (e.g. CI's frontend
          # job) so it isn't paying for a Python venv bootstrap it never
          # touches.
          frontend = pkgs.mkShell {
            name = "parolesub-frontend";
            packages = commonPkgs ++ nodePkgs;
          };
        };
      });
}
