#!/usr/bin/env bash
# Authenticate Codex from the environment, then hand over to the real command.
#
# The key is read from the environment and piped straight into `codex login`,
# so it is never written to a file by us and never baked into the image. Set
# OPENAI_API_KEY as a secret in the host's dashboard — not in the repository.
set -euo pipefail

if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  if printenv OPENAI_API_KEY | codex login --with-api-key >/dev/null 2>&1; then
    echo "mender: codex authenticated from OPENAI_API_KEY"
  else
    echo "mender: WARNING — codex login failed; heals will not work" >&2
  fi
else
  echo "mender: WARNING — OPENAI_API_KEY is not set; heals will not work" >&2
fi

# git refuses to operate on a tree it does not consider trustworthy, which is
# every bind-mounted or freshly-copied directory in a container.
git config --global --add safe.directory '*' || true
git config --global init.defaultBranch main || true

exec "$@"
