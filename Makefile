hooks:
	@if [ "$$(git config --local --get core.hooksPath)" = ".github/hooks" ]; then \
		echo "pre-commit hooks already active (core.hooksPath=.github/hooks)"; \
	else \
		printf 'Enable this repo'\''s git hooks? Runs:\n  git config --local core.hooksPath .github/hooks\nProceed? [y/N] '; \
		read ans; \
		case "$$ans" in \
			[yY]|[yY][eE][sS]) git config --local core.hooksPath .github/hooks && echo "hooks enabled -> .github/hooks";; \
			*) echo "skipped";; \
		esac; \
	fi

bench:
	@uv run python ops/bench.py $(BENCH_ARGS)

pr-info:
	@uname -a
	@claude --version 2>/dev/null || echo "claude: not installed"
	@echo "TERM=$$TERM TERM_PROGRAM=$$TERM_PROGRAM SHELL=$$SHELL COLORTERM=$$COLORTERM"
	@echo "LANG=$$LANG LC_ALL=$$LC_ALL"
	@python3 -V
	@uv --version 2>/dev/null || echo "uv: not installed"

demo:
	@uv run python3 ops/demo.py

demo/img:
	@uv run python3 ops/demo.py --snapshots demo/

test:
	@uv run pytest -q

statusline/test:
	@uv run python ops/demo.py

mon/run:
	uv run python claude/mon.py

# usage:
# VERSION=0.X.Y make version/bump
version/bump:
	# update plugin.json
	sed -i 's/$(shell uv version --short)/$(VERSION)/g' .claude-plugin/plugin.json
	# update pyproject.toml & uv.lock
	uv version $(VERSION)
	@uv lock && uv sync --all-groups
	@git add .claude-plugin/plugin.json pyproject.toml uv.lock
	@git commit -m "Bump version to $(VERSION)"
	@git push

.PHONY: hooks bench pr-info demo demo/img test statusline/test mon/run version/bump
