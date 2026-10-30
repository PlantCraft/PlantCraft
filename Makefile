# Same checks as CI. `make ci` must be green before every push (AGENTS.md, section 4).
.PHONY: ci ci-all api-contract lint test test-fast frontend notebooks notebook-kits notebook-kit-lock e2e e2e-suite e2e-bundle e2e-upgrade bench-suite soak format image simcraft-image bundle isolation lock apps-images release-bundle

# macOS ships python3 only; a virtual environment gives both names.
PYTHON ?= $(shell command -v python >/dev/null 2>&1 && echo python || echo python3)

ci: sdk lint test frontend

# The platform's checks, then every app's and the Simulator's own `make ci`, one after the other
# (in CI each folder's workflow runs its own). `dev/ship` runs only the parts a change touches.
ci-all: ci
	@for dir in apps/*/ simulator/; do echo "== $$dir"; $(MAKE) -C $$dir ci || exit 1; done

# API v1 as this commit serves it (docs/api/v1/openapi.json) and its reference page; CI refuses a
# commit whose API v1 differs from the file, or that breaks a release's (plantcraft.api.contract).
api-contract:
	$(PYTHON) -m plantcraft.api.contract write

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

test:
	$(PYTHON) -m pytest -q --ignore=tests/e2e
	$(PYTHON) -m pytest -q sdk/python/tests

# The loop while working: everything but the slow tier (docs/testing.md).
test-fast:
	$(PYTHON) -m pytest -q --ignore=tests/e2e -m "not slow"
	$(PYTHON) -m pytest -q sdk/python/tests -m "not slow"

# plantcraft-sdk (sdk/python) is a dependency of plantcraft: install it from the tree, into
# the active virtual environment only. Nothing is installed when the SDK Python imports is already
# this tree's; outside a virtual environment (and outside CI, which sets CI) it stops instead of
# changing a shared Python. GitHub CI installs it in its own steps (.github/workflows/ci.yml).
.PHONY: sdk
sdk:
	@$(PYTHON) -c "$$SDK_CHECK"; status=$$?; \
		if [ $$status -eq 3 ]; then $(PYTHON) -m pip install -q -e sdk/python; \
		elif [ $$status -ne 0 ]; then exit $$status; fi

# Exit 0: the SDK Python imports is this tree's; 3: install it here; 2: not in a virtual env.
define SDK_CHECK
import importlib.util, os, pathlib, sys
spec = importlib.util.find_spec("plantcraft_sdk")
tree = pathlib.Path("sdk/python").resolve()
if spec and spec.origin and tree in pathlib.Path(spec.origin).resolve().parents:
    sys.exit(0)
if sys.prefix != sys.base_prefix or os.environ.get("CI"):
    sys.exit(3)
print(f"make sdk: {sys.executable} is not a virtual environment; activate one (python -m venv .venv)"
      " so plantcraft-sdk is installed there, not into a shared Python.", file=sys.stderr)
sys.exit(2)
endef
export SDK_CHECK

# The plantcraft-sdk wheel apps vendor (docs/app-standard.md, section 3): the same bytes from
# the same sources on any machine. Built from a copy of sdk/python's files (git's view, tests
# left out) with fixed modes, umask and timestamps, by the setuptools pinned in its [build-system].
# Offline: PIP_FIND_LINKS=<folder with that setuptools wheel> PIP_NO_INDEX=1 make sdk-wheel.
SDK_EPOCH := 315532800
.PHONY: sdk-wheel
sdk-wheel:
	rm -rf build/sdk-wheel && mkdir -p build/sdk-wheel dist
	git ls-files -z --cached --others --exclude-standard sdk/python \
		| grep -zv '^sdk/python/tests/' | xargs -0 cp --parents -t build/sdk-wheel
	find build/sdk-wheel -type d -exec chmod 755 {} + && find build/sdk-wheel -type f -exec chmod 644 {} +
	rm -f dist/plantcraft_sdk-*.whl
	umask 022 && SOURCE_DATE_EPOCH=$(SDK_EPOCH) PYTHONHASHSEED=0 $(PYTHON) -m pip wheel -q --no-deps --no-cache-dir \
		-w dist build/sdk-wheel/sdk/python
	rm -rf build/sdk-wheel
	@sha256sum dist/plantcraft_sdk-*.whl

frontend: ui-check
	cd frontend && npm ci && npm run build && npm test

# Notebooks: JupyterLite with a pruned Pyodide in notebooks/dist (online, about a minute; the image
# builds it in its own stage). Its own virtual environment: Jupyter's pins stay out of ours.
notebooks:
	test -x notebooks/.venv/bin/python || $(PYTHON) -m venv notebooks/.venv
	notebooks/.venv/bin/pip install -q -r notebooks/requirements.txt
	notebooks/.venv/bin/python notebooks/build.py

# Notebooks kits: Python and JupyterLab for Windows, macOS and Linux in notebooks/kit/dist (online,
# a few minutes, about 180 MB each; an optional part of the bundle). uv fetches each system's wheels,
# checked against notebooks/kit/requirements.txt; notebook-kit-lock writes that file again.
notebook-kits:
	test -x notebooks/.venv/bin/python || $(PYTHON) -m venv notebooks/.venv
	notebooks/.venv/bin/pip install -q uv==0.11.32
	UV=notebooks/.venv/bin/uv notebooks/.venv/bin/python notebooks/kit/build_kit.py

notebook-kit-lock:
	cd notebooks/kit && uv pip compile requirements.in --universal --python-version 3.12 \
		--generate-hashes --no-header -o requirements.txt

# @plantcraft/ui (ui/): the suite frame every app draws (docs/app-standard.md, section 10).
# Apps vendor the packed file like the SDK wheel; PlantCraft's own frontend installs the same
# file from frontend/vendor/. `make ui-package` rebuilds it; `make ui-check` (part of `make
# frontend`) fails when the vendored file is not what ui/ builds now.
UI_VERSION := $(shell $(PYTHON) -c "import json; print(json.load(open('ui/package.json'))['version'])")
UI_TGZ := plantcraft-ui-$(UI_VERSION).tgz
.PHONY: ui ui-package ui-check
ui:
	cd ui && npm ci && npm test && npm run build

ui-package: ui
	mkdir -p dist && rm -f dist/plantcraft-ui-*.tgz
	cd ui && npm pack --silent --pack-destination ../dist >/dev/null
	mkdir -p frontend/vendor && cp dist/$(UI_TGZ) frontend/vendor/$(UI_TGZ)
	@sha256sum dist/$(UI_TGZ)

ui-check: ui
	mkdir -p build/ui-check && rm -f build/ui-check/*.tgz
	cd ui && npm pack --silent --pack-destination ../build/ui-check >/dev/null
	@cmp -s build/ui-check/$(UI_TGZ) frontend/vendor/$(UI_TGZ) \
		|| { echo "frontend/vendor/$(UI_TGZ) is not what ui/ builds now: run make ui-package"; exit 1; }
	@sha256sum frontend/vendor/$(UI_TGZ)

e2e:
	$(PYTHON) -m pytest -q tests/e2e

# The demo story across every app, on a live installation (never in GitHub CI: locally or on the
# Mac mini runner). SUITE_URL=https://host/ ; see tests/e2e_suite/conftest.py for the options.
e2e-suite:
	PLANTCRAFT_SUITE_URL=$(SUITE_URL) $(PYTHON) -m pytest -q tests/e2e_suite

# Source to walked demo on this machine: every image, the bundle, a clean install with the public
# demo and the suite journeys (ci/e2e-bundle.sh; needs the app checkouts next to this one).
e2e-bundle:
	ci/e2e-bundle.sh

# A released bundle installed with data, updated to these checkouts and rolled back, keeping
# everything (ci/e2e-upgrade.sh; never in GitHub CI). FROM_BUNDLE=<released .tar.gz or folder>.
e2e-upgrade:
	FROM_BUNDLE="$(FROM_BUNDLE)" ci/e2e-upgrade.sh

# The suite at plant scale on an installed stack: seeds HistCraft, the plant map, reads, Link
# rounds, a dashboard and twins, then writes docs/bench/results/<host>-<time>-<scale>.json
# (ci/bench/suite_bench.py, docs/bench/README.md; never in GitHub CI). Asks before adding data.
BENCH_PREFIX ?= dist/e2e-bundle/install
BENCH_SCALE ?= target
bench-suite:
	python3 ci/bench/suite_bench.py --prefix "$(BENCH_PREFIX)" --scale $(BENCH_SCALE) $(BENCH_FLAGS)

# Days on one build: probes and the suite's own health, with the Mac mini's deploys held, then a
# verdict in <prefix>/data/soak/report.md (ci/bench/soak.py, docs/bench/README.md).
SOAK_HOURS ?= 72
soak:
	python3 ci/bench/soak.py --prefix "$(BENCH_PREFIX)" --hours $(SOAK_HOURS)

# Offline Docker deployment (deploy/, docs/install-offline.md).
VERSION ?= $(shell $(PYTHON) -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])")
LINKCRAFT_VERSION ?= $(VERSION)
DASHCRAFT_VERSION ?= $(VERSION)
HISTCRAFT_VERSION ?= $(VERSION)
# The Simulator (the `demo` profile's OPC UA simulator) is its own product with its own version:
# its image is built from simulator/ and bundled and tested only when that image exists.
SIMCRAFT_VERSION ?= 0.5.1
SIMCRAFT_SRC ?= simulator
# Optional: BUILD_CA=/path/ca.pem behind a TLS-inspecting proxy; DOCKER_BUILD_FLAGS for the rest
# (for example --network host); PROXY_BUILD_FLAGS only for the proxy image (for example
# --build-arg CADDY_IMAGE=<mirror>/caddy:2.11.2-alpine@sha256:<same digest>).
BUILD_CA ?=
PROXY_BUILD_FLAGS ?=
comma := ,
DOCKER_BUILD_FLAGS ?=

image:
	docker build $(DOCKER_BUILD_FLAGS) $(if $(BUILD_CA),--secret id=build_ca$(comma)src=$(BUILD_CA)) \
		--build-arg VERSION=$(VERSION) \
		--build-arg REVISION=$$(git rev-parse --short HEAD 2>/dev/null || echo unknown) \
		--build-arg CREATED=$$(date -u +%Y-%m-%dT%H:%M:%SZ) \
		-t processcraft:$(VERSION) .
	docker build $(DOCKER_BUILD_FLAGS) $(PROXY_BUILD_FLAGS) \
		--build-arg VERSION=$(VERSION) \
		--build-arg REVISION=$$(git rev-parse --short HEAD 2>/dev/null || echo unknown) \
		--build-arg CREATED=$$(date -u +%Y-%m-%dT%H:%M:%SZ) \
		-t processcraft-proxy:$(VERSION) deploy/proxy
	docker build $(DOCKER_BUILD_FLAGS) $(if $(BUILD_CA),--secret id=build_ca$(comma)src=$(BUILD_CA)) \
		--build-arg VERSION=$(VERSION) \
		--build-arg REVISION=$$(git rev-parse --short HEAD 2>/dev/null || echo unknown) \
		--build-arg CREATED=$$(date -u +%Y-%m-%dT%H:%M:%SZ) \
		-f deploy/installer/Dockerfile -t processcraft-installer:$(VERSION) .

# simcraft:$(SIMCRAFT_VERSION) from $(SIMCRAFT_SRC), with the same BUILD_CA and
# DOCKER_BUILD_FLAGS (for example --build-arg PYTHON_IMAGE=<mirror>/python:...@sha256:<same digest>).
simcraft-image:
	@test -f "$(SIMCRAFT_SRC)/Dockerfile" || { echo "no Simulator at $(SIMCRAFT_SRC): set SIMCRAFT_SRC"; exit 1; }
	@found=$$(cd "$(SIMCRAFT_SRC)" && $(PYTHON) -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])"); \
		test "$$found" = "$(SIMCRAFT_VERSION)" || { echo "$(SIMCRAFT_SRC) is the Simulator $$found, not $(SIMCRAFT_VERSION): set SIMCRAFT_VERSION"; exit 1; }
	$(MAKE) -C "$(SIMCRAFT_SRC)" image VERSION=$(SIMCRAFT_VERSION) BUILD_CA="$(BUILD_CA)" \
		DOCKER_BUILD_FLAGS="$(DOCKER_BUILD_FLAGS)"

# A publisher key pair for development: keys/dev-publisher.key (private, gitignored, never
# shipped) and deploy/trusted-publishers/dev-publisher.pub (gitignored too), so packages signed
# with it install on a development stack (docs/app-package.md).
.PHONY: dev-publisher
dev-publisher:
	$(PYTHON) plantcraft/apps/package.py keygen --name dev-publisher --out-dir keys
	cp keys/dev-publisher.pub deploy/trusted-publishers/dev-publisher.pub

# With the Simulator at SIMCRAFT_SRC its image is built too; without it, the bundle
# ships without the Simulator and the isolation tests use a stand-in on the demo network.
WITH_SIMCRAFT := $(if $(wildcard $(SIMCRAFT_SRC)/Dockerfile),simcraft-image)

# Every app's image at this checkout's versions (and Models' runner): what `release-bundle` ships.
apps-images:
	for app in alarms documents historian link models view; do $(MAKE) -C apps/$$app image || exit 1; done
	$(MAKE) -C apps/models runner-image

# The release: the platform, every app and the Simulator in one bundle.
release-bundle: apps-images bundle

# The bundle carries the Notebooks kits (built again only when what makes them changed).
bundle: image notebook-kits $(WITH_SIMCRAFT)
	VERSION=$(VERSION) LINKCRAFT_VERSION=$(LINKCRAFT_VERSION) \
		DASHCRAFT_VERSION=$(DASHCRAFT_VERSION) HISTCRAFT_VERSION=$(HISTCRAFT_VERSION) \
		SIMCRAFT_VERSION=$(SIMCRAFT_VERSION) deploy/bundle.sh

isolation: image $(WITH_SIMCRAFT)
	PLANTCRAFT_ISOLATION=live PLANTCRAFT_VERSION=$(VERSION) LINKCRAFT_VERSION=$(LINKCRAFT_VERSION) \
		DASHCRAFT_VERSION=$(DASHCRAFT_VERSION) \
		HISTCRAFT_VERSION=$(HISTCRAFT_VERSION) \
		SIMCRAFT_VERSION=$(SIMCRAFT_VERSION) $(PYTHON) -m pytest -q tests/test_isolation.py

lock:
	uv pip compile deploy/requirements.in --python-version 3.13 \
		--python-platform x86_64-manylinux_2_28 --generate-hashes --no-header --quiet \
		--no-emit-package plantcraft --no-emit-package plantcraft-sdk \
		-o deploy/requirements.lock
	sed -i '1i # Pinned, hashed dependencies of the Docker image (Python 3.13, Linux). Regenerate with\n# `make lock` after changing a pyproject.toml; the image build refuses any file whose hash differs.' deploy/requirements.lock
