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
	@echo "| Key | Value |"
	@echo "|-----|-------|"
	@printf "| OS | %s |\n" "$$(uname -a)"
	@printf "| Claude Code | %s |\n" "$$(claude --version 2>/dev/null || echo 'not installed')"
	@printf "| Terminal | TERM=$$TERM TERM_PROGRAM=$$TERM_PROGRAM SHELL=$$SHELL COLORTERM=$$COLORTERM |\n"
	@printf "| Locale | LANG=$$LANG LC_ALL=$$LC_ALL |\n"
	@printf "| Python | %s |\n" "$$(python3 -V 2>&1)"
	@printf "| uv | %s |\n" "$$(uv --version 2>/dev/null || echo 'not installed')"

demo:
	@uv run python3 ops/demo.py

# Renders every scenario .txt (plus per-theme kitchen-sink renders) into demo/.
# Set DEMO_ONLY=<scenario-name> to render just one scenario's .txt, e.g.
#   DEMO_ONLY=tasks make demo/img
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
