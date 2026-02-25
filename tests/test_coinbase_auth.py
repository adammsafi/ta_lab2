"""
Unit tests for Coinbase Advanced Trade JWT authentication.

All tests use mocks - no live API calls, no credentials, no network.
Tests cover: JWT structure (mocked jwt.encode), sandbox vs production host,
Bearer Authorization header, AuthenticationError when credentials missing,
ExchangeConfig integration.
"""

from unittest.mock import MagicMock, patch

import pytest

from ta_lab2.connectivity.coinbase import BASE_HOST, SANDBOX_HOST, CoinbaseExchange
from ta_lab2.connectivity.exceptions import AuthenticationError
from ta_lab2.connectivity.exchange_config import ExchangeConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_KEY = "organizations/abc/apiKeys/xyz"
FAKE_PEM = "-----BEGIN EC PRIVATE KEY-----\nfakepem\n-----END EC PRIVATE KEY-----"


def make_exchange(api_key=FAKE_KEY, api_secret=FAKE_PEM, sandbox=False):
    """Build a CoinbaseExchange with provided credentials."""
    cfg = ExchangeConfig(
        venue="coinbase",
        environment="sandbox" if sandbox else "production",
        api_key=api_key,
        api_secret=api_secret,
    )
    return CoinbaseExchange(config=cfg)


# ---------------------------------------------------------------------------
# Host selection (sandbox vs production)
# ---------------------------------------------------------------------------


class TestHostSelection:
    def test_production_host_used_when_not_sandbox(self):
        ex = make_exchange(sandbox=False)
        assert BASE_HOST in ex.base_url
        assert SANDBOX_HOST not in ex.base_url

    def test_sandbox_host_used_when_sandbox(self):
        ex = make_exchange(sandbox=True)
        assert SANDBOX_HOST in ex.base_url

    def test_default_without_config_uses_production_host(self):
        ex = CoinbaseExchange(api_key=FAKE_KEY, api_secret=FAKE_PEM)
        assert BASE_HOST in ex.base_url


# ---------------------------------------------------------------------------
# JWT structure tests
# ---------------------------------------------------------------------------


class TestBuildJwt:
    def _make_mock_private_key(self):
        return MagicMock(name="ec_private_key")

    def test_jwt_encode_called_with_es256_algorithm(self):
        ex = make_exchange()
        mock_key = self._make_mock_private_key()

        with (
            patch(
                "ta_lab2.connectivity.coinbase.load_pem_private_key",
                return_value=mock_key,
            ),
            patch(
                "ta_lab2.connectivity.coinbase.jwt.encode", return_value="tok"
            ) as mock_encode,
        ):
            ex._build_jwt("GET", "/api/v3/brokerage/accounts")
            call_kwargs = mock_encode.call_args
            assert (
                call_kwargs.kwargs.get("algorithm") == "ES256"
                or call_kwargs.args[2] == "ES256"
            )

    def test_jwt_payload_contains_sub_as_api_key(self):
        ex = make_exchange(api_key=FAKE_KEY)
        mock_key = self._make_mock_private_key()

        captured_payload = {}

        def capture_encode(payload, *args, **kwargs):
            captured_payload.update(payload)
            return "token"

        with (
            patch(
                "ta_lab2.connectivity.coinbase.load_pem_private_key",
                return_value=mock_key,
            ),
            patch(
                "ta_lab2.connectivity.coinbase.jwt.encode", side_effect=capture_encode
            ),
        ):
            ex._build_jwt("GET", "/api/v3/brokerage/accounts")

        assert captured_payload["sub"] == FAKE_KEY

    def test_jwt_payload_contains_iss_cdp(self):
        ex = make_exchange()
        mock_key = self._make_mock_private_key()
        captured_payload = {}

        def capture_encode(payload, *args, **kwargs):
            captured_payload.update(payload)
            return "token"

        with (
            patch(
                "ta_lab2.connectivity.coinbase.load_pem_private_key",
                return_value=mock_key,
            ),
            patch(
                "ta_lab2.connectivity.coinbase.jwt.encode", side_effect=capture_encode
            ),
        ):
            ex._build_jwt("GET", "/api/v3/brokerage/accounts")

        assert captured_payload["iss"] == "cdp"

    def test_jwt_payload_contains_uri_with_method_and_host(self):
        ex = make_exchange()
        mock_key = self._make_mock_private_key()
        captured_payload = {}

        def capture_encode(payload, *args, **kwargs):
            captured_payload.update(payload)
            return "token"

        with (
            patch(
                "ta_lab2.connectivity.coinbase.load_pem_private_key",
                return_value=mock_key,
            ),
            patch(
                "ta_lab2.connectivity.coinbase.jwt.encode", side_effect=capture_encode
            ),
        ):
            ex._build_jwt("GET", "/api/v3/brokerage/accounts")

        uri = captured_payload["uri"]
        assert "GET" in uri
        assert BASE_HOST in uri
        assert "/api/v3/brokerage/accounts" in uri

    def test_jwt_payload_exp_greater_than_nbf(self):
        ex = make_exchange()
        mock_key = self._make_mock_private_key()
        captured_payload = {}

        def capture_encode(payload, *args, **kwargs):
            captured_payload.update(payload)
            return "token"

        with (
            patch(
                "ta_lab2.connectivity.coinbase.load_pem_private_key",
                return_value=mock_key,
            ),
            patch(
                "ta_lab2.connectivity.coinbase.jwt.encode", side_effect=capture_encode
            ),
        ):
            ex._build_jwt("POST", "/api/v3/brokerage/orders")

        assert captured_payload["exp"] > captured_payload["nbf"]

    def test_jwt_headers_contain_kid_as_api_key(self):
        ex = make_exchange(api_key=FAKE_KEY)
        mock_key = self._make_mock_private_key()
        captured_headers = {}

        def capture_encode(payload, key, algorithm, headers=None):
            if headers:
                captured_headers.update(headers)
            return "token"

        with (
            patch(
                "ta_lab2.connectivity.coinbase.load_pem_private_key",
                return_value=mock_key,
            ),
            patch(
                "ta_lab2.connectivity.coinbase.jwt.encode", side_effect=capture_encode
            ),
        ):
            ex._build_jwt("GET", "/api/v3/brokerage/accounts")

        assert captured_headers.get("kid") == FAKE_KEY

    def test_jwt_headers_contain_nonce(self):
        ex = make_exchange()
        mock_key = self._make_mock_private_key()
        captured_headers = {}

        def capture_encode(payload, key, algorithm, headers=None):
            if headers:
                captured_headers.update(headers)
            return "token"

        with (
            patch(
                "ta_lab2.connectivity.coinbase.load_pem_private_key",
                return_value=mock_key,
            ),
            patch(
                "ta_lab2.connectivity.coinbase.jwt.encode", side_effect=capture_encode
            ),
        ):
            ex._build_jwt("GET", "/api/v3/brokerage/accounts")

        assert "nonce" in captured_headers
        assert len(captured_headers["nonce"]) > 0

    def test_jwt_nonce_is_unique_per_call(self):
        ex = make_exchange()
        mock_key = self._make_mock_private_key()
        nonces = []

        def capture_encode(payload, key, algorithm, headers=None):
            if headers and "nonce" in headers:
                nonces.append(headers["nonce"])
            return "token"

        with (
            patch(
                "ta_lab2.connectivity.coinbase.load_pem_private_key",
                return_value=mock_key,
            ),
            patch(
                "ta_lab2.connectivity.coinbase.jwt.encode", side_effect=capture_encode
            ),
        ):
            ex._build_jwt("GET", "/api/v3/brokerage/accounts")
            ex._build_jwt("GET", "/api/v3/brokerage/accounts")

        assert nonces[0] != nonces[1], "Nonces should be unique per JWT"

    def test_load_pem_private_key_called_with_secret_bytes(self):
        ex = make_exchange(api_secret=FAKE_PEM)
        mock_key = self._make_mock_private_key()

        with (
            patch(
                "ta_lab2.connectivity.coinbase.load_pem_private_key",
                return_value=mock_key,
            ) as mock_load,
            patch("ta_lab2.connectivity.coinbase.jwt.encode", return_value="tok"),
        ):
            ex._build_jwt("GET", "/path")
            call_args = mock_load.call_args
            pem_bytes = (
                call_args.args[0] if call_args.args else call_args.kwargs.get("data")
            )
            assert isinstance(pem_bytes, bytes)
            assert pem_bytes == FAKE_PEM.encode("utf-8")


# ---------------------------------------------------------------------------
# AuthenticationError when credentials missing
# ---------------------------------------------------------------------------


class TestAuthenticationErrors:
    def test_build_jwt_raises_when_api_key_empty(self):
        ex = CoinbaseExchange(api_key="", api_secret=FAKE_PEM)
        with pytest.raises(AuthenticationError):
            ex._build_jwt("GET", "/path")

    def test_build_jwt_raises_when_api_secret_empty(self):
        ex = CoinbaseExchange(api_key=FAKE_KEY, api_secret="")
        with pytest.raises(AuthenticationError):
            ex._build_jwt("GET", "/path")

    def test_build_jwt_raises_when_both_empty(self):
        ex = CoinbaseExchange()
        with pytest.raises(AuthenticationError):
            ex._build_jwt("GET", "/path")

    def test_build_jwt_raises_authentication_error_on_invalid_pem(self):
        """If load_pem_private_key raises, _build_jwt should raise AuthenticationError."""
        ex = make_exchange(api_secret="not-valid-pem")
        with pytest.raises(AuthenticationError, match="failed to load EC private key"):
            ex._build_jwt("GET", "/path")


# ---------------------------------------------------------------------------
# Bearer Authorization header in authenticated request
# ---------------------------------------------------------------------------


class TestAuthenticatedRequestHeader:
    def test_bearer_token_in_authorization_header(self):
        ex = make_exchange()
        mock_key = MagicMock()

        mock_response = MagicMock()
        mock_response.json.return_value = {"accounts": []}

        with (
            patch(
                "ta_lab2.connectivity.coinbase.load_pem_private_key",
                return_value=mock_key,
            ),
            patch(
                "ta_lab2.connectivity.coinbase.jwt.encode", return_value="my.jwt.token"
            ),
            patch.object(ex.session, "get", return_value=mock_response) as mock_get,
        ):
            ex._authenticated_request("GET", "/api/v3/brokerage/accounts")

        call_kwargs = mock_get.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs.args[1]
        assert headers["Authorization"] == "Bearer my.jwt.token"

    def test_content_type_json_in_headers(self):
        ex = make_exchange()
        mock_key = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = {}

        with (
            patch(
                "ta_lab2.connectivity.coinbase.load_pem_private_key",
                return_value=mock_key,
            ),
            patch("ta_lab2.connectivity.coinbase.jwt.encode", return_value="tok"),
            patch.object(ex.session, "get", return_value=mock_response) as mock_get,
        ):
            ex._authenticated_request("GET", "/api/v3/brokerage/accounts")

        headers = mock_get.call_args.kwargs.get("headers") or mock_get.call_args.args[1]
        assert headers.get("Content-Type") == "application/json"

    def test_post_uses_fresh_jwt_per_request(self):
        """Each authenticated request builds a fresh JWT (not cached)."""
        ex = make_exchange()
        mock_key = MagicMock()
        call_count = {"n": 0}

        def mock_encode(payload, key, algorithm, headers=None):
            call_count["n"] += 1
            return f"token-{call_count['n']}"

        mock_response = MagicMock()
        mock_response.json.return_value = {}

        with (
            patch(
                "ta_lab2.connectivity.coinbase.load_pem_private_key",
                return_value=mock_key,
            ),
            patch("ta_lab2.connectivity.coinbase.jwt.encode", side_effect=mock_encode),
            patch.object(ex.session, "get", return_value=mock_response),
        ):
            ex._authenticated_request("GET", "/api/v3/brokerage/accounts")
            ex._authenticated_request("GET", "/api/v3/brokerage/accounts")

        assert call_count["n"] == 2, "jwt.encode should be called once per request"


# ---------------------------------------------------------------------------
# ExchangeConfig integration
# ---------------------------------------------------------------------------


class TestExchangeConfigIntegration:
    def test_config_api_key_used_for_auth(self):
        cfg = ExchangeConfig(
            venue="coinbase",
            environment="production",
            api_key="config-key",
            api_secret=FAKE_PEM,
        )
        ex = CoinbaseExchange(config=cfg)
        assert ex.api_key == "config-key"

    def test_config_api_secret_used_for_auth(self):
        cfg = ExchangeConfig(
            venue="coinbase",
            environment="production",
            api_key=FAKE_KEY,
            api_secret="config-secret",
        )
        ex = CoinbaseExchange(config=cfg)
        assert ex.api_secret == "config-secret"

    def test_direct_args_override_config(self):
        """api_key / api_secret passed directly override config values."""
        cfg = ExchangeConfig(
            venue="coinbase",
            environment="production",
            api_key="config-key",
            api_secret="config-secret",
        )
        ex = CoinbaseExchange(
            api_key="direct-key", api_secret="direct-secret", config=cfg
        )
        assert ex.api_key == "direct-key"
        assert ex.api_secret == "direct-secret"

    def test_sandbox_config_sets_sandbox_host(self):
        cfg = ExchangeConfig(
            venue="coinbase",
            environment="sandbox",
            api_key=FAKE_KEY,
            api_secret=FAKE_PEM,
        )
        ex = CoinbaseExchange(config=cfg)
        assert SANDBOX_HOST in ex.base_url

    def test_production_config_sets_production_host(self):
        cfg = ExchangeConfig(
            venue="coinbase",
            environment="production",
            api_key=FAKE_KEY,
            api_secret=FAKE_PEM,
        )
        ex = CoinbaseExchange(config=cfg)
        assert BASE_HOST in ex.base_url
        assert SANDBOX_HOST not in ex.base_url
