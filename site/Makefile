# PlantCraft's site and its chat. `make ci` before every push (AGENTS.md, section 4).
.PHONY: ci lint test build serve eval

ci: lint test

lint:
	ruff check .
	ruff format --check .

test:
	python -m pytest -q -p no:playwright

build:
	python build.py --draft

# The site at http://127.0.0.1:8090 with its chat (off unless SITE_CHAT_PROVIDER and a key are set).
serve: build
	python -m sitechat serve

# Every question of eval/questions.toml to the configured model; the report lands in eval-report/.
eval: build
	python -m sitechat eval --judge
