# Per-episode sandbox: the agent's shell runs here with --network none.
FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends coreutils grep sed procps && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
CMD ["sleep", "infinity"]
