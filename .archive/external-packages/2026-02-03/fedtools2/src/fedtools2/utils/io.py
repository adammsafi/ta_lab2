# -*- coding: utf-8 -*-
"""Small IO helpers for loading/saving."""

from pathlib import Path
import pandas as pd
import os
import yaml

import os
import yaml
from dotenv import load_dotenv


def load_config() -> dict:
    """
    Load configuration from default.yaml, overridden by private.yaml if present.
    Also loads DB credentials from db_config.env if present in project root.
    """
    base_path = "src/fedtools2/config"
    priv = os.path.join(base_path, "private.yaml")
    default = os.path.join(base_path, "default.yaml")

    # ✅ NEW: load db_config.env if it exists
    env_file = "db_config.env"
    if os.path.exists(env_file):
        load_dotenv(env_file)
        print(f"🔑 Loaded environment variables from {env_file}")
    else:
        # fallback to .env if someone renames it
        if os.path.exists(".env"):
            load_dotenv(".env")
            print("🔑 Loaded environment variables from .env")

    # Load default YAML config
    with open(default, "r") as f:
        cfg = yaml.safe_load(f)

    # Merge private.yaml if exists
    if os.path.exists(priv):
        with open(priv, "r") as f:
            priv_cfg = yaml.safe_load(f)
        cfg.update(priv_cfg)

    print(f"🔧 Loaded configuration from {priv if os.path.exists(priv) else default}")
    return cfg


def read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    return df

def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)