# Shingle: harness, checks, grading app and site builder in one image.
FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PATH="/app/.venv/bin:$PATH"
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /usr/local/bin/uv
# docker CLI so the harness can start per-episode sandbox containers (via the mounted socket)
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
# Node + Lighthouse for real Lighthouse audits (falls back to built-in audits if unavailable)
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && npm install -g lighthouse@12.2.1 --no-audit --no-fund
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project --python /usr/local/bin/python3.12
RUN playwright install --with-deps chromium
COPY . .
RUN uv sync --frozen --no-dev --python /usr/local/bin/python3.12
EXPOSE 8000 8080
CMD ["shingle", "--help"]
