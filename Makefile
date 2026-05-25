STATUSLINE_SRC    := $(CURDIR)/claude/statusline_command.py
THEMES_SRC        := $(CURDIR)/claude/statusline/themes.py
MON_SRC           := $(CURDIR)/claude/mon.py
CLAUDE_CONFIG_DIR ?= $(HOME)/.claude

install:
	@mkdir -p "$(CLAUDE_CONFIG_DIR)/statusline"
	@ln -sfv $(STATUSLINE_SRC) "$(CLAUDE_CONFIG_DIR)/statusline_command.py" || true
	@ln -sfv $(THEMES_SRC) "$(CLAUDE_CONFIG_DIR)/statusline/themes.py" || true

demo:
	@python3 claude/statusline/demo.py

demo/img:
	@python3 claude/statusline/demo.py --snapshots demo/

mon/install:
	@ln -sfv $(MON_SRC) "$(CLAUDE_CONFIG_DIR)/mon.py" || true

mon/run:
	uv run python claude/mon.py

.PHONY: install demo demo/img mon/install mon/run
