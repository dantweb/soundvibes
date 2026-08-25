# soundvibes task runner.
#
#   make install            create the venv and install dependencies
#   make install offline    ...and add fully offline translation (see below)
#
#   make start              transcribe in this terminal; Ctrl-C stops it
#   make start fr           ...and show a French translation as you speak
#   make start fr de        ...several languages at once
#
#   make start-d            transcribe in the background
#   make start-d fr         ...with a French translation running alongside
#   make stop               stop the background transcription
#   make status             is it running, and what has it written
#   make logs               follow the background transcript live
#
#   make test               fast unit suite (no model, no microphone)
#   make selftest           end-to-end check against the real model
#
# Note on `make start -d`: GNU make claims `-d` as its own debug flag wherever
# it appears on the command line, so it cannot be passed through to a target.
# `make start-d` is the working spelling.

.DEFAULT_GOAL := help
SHELL := /bin/bash

PYTHON   := ./.venv/bin/python
PIP      := ./.venv/bin/pip
OUTPUT   ?= transcripts/transcript.txt
RUN_DIR  := var
PID_FILE := $(RUN_DIR)/soundvibes.pid
LOG_FILE := $(RUN_DIR)/soundvibes.log
STOP_TIMEOUT := 15

# Commands, as opposed to language arguments.
COMMANDS := help start start-d stop restart status logs install offline \
            test selftest clean venv translate-ready

# Anything else on the command line is a language: `make start fr de`
COMMA := ,
EMPTY :=
SPACE := $(EMPTY) $(EMPTY)
LANGUAGES := $(filter-out $(COMMANDS),$(MAKECMDGOALS))
LANGS ?= $(subst $(SPACE),$(COMMA),$(strip $(LANGUAGES)))
TRANSLATE := $(if $(LANGS),--translate $(LANGS),)

.PHONY: $(COMMANDS)

help:
	@awk '/^#/{sub(/^# ?/, ""); print; next} {exit}' $(MAKEFILE_LIST)

venv:
	@test -x $(PYTHON) || { \
	  echo "No virtualenv yet. Run 'make install' first."; exit 1; }

# ── running ──────────────────────────────────────────────────────────────

# Refuse to start with translation requested but no working backend, rather
# than running happily and leaving the translate.*.txt files empty.
translate-ready:
	@if [ -n "$(LANGS)" ] \
	   && [ "$$($(PYTHON) -c 'from soundvibes.config import CONFIG; print(CONFIG.translation.backend)')" = "argos" ] \
	   && ! $(PIP) show argostranslate >/dev/null 2>&1; then \
	  echo "Translation into [$(LANGS)] was requested, but the offline backend"; \
	  echo "is not installed, so the translate.*.txt files would stay empty."; \
	  echo; \
	  echo "  make install offline      install it (large: stanza, spacy, torch)"; \
	  echo "  --translator claude       use the API instead (text leaves the machine)"; \
	  exit 1; \
	fi

start: venv translate-ready
	@echo "Transcribing to $(OUTPUT)$(if $(LANGS), + translate.*.txt [$(LANGS)],)"
	@echo "Press Ctrl-C to stop."
	@echo
	@$(PYTHON) soundvibes.py -o $(OUTPUT) $(TRANSLATE)

start-d: venv translate-ready
	@if [ -f $(PID_FILE) ] && kill -0 "$$(cat $(PID_FILE))" 2>/dev/null; then \
	  echo "Already running (pid $$(cat $(PID_FILE))). Use 'make stop' first."; \
	  exit 1; \
	fi
	@mkdir -p $(RUN_DIR) $(dir $(OUTPUT))
	@nohup $(PYTHON) soundvibes.py -o $(OUTPUT) $(TRANSLATE) \
	  >> $(LOG_FILE) 2>&1 & echo $$! > $(PID_FILE)
	@sleep 1
	@if kill -0 "$$(cat $(PID_FILE))" 2>/dev/null; then \
	  echo "Started in the background (pid $$(cat $(PID_FILE)))."; \
	  echo "  transcript : $(OUTPUT)"; \
	  $(if $(LANGS),echo "  translating: $(LANGS)";,) \
	  echo "  follow     : make logs"; \
	  echo "  stop       : make stop"; \
	else \
	  echo "It exited immediately. Last lines of $(LOG_FILE):"; \
	  tail -n 15 $(LOG_FILE); rm -f $(PID_FILE); exit 1; \
	fi

stop:
	@if [ ! -f $(PID_FILE) ]; then echo "Not running (no $(PID_FILE))."; exit 0; fi; \
	pid=$$(cat $(PID_FILE)); \
	if ! kill -0 "$$pid" 2>/dev/null; then \
	  echo "Not running (stale pid $$pid); cleaning up."; rm -f $(PID_FILE); exit 0; \
	fi; \
	echo "Stopping pid $$pid (draining the queue)..."; \
	kill "$$pid"; \
	for i in $$(seq 1 $(STOP_TIMEOUT)); do \
	  kill -0 "$$pid" 2>/dev/null || break; sleep 1; \
	done; \
	if kill -0 "$$pid" 2>/dev/null; then \
	  echo "Still alive after $(STOP_TIMEOUT)s; sending SIGKILL."; kill -9 "$$pid"; \
	fi; \
	rm -f $(PID_FILE); echo "Stopped."

restart: stop start-d

status:
	@if [ -f $(PID_FILE) ] && kill -0 "$$(cat $(PID_FILE))" 2>/dev/null; then \
	  echo "running (pid $$(cat $(PID_FILE)))"; \
	else \
	  echo "not running"; \
	fi
	@for f in $(dir $(OUTPUT))transcript* $(dir $(OUTPUT))translate.*; do \
	  [ -f "$$f" ] && printf '  %-34s %s lines\n' "$$f" "$$(wc -l < $$f | tr -d ' ')"; \
	done; true

logs:
	@touch $(LOG_FILE); tail -f $(LOG_FILE)

# ── install ──────────────────────────────────────────────────────────────

install:
	@./setup.sh

offline: venv
	@echo "Installing offline translation (this is large: stanza, spacy, torch)..."
	@$(PIP) install -r requirements-translate.txt
	@$(PYTHON) offline_setup.py

# ── checks ───────────────────────────────────────────────────────────────

test: venv
	@$(PYTHON) -m pytest tests/ -q

selftest: venv
	@$(PYTHON) selftest.py

clean:
	@rm -rf .pytest_cache $(RUN_DIR)
	@find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null; true
	@echo "Cleaned. Transcripts and .venv were left alone."

# Language arguments (`make start fr`) reach make as goals. Absorb them, but
# refuse a bare `make fr` so a mistyped command is not silently a no-op.
%:
	@if [ -z "$(filter $(COMMANDS),$(MAKECMDGOALS))" ]; then \
	  echo "soundvibes: '$@' is not a command. Try 'make help'."; exit 2; \
	fi
