# Mender needs three things at runtime that a plain Python image does not have:
# git (worktrees are the sandbox), Node (the Codex CLI ships as an npm package),
# and a writable HOME for Codex to keep its auth and session state.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    NODE_MAJOR=22

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates curl gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_$NODE_MAJOR.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @openai/codex \
    && apt-get purge -y gnupg && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first so edits to source do not invalidate the pip layer.
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir fastapi uvicorn[standard] pytest

COPY mender/ ./mender/
COPY dashboard/ ./dashboard/
COPY demo-repo/ ./demo-repo/
COPY tests/ ./tests/
# Recorded sessions. Without these an instance that cannot reach Codex has
# nothing to fall back on, so a missing key would mean a dead demo rather than
# a replayed one.
COPY replays/ ./replays/
RUN pip install --no-cache-dir --no-deps -e .

# Codex writes auth and session state under HOME; the demo sandbox and the
# per-attempt worktrees live under /app. Both must be writable by a non-root
# user, which most hosts insist on.
RUN useradd --create-home --uid 10001 mender \
    && mkdir -p /app/.mender-demo /app/.mender-work \
    && chown -R mender:mender /app /home/mender
USER mender

ENV HOME=/home/mender \
    CODEX_HOME=/home/mender/.codex \
    HOST=0.0.0.0 \
    PORT=8000 \
    MENDER_PUBLIC=1 \
    MENDER_CODEX_BYPASS_SANDBOX=1 \
    GIT_AUTHOR_NAME=Mender \
    GIT_AUTHOR_EMAIL=mender@localhost \
    GIT_COMMITTER_NAME=Mender \
    GIT_COMMITTER_EMAIL=mender@localhost

EXPOSE 8000

COPY --chown=mender:mender docker-entrypoint.sh /usr/local/bin/
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "mender", "serve"]
