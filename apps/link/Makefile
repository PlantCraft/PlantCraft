# Same checks as CI. `make ci` must be green before every push (AGENTS.md, section 4).
.PHONY: ci deps standard lint format test test-fast frontend e2e bench serve image package lock

PYTHON ?= $(shell command -v python >/dev/null 2>&1 && echo python || echo python3)
SDK := plantcraft-sdk==0.102.0

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
	$(PYTHON) -m plantcraft_sdk.i18n_check --strict .

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
	LINKCRAFT_E2E_REQUIRED=1 $(PYTHON) -m pytest -q tests/e2e

bench:
	$(PYTHON) -m linkcraft.bench --loops 2000 --processes 4 --latency-ms 2

serve:
	linkcraft serve --port 8140

# Metadata from app.toml, the one source (PlantCraft app standard, section 4).
manifest = $(shell $(PYTHON) -c "import tomllib; m = tomllib.load(open('app.toml', 'rb')); print(m$(1))")
# The version is app.toml's, nowhere else: the image tag, its label, the package and /healthz
# (the installed package's version) all say the same; `make image VERSION=...` is refused.
APP_VERSION := $(call manifest,['app']['version'])
VERSION := $(APP_VERSION)
APP_ID := $(call manifest,['app']['id'])
APP_PREFIX := $(call manifest,['runtime']['prefix'])
APP_PORT := $(call manifest,['runtime']['port'])
APP_UID := $(call manifest,['runtime']['uid'])
APP_SUMMARY := $(call manifest,['app']['summary'])
# Optional: BUILD_CA=/path/ca.pem behind a TLS-inspecting proxy; DOCKER_BUILD_FLAGS for the rest.
BUILD_CA ?=
comma := ,
DOCKER_BUILD_FLAGS ?=

image:
	@test "$(VERSION)" = "$(APP_VERSION)" || { echo "make image: the version is app.toml's" \
		"($(APP_VERSION)); change it there, not with VERSION=$(VERSION)." >&2; exit 1; }
	docker build $(DOCKER_BUILD_FLAGS) $(if $(BUILD_CA),--secret id=build_ca$(comma)src=$(BUILD_CA)) \
		--build-arg VERSION=$(VERSION) \
		--build-arg APP_ID=$(APP_ID) --build-arg APP_PREFIX=$(APP_PREFIX) \
		--build-arg APP_PORT=$(APP_PORT) --build-arg APP_UID=$(APP_UID) \
		--build-arg SUMMARY="$(APP_SUMMARY)" \
		--build-arg REVISION=$$(git rev-parse --short HEAD 2>/dev/null || echo unknown) \
		--build-arg CREATED=$$(date -u +%Y-%m-%dT%H:%M:%SZ) \
		-t $(APP_ID):$(VERSION) .

# The signed dist/<id>-<version>.pcapp (app standard, section 8; PlantCraft
# docs/app-package.md): PlantCraft's deploy/package.sh signs app.toml, the image and its SBOM.
# PLANTCRAFT_DIR is the root of the PlantCraft repository (default ../..); PUBLISHER_KEY the publisher's Ed25519 private key,
# kept outside every repository. Without PUBLISHER_KEY a development key pair is made for this
# build in build/dev-publisher/ (gitignored, made again every time) and the package is checked
# against it: such a package installs only where that .pub is trusted. The SBOM is the image's
# /app/sbom.json (python -m plantcraft_sdk.sbom, run inside it at build) unless SBOM names one (syft's, for example).
PLANTCRAFT_DIR ?= ../..
PUBLISHER_KEY ?=
SBOM ?=
PUBLISHER_ID := $(shell $(PYTHON) -c "import re, tomllib; \
	name = tomllib.load(open('app.toml', 'rb'))['app']['publisher']; \
	print(re.sub('[^a-z0-9]+', '-', name.lower()).strip('-'))")
DEV_KEYS := build/dev-publisher
PACKAGE_PY := $(PLANTCRAFT_DIR)/plantcraft/apps/package.py

package: image
	@test -x "$(PLANTCRAFT_DIR)/deploy/package.sh" || { echo "make package: no" \
		"$(PLANTCRAFT_DIR)/deploy/package.sh; set PLANTCRAFT_DIR to a PlantCraft checkout." >&2; \
		exit 1; }
	mkdir -p dist
ifeq ($(PUBLISHER_KEY),)
	rm -rf $(DEV_KEYS)
	python3 $(PACKAGE_PY) keygen --name $(PUBLISHER_ID) --out-dir $(DEV_KEYS)
	@echo "make package: no PUBLISHER_KEY; signed with a development key made now" \
		"($(DEV_KEYS)/$(PUBLISHER_ID).key, never committed)." >&2
endif
	$(if $(SBOM),,docker run --rm --network none --entrypoint cat $(APP_ID):$(VERSION) /app/sbom.json > dist/sbom.spdx.json)
	"$(PLANTCRAFT_DIR)/deploy/package.sh" --app app.toml \
		--key "$(or $(PUBLISHER_KEY),$(DEV_KEYS)/$(PUBLISHER_ID).key)" \
		--sbom "$(or $(SBOM),dist/sbom.spdx.json)" --out dist
ifeq ($(PUBLISHER_KEY),)
	python3 $(PACKAGE_PY) verify --trusted $(DEV_KEYS) dist/$(APP_ID)-$(VERSION).pcapp
endif

lock:
	uv pip compile deploy/requirements.in --python-version 3.13 \
		--python-platform x86_64-manylinux_2_28 --generate-hashes --no-header --quiet \
		--find-links vendor --override deploy/overrides.txt --no-emit-package linkcraft --no-emit-package plantcraft-sdk \
		-o deploy/requirements.lock
	sed -i '1i # Pinned, hashed dependencies of the Docker image (Python 3.13, Linux). Regenerate with\n# `make lock` after changing pyproject.toml; the image build refuses any file whose hash differs.' deploy/requirements.lock
