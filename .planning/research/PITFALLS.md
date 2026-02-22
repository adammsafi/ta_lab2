# Domain Pitfalls: v0.8.0 Polish & Hardening

**Domain:** Hardening existing Python quant platform (ta_lab2)
**Researched:** 2026-02-22
**Scope:** Five hardening features added to a live system with ~50 tables, 22M+ rows,
408 Python source files, Windows development environment, Ubuntu CI

---

## 1. Alembic Migration Bootstrapping

### Critical: Stamp-then-Autogenerate Recreates All Existing Tables

**What goes wrong:** You run `alembic stamp head` to mark the live database as current,
then run `alembic revision --autogenerate`. The generated migration file contains
`op.create_table()` statements for tables that already exist. Running `alembic upgrade head`
then fails with `DuplicateTable: relation already exists`.

**Why it happens:** `stamp` only writes a row to the `alembic_version` table. It does NOT
synchronize Alembic's model of the schema. Autogenerate compares the SQLAlchemy `MetaData`
object (populated from ORM models) against the live database. This project has NO ORM models —
only raw SQL DDL files. That means `target_metadata` is empty, and Alembic interprets every
existing table as "missing from the model" and tries to recreate all 50 of them.

**Consequences:** Corrupted migration history. `alembic_version` shows "head" but the
migration file is not safe to apply. Rolling back requires manual edits to migration files.

**Prevention:**
- Do NOT use `--autogenerate` until SQLAlchemy ORM models that cover all 50 tables exist.
  For this codebase, autogenerate is not the right bootstrapping path.
- Write a baseline migration by hand that contains zero `op.*` operations — only comments
  documenting that the schema already exists on the live database. This migration exists
  solely to establish a versioning anchor.
- Apply the baseline migration with `alembic upgrade head` on a test/staging database
  (not production) to confirm it runs without error.
- Stamp production with `alembic stamp head` only after the baseline migration is verified.
- For subsequent migrations, write incremental `op.add_column()`, `op.create_index()` etc.
  by hand, referencing the relevant `sql/migration/` file as the source of truth.

**Warning signs:**
- Generated migration file contains more than a handful of `op.create_table()` calls
- `env.py` has `target_metadata = None` or an empty MetaData
- `alembic revision --autogenerate` on first run produces a file longer than 50 lines

**Phase:** Alembic bootstrapping. Write the no-op baseline migration before touching anything else.

---

### Critical: Windows Path Mixing Breaks CI (and Breaks Other Developers)

**What goes wrong:** `alembic.ini` is initialized on Windows with `script_location`
containing a backslash path. CI runs on Ubuntu. The path fails immediately.
Alternatively, paths that work in one working directory break when `alembic` is invoked
from a different directory (e.g., project root vs. `src/`).

**Windows-specific hazard already documented in MEMORY.md:** The existing raw SQL
migration files contain UTF-8 box-drawing characters (═══) in comments. If `env.py`
reads SQL files using `open(path)` without `encoding='utf-8'`, the same
`UnicodeDecodeError` that has already been hit will recur — but now inside the Alembic
migration runner rather than in a standalone script.

**Consequences:** CI passes on Windows, fails on Ubuntu. Or: works when run from project
root, fails when invoked as a pre-commit hook from a different working directory.

**Prevention:**
- Use forward-slash paths in `alembic.ini` even when created on Windows.
- Use `script_location = %(here)s/migrations` where `alembic.ini` lives at project root.
- In `env.py`, any `open()` call for SQL files must use `encoding='utf-8'`.
- Add `alembic current` and `alembic history` to the CI lint job so path problems are
  caught before they reach the migration job.
- Do not split SQL migration content by `;` naively — a SQL comment containing `--`
  before a semicolon will cause the `ALTER TABLE` statement after it to be silently skipped
  (already documented in MEMORY.md).

**Warning signs:**
- `alembic.ini` was created on Windows and contains backslashes in `script_location`
- `env.py` opens any file without `encoding='utf-8'`
- `alembic history` has never been run in CI

**Phase:** Alembic bootstrapping. Validate in CI before considering the setup complete.

---

### Moderate: The 16 Raw Migrations Have Ambiguous Application Order

**What goes wrong:** `sql/migration/` contains numbered files (`016_` through `021_`) and
ad-hoc named files (`alter_cmc_features_redesign.sql`, `alter_returns_tables_add_zscore.sql`,
etc.). When converting to Alembic, there is no canonical ordering for the ad-hoc files.
Applying them in the wrong order corrupts the schema — for example, adding a z-score
column before the table exists, or applying a redesign migration before the column it
replaces has been added.

**Why it happens:** The ad-hoc migrations were applied manually at different times. The
repository filesystem dates do not reliably reflect application order. Only `git log`
contains the true ordering.

**Consequences:** Alembic migration history diverges from reality. A fresh environment
(e.g., staging, CI integration test) cannot be bootstrapped correctly from migrations.

**Prevention:**
- Before writing any Alembic `.py` migration file, reconstruct the confirmed application
  order from `git log --follow --diff-filter=A -- sql/migration/` for each file.
- Accept that some ad-hoc migrations cannot be faithfully replicated as Alembic ops if
  they contained data transformations that are no longer meaningful on the current schema.
  These can be represented as no-ops with a comment explaining what was done manually.
- Assign Alembic revision numbers based on confirmed chronological order, not filename sort order.

**Warning signs:**
- Two files modify the same table and there is no clear dependency ordering
- An ad-hoc file references a column or table that does not appear in the numbered files

**Phase:** Alembic migration conversion. Reconstruct order from git log before writing Python files.

---

## 2. mypy Strictness Ramp-Up

### Critical: Running mypy Globally on Day One Produces an Unworkable Error Volume

**What goes wrong:** `mypy src/` with default settings on this codebase (~408 files,
~2,722 function definitions, 221 files importing pandas/numpy/SQLAlchemy) produces
thousands of errors immediately. The team treats this as "mypy is too hard," reverts
to non-enforcement, and the tooling sits perpetually broken.

**Why it happens:** Specific error clusters to expect on this codebase:
- `pandas-stubs` reports errors on `.values` on tz-aware DatetimeSeries — this is the
  exact pattern documented in MEMORY.md's "CRITICAL: Pandas tz-aware timestamp pitfall."
  The workaround (`.tz_localize("UTC")` or `.tolist()`) is not annotated, so mypy sees
  the return type as wrong.
- `vectorbt`: No stubs available. Every `import vectorbt` triggers `import-untyped`.
- `sqlalchemy`: Column types are `Any` without the sqlalchemy mypy plugin. The existing
  `NullPool` pattern and `text()` queries produce numerous false positives.
- `polars`: Stubs exist but version-pinned. Mismatches with `polars>=0.19.0` are common.
- 106 existing `# type: ignore` comments are bare (no error code), suppressing unknown
  errors silently rather than being specific suppressions.

The codebase currently has ~2,722 function definitions with ~1,786 return type annotations,
meaning roughly 35% of functions are unannotated — but the coverage is not uniform.
Scripts and tools layers have far less coverage than features and regimes layers.

**Consequences:** CI fails on first enforcement. Team reverts to `|| true` or removes
mypy from CI entirely. Zero net progress.

**Prevention:**
- Begin with a narrow scope. Check only the two most annotation-complete layers:
  `mypy src/ta_lab2/features src/ta_lab2/regimes`
- Add per-library ignores immediately so the initial run is clean:
  ```ini
  [mypy]
  check_untyped_defs = True
  warn_return_any = False

  [mypy-pandas.*]
  ignore_missing_imports = True
  [mypy-numpy.*]
  ignore_missing_imports = True
  [mypy-vectorbt.*]
  ignore_missing_imports = True
  [mypy-psycopg2.*]
  ignore_missing_imports = True
  [mypy-polars.*]
  ignore_missing_imports = True
  ```
- Add the narrow check to CI immediately to prevent regression in the two clean layers.
- Expand scope one package at a time: `ta_lab2.signals`, then `ta_lab2.backtests`, then
  `ta_lab2.tools`, then `ta_lab2.scripts` (expected to be last — most untyped).
- Gate each expansion on a green CI run for the expanded scope.

**Warning signs:**
- `mypy src/` on first run produces more than 500 errors (check before committing to a scope)
- Any `import vectorbt` in a checked module before stubs are suppressed

**Phase:** Code quality phase. The initial enforcement PR should check only `features` and `regimes`.

---

### Moderate: pandas-stubs Installation Can Break the numpy Version and Crash Backtests

**What goes wrong:** Installing `pandas-stubs` to silence `import-untyped` errors causes
pip to resolve a `numpy` version incompatible with `vectorbt 0.28.1`. The environment
breaks silently — tests pass (because numpy typing changed, not numerics), but the backtest
pipeline produces NaN results or crashes on dtype assumptions.

**Why it happens:** `pandas-stubs` pins a specific `numpy` version range. `pyproject.toml`
has `numpy` unpinned, so pip upgrades freely. `vectorbt 0.28.1` has documented
incompatibilities with numpy 2.x (the `_ensure_utc` helper and tz-strip logic already in
MEMORY.md are version-sensitive).

**Consequences:** Backtest metrics differ from baseline after stub installation. Difficult
to diagnose because the symptom is numerical, not a Python exception.

**Prevention:**
- Install `pandas-stubs` ONLY in the `dev` optional group, explicitly pinned
  (e.g., `pandas-stubs==2.2.*`), never in `dependencies` or `all`.
- After any stub installation, run the full backtest smoke test against `cmc_backtest_runs`
  and compare metrics to baseline.
- If `pip show pandas-stubs` shows numpy being upgraded to 2.x, add `numpy<2.0` as a
  constraint in `pyproject.toml` before proceeding.

**Warning signs:**
- `pip install pandas-stubs` output shows `numpy` being upgraded beyond current pinned version
- Backtest metrics diverge from baseline after installing type stubs

**Phase:** Code quality phase. Run backtest smoke test after any stub package installation.

---

### Minor: Bare `# type: ignore` Comments Hide Future Regressions

**What goes wrong:** 106 existing `# type: ignore` comments are written without error
codes. When mypy is enforced, bare ignores suppress all errors on that line — including
new errors introduced by later code changes. Type regressions that would be caught by
mypy pass silently.

**Why it happens:** Bare ignores were the fastest fix when errors originally appeared.
Without `--warn-unused-ignores`, there is no signal when an ignore is no longer needed.

**Prevention:**
- Add `warn_unused_ignores = True` to `mypy.ini` from the start.
- Gradually convert bare ignores to specific ones: `# type: ignore[misc]`.
- Apply a per-PR rule: any file touched by a PR must have its `# type: ignore` comments
  converted to specific codes. This amortizes the cleanup without requiring a big-bang fix.

**Phase:** Code quality phase. Do not require resolving all 106 before enforcement begins.

---

## 3. Making Ruff Lint Blocking in CI

### Critical: Removing `|| true` Breaks All Open PRs Immediately

**What goes wrong:** The current `ci.yml` has `ruff check src || true`. Removing
`|| true` without first achieving zero violations means every open pull request fails
its lint job, even PRs that touch no Python files. Development stops.

**Why it happens:** Ruff reports violations in files unrelated to the PR. CI checks the
entire `src/` directory on every run. Pre-existing violations block every PR until they
are fixed.

**Consequences:** All open PRs are blocked. Team frustration erodes trust in the
linting gate before it provides any value.

**Prevention:**
- Before changing CI, run `ruff check src --statistics` to get the current violation
  count by rule. This is the baseline to reach zero on.
- Fix all violations OR add per-rule ignores to `[tool.ruff.lint] ignore` in
  `pyproject.toml` to reach zero violations.
- Only after `ruff check src` exits 0 should the `|| true` be removed.
- Do this in two separate PRs: (1) achieve zero violations, (2) remove `|| true`.
  Keeping them separate makes rollback easier if CI reveals unexpected failures.

**Warning signs:**
- `ruff check src` currently produces any output on violations (check before starting)
- No `--statistics` baseline was captured

**Phase:** Code quality phase. The very first step is running `ruff check src --statistics`.

---

### Moderate: Ruff Version Drift Between Local Dev and CI Causes "Works on My Machine" Failures

**What goes wrong:** `pyproject.toml` specifies `ruff>=0.1.5` — an extremely loose lower
bound. CI installs the latest ruff. A developer running an older ruff locally sees clean
lint; CI runs a newer version with additional default rules. The PR fails CI despite
passing local lint.

**Why it happens:** Ruff has added new enabled-by-default rules in every minor version.
Without a pinned version, local and CI environments diverge immediately.

**Consequences:** Developers cannot trust local lint results. Frustration erodes adoption
of the blocking gate. False failures erode confidence in CI.

**Prevention:**
- Pin ruff to a specific minor version: `ruff==0.9.*` or `ruff>=0.9,<1.0`.
- Document the pin explicitly in `pyproject.toml` with a comment: `# pin to prevent
  unexpected new rules breaking CI on minor version bumps`.
- Upgrade the pin deliberately (with a PR that reviews what new rules were added).

**Warning signs:**
- `pip show ruff` on CI output differs from local `pip show ruff`
- CI lint failures appear on rules not triggered during local development

**Phase:** Code quality phase. Pin the version in the same PR that achieves zero violations.

---

## 4. Documentation Version Sync

### Moderate: Three Version Strings in Three Files Have Already Drifted and Will Drift Again

**What goes wrong:** Three files currently carry version strings, all different:
- `pyproject.toml`: `version = "0.5.0"` (actual code is v0.7.0+)
- `mkdocs.yml`: `site_name: ta_lab2 v0.4.0`
- `README.md`: `# ta_lab2 v0.5.0`

After a v0.8.0 release, any manual update will miss at least one of these. Future readers
(and AI assistants working in the codebase) will encounter contradictory version claims.
The `importlib.metadata.version("ta_lab2")` API returns `0.5.0` while the changelog
and memory files reference `v0.7.0`.

**Why it happens:** No single source of truth and no CI check that enforces consistency.

**Consequences:** Tooling that reads `pyproject.toml` version (release automation, badges)
reports the wrong version. Developers working from the README have wrong expectations.

**Prevention:**
- Update `pyproject.toml` version to `0.8.0` as the first commit of this milestone.
  `pyproject.toml` is the canonical source because it is the installed package version.
- Update `mkdocs.yml` `site_name` and `README.md` heading to match in the same commit.
- Add a one-line CI check in `ci.yml` to prevent future drift:
  ```yaml
  - name: Verify version consistency
    run: |
      pyproject_ver=$(python -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); print(d['project']['version'])")
      readme_ver=$(grep -o 'v[0-9]\+\.[0-9]\+\.[0-9]\+' README.md | head -1)
      [ "$pyproject_ver" = "${readme_ver#v}" ] || (echo "Version mismatch"; exit 1)
  ```
- Longer term: consider `setuptools-scm` to derive version from git tags, eliminating
  manual bumps entirely.

**Warning signs:**
- `grep -r "v0\." mkdocs.yml README.md pyproject.toml` returns three different version numbers
- Release PRs do not include a `pyproject.toml` version bump

**Phase:** Documentation phase. Fix all three version strings before writing any new content.
Otherwise you will be documenting v0.8.0 features under a v0.4.0 site name.

---

### Moderate: mkdocs Nav References Files That Do Not Exist

**What goes wrong:** `mkdocs.yml` references `api/memory.md`, `api/orchestrator.md`,
`time/time_model_overview.md`, `time/returns_volatility.md`, `time/regime_integration.md`
in the `nav` section. If any of these files are absent, `mkdocs build` fails with a
"file not found" error, breaking any docs CI job immediately.

**Why it happens:** Nav entries were added speculatively during earlier milestones but
the corresponding `.md` files were either never created or were placed in different directories.

**Consequences:** Any attempt to run `mkdocs build` fails before any new v0.8.0 content
can be added. The docs pipeline cannot be used at all.

**Prevention:**
- Run `mkdocs build --strict` locally before merging any docs PR. This surfaces missing
  files and broken links.
- Audit the `docs/` directory against every path in the `mkdocs.yml` nav. Either create
  placeholder stubs for missing files (one sentence is sufficient) or remove the nav entry.
- Add `mkdocs build --strict` as a separate CI job so broken nav is caught at PR time.

**Warning signs:**
- `mkdocs build` has not been run since the last codebase reorganization
- `docs/api/` or `docs/time/` directories do not exist in the filesystem

**Phase:** Documentation phase. Validate `mkdocs build --strict` succeeds before writing new content.

---

### Minor: Mike Versioning Is Wired but Non-Functional

**What goes wrong:** `mkdocs.yml` has `extra.version.provider: mike` configured. Mike
requires a `gh-pages` branch and does not work with `mkdocs serve`. Developers who
try to preview docs locally get no version-switcher feedback. If the `gh-pages` branch
does not exist, `mike deploy` fails on first use.

**Prevention:**
- For v0.8.0, remove the `mike` provider from `mkdocs.yml` unless the `gh-pages` branch
  is being actively set up as part of this milestone.
- Document the intended workflow: use `mkdocs build` to validate, not `mkdocs serve`
  for version-switching preview.

**Phase:** Documentation phase. Remove or explicitly activate mike — do not leave it in a broken intermediate state.

---

## 5. Wiring More Steps into the Orchestrator

### Critical: No Timeout on Subprocess Calls — One Hanging Step Blocks the Entire Pipeline

**What goes wrong:** Every `subprocess.run()` call in `run_daily_refresh.py`,
`run_all_bar_builders.py`, `run_all_ema_refreshes.py`, and `run_all_stats_refreshes.py`
has no `timeout` parameter. If a new stats runner hangs (slow query, database deadlock,
or a large-table full-scan), the orchestrator waits indefinitely. The daily refresh does
not complete. The next day's cron trigger starts a second instance while the first is
still running, potentially producing write conflicts on stats tables.

**Windows-specific risk:** There are documented CPython bugs where `subprocess.run` with
`capture_output=True` on Windows can hang indefinitely if the child process writes to
stdout/stderr faster than the pipe buffer is drained. The current code uses
`capture_output=True` in non-verbose mode across all subprocess calls, which is exactly
the pattern that triggers this issue.

**Consequences:** Silent production hang overnight. No error is raised. The machine sits
with a hung Python process. The database may hold an implicit lock from the incomplete step.

**Prevention:**
- Add `timeout=` to every `subprocess.run()` call. Conservative defaults for this system:
  - Stats runners (known fast): `timeout=600` (10 minutes)
  - EMA refreshers: `timeout=3600` (1 hour for full refresh)
  - Bar builders: `timeout=7200` (2 hours for full backfill)
- Handle `subprocess.TimeoutExpired` explicitly:
  ```python
  try:
      result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=600)
  except subprocess.TimeoutExpired:
      print(f"[TIMEOUT] {component} exceeded 600s — process killed")
      return ComponentResult(component=component, success=False, duration_sec=600, returncode=-1,
                             error_message="Timeout exceeded")
  ```
- Verify that `subprocess.TimeoutExpired` kills the child process and does not leave it
  as an orphan (Python 3.10+ behavior is correct, but confirm on Windows).
- Do NOT add new subprocess steps without adding a `timeout` — this should be a code
  review gate.

**Warning signs:**
- `grep -r "subprocess.run" src --include="*.py" | grep -v timeout` returns any matches
  (currently returns 15+ matches)
- No CI test exercises the orchestrator with a bounded runtime budget

**Phase:** Orchestrator wiring phase. Add timeouts to all existing calls before adding any new subprocess steps.

---

### Moderate: 5 Stats Runners in Series May Push Total Refresh Time Past 24 Hours

**What goes wrong:** The existing refresh chain (bars → EMAs → regimes) already has an
unknown runtime on the full asset universe. Adding 5 stats runners in series, each
potentially taking 10-20 minutes on large tables (EMA stats tables have stats across
22M+ rows of EMA data), adds 50-100 minutes to an already long serial pipeline. If total
runtime exceeds 24 hours, the next scheduled refresh starts before the previous one finishes.

**Why it happens:** Stats runners are added to the orchestrator without profiling their
marginal cost on the production dataset. The subprocess model is sequential by default.

**Consequences:** Second orchestrator instance writes to stats tables concurrently with
the first. Depending on the upsert pattern, this produces duplicate rows or silent
data corruption. Alternatively, the second instance's bar staleness check finds bars from
yesterday and skips the entire EMA refresh.

**Prevention:**
- Before wiring any stats runner into the orchestrator, profile it in isolation against
  the full production asset universe:
  `time python -m ta_lab2.scripts.emas.stats.run_ema_stats --all --all-tfs`
- If the sum of all 5 runners exceeds 20 minutes, consider running them in parallel
  using the same `num_processes` pattern already implemented in bar builders and EMA refreshers.
- Add a refresh lock: a sentinel file or a DB row that prevents a second orchestrator
  from starting if the first is still running.

**Warning signs:**
- No timing baseline captured for any stats runner on full asset universe
- No mechanism to prevent concurrent orchestrator runs (no lockfile, no DB semaphore)

**Phase:** Orchestrator wiring phase. Profile each runner before wiring. Implement lock before adding any new step.

---

### Minor: `--continue-on-error` Can Produce a QC Digest Based on Stale Data

**What goes wrong:** The orchestrator's `--continue-on-error` flag means a failing stats
runner does not stop the refresh. If the QC digest report is the final step, and it reads
from stats tables that were not refreshed (because a preceding step failed), it will
produce a report based on yesterday's data with no indication that the data is stale.

**Why it happens:** `print_combined_summary()` in `run_daily_refresh.py` reports the
failure, but the QC digest script does not receive that signal — it is a separate subprocess
that reads directly from the database.

**Prevention:**
- The QC digest step must query each stats table's `ingested_at` watermark as its first
  operation and flag any table that was not refreshed within the expected window before
  generating any output.
- Alternatively: the QC digest subprocess should only be invoked if `all_success=True`
  from the orchestrator — do not run it under `--continue-on-error` without this guard.

**Phase:** Orchestrator wiring phase. Build staleness check into QC digest as a precondition, not an afterthought.

---

## Phase-Specific Warnings Summary

| Phase Topic | Likely Pitfall | Mitigation |
|---|---|---|
| Alembic baseline migration | Autogenerate recreates all 50 tables | Write no-op baseline by hand; no `--autogenerate` until ORM models exist |
| Alembic SQL file conversion | Wrong application order corrupts fresh-deploy schema | Reconstruct order from `git log` before assigning revision IDs |
| Alembic on Windows | Path mixing, UTF-8 SQL comments | Use `%(here)s`, `encoding='utf-8'` in `env.py`, validate in CI |
| mypy initial enforcement | Thousands of errors on first global run | Scope to `features` and `regimes` only; suppress library stubs first |
| mypy + pandas/vectorbt | Stub install breaks numpy, corrupts backtest numerics | Stubs in `dev` group only; run backtest smoke test after install |
| Ruff blocking | Removing `|| true` blocks all open PRs | Achieve zero violations first; remove flag in a separate PR |
| Ruff version drift | CI uses newer ruff with new rules | Pin to `ruff==0.9.*` before removing `|| true` |
| Docs version strings | Three files, three different versions (already the case) | Update `pyproject.toml` first; add CI version-consistency check |
| mkdocs nav | Missing files break `mkdocs build` immediately | Run `mkdocs build --strict` before merging any docs PR |
| Subprocess timeout | New stats runner hangs, blocks orchestrator overnight | Add `timeout=` to all existing calls before adding new steps |
| Refresh pipeline runtime | 5 serial runners push past 24h window | Profile each runner; add parallelism or lockfile before wiring |
| QC digest under continue-on-error | Digest reports success on stale data | Add `ingested_at` staleness check as first operation in digest |

---

## Sources

- [Alembic autogenerate documentation](https://alembic.sqlalchemy.org/en/latest/autogenerate.html) — HIGH confidence (official docs)
- [Alembic cookbook: building from scratch](https://alembic.sqlalchemy.org/en/latest/cookbook.html) — HIGH confidence (official docs)
- [Alembic Discussion #1425: Existing PostgreSQL DB bootstrapping](https://github.com/sqlalchemy/alembic/discussions/1425) — MEDIUM confidence (community discussion verified against official docs)
- [Alembic Discussion #887: Paths and environment organization](https://github.com/sqlalchemy/alembic/discussions/887) — MEDIUM confidence
- [Alembic Issue #590: Windows path mixing in script_location](https://github.com/sqlalchemy/alembic/issues/590) — HIGH confidence (issue tracker)
- [mypy: Using mypy with an existing codebase](https://mypy.readthedocs.io/en/stable/existing_code.html) — HIGH confidence (official docs)
- [mypy: Common issues and solutions](https://mypy.readthedocs.io/en/stable/common_issues.html) — HIGH confidence (official docs)
- [Quantlane: Type-checking a large Python codebase](https://quantlane.com/blog/type-checking-large-codebase/) — MEDIUM confidence (engineering blog, consistent with official docs)
- [Airbus: Python code quality with Ruff, one step at a time](https://cyber.airbus.com/en/newsroom/stories/2025-10-python-code-quality-with-ruff-one-step-at-a-time-part-1) — MEDIUM confidence (industry engineering blog)
- [CPython issue #88693: subprocess.run gets stuck on Windows](https://github.com/python/cpython/issues/88693) — HIGH confidence (CPython tracker)
- [CPython issue #87512: subprocess timeout ignored on Windows with capture_output](https://bugs.python.org/issue87512) — HIGH confidence (CPython tracker)
- [pandas-stubs PyPI](https://pypi.org/project/pandas-stubs/) — HIGH confidence (official package page)
- [mypy issue #17852: install-types breaks numpy version dependencies](https://github.com/python/mypy/issues/17852) — MEDIUM confidence (mypy issue tracker)
- Codebase direct inspection: `pyproject.toml`, `.github/workflows/ci.yml`, `mkdocs.yml`,
  `README.md`, `run_daily_refresh.py`, `sql/migration/` directory, subprocess call audit — HIGH confidence (observed directly)
