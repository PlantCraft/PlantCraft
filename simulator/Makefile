# Same checks as CI. `make ci` must be green before every push (AGENTS.md, section 4).
.PHONY: ci deps lint format test catalog build serve loops image smoke lock

PYTHON ?= python

ci: deps lint catalog test build

deps:
	$(PYTHON) -m pip install -q -e ".[test]"

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

catalog:
	simcraft validate-catalog

test:
	$(PYTHON) -m pytest -q

build:
	$(PYTHON) -m build --outdir dist .

# The 50-loop portfolio the PlantCraft demo reads, and the 500-signal benchmark.
loops:
	simcraft loops serve

serve:
	simcraft serve --profile development

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
		-t simcraft:$(VERSION) .

# Start the image as the suite's compose file does (read-only, no capabilities, uid 10004) and
# wait for its own HEALTHCHECK. Short history so the check answers within a minute.
smoke:
	docker rm -f simcraft-smoke >/dev/null 2>&1 || true
	docker run -d --name simcraft-smoke --read-only --tmpfs /tmp --cap-drop ALL \
		--security-opt no-new-privileges:true --user 10004:10004 -v simcraft-smoke:/data \
		-e SIMCRAFT_HISTORY_HOURS=0.2 simcraft:$(VERSION)
	for i in $$(seq 60); do \
		status=$$(docker inspect -f '{{.State.Health.Status}}' simcraft-smoke); \
		[ "$$status" = healthy ] && break; sleep 2; done; \
		docker logs simcraft-smoke; docker inspect -f '{{.State.Health.Status}}' simcraft-smoke; \
		[ "$$status" = healthy ]; ok=$$?; docker rm -f simcraft-smoke >/dev/null; \
		docker volume rm simcraft-smoke >/dev/null; exit $$ok

lock:
	uv pip compile deploy/requirements.in --python-version 3.13 \
		--python-platform x86_64-manylinux_2_28 --generate-hashes --no-header --quiet \
		-o deploy/requirements.lock
	sed -i '1i # Pinned, hashed dependencies of the Docker image (Python 3.13, Linux). Regenerate with\n# `make lock` after changing pyproject.toml; the image build refuses any file whose hash differs.' deploy/requirements.lock
