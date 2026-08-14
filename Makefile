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
# With DEMO_ONLY set, also emits a deterministic PNG screenshot next to the .txt
# (demo/<scenario>.png) via ops/ansi_png.py — handy for before/after PR shots.
# Font/size/colours are overridable; see ops/ansi_png.py for the env knobs:
#   DEMO_ONLY=tasks YAS_DEMO_FONT='FiraCode Nerd Font Mono' make demo/img
# Set SKIP_PNG=1 to skip the PNG conversion step (still requires DEMO_ONLY):
#   SKIP_PNG=1 DEMO_ONLY=tasks make demo/img
demo/img:
	@uv run python3 ops/demo.py --snapshots demo/
	@if [ -n "$(DEMO_ONLY)" ] && [ -z "$(SKIP_PNG)" ]; then \
		case "$(DEMO_ONLY)" in \
			subagent-tree-*) d=demo/subagents;; \
			*) d=demo;; \
		esac; \
		uv run python3 ops/ansi_png.py $$d/$(DEMO_ONLY).txt $$d/$(DEMO_ONLY).png; \
	fi

# Renders one scenario at every max_width in a range into a single gzipped,
# delimited archive (demo/widths.txt.gz) -- the width sweep used to catch layout
# breakage that only shows up at particular column counts.
#   make demo/widths                       # kitchen-sink, widths 1-350
#   DEMO_ONLY=tasks make demo/widths       # a different scenario
#   FROM=40 TO=120 JOBS=8 make demo/widths # a narrower range / less parallelism
# Inspect the archive with the same script:
#   ./f.sh play | ./f.sh extract <width> | ./f.sh changes
demo/widths:
	@DEMO="$(or $(DEMO_ONLY),kitchen-sink)" ./ops/f.sh render

test:
	@uv run pytest -q

statusline/test:
	@uv run python ops/demo.py

# Replay: build and play a session recording
# Usage: make replay SESSION=<session-id> [SPEED=10.0] [WIDTH=recorded]
# SESSION: session ID or path to .psv.gz recording
# SPEED: playback speed multiplier (default: 10.0)
# WIDTH: width mode (recorded/current/N, default: recorded)
replay:
	@uv run python3 ops/replay.py build $(SESSION) -o /tmp/replay.psv
	@uv run python3 ops/replay.py play /tmp/replay.psv --speed $(SPEED) --width $(WIDTH)

mon/run:
	uv run python claude/mon.py

# usage:
# VERSION=0.X.Y make version/bump
version/bump:
	# update plugin.json
	sed -i 's/$(shell uv version --short)/$(VERSION)/g' .claude-plugin/plugin.json
	# update the runtime copy (claude/yas/constants.py isn't pip/uv-installed --
	# ops/install.sh runs the loose files directly, so this can't read the
	# version via importlib.metadata and has to carry its own literal).
	# Anchored on the VERSION line itself rather than the old value, so it
	# doesn't matter whether this runs before or after `uv version` mutates
	# pyproject.toml below.
	sed -i "s/^VERSION[[:space:]]*=.*/VERSION    = '$(VERSION)'/" claude/yas/constants.py
	# update pyproject.toml & uv.lock
	uv version $(VERSION)
	@uv lock && uv sync --all-groups
	@git add .claude-plugin/plugin.json claude/yas/constants.py pyproject.toml uv.lock
	@git commit -m "Bump version to $(VERSION)"
	@git push

.PHONY: hooks bench pr-info demo demo/img demo/widths test statusline/test mon/run replay version/bump
