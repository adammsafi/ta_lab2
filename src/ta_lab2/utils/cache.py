# src/ta_lab2/utils/cache.py
from pathlib import Path
import joblib, hashlib, json

CACHE_DIR = Path("artifacts/cache"); CACHE_DIR.mkdir(parents=True, exist_ok=True)

def _key(name, params):
    blob = json.dumps(params, sort_keys=True).encode()
    return f"{name}_{hashlib.md5(blob).hexdigest()}.joblib"

def disk_cache(name, compute_fn, **params):
    path = CACHE_DIR / _key(name, params)
    if path.exists():
        return joblib.load(path)
    out = compute_fn(**params)
    joblib.dump(out, path)
    return out
