"""
Unit tests for ExchangeConfig dataclass.

All tests are pure unit tests - no network calls, no database, no API keys.
Tests cover: defaults, validate() error cases, is_sandbox property,
from_env_file parsing (quotes, comments, blank lines, missing keys, missing file).
"""

import os
import pytest

from ta_lab2.connectivity.exchange_config import ExchangeConfig


# ---------------------------------------------------------------------------
# Defaults and construction
# ---------------------------------------------------------------------------


class TestExchangeConfigDefaults:
    def test_required_venue_field(self):
        cfg = ExchangeConfig(venue="coinbase")
        assert cfg.venue == "coinbase"

    def test_default_environment_is_sandbox(self):
        cfg = ExchangeConfig(venue="coinbase")
        assert cfg.environment == "sandbox"

    def test_default_credentials_are_empty(self):
        cfg = ExchangeConfig(venue="kraken")
        assert cfg.api_key == ""
        assert cfg.api_secret == ""
        assert cfg.passphrase == ""

    def test_default_env_file_is_empty(self):
        cfg = ExchangeConfig(venue="kraken")
        assert cfg.env_file == ""

    def test_explicit_production_environment(self):
        cfg = ExchangeConfig(venue="coinbase", environment="production")
        assert cfg.environment == "production"

    def test_explicit_credentials(self):
        cfg = ExchangeConfig(
            venue="coinbase", api_key="k1", api_secret="s1", passphrase="p1"
        )
        assert cfg.api_key == "k1"
        assert cfg.api_secret == "s1"
        assert cfg.passphrase == "p1"


# ---------------------------------------------------------------------------
# is_sandbox property
# ---------------------------------------------------------------------------


class TestIsSandbox:
    def test_is_sandbox_true_when_sandbox(self):
        cfg = ExchangeConfig(venue="coinbase", environment="sandbox")
        assert cfg.is_sandbox is True

    def test_is_sandbox_false_when_production(self):
        cfg = ExchangeConfig(venue="coinbase", environment="production")
        assert cfg.is_sandbox is False

    def test_is_sandbox_default_is_true(self):
        cfg = ExchangeConfig(venue="kraken")
        assert cfg.is_sandbox is True


# ---------------------------------------------------------------------------
# validate() error cases
# ---------------------------------------------------------------------------


class TestValidate:
    def test_validate_passes_with_valid_credentials(self):
        cfg = ExchangeConfig(venue="coinbase", api_key="mykey", api_secret="mysecret")
        cfg.validate()  # should not raise

    def test_validate_raises_when_api_key_empty(self):
        cfg = ExchangeConfig(venue="coinbase", api_key="", api_secret="mysecret")
        with pytest.raises(ValueError, match="api_key is missing or empty"):
            cfg.validate()

    def test_validate_raises_when_api_key_whitespace(self):
        cfg = ExchangeConfig(venue="coinbase", api_key="   ", api_secret="mysecret")
        with pytest.raises(ValueError, match="api_key is missing or empty"):
            cfg.validate()

    def test_validate_raises_when_api_secret_empty(self):
        cfg = ExchangeConfig(venue="coinbase", api_key="mykey", api_secret="")
        with pytest.raises(ValueError, match="api_secret is missing or empty"):
            cfg.validate()

    def test_validate_raises_when_api_secret_whitespace(self):
        cfg = ExchangeConfig(venue="coinbase", api_key="mykey", api_secret="  \t  ")
        with pytest.raises(ValueError, match="api_secret is missing or empty"):
            cfg.validate()

    def test_validate_error_message_includes_venue(self):
        cfg = ExchangeConfig(venue="kraken", api_key="", api_secret="secret")
        with pytest.raises(ValueError, match="kraken"):
            cfg.validate()

    def test_validate_raises_when_both_missing(self):
        cfg = ExchangeConfig(venue="coinbase")
        with pytest.raises(ValueError):
            cfg.validate()

    def test_validate_passphrase_not_required(self):
        """passphrase is optional - validate() should not complain when it's missing."""
        cfg = ExchangeConfig(
            venue="coinbase", api_key="mykey", api_secret="mysecret", passphrase=""
        )
        cfg.validate()  # should not raise


# ---------------------------------------------------------------------------
# from_env_file factory - basic parsing
# ---------------------------------------------------------------------------


class TestFromEnvFileBasicParsing:
    def test_loads_api_key_and_secret(self, tmp_path):
        env = tmp_path / "test.env"
        env.write_text("API_KEY=mykey\nAPI_SECRET=mysecret\n", encoding="utf-8")
        cfg = ExchangeConfig.from_env_file("coinbase", str(env))
        assert cfg.api_key == "mykey"
        assert cfg.api_secret == "mysecret"

    def test_loads_passphrase(self, tmp_path):
        env = tmp_path / "test.env"
        env.write_text("API_KEY=k\nAPI_SECRET=s\nPASSPHRASE=mypass\n", encoding="utf-8")
        cfg = ExchangeConfig.from_env_file("coinbase", str(env))
        assert cfg.passphrase == "mypass"

    def test_venue_stored_correctly(self, tmp_path):
        env = tmp_path / "test.env"
        env.write_text("API_KEY=k\nAPI_SECRET=s\n", encoding="utf-8")
        cfg = ExchangeConfig.from_env_file("kraken", str(env))
        assert cfg.venue == "kraken"

    def test_env_file_path_stored(self, tmp_path):
        env = tmp_path / "test.env"
        env.write_text("API_KEY=k\nAPI_SECRET=s\n", encoding="utf-8")
        cfg = ExchangeConfig.from_env_file("kraken", str(env))
        assert cfg.env_file == os.path.abspath(str(env))

    def test_default_environment_sandbox(self, tmp_path):
        env = tmp_path / "test.env"
        env.write_text("API_KEY=k\nAPI_SECRET=s\n", encoding="utf-8")
        cfg = ExchangeConfig.from_env_file("coinbase", str(env))
        assert cfg.environment == "sandbox"

    def test_environment_parameter_respected(self, tmp_path):
        env = tmp_path / "test.env"
        env.write_text("API_KEY=k\nAPI_SECRET=s\n", encoding="utf-8")
        cfg = ExchangeConfig.from_env_file(
            "coinbase", str(env), environment="production"
        )
        assert cfg.environment == "production"

    def test_environment_key_in_file_overrides_parameter(self, tmp_path):
        env = tmp_path / "test.env"
        env.write_text(
            "API_KEY=k\nAPI_SECRET=s\nENVIRONMENT=production\n", encoding="utf-8"
        )
        cfg = ExchangeConfig.from_env_file("coinbase", str(env), environment="sandbox")
        assert cfg.environment == "production"

    def test_environment_sandbox_in_file(self, tmp_path):
        env = tmp_path / "test.env"
        env.write_text(
            "API_KEY=k\nAPI_SECRET=s\nENVIRONMENT=sandbox\n", encoding="utf-8"
        )
        cfg = ExchangeConfig.from_env_file(
            "coinbase", str(env), environment="production"
        )
        assert cfg.environment == "sandbox"

    def test_keys_are_case_insensitive(self, tmp_path):
        """Keys should be normalised to uppercase for matching."""
        env = tmp_path / "test.env"
        env.write_text("api_key=mykey\napi_secret=mysecret\n", encoding="utf-8")
        cfg = ExchangeConfig.from_env_file("coinbase", str(env))
        assert cfg.api_key == "mykey"
        assert cfg.api_secret == "mysecret"


# ---------------------------------------------------------------------------
# from_env_file factory - quote stripping
# ---------------------------------------------------------------------------


class TestFromEnvFileQuoteStripping:
    def test_strips_double_quotes(self, tmp_path):
        env = tmp_path / "test.env"
        env.write_text('API_KEY="mykey"\nAPI_SECRET="mysecret"\n', encoding="utf-8")
        cfg = ExchangeConfig.from_env_file("coinbase", str(env))
        assert cfg.api_key == "mykey"
        assert cfg.api_secret == "mysecret"

    def test_strips_single_quotes(self, tmp_path):
        env = tmp_path / "test.env"
        env.write_text("API_KEY='mykey'\nAPI_SECRET='mysecret'\n", encoding="utf-8")
        cfg = ExchangeConfig.from_env_file("coinbase", str(env))
        assert cfg.api_key == "mykey"
        assert cfg.api_secret == "mysecret"

    def test_unquoted_values_unmodified(self, tmp_path):
        env = tmp_path / "test.env"
        env.write_text(
            "API_KEY=plain-value\nAPI_SECRET=anothersecret\n", encoding="utf-8"
        )
        cfg = ExchangeConfig.from_env_file("coinbase", str(env))
        assert cfg.api_key == "plain-value"

    def test_mismatched_quotes_not_stripped(self, tmp_path):
        """Value like "mykey' (mismatched) should not be stripped."""
        env = tmp_path / "test.env"
        env.write_text("API_KEY=\"mykey'\nAPI_SECRET=s\n", encoding="utf-8")
        cfg = ExchangeConfig.from_env_file("coinbase", str(env))
        # Mismatched quotes: should remain as-is
        assert '"' in cfg.api_key or "'" in cfg.api_key

    def test_value_with_equals_sign(self, tmp_path):
        """Value containing '=' should be handled: partition splits on first '=' only."""
        env = tmp_path / "test.env"
        env.write_text("API_KEY=a=b=c\nAPI_SECRET=s\n", encoding="utf-8")
        cfg = ExchangeConfig.from_env_file("coinbase", str(env))
        assert cfg.api_key == "a=b=c"


# ---------------------------------------------------------------------------
# from_env_file factory - comments and blank lines
# ---------------------------------------------------------------------------


class TestFromEnvFileCommentsAndBlanks:
    def test_comment_lines_skipped(self, tmp_path):
        env = tmp_path / "test.env"
        env.write_text(
            "# This is a comment\nAPI_KEY=mykey\n# Another comment\nAPI_SECRET=mysecret\n",
            encoding="utf-8",
        )
        cfg = ExchangeConfig.from_env_file("coinbase", str(env))
        assert cfg.api_key == "mykey"

    def test_blank_lines_skipped(self, tmp_path):
        env = tmp_path / "test.env"
        env.write_text(
            "\n\nAPI_KEY=mykey\n\n\nAPI_SECRET=mysecret\n\n",
            encoding="utf-8",
        )
        cfg = ExchangeConfig.from_env_file("coinbase", str(env))
        assert cfg.api_key == "mykey"
        assert cfg.api_secret == "mysecret"

    def test_inline_comment_is_part_of_value(self, tmp_path):
        """Lines like 'API_KEY=value # comment' — the comment is part of the value."""
        env = tmp_path / "test.env"
        env.write_text(
            "API_KEY=mykey # inline comment\nAPI_SECRET=s\n", encoding="utf-8"
        )
        cfg = ExchangeConfig.from_env_file("coinbase", str(env))
        # The value includes the inline comment (no inline-comment stripping)
        assert cfg.api_key.startswith("mykey")

    def test_lines_without_equals_skipped(self, tmp_path):
        env = tmp_path / "test.env"
        env.write_text(
            "SOMEKEY_NO_EQUALS\nAPI_KEY=mykey\nAPI_SECRET=s\n", encoding="utf-8"
        )
        cfg = ExchangeConfig.from_env_file("coinbase", str(env))
        assert cfg.api_key == "mykey"

    def test_full_env_file_with_comments_and_blanks(self, tmp_path):
        content = (
            "# Coinbase API credentials\n"
            "\n"
            "API_KEY=orgid/keyid/abc123\n"
            "API_SECRET=-----BEGIN EC PRIVATE KEY-----\n"
            "PASSPHRASE=topsecret\n"
            "# Production endpoint\n"
            "ENVIRONMENT=production\n"
        )
        env = tmp_path / "coinbase.env"
        env.write_text(content, encoding="utf-8")
        cfg = ExchangeConfig.from_env_file("coinbase", str(env))
        assert cfg.api_key == "orgid/keyid/abc123"
        assert cfg.passphrase == "topsecret"
        assert cfg.environment == "production"


# ---------------------------------------------------------------------------
# from_env_file factory - missing file
# ---------------------------------------------------------------------------


class TestFromEnvFileMissing:
    def test_raises_file_not_found_on_missing_file(self, tmp_path):
        missing = str(tmp_path / "nonexistent.env")
        with pytest.raises(FileNotFoundError, match="file not found"):
            ExchangeConfig.from_env_file("coinbase", missing)

    def test_error_message_includes_path(self, tmp_path):
        missing = str(tmp_path / "nonexistent.env")
        with pytest.raises(FileNotFoundError) as exc_info:
            ExchangeConfig.from_env_file("coinbase", missing)
        assert "nonexistent.env" in str(exc_info.value)


# ---------------------------------------------------------------------------
# from_env_file - missing credentials remain empty
# ---------------------------------------------------------------------------


class TestFromEnvFileMissingKeys:
    def test_missing_api_key_defaults_empty(self, tmp_path):
        env = tmp_path / "test.env"
        env.write_text("API_SECRET=s\n", encoding="utf-8")
        cfg = ExchangeConfig.from_env_file("coinbase", str(env))
        assert cfg.api_key == ""

    def test_missing_api_secret_defaults_empty(self, tmp_path):
        env = tmp_path / "test.env"
        env.write_text("API_KEY=k\n", encoding="utf-8")
        cfg = ExchangeConfig.from_env_file("coinbase", str(env))
        assert cfg.api_secret == ""

    def test_missing_passphrase_defaults_empty(self, tmp_path):
        env = tmp_path / "test.env"
        env.write_text("API_KEY=k\nAPI_SECRET=s\n", encoding="utf-8")
        cfg = ExchangeConfig.from_env_file("coinbase", str(env))
        assert cfg.passphrase == ""


# ---------------------------------------------------------------------------
# __repr__
# ---------------------------------------------------------------------------


class TestRepr:
    def test_repr_masks_api_key_after_4_chars(self):
        cfg = ExchangeConfig(venue="coinbase", api_key="abcdefgh", api_secret="s")
        r = repr(cfg)
        assert "abcd***" in r

    def test_repr_shows_empty_when_no_key(self):
        cfg = ExchangeConfig(venue="coinbase")
        r = repr(cfg)
        assert "<empty>" in r

    def test_repr_shows_venue_and_environment(self):
        cfg = ExchangeConfig(venue="kraken", environment="production")
        r = repr(cfg)
        assert "kraken" in r
        assert "production" in r
