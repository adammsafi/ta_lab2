from fedtools2.etl import _load_config, build_dataset

def test_build_dataset_smoke():
    cfg = _load_config(None)
    df = build_dataset(cfg)
    assert "TARGET_MID" in df.columns
    assert "FEDFUNDS" in df.columns
    assert df.index.is_monotonic_increasing