PYTHON := venv/bin/python
MANAGE := $(PYTHON) manage.py
ARGS ?=

.PHONY: install check migrate test test-core run seed

install:
	$(PYTHON) -m pip install -r requirements.txt

check:
	$(MANAGE) check

migrate:
	$(MANAGE) migrate

test:
	$(MANAGE) test $(ARGS)

test-core:
	$(MANAGE) test apps.reports apps.workspaces apps.finance apps.core.tests apps.hotel $(ARGS)

run:
	$(MANAGE) runserver $(ARGS)

seed:
	$(MANAGE) seed_demo
