# Same checks as CI. `make ci` must be green before every push (AGENTS.md, section 4).
.PHONY: ci deps standard lint format test test-fast frontend e2e serve dev rename image package dev-package lock

PYTHON ?= python
SDK := plantcraft-sdk==0.77.0

ci: deps standard lint frontend test

# The suite's app standard (PlantCraft docs/app-standard.md): app.toml, layout, Makefile
# targets, vendored SDK hash; run as a module so $(PYTHON) finds it.
standard:
	$(PYTHON) -m plantcraft_sdk.app_cli check .

# plantcraft-sdk is not on any index: it is installed from the wheel in vendor/ only, always
# reinstalled so another copy in the same Python never stands in for it.
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
	STARTER_E2E_REQUIRED=1 $(PYTHON) -m pytest -q tests/e2e

serve:
	starter serve --port 9100

# PlantCraft's checkout: the repository's root inside PlantCraft (templates/app), else a
# PlantCraft clone beside this folder. Override with PLANTCRAFT_DIR=/path/to/PlantCraft.
PLANTCRAFT_DIR ?= $(if $(wildcard ../../deploy/package.sh),../..,../PlantCraft)

# The app inside the platform, without an image: the Simulator, PlantCraft on :8060 and this app
# on :9100, signed in through PlantCraft and listed in its launcher (prompts/04-try-in-platform.md).
dev: deps frontend
	cd "$(PLANTCRAFT_DIR)" && $(PYTHON) run_opcua_demo.py --no-linkcraft \
		--app starter=http://127.0.0.1:9100/starter/ $(DEV_FLAGS)

# Give the app its own name, once: make rename NAME=Logbook [PORT=9110] [UID=20110].
NAME ?=
PORT ?=
UID ?=
rename:
	@test -n "$(NAME)" || { echo "Usage: make rename NAME=Logbook [PORT=9110] [UID=20110]"; exit 1; }
	$(PYTHON) tools/rename.py "$(NAME)" $(if $(PORT),--port $(PORT)) $(if $(UID),--uid $(UID))

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
		-t starter:$(VERSION) .

# The suite's signed app package, dist/starter-<version>.pcapp (the app standard, section 8;
# PlantCraft docs/app-package.md): PlantCraft's deploy/package.sh signs app.toml, the image and
# its SBOM with the publisher key. PUBLISHER_KEY is the Ed25519 private key, kept outside every
# repository. The SBOM is the image's /app/sbom.json (plantcraft-app sbom, written at build)
# unless SBOM names one (syft's, for example).
PUBLISHER_KEY ?=
SBOM ?=

package: image
	@test -x "$(PLANTCRAFT_DIR)/deploy/package.sh" || { \
		echo "No $(PLANTCRAFT_DIR)/deploy/package.sh: set PLANTCRAFT_DIR to a PlantCraft checkout."; \
		exit 1; }
	@test -n "$(PUBLISHER_KEY)" || { echo "Set PUBLISHER_KEY to the publisher's private key file."; exit 1; }
	mkdir -p dist
	$(if $(SBOM),,docker run --rm --network none --entrypoint cat starter:$(VERSION) /app/sbom.json > dist/sbom.spdx.json)
	"$(PLANTCRAFT_DIR)/deploy/package.sh" --app app.toml --key "$(PUBLISHER_KEY)" \
		--sbom "$(or $(SBOM),dist/sbom.spdx.json)" --out dist

# The same package signed with PlantCraft's development key (`make dev-publisher` there), which
# a development stack trusts: install dist/starter-<version>.pcapp from Apps > Install.
dev-package:
	@test -f "$(PLANTCRAFT_DIR)/keys/dev-publisher.key" || { \
		echo "Run make dev-publisher in $(PLANTCRAFT_DIR) first."; exit 1; }
	$(MAKE) package PUBLISHER_KEY="$(PLANTCRAFT_DIR)/keys/dev-publisher.key"

lock:
	uv pip compile deploy/requirements.in --python-version 3.13 \
		--python-platform x86_64-manylinux_2_28 --generate-hashes --no-header --quiet \
		--find-links vendor --no-emit-package starter --no-emit-package plantcraft-sdk \
		-o deploy/requirements.lock
	sed -i '1i # Pinned, hashed dependencies of the Docker image (Python 3.13, Linux). Regenerate with\n# `make lock` after changing pyproject.toml; the image build refuses any file whose hash differs.' deploy/requirements.lock
