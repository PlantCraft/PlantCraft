# Same checks as CI. `make ci` must be green before every push (AGENTS.md, section 4).
.PHONY: ci deps standard lint format test test-fast frontend e2e serve image runner-image runner package lock

PYTHON ?= $(shell command -v python >/dev/null 2>&1 && echo python || echo python3)
SDK := plantcraft-sdk==0.101.0

ci: deps standard lint frontend test

# The suite's app standard (PlantCraft docs/app-standard.md): app.toml, layout, Makefile
# targets, vendored SDK hash; run as a module so $(PYTHON) finds it.
standard:
	$(PYTHON) -m plantcraft_sdk.app_cli check .
	$(PYTHON) -m plantcraft_sdk.i18n_check .

# plantcraft-sdk is not on any index: it is installed from the wheel in vendor/ only, always
# reinstalled so a copy left by another folder's job on a shared runner never stands in for it.
deps:
	$(PYTHON) -m pip install -q --force-reinstall --no-index --find-links vendor --no-deps "$(SDK)"
	$(PYTHON) -m pip install -q --find-links vendor -e ".[dev]"

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

# The interface is built first so the page tests (sign-in redirect) run against it.
test:
	$(PYTHON) -m pytest -q

# The quick loop while working: everything but the slow tier (PlantCraft docs/testing.md).
test-fast:
	$(PYTHON) -m pytest -q -m "not slow"

frontend:
	cd frontend && npm ci --no-audit --no-fund && npm run build && npm test

# Browser journeys (needs `pip install -e ".[e2e]"` and Chromium; set
# PLAYWRIGHT_CHROMIUM_EXECUTABLE to use a Chromium already on the machine).
e2e: frontend
	MODELCRAFT_E2E_REQUIRED=1 $(PYTHON) -m pytest -q tests/e2e

serve:
	modelcraft serve --port 8130

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
		-t modelcraft:$(VERSION) .

# The Modelica runner (OpenModelica + the Modelica Standard Library): its own image, run by the
# suite with no network, no secret, a read-only root filesystem and limits (deploy/runner/).
runner-image:
	docker build $(DOCKER_BUILD_FLAGS) $(if $(BUILD_CA),--secret id=build_ca$(comma)src=$(BUILD_CA)) \
		--build-arg VERSION=$(VERSION) \
		--build-arg REVISION=$$(git rev-parse --short HEAD 2>/dev/null || echo unknown) \
		--build-arg CREATED=$$(date -u +%Y-%m-%dT%H:%M:%SZ) \
		-f deploy/runner/Dockerfile -t modelcraft-runner:$(VERSION) .

# The runner for development, sandboxed as in the suite, on the jobs folder JOBS (absolute path)
# that `modelcraft serve` uses (MODELCRAFT_JOBS_DIR).
JOBS ?= $(CURDIR)/var/jobs
runner:
	mkdir -p "$(JOBS)"
	docker run --rm --name modelcraft-runner --network none --read-only --tmpfs /tmp \
		--cap-drop ALL --security-opt no-new-privileges:true --memory 4g --cpus 2 --pids-limit 256 \
		--user $$(id -u):$$(id -g) -v "$(JOBS)":/jobs modelcraft-runner:$(VERSION)

# The suite's signed app package, dist/modelcraft-<version>.pcapp (the app standard, section 8;
# PlantCraft docs/app-package.md): PlantCraft's deploy/package.sh signs app.toml, the image and
# its SBOM with the publisher key. PLANTCRAFT_DIR is the root of the PlantCraft repository (default ../..); PUBLISHER_KEY is
# the Ed25519 private key, kept outside every repository. The SBOM is the image's /app/sbom.json
# (plantcraft-app sbom, written at build) unless SBOM names one (syft's, for example).
PLANTCRAFT_DIR ?= ../..
PUBLISHER_KEY ?=
SBOM ?=

package: image
	@test -x "$(PLANTCRAFT_DIR)/deploy/package.sh" || { \
		echo "No $(PLANTCRAFT_DIR)/deploy/package.sh: set PLANTCRAFT_DIR to a PlantCraft checkout."; \
		exit 1; }
	@test -n "$(PUBLISHER_KEY)" || { echo "Set PUBLISHER_KEY to the publisher's private key file."; exit 1; }
	mkdir -p dist
	$(if $(SBOM),,docker run --rm --network none --entrypoint cat modelcraft:$(VERSION) /app/sbom.json > dist/sbom.spdx.json)
	"$(PLANTCRAFT_DIR)/deploy/package.sh" --app app.toml --key "$(PUBLISHER_KEY)" \
		--sbom "$(or $(SBOM),dist/sbom.spdx.json)" --out dist

lock:
	uv pip compile deploy/requirements.in --python-version 3.13 \
		--python-platform x86_64-manylinux_2_28 --generate-hashes --no-header --quiet \
		--find-links vendor --no-emit-package modelcraft --no-emit-package plantcraft-sdk \
		-o deploy/requirements.lock
	sed -i '1i # Pinned, hashed dependencies of the Docker image (Python 3.13, Linux). Regenerate with\n# `make lock` after changing pyproject.toml; the image build refuses any file whose hash differs.' deploy/requirements.lock
