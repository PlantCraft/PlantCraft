# Same checks as CI. `make ci` must be green before every push (AGENTS.md, section 4).
.PHONY: ci deps standard lint format test test-fast test-postgres sources-check sources-public frontend e2e bench serve collect image package lock

PYTHON ?= python
SDK := plantcraft-sdk==0.77.0

ci: deps standard lint frontend test

# plantcraft-sdk is not on any index: it is installed from the wheel in vendor/ only, always
# reinstalled so a copy left by another folder's job on a shared runner never stands in for it.
deps:
	$(PYTHON) -m pip install -q --force-reinstall --no-index --find-links vendor --no-deps "$(SDK)"
	$(PYTHON) -m pip install -q --find-links vendor -e ".[dev]"

# The suite's app standard (PlantCraft docs/app-standard.md): app.toml, layout, Makefile
# targets, vendored SDK hash; run as a module so $(PYTHON) finds it.
standard:
	$(PYTHON) -m plantcraft_sdk.app_cli check .

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

test:
	$(PYTHON) -m pytest -q

# The quick loop while working: everything but the slow tier (PlantCraft docs/testing.md).
test-fast:
	$(PYTHON) -m pytest -q -m "not slow"

# The same suite on PostgreSQL: HISTCRAFT_TEST_DATABASE_URL=postgresql://user:pw@host/db (an
# empty database; each test gets a schema, dropped at the end). CI job `postgres`.
test-postgres:
	@test -n "$$HISTCRAFT_TEST_DATABASE_URL" || { echo "Set HISTCRAFT_TEST_DATABASE_URL"; exit 1; }
	$(PYTHON) -m pytest -q

# Every source kind against the Simulator's test kit (sources_check/, docs/source-checks.md):
# CSV, PI Web API, OPC UA, and MQTT, Modbus and SQL through the suite's pinned Telegraf. SQL needs
# HISTCRAFT_SOURCES_PG (a PostgreSQL DSN) or initdb, else it is skipped; HISTCRAFT_SOURCES_STRICT=1
# fails when Telegraf cannot be had instead of skipping. Needs Python 3.12+ (the Simulator's).
sources-check:
	$(PYTHON) -m pip install -q -e "../../simulator[testkit]"
	$(PYTHON) -m pytest -q -rs sources_check

# Historian's readers against public test servers. By hand only, never in CI (not our servers).
sources-public:
	$(PYTHON) -m pip install -q -e "../../simulator[testkit]"
	$(PYTHON) -m sources_check.public

frontend:
	cd frontend && npm ci --no-audit --no-fund && npm run build && npm test

# No browser journeys yet (docs/gaps.md, G12); the target exists so every app has the same names.
e2e:
	@echo "PlantCraft Historian has no e2e journeys yet (docs/gaps.md, G12)."

bench:
	$(PYTHON) -m histcraft.bench --points 2000 --seconds 1800

serve:
	histcraft serve --port 8100

collect:
	HISTCRAFT_COLLECTOR=off histcraft collect

VERSION ?= $(shell $(PYTHON) -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])")
# Optional: BUILD_CA=/path/ca.pem behind a TLS-inspecting proxy; DOCKER_BUILD_FLAGS for the rest.
BUILD_CA ?=
comma := ,
DOCKER_BUILD_FLAGS ?=

image:
	docker build $(DOCKER_BUILD_FLAGS) $(if $(BUILD_CA),--secret id=build_ca$(comma)src=$(BUILD_CA)) \
		--build-arg VERSION=$(VERSION) \
		--build-arg REVISION=$$(git rev-parse --short HEAD 2>/dev/null || echo unknown) \
		--build-arg CREATED=$$(date -u +%Y-%m-%dT%H:%M:%SZ) \
		-t histcraft:$(VERSION) .

# The signed .pcapp package (PlantCraft docs/app-package.md), built by PlantCraft's
# deploy/package.sh from app.toml. PLANTCRAFT_DIR is the root of the PlantCraft repository (default ../..); PUBLISHER_KEY the
# publisher's Ed25519 private key (PEM, never committed).
PLANTCRAFT_DIR ?= ../..
PUBLISHER_KEY ?=

package: image
	@test -n "$(PUBLISHER_KEY)" || { echo "Set PUBLISHER_KEY=/path/to/publisher.key"; exit 1; }
	$(PLANTCRAFT_DIR)/deploy/package.sh --app app.toml --key $(PUBLISHER_KEY) --out dist/

lock:
	uv pip compile deploy/requirements.in --python-version 3.13 \
		--python-platform x86_64-manylinux_2_28 --generate-hashes --no-header --quiet \
		--find-links vendor --no-emit-package histcraft --no-emit-package plantcraft-sdk \
		-o deploy/requirements.lock
	sed -i '1i # Pinned, hashed dependencies of the Docker image (Python 3.13, Linux). Regenerate with\n# `make lock` after changing pyproject.toml; the image build refuses any file whose hash differs.' deploy/requirements.lock
