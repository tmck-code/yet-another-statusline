STATUSLINE_SRC := $(CURDIR)/claude/statusline_command.py
THEMES_SRC     := $(CURDIR)/claude/statusline/themes.py
MON_SRC        := $(CURDIR)/claude/mon.py
INSTALL_DIR	   := $(HOME)/.claude

install:
	@mkdir -p "$(INSTALL_DIR)/statusline"
	@ln -sf $(STATUSLINE_SRC) "$(INSTALL_DIR)/statusline_command.py" || true
	@ln -sf $(THEMES_SRC)     "$(INSTALL_DIR)/statusline/themes.py" || true
	@echo "installed -> $(INSTALL_DIR)/statusline_command.py"
	@echo "installed -> $(INSTALL_DIR)/statusline/themes.py"

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
	@python3 claude/statusline/demo.py

demo/img:
	@python3 claude/statusline/demo.py --snapshots demo/

mon/install:
	@for dir in $(INSTALL_DIRS); do \
		if ! test -d "$$dir"; then \
			echo "directory $$dir does not exist, skipping"; \
			continue; \
		fi; \
		ln -sf $(MON_SRC) "$$dir/mon.py"; \
		echo "installed mon -> $$dir"; \
	done

mon/run:
	uv run python claude/mon.py

.PHONY: install bench pr-info demo demo/img mon/install mon/run
