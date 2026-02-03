import requests

BASE = "https://api.stlouisfed.org/fred"


def get_releases(api_key: str, limit=10000):
    r = requests.get(
        f"{BASE}/releases",
        params={"api_key": api_key, "file_type": "json", "limit": limit},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if "releases" not in data:
        raise RuntimeError(f"no 'releases' in payload: {data}")
    return data["releases"]


def get_series_observations(api_key: str, series_id: str, observation_start=None):
    params = {"api_key": api_key, "series_id": series_id, "file_type": "json"}
    if observation_start:
        params["observation_start"] = observation_start
    r = requests.get(f"{BASE}/series/observations", params=params, timeout=30)
    r.raise_for_status()
    return r.json().get("observations", [])
