statusline/test:
	@echo
	@cat claude/statusline/session-info-example.json | python3 ./claude/statusline-command.py
	@echo -e "\n"

.PHONY: statusline/test
