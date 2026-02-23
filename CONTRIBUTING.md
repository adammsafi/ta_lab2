# Contributing to ta_lab2

Thanks for helping build the quant stack.

## Dev setup

- Python 3.12 recommended.
- Create a virtualenv and install in editable mode:

  ```bash
  pip install -e ".[dev]"

## Branch & commit style

Branches should describe the kind of change and the area they touch.

Use this pattern:

- feature/<area>-<short-description>
- fix/<area>-<short-description>
- chore/<area>-<short-description>

Examples:

- feature/pipeline-btc-daily-ingest
- fix/db-null-timeopen
- chore/docs-readme-cleanup

Commit messages should be short, clear, and in the imperative mood
(as if you’re giving an instruction):

- ✅ "add ema feature registry"
- ✅ "fix cmc history type mismatch"
- ✅ "update project automation docs"

Avoid:

- ❌ "fixed stuff"
- ❌ "final commit"
- ❌ "lol oops"

If a commit closes an issue, mention it in the body:

- `Fix type mismatch for circulatingsupply. Closes #23.`


## Code style & expectations

- Python version: 3.12 (match the repo’s `pyproject.toml` / tooling).
- Follow PEP 8 style unless there’s an existing local convention.
- Prefer small, composable functions over giant scripts.
- Add docstrings for any public function, class, or module that’s part of the ta_lab2 “surface area”.
- Keep business logic out of CLI code – CLI should call into library functions in `src/ta_lab2/`.

If you touch existing code, try to leave it a little cleaner than you found it.


## Tests

- Put tests under `tests/` mirroring the module path when possible.
- If you add a new feature, add at least one test that fails without your change and passes with it.
- If you fix a bug, add a regression test that would have caught it.

Before opening a PR:

- Run the test suite: `pytest`
- Run linting and formatting: `ruff check src/ --fix && ruff format src/`


## Opening a pull request

When you open a PR:

- Use a clear title, e.g. `Add BTC daily ingest pipeline` or `Fix cmc_price_histories type mismatch`.
- In the description, include:
  - What the change does
  - Any relevant issue numbers (e.g. `Closes #12`)
  - Notes on testing: how you verified it works (commands, datasets, etc.)

Small PRs are easier to review than giant ones. If something is big,
try to split it into a series (e.g., “1/3: package layout”, “2/3: add EMA features”).


## Security & secrets

- Never commit API keys, database passwords, or private URLs.
- Use `.env` files or GitHub Actions secrets instead.
- If you accidentally commit a secret, rotate it immediately and then
  open an issue or note in the PR so it can be cleaned up.

If you find a security issue that might expose real infrastructure or data,
do **not** open a public issue. Contact the maintainer privately instead.


## Schema Migrations (Alembic)

All schema changes (new tables, new columns, index changes) must go through Alembic revisions.
Never apply raw SQL directly to the production DB for schema changes.

### Quick reference: 5-step workflow

```bash
# 1. Create revision file (before writing any SQL)
alembic revision -m "add_foo_to_bar"

# 2. Edit upgrade() and downgrade() in the generated file
#    alembic/versions/<rev>_add_foo_to_bar.py

# 3. Commit the revision file
git add alembic/versions/<rev>_add_foo_to_bar.py
git commit -m "feat: add foo to bar"

# 4. Apply on the live DB
alembic upgrade head

# 5. Verify
alembic current
```

### Conventions

- **Write all revisions by hand** — never use `--autogenerate` (see Gotchas below).
- **Always implement `downgrade()`** — even if it is just `pass` with a comment explaining why
  rollback is unsafe. `alembic downgrade -1` is the emergency rollback command.
- **Use descriptive slugs** in revision messages — e.g., `add_is_outlier_to_cmc_vol`,
  `drop_legacy_ema_columns_from_features`. Avoid generic slugs like `fix` or `update`.
- **Run from project root** — `alembic.ini` must be in the current working directory.
  Use `alembic -c /path/to/alembic.ini` if running from elsewhere.

### Gotchas

**1. Never use `--autogenerate`**

Without ORM models, `--autogenerate` compares the live DB against an empty SQLAlchemy
`MetaData` object. It sees 50+ existing tables as "missing" and generates `op.create_table()`
for all of them. Running `alembic upgrade head` on such a revision would attempt to recreate
tables that already exist, causing errors. `target_metadata = None` in `alembic/env.py`
permanently disables this. Never change it.

Warning sign: a generated revision file that contains `op.create_table()` calls.

**2. Windows encoding: always use `encoding='utf-8'`**

`alembic/env.py` already calls `fileConfig(..., encoding="utf-8")` to prevent
`UnicodeDecodeError` when `alembic.ini` is opened on Windows (default encoding is `cp1252`
which cannot decode UTF-8 box-drawing characters). If you open SQL files inside a migration
script, always pass `encoding='utf-8'` explicitly.

**3. CWD matters**

Run all alembic commands from the project root where `alembic.ini` lives:

```bash
# Correct (from project root):
alembic history
alembic upgrade head

# Also correct (explicit config path):
alembic -c /path/to/alembic.ini upgrade head

# Wrong (from a subdirectory — alembic.ini not found):
cd alembic && alembic upgrade head  # FAILS
```

**4. `stamp` vs `upgrade` — use the right command**

- `alembic stamp head` — records where the DB is **now** without executing any SQL.
  Use only during initial setup or disaster recovery (when the schema already matches head).
- `alembic upgrade head` — runs all pending migration scripts.
  Use for every new revision after the initial bootstrap.

Mixing these up is safe (the baseline is a no-op), but semantically confusing.

### Historical migrations

Before Alembic was adopted (as of 2026-02-23), 17 raw SQL files were applied directly.
These are cataloged in [`sql/migration/CATALOG.md`](sql/migration/CATALOG.md) for reference.
Do not re-apply them — they are already in the live DB and the Alembic baseline revision
(`25f2b3c90f65`) records their cumulative state.
