ZENSICAL_VERSION ?= 0.0.70
ZENSICAL := uvx zensical==$(ZENSICAL_VERSION)

.PHONY: help
help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-12s %s\n", $$1, $$2}'

.PHONY: test
test: ## Run the plugin's unittest suite
	python3 plugins/pipeline/tests/run.py

.PHONY: docs
docs: docs-test ## Build the documentation site to out/site, failing on broken links (as checks.yaml's docs job)
	$(ZENSICAL) build --strict --clean

.PHONY: docs-test
docs-test: ## Check the reference pages cover every command, agent, skill and pipeline.json key, and the nav every page
	python3 docs/check.py

.PHONY: docs-serve
docs-serve: ## Preview the documentation site with live reload
	$(ZENSICAL) serve
