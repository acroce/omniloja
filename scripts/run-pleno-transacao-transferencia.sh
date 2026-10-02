#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if command -v node >/dev/null 2>&1; then
  exec node scripts/pleno-transacao-transferencia.mjs
fi

CODEX_NODE="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
if [ -x "$CODEX_NODE" ]; then
  exec "$CODEX_NODE" scripts/pleno-transacao-transferencia.mjs
fi

echo "Node.js nao encontrado. Instale Node.js ou rode pelo ambiente do Codex." >&2
exit 1
