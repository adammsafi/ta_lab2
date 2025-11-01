from pathlib import Path
from ta_lab2.config import load_settings, project_root

def test_config_loads_default():
    root = project_root()
    cfg = load_settings(root / "configs" / "default.yaml")
    assert (root / cfg.data_csv).exists(), "CSV path in config should exist"
