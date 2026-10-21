"""Tests for the usage limits service (qpEbW)."""

import json
from unittest.mock import AsyncMock, MagicMock

from gemini_web_mcp_cli.core.models import BatchResult
from gemini_web_mcp_cli.services.limits import Feature, FeatureLimit, LimitsService


class TestBuildPayloads:
    def test_one_payload_per_feature(self):
        payloads = LimitsService._build_payloads()
        assert len(payloads) == len(set(int(f) for f in Feature))
        assert all(p.rpc_id == "qpEbW" for p in payloads)

    def test_payload_shape_is_feature_pair(self):
        payloads = LimitsService._build_payloads()
        for p in payloads:
            outer = json.loads(p.payload)
            pair = outer[0][0]
            assert pair[0] == 1
            assert pair[1] in {int(f) for f in Feature}


class TestParseUsageData:
    def test_parses_entry(self):
        svc = LimitsService(MagicMock())
        data = [
            [[[None, 5], 2, 12, [1789863996, 532586000], 2400, 2091]],
            "",
        ]
        limits = svc._parse_usage_data(data)
        assert len(limits) == 1
        fl = limits[0]
        assert fl.feature_id == 5
        assert fl.used == 12
        assert fl.limit == 2400
        assert fl.remaining == 2091

    def test_empty_entries(self):
        svc = LimitsService(MagicMock())
        assert svc._parse_usage_data([[], ""]) == []

    def test_bad_structure(self):
        svc = LimitsService(MagicMock())
        assert svc._parse_usage_data([]) == []
        assert svc._parse_usage_data(None) == []


class TestGetLimits:
    async def test_aggregates_all_results(self):
        """get_limits merges entries from every batched qpEbW result."""
        mock_client = MagicMock()
        results = [
            BatchResult(
                rpc_id="qpEbW",
                data=[[[[None, 3], 2, 15, [1789863997, 0], 2400, 2040]], ""],
                raw="",
            ),
            BatchResult(
                rpc_id="qpEbW",
                data=[[[[None, 5], 2, 12, [1789863996, 0], 2400, 2091]], ""],
                raw="",
            ),
        ]
        mock_client.execute_rpcs_with_browser_cookies = AsyncMock(return_value=results)
        svc = LimitsService(mock_client)

        limits = await svc.get_limits()
        assert [fl.feature_id for fl in limits] == [3, 5]
        assert limits[0].name == "Deep Think"
        assert limits[1].name == "Video (Gemini Omni)"

        # Verify it sent one payload per feature in a single batch
        call_args = mock_client.execute_rpcs_with_browser_cookies.call_args
        payloads = call_args.args[0]
        assert len(payloads) == len(set(int(f) for f in Feature))

    async def test_no_data_returns_empty(self):
        mock_client = MagicMock()
        mock_client.execute_rpcs_with_browser_cookies = AsyncMock(return_value=[])
        svc = LimitsService(mock_client)
        assert await svc.get_limits() == []


class TestFeatureLimit:
    def test_exhausted(self):
        fl = FeatureLimit(5, used=10, limit=10, remaining=0, reset_timestamp=0)
        assert fl.is_exhausted is True

    def test_not_exhausted(self):
        fl = FeatureLimit(5, used=1, limit=10, remaining=9, reset_timestamp=0)
        assert fl.is_exhausted is False
