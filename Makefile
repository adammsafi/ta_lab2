# ============================================================================
# Data Refresh Targets
# ============================================================================
#
# Convenience commands for daily refresh workflow.
# All commands use Python scripts from src/ta_lab2/scripts/
# ============================================================================

.PHONY: bars emas daily-refresh daily-refresh-validate dry-run validate clean-logs help-refresh

# Run all bar builders
bars:
	python src/ta_lab2/scripts/bars/run_all_bar_builders.py --ids all --verbose

# Run all EMA refreshers
emas:
	python src/ta_lab2/scripts/emas/run_all_ema_refreshes.py --verbose

# Full daily refresh (bars + EMAs) with logging
daily-refresh:
	@python -c "import datetime; print('.logs/refresh-' + datetime.date.today().isoformat() + '.log')" > .tmp_logfile
	@python src/ta_lab2/scripts/run_daily_refresh.py --all --verbose --log-file $$(cat .tmp_logfile)
	@rm .tmp_logfile

# Run with validation and alerts
daily-refresh-validate:
	@python -c "import datetime; print('.logs/refresh-' + datetime.date.today().isoformat() + '.log')" > .tmp_logfile
	@python src/ta_lab2/scripts/run_daily_refresh.py --all --verbose --validate --alert-on-error --log-file $$(cat .tmp_logfile)
	@rm .tmp_logfile

# Show what would execute without running
dry-run:
	python src/ta_lab2/scripts/run_daily_refresh.py --all --dry-run

# Run validation only (no refresh)
validate:
	python src/ta_lab2/scripts/emas/run_all_ema_refreshes.py --only "" --validate

# Clean old log files (keep last 30 days)
clean-logs:
	@echo "Cleaning log files older than 30 days..."
	@python -c "import os, time; from pathlib import Path; log_dir = Path('.logs'); [f.unlink() for f in log_dir.glob('refresh-*.log') if log_dir.exists() and (time.time() - f.stat().st_mtime) > 30*24*3600]" 2>/dev/null || echo "No old logs to clean"

# Help target
help-refresh:
	@echo "Data Refresh Targets:"
	@echo "  make bars                    - Run all bar builders"
	@echo "  make emas                    - Run all EMA refreshers"
	@echo "  make daily-refresh           - Full bars + EMAs refresh with logging"
	@echo "  make daily-refresh-validate  - Full refresh with validation and alerts"
	@echo "  make dry-run                 - Show what would execute without running"
	@echo "  make validate                - Run EMA validation only (no refresh)"
	@echo "  make clean-logs              - Remove logs older than 30 days"
