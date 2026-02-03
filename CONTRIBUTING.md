# Contributing to ta_lab2

Thanks for helping build the quant stack.

## Dev setup

- Python 3.11 recommended.
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

- Python version: 3.11 (match the repo’s `pyproject.toml` / tooling).
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
- If we add linters/formatters later (e.g., `ruff`, `black`), run those too.


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
