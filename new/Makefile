.PHONY: setup test lint scrape build verify serve clean

setup:
	python -m pip install -e ".[dev]"

test:
	python -m pytest -q

lint:
	ruff check .

# SOURCES=all or a comma-separated list
scrape:
	python -m pipeline.run_scrapers --sources "$${SOURCES:-all}"

build:
	python -m pipeline.build_clean
	python -m pipeline.build_entities
	python -m pipeline.build_dist

verify:
	python -m pipeline.verify

# Serve the site against the current data/dist. Parquet needs real HTTP range
# requests, so file:// will not work.
serve:
	@mkdir -p site/data && cp -r data/dist/* site/data/ 2>/dev/null || true
	python -m http.server 8000 --directory site

clean:
	rm -rf data/clean data/dist site/data .cache
