"""
ExchangeConfig dataclass for credential management and environment switching.

Supports per-exchange .env files (e.g., coinbase.env, kraken.env).
No dependency on python-dotenv -- parses dotenv-style files manually.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal


@dataclass
class ExchangeConfig:
    """
    Configuration for a single exchange connection.

    Fields
    ------
    venue : str
        Exchange name, e.g. 'coinbase', 'kraken'.
    environment : Literal['sandbox', 'production']
        Target environment. 'sandbox' routes to testnet/paper endpoints.
    api_key : str
        API key credential (empty string if not yet loaded).
    api_secret : str
        API secret credential (empty string if not yet loaded).
    passphrase : str
        Optional passphrase (required by Coinbase Advanced Trade).
    env_file : str
        Path to the .env file that credentials were loaded from, or empty
        string if credentials were provided directly.
    """

    venue: str
    environment: Literal["sandbox", "production"] = "sandbox"
    api_key: str = ""
    api_secret: str = ""
    passphrase: str = ""
    env_file: str = ""

    # ------------------------------------------------------------------ #
    # Properties                                                           #
    # ------------------------------------------------------------------ #

    @property
    def is_sandbox(self) -> bool:
        """Return True when targeting a testnet / sandbox endpoint."""
        return self.environment == "sandbox"

    # ------------------------------------------------------------------ #
    # Validation                                                           #
    # ------------------------------------------------------------------ #

    def validate(self) -> None:
        """
        Raise ValueError if required credentials are missing.

        Checks api_key and api_secret are non-empty strings.
        Does NOT make a live network call; call a lightweight exchange
        endpoint separately to confirm connectivity/permissions.

        Raises
        ------
        ValueError
            When api_key or api_secret is empty or contains only whitespace.
        """
        if not self.api_key or not self.api_key.strip():
            raise ValueError(
                f"ExchangeConfig for '{self.venue}': api_key is missing or empty. "
                "Load credentials via from_env_file() or set api_key directly."
            )
        if not self.api_secret or not self.api_secret.strip():
            raise ValueError(
                f"ExchangeConfig for '{self.venue}': api_secret is missing or empty. "
                "Load credentials via from_env_file() or set api_secret directly."
            )

    # ------------------------------------------------------------------ #
    # Factory                                                              #
    # ------------------------------------------------------------------ #

    @classmethod
    def from_env_file(
        cls,
        venue: str,
        env_file: str,
        environment: Literal["sandbox", "production"] = "sandbox",
    ) -> "ExchangeConfig":
        """
        Load credentials from a dotenv-style .env file.

        The file is parsed line-by-line. Lines beginning with '#' (after
        stripping leading whitespace) and blank lines are skipped.
        Each remaining line is split on the first '=' character; the value
        is stripped of surrounding whitespace and optional surrounding
        single/double quotes.

        Well-known keys loaded (case-insensitive match against uppercased
        key names):
            API_KEY       -> api_key
            API_SECRET    -> api_secret
            PASSPHRASE    -> passphrase
            ENVIRONMENT   -> environment (overrides the parameter if present)

        Parameters
        ----------
        venue : str
            Exchange name (stored as-is; used only for error messages).
        env_file : str
            Absolute or relative path to the .env file.
        environment : Literal['sandbox', 'production']
            Default environment; overridden if ENVIRONMENT key found in file.

        Returns
        -------
        ExchangeConfig
            Populated config instance.

        Raises
        ------
        FileNotFoundError
            When env_file does not exist.
        """
        path = os.path.abspath(env_file)
        if not os.path.isfile(path):
            raise FileNotFoundError(
                f"ExchangeConfig.from_env_file: file not found: {path!r}"
            )

        parsed: dict[str, str] = {}
        with open(path, encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key_raw, _, val_raw = line.partition("=")
                key = key_raw.strip().upper()
                val = val_raw.strip()
                # Strip optional surrounding quotes (single or double)
                if len(val) >= 2 and val[0] in ('"', "'") and val[-1] == val[0]:
                    val = val[1:-1]
                parsed[key] = val

        api_key = parsed.get("API_KEY", "")
        api_secret = parsed.get("API_SECRET", "")
        passphrase = parsed.get("PASSPHRASE", "")

        # Allow env file to override the environment parameter
        env_override = parsed.get("ENVIRONMENT", "").lower()
        if env_override in ("sandbox", "production"):
            environment = env_override  # type: ignore[assignment]

        return cls(
            venue=venue,
            environment=environment,
            api_key=api_key,
            api_secret=api_secret,
            passphrase=passphrase,
            env_file=path,
        )

    # ------------------------------------------------------------------ #
    # Representation                                                       #
    # ------------------------------------------------------------------ #

    def __repr__(self) -> str:
        key_masked = (
            f"{self.api_key[:4]}***"
            if len(self.api_key) >= 4
            else ("***" if self.api_key else "<empty>")
        )
        return (
            f"ExchangeConfig(venue={self.venue!r}, "
            f"environment={self.environment!r}, "
            f"api_key={key_masked!r}, "
            f"is_sandbox={self.is_sandbox})"
        )
