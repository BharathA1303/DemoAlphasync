import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
from providers.alice_blue_provider import AliceBlueProvider
from providers.base import ProviderStatus


@pytest.fixture
def mock_redis():
    return MagicMock()


@pytest.fixture
def provider(mock_redis):
    # Initialize the provider with dummy credentials
    return AliceBlueProvider(
        ws_url="wss://ws_dummy/NorenWS",
        user_id="AB12345",
        session_token="dummy_session_token_xyz",
        api_url="https://api_dummy/rest/AliceBlueAPIService/api",
        redis_client=mock_redis,
    )


class TestAliceBlueProviderUnit:
    """Unit tests for Alice Blue provider functions."""

    def test_parse_interval_minutes(self):
        """Verify interval mapping strings convert to integer minutes correctly."""
        assert AliceBlueProvider._parse_interval_minutes("1m") == 1
        assert AliceBlueProvider._parse_interval_minutes("5m") == 5
        assert AliceBlueProvider._parse_interval_minutes("15m") == 15
        assert AliceBlueProvider._parse_interval_minutes("1h") == 60
        assert AliceBlueProvider._parse_interval_minutes("2h") == 120
        assert AliceBlueProvider._parse_interval_minutes("1d") == 1440
        assert AliceBlueProvider._parse_interval_minutes("5") == 5
        assert AliceBlueProvider._parse_interval_minutes("invalid") == 1

    def test_parse_candle_standard(self, provider):
        """Verify standard lowercase field parsing and IST time string parsing."""
        raw = {
            "open": 150.25,
            "high": 155.00,
            "low": 149.50,
            "close": 153.75,
            "volume": 12000,
            "time": "2023-10-27 09:15:00"
        }
        parsed = provider._parse_candle(raw)
        assert parsed is not None
        assert parsed["open"] == 150.25
        assert parsed["high"] == 155.00
        assert parsed["low"] == 149.50
        assert parsed["close"] == 153.75
        assert parsed["volume"] == 12000
        
        # Verify timezone conversion from IST to epoch timestamp
        # 2023-10-27 09:15:00 IST = 2023-10-27 03:45:00 UTC
        expected_dt = datetime(2023, 10, 27, 9, 15, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        assert parsed["time"] == int(expected_dt.timestamp())

    def test_parse_candle_fallback_keys(self, provider):
        """Verify fallback abbreviated keys and numeric/epoch timestamp parsing."""
        raw = {
            "o": "100.1",
            "h": "102.5",
            "l": "99.8",
            "c": "101.2",
            "v": "5000",
            "t": 1698378900000  # ms timestamp
        }
        parsed = provider._parse_candle(raw)
        assert parsed is not None
        assert parsed["open"] == 100.1
        assert parsed["high"] == 102.5
        assert parsed["low"] == 99.8
        assert parsed["close"] == 101.2
        assert parsed["volume"] == 5000
        assert parsed["time"] == 1698378900  # converted to seconds

    def test_parse_candle_capitalized(self, provider):
        """Verify capitalized field parsing and IST time string parsing as returned by the official API v2."""
        raw = {
            "Open": 150.25,
            "High": 155.00,
            "Low": 149.50,
            "Close": 153.75,
            "Volume": 12000,
            "Time": "2023-10-27 09:15:00"
        }
        parsed = provider._parse_candle(raw)
        assert parsed is not None
        assert parsed["open"] == 150.25
        assert parsed["high"] == 155.00
        assert parsed["low"] == 149.50
        assert parsed["close"] == 153.75
        assert parsed["volume"] == 12000
        
        expected_dt = datetime(2023, 10, 27, 9, 15, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        assert parsed["time"] == int(expected_dt.timestamp())

    def test_resample_candles(self):
        """Verify resampling of 1-minute candles to 5-minute candles."""
        # 5 consecutive 1-minute candles starting at 9:15:00 (551700 epoch seconds)
        base_time = 1698378900  # 9:15:00 IST
        candles = [
            {"time": base_time + 0, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 100},
            {"time": base_time + 60, "open": 100.5, "high": 102.0, "low": 100.0, "close": 101.5, "volume": 150},
            {"time": base_time + 120, "open": 101.5, "high": 101.8, "low": 98.5, "close": 99.0, "volume": 200},
            {"time": base_time + 180, "open": 99.0, "high": 100.0, "low": 99.0, "close": 99.5, "volume": 50},
            {"time": base_time + 240, "open": 99.5, "high": 103.0, "low": 99.5, "close": 102.0, "volume": 300},
        ]
        
        resampled = AliceBlueProvider._resample_candles(candles, 5)
        assert len(resampled) == 1
        b = resampled[0]
        assert b["time"] == base_time
        assert b["open"] == 100.0
        assert b["high"] == 103.0
        assert b["low"] == 98.5
        assert b["close"] == 102.0
        assert b["volume"] == 800

    @pytest.mark.asyncio
    @patch("providers.alice_blue_provider.httpx.AsyncClient")
    async def test_connect_authorization_headers(self, mock_client_cls, provider):
        """Verify connect calls createWsSess REST endpoint with Bearer session_token only."""
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = MagicMock(status_code=200, text="Success")
        
        # Mock websockets connect and WS auth exchange
        mock_ws = AsyncMock()
        mock_ws.recv.return_value = '{"t":"cf","k":"OK"}'
        
        with patch("providers.alice_blue_provider.websockets.connect", new_callable=AsyncMock) as mock_ws_connect:
            mock_ws_connect.return_value = mock_ws
            
            # Start connection
            await provider._connect()
            
            # Verify POST request headers
            mock_client.post.assert_called_once()
            called_args, called_kwargs = mock_client.post.call_args
            headers = called_kwargs.get("headers", {})
            
            assert headers["Authorization"] == "Bearer dummy_session_token_xyz"
            assert headers["Content-Type"] == "application/json"
            assert provider._status == ProviderStatus.CONNECTED

    @pytest.mark.asyncio
    @patch("providers.alice_blue_provider.httpx.AsyncClient")
    async def test_chart_history_daily_resolution_mapping(self, mock_client_cls, provider):
        """Verify that requests for daily intervals map to resolution 'D' and make HTTP call."""
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.post.return_value = MagicMock(status_code=200, json=lambda: {"status": "Ok", "result": []})
        
        result = await provider._alice_chart_history(
            "/EODChartData",
            {"token": "26000", "exchange": "NSE", "from": "1698378900", "to": "1698382500", "intrv": "1D"}
        )
        
        # Verify HTTP client was called
        mock_client.post.assert_called_once()
        called_args, called_kwargs = mock_client.post.call_args
        body = called_kwargs.get("json", {})
        
        assert body["resolution"] == "D"
        assert body["token"] == "26000"
        assert body["exchange"] == "NSE"
        assert result == []
