# CLAUDE.md 嘅 make targets（Windows 冇 make 就照 docs/runbook.md 用 python 指令）

dev:
	python -m pip install -r requirements.txt

test:
	python -m pytest tests/ -q

run:
	@echo "Step 6 先有 pipeline run（見 PLAN.md）"
