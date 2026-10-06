.DEFAULT_GOAL := help
IMAGE ?= ethereum-wallet-cli:local
PYTHON ?= python3
RUFF ?= ruff

.PHONY: help build test test-integration test-docker lint format format-check run run-monad clean
help:
	@echo 'build              Build Docker image (IMAGE=ethereum-wallet-cli:local)'
	@echo 'test               Run offline tests'
	@echo 'test-integration   Run isolated Foundry/Anvil tests in Docker'
	@echo 'test-docker        Test both real launchers with disposable encrypted wallets'
	@echo 'lint               Compile Python and check shell syntax'
	@echo 'format             Format Python source and tests (requires Ruff)'
	@echo 'format-check       Check Python formatting'
	@echo 'run                Launch Docker wallet shell (ARGS="...")'
	@echo 'run-monad          Launch Monad wallet shell (ARGS="...")'
	@echo 'clean              Remove generated Python cache files'
build:
	docker build -t $(IMAGE) .
test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v
test-integration: build
	docker run --rm --entrypoint python -e PYTHONPATH=/app/src -e WALLET_CLI_INTEGRATION=1 --mount type=bind,source=$(CURDIR)/tests,target=/app/tests,readonly --mount type=bind,source=$(CURDIR)/scripts,target=/app/scripts,readonly $(IMAGE) -m unittest discover -s /app/tests -v
test-docker: build
	WALLET_CLI_DOCKER_E2E=1 WALLET_CLI_DOCKER_E2E_IMAGE=$(IMAGE) PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -p test_docker_e2e.py -v
lint:
	$(RUFF) check --config pyproject.toml src tests
	$(PYTHON) -m compileall -q src tests
	bash -n scripts/ethereum-wallet-cli scripts/monad-wallet-cli
	sh -n scripts/container/ethereum-wallet-cli scripts/container/monad-wallet-cli
format:
	$(RUFF) check --config pyproject.toml --select I --fix src tests
	$(RUFF) format --config pyproject.toml src tests
format-check:
	$(RUFF) check --config pyproject.toml --select I src tests
	$(RUFF) format --config pyproject.toml --check src tests
run:
	ETHEREUM_WALLET_IMAGE=$(IMAGE) scripts/ethereum-wallet-cli $(ARGS)
run-monad:
	MONAD_WALLET_IMAGE=$(IMAGE) scripts/monad-wallet-cli $(ARGS)
clean:
	find src tests -type d -name __pycache__ -exec rm -rf {} +
