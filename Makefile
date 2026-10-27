.PHONY: dev setup demo up test site clean-demo public
# One command from a clean clone: install, run the demo round, serve app (:8000) + site (:8080).
dev: setup up

setup:
	uv sync
	uv run playwright install chromium

up:
	uv run shingle up

demo:
	uv run shingle demo --fresh

test:
	uv run pytest

site:
	uv run shingle site demo-r1

public:
	./scripts/export_public.sh
