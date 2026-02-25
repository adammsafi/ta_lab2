"""
Unit tests for Kraken HMAC-SHA512 authentication.

All tests use mocks or known test vectors - no live API, no credentials, no network.
Tests cover: HMAC-SHA512 known vector, _requires_auth errors, nonce is millisecond
timestamp, headers sent to API, error checking, ExchangeConfig integration.
"""

import base64
import hashlib
import hmac
import time
import urllib.parse
from unittest.mock import MagicMock, patch

import pytest

from ta_lab2.connectivity.exceptions import AuthenticationError, InvalidRequestError
from ta_lab2.connectivity.exchange_config import ExchangeConfig
from ta_lab2.connectivity.kraken import KrakenExchange


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A 64-byte base64-encoded secret that decodes cleanly (valid for base64.b64decode)
VALID_SECRET_BYTES = b"x" * 64
VALID_SECRET = base64.b64encode(VALID_SECRET_BYTES).decode()
VALID_KEY = "my-api-key"


def make_kraken(api_key=VALID_KEY, api_secret=VALID_SECRET):
    return KrakenExchange(api_key=api_key, api_secret=api_secret)


# ---------------------------------------------------------------------------
# _requires_auth error cases
# ---------------------------------------------------------------------------


class TestRequiresAuth:
    def test_no_credentials_raises_authentication_error(self):
        ex = KrakenExchange()
        with pytest.raises(AuthenticationError):
            ex._requires_auth()

    def test_missing_api_key_raises(self):
        ex = KrakenExchange(api_key="", api_secret=VALID_SECRET)
        with pytest.raises(AuthenticationError):
            ex._requires_auth()

    def test_missing_api_secret_raises(self):
        ex = KrakenExchange(api_key=VALID_KEY, api_secret="")
        with pytest.raises(AuthenticationError):
            ex._requires_auth()

    def test_credentials_present_does_not_raise(self):
        ex = make_kraken()
        ex._requires_auth()  # should not raise

    def test_error_message_mentions_api_key(self):
        ex = KrakenExchange()
        with pytest.raises(AuthenticationError, match="api_key"):
            ex._requires_auth()


# ---------------------------------------------------------------------------
# _sign HMAC-SHA512 known vector
# ---------------------------------------------------------------------------


class TestSign:
    def _expected_signature(self, api_secret: str, urlpath: str, data: dict) -> str:
        """Recompute signature using the same algorithm as _sign for comparison."""
        encoded = (str(data["nonce"]) + urllib.parse.urlencode(data)).encode()
        message = urlpath.encode() + hashlib.sha256(encoded).digest()
        mac = hmac.new(base64.b64decode(api_secret), message, hashlib.sha512)
        return base64.b64encode(mac.digest()).decode()

    def test_sign_matches_reference_implementation(self):
        ex = make_kraken()
        urlpath = "/0/private/Balance"
        data = {"nonce": "1616492376594"}
        result = ex._sign(urlpath, data)
        expected = self._expected_signature(VALID_SECRET, urlpath, data)
        assert result == expected

    def test_sign_returns_base64_string(self):
        ex = make_kraken()
        result = ex._sign("/0/private/Balance", {"nonce": "1234567890"})
        # Should be valid base64
        try:
            base64.b64decode(result)
        except Exception as e:
            pytest.fail(f"_sign did not return valid base64: {e}")

    def test_sign_different_nonces_produce_different_signatures(self):
        ex = make_kraken()
        sig1 = ex._sign("/0/private/Balance", {"nonce": "1000000000000"})
        sig2 = ex._sign("/0/private/Balance", {"nonce": "1000000000001"})
        assert sig1 != sig2

    def test_sign_different_paths_produce_different_signatures(self):
        ex = make_kraken()
        data = {"nonce": "1234567890000"}
        sig1 = ex._sign("/0/private/Balance", data)
        sig2 = ex._sign("/0/private/AddOrder", data)
        assert sig1 != sig2

    def test_sign_with_additional_data_fields(self):
        ex = make_kraken()
        data = {
            "nonce": "1616492376594",
            "pair": "XBTUSD",
            "type": "buy",
            "ordertype": "market",
            "volume": "0.5",
        }
        urlpath = "/0/private/AddOrder"
        result = ex._sign(urlpath, data)
        expected = self._expected_signature(VALID_SECRET, urlpath, data)
        assert result == expected


# ---------------------------------------------------------------------------
# Nonce is millisecond-resolution timestamp
# ---------------------------------------------------------------------------


class TestNonce:
    def test_nonce_is_millisecond_timestamp(self):
        """Nonce should be current time in milliseconds (10+ digits)."""
        ex = make_kraken()

        before_ms = int(time.time() * 1000)

        # Capture nonce by intercepting the session.post call
        captured_data = {}

        def mock_post(url, headers=None, data=None):
            if data:
                captured_data.update(data)
            resp = MagicMock()
            resp.json.return_value = {"error": [], "result": {}}
            return resp

        with patch.object(ex.session, "post", side_effect=mock_post):
            ex._private_post("Balance")

        after_ms = int(time.time() * 1000)
        nonce = int(captured_data["nonce"])

        assert before_ms <= nonce <= after_ms + 10, (
            f"Nonce {nonce} not in expected millisecond range [{before_ms}, {after_ms}]"
        )

    def test_nonce_has_at_least_10_digits(self):
        """Millisecond timestamps have 13 digits in 2024+."""
        ex = make_kraken()
        captured_data = {}

        def mock_post(url, headers=None, data=None):
            if data:
                captured_data.update(data)
            resp = MagicMock()
            resp.json.return_value = {"error": [], "result": {}}
            return resp

        with patch.object(ex.session, "post", side_effect=mock_post):
            ex._private_post("Balance")

        assert len(captured_data["nonce"]) >= 10


# ---------------------------------------------------------------------------
# Headers sent to Kraken API
# ---------------------------------------------------------------------------


class TestPrivatePostHeaders:
    def _make_mock_response(self, result=None, error=None):
        resp = MagicMock()
        resp.json.return_value = {"error": error or [], "result": result or {}}
        return resp

    def test_api_key_header_sent(self):
        ex = make_kraken(api_key=VALID_KEY)
        captured_headers = {}

        def mock_post(url, headers=None, data=None):
            if headers:
                captured_headers.update(headers)
            return self._make_mock_response(result={})

        with patch.object(ex.session, "post", side_effect=mock_post):
            ex._private_post("Balance")

        assert captured_headers.get("API-Key") == VALID_KEY

    def test_api_sign_header_sent(self):
        ex = make_kraken()
        captured_headers = {}

        def mock_post(url, headers=None, data=None):
            if headers:
                captured_headers.update(headers)
            return self._make_mock_response(result={})

        with patch.object(ex.session, "post", side_effect=mock_post):
            ex._private_post("Balance")

        assert "API-Sign" in captured_headers
        assert len(captured_headers["API-Sign"]) > 0

    def test_api_sign_is_valid_base64(self):
        ex = make_kraken()
        captured_headers = {}

        def mock_post(url, headers=None, data=None):
            if headers:
                captured_headers.update(headers)
            return self._make_mock_response(result={})

        with patch.object(ex.session, "post", side_effect=mock_post):
            ex._private_post("Balance")

        sign = captured_headers["API-Sign"]
        try:
            base64.b64decode(sign)
        except Exception as e:
            pytest.fail(f"API-Sign is not valid base64: {e}")

    def test_url_contains_endpoint_name(self):
        ex = make_kraken()
        captured_urls = []

        def mock_post(url, headers=None, data=None):
            captured_urls.append(url)
            return self._make_mock_response(result={})

        with patch.object(ex.session, "post", side_effect=mock_post):
            ex._private_post("Balance")

        assert any("Balance" in url for url in captured_urls)

    def test_url_uses_kraken_private_endpoint(self):
        ex = make_kraken()
        captured_urls = []

        def mock_post(url, headers=None, data=None):
            captured_urls.append(url)
            return self._make_mock_response(result={})

        with patch.object(ex.session, "post", side_effect=mock_post):
            ex._private_post("Balance")

        assert any("api.kraken.com/0/private" in url for url in captured_urls)


# ---------------------------------------------------------------------------
# Error checking in response
# ---------------------------------------------------------------------------


class TestErrorChecking:
    def test_non_empty_error_list_raises_invalid_request_error(self):
        ex = make_kraken()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "error": ["EGeneral:Invalid arguments"],
            "result": {},
        }

        with patch.object(ex.session, "post", return_value=mock_resp):
            with pytest.raises(InvalidRequestError, match="Kraken error"):
                ex._private_post("AddOrder")

    def test_error_message_contains_kraken_error_text(self):
        ex = make_kraken()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "error": ["EOrder:Insufficient funds"],
            "result": {},
        }

        with patch.object(ex.session, "post", return_value=mock_resp):
            with pytest.raises(InvalidRequestError, match="Insufficient funds"):
                ex._private_post("AddOrder")

    def test_empty_error_list_returns_result(self):
        ex = make_kraken()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "error": [],
            "result": {"XXBT": "0.5"},
        }

        with patch.object(ex.session, "post", return_value=mock_resp):
            result = ex._private_post("Balance")

        assert result == {"XXBT": "0.5"}

    def test_requires_auth_called_before_post(self):
        """_private_post should raise AuthenticationError before making the HTTP call."""
        ex = KrakenExchange()  # no credentials

        with pytest.raises(AuthenticationError):
            ex._private_post("Balance")


# ---------------------------------------------------------------------------
# ExchangeConfig integration
# ---------------------------------------------------------------------------


class TestExchangeConfigIntegration:
    def test_config_credentials_used(self):
        cfg = ExchangeConfig(
            venue="kraken",
            environment="production",
            api_key=VALID_KEY,
            api_secret=VALID_SECRET,
        )
        ex = KrakenExchange(config=cfg)
        assert ex.api_key == VALID_KEY
        assert ex.api_secret == VALID_SECRET

    def test_config_overrides_none_credentials(self):
        cfg = ExchangeConfig(
            venue="kraken",
            environment="production",
            api_key="config-key",
            api_secret="config-secret",
        )
        ex = KrakenExchange(api_key=None, api_secret=None, config=cfg)
        assert ex.api_key == "config-key"

    def test_no_config_and_no_credentials_raises_on_private_post(self):
        ex = KrakenExchange()
        with pytest.raises(AuthenticationError):
            ex._private_post("Balance")

    def test_config_credentials_allow_private_post(self):
        cfg = ExchangeConfig(
            venue="kraken",
            environment="production",
            api_key=VALID_KEY,
            api_secret=VALID_SECRET,
        )
        ex = KrakenExchange(config=cfg)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": [], "result": {"XXBT": "1.0"}}

        with patch.object(ex.session, "post", return_value=mock_resp):
            result = ex._private_post("Balance")

        assert result == {"XXBT": "1.0"}
