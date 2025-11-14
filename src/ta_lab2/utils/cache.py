# src/ta_lab2/utils/cache.py
from pathlib import Path
import hashlib
import json

# Soft import: allow importing ta_lab2.utils.cache even if joblib is missing.
try:
    import joblib
except ImportError:  # pragma: no cover
    joblib = None  # type: ignore[assignment]

CACHE_DIR = Path("artifacts/cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _ensure_joblib_available() -> None:
    """
    Raise a clear error if joblib is not installed.

    Importing this module should not require joblib, but actually *using*
    disk_cache does, so we check here.
    """
    if joblib is None:
        raise ImportError(
            "joblib is required for ta_lab2.utils.cache.disk_cache. "
            "Please `pip install joblib` to use these caching utilities."
        )


def _key(name, params):
    blob = json.dumps(params, sort_keys=True).encode()
    return f"{name}_{hashlib.md5(blob).hexdigest()}.joblib"


def disk_cache(name, compute_fn, **params):
    """
    Simple disk-backed cache using joblib.

    Parameters
    ----------
    name : str
        Logical cache name (becomes part of the filename).
    compute_fn : callable
        Function to compute the value if not cached.
    **params :
        Parameters that define the cache key and are passed to compute_fn.

    Returns
    -------
    Any
        Cached or freshly computed result.
    """
    _ensure_joblib_available()

    path = CACHE_DIR / _key(name, params)
    if path.exists():
        return joblib.load(path)
    out = compute_fn(**params)
    joblib.dump(out, path)
    return out
