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
	@uv run python3 claude/statusline/demo.py

demo/img:
	@uv run python3 claude/statusline/demo.py --snapshots demo/

test:
	@uv run pytest -q

statusline/test:
	@uv run python claude/statusline/demo.py

mon/run:
	uv run python claude/mon.py

.PHONY: hooks bench pr-info demo demo/img test statusline/test mon/run
