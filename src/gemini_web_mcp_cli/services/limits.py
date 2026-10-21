"""Limits service: check usage quotas via qpEbW RPC."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import IntEnum

from loguru import logger

from gemini_web_mcp_cli.core.client import GeminiClient
from gemini_web_mcp_cli.core.constants import RPC
from gemini_web_mcp_cli.core.models import RPCPayload


class Feature(IntEnum):
    """Known Gemini feature IDs from the qpEbW usage response.

    Mapped by cross-referencing observed limits with the Google AI Pro/Ultra
    limits table at support.google.com/gemini/answer/16275805.
    """

    DEEP_THINK = 3
    DYNAMIC_VIEW = 4
    VIDEO = 5
    IMAGES = 7
    DEEP_RESEARCH = 8
    PRO_PROMPTS = 9
    AUDIO_OVERVIEWS = 11
    THINKING_PROMPTS = 15
    AGENT = 16
    MUSIC = 17
    SLIDES = 14
    NANO_BANANA_PRO = 19
    NANO_BANANA_2 = 21


FEATURE_LABELS: dict[int, str] = {
    Feature.DEEP_THINK: "Deep Think",
    Feature.DYNAMIC_VIEW: "Dynamic View",
    Feature.VIDEO: "Video (Gemini Omni)",
    Feature.IMAGES: "Images",
    Feature.DEEP_RESEARCH: "Deep Research",
    Feature.PRO_PROMPTS: "Pro Prompts",
    Feature.AUDIO_OVERVIEWS: "Audio Overviews",
    Feature.THINKING_PROMPTS: "Thinking Prompts",
    Feature.AGENT: "Agent Requests",
    Feature.MUSIC: "Music (Lyria 3.5)",
    Feature.SLIDES: "Slides",
    Feature.NANO_BANANA_PRO: "Nano Banana Pro",
    Feature.NANO_BANANA_2: "Nano Banana 2",
}


class FeatureLimit:
    """A single feature's usage data from qpEbW.

    Units (verified against gemini.google.com/usage, Feb 2026):
    - ``used`` is the server-reported **usage percentage** for that feature
      (the usage page shows the same value as "X% used").
    - ``limit`` is the plan pool size in **credits** (depends on the plan,
      e.g. 2400 or 48384).
    - ``remaining`` is the credits left in that pool.
    """

    def __init__(self, feature_id: int, used: int, limit: int, remaining: int,
                 reset_timestamp: float):
        self.feature_id = feature_id
        self.used = used
        self.limit = limit
        self.remaining = remaining
        self.reset_at = datetime.fromtimestamp(reset_timestamp, tz=timezone.utc)

    @property
    def name(self) -> str:
        return FEATURE_LABELS.get(self.feature_id, f"Unknown ({self.feature_id})")

    @property
    def is_exhausted(self) -> bool:
        return self.limit > 0 and self.remaining <= 0

    @property
    def reset_in_seconds(self) -> float:
        delta = self.reset_at - datetime.now(tz=timezone.utc)
        return max(0.0, delta.total_seconds())

    def to_dict(self) -> dict:
        return {
            "feature_id": self.feature_id,
            "name": self.name,
            "used": self.used,
            "limit": self.limit,
            "remaining": self.remaining,
            "reset_at": self.reset_at.isoformat(),
            "reset_in_seconds": round(self.reset_in_seconds),
        }

    def __repr__(self) -> str:
        return (
            f"FeatureLimit({self.name}: {self.used}/{self.limit}, "
            f"remaining={self.remaining})"
        )


class LimitsService:
    """Service for querying Gemini usage limits via the qpEbW RPC.

    Requires full browser cookies (Token Factory). The qpEbW RPC returns
    per-feature usage data including current usage count, plan limit,
    remaining quota, and rolling reset time.

    The RPC requires an explicit feature list in its payload — an empty
    payload returns no entries. The payload format is a list of
    ``[1, feature_id]`` pairs (captured from the live UI, Feb 2026).
    """

    def __init__(self, client: GeminiClient):
        self.client = client

    @staticmethod
    def _build_payloads() -> list[RPCPayload]:
        """Build one qpEbW payload per feature.

        The server processes a single feature pair per call, so each feature
        gets its own payload; they are sent together in one batchexecute call.
        """
        feature_ids = sorted({int(f) for f in Feature})
        return [
            RPCPayload(rpc_id=RPC.USAGE_INFO, payload=json.dumps([[[1, fid]]]))
            for fid in feature_ids
        ]

    async def get_limits(self) -> list[FeatureLimit]:
        """Fetch current usage limits for all features.

        Returns a list of FeatureLimit objects sorted by feature ID.
        Requires browser cookies (call after a Token Factory operation
        or use force_token_factory on the client).
        """
        results = await self.client.execute_rpcs_with_browser_cookies(
            self._build_payloads()
        )

        limits: list[FeatureLimit] = []
        for result in results:
            if result.data:
                limits.extend(self._parse_usage_data(result.data))

        if not results or not any(r.data for r in results):
            logger.warning("qpEbW returned no data (browser cookies required)")
            return []

        limits.sort(key=lambda fl: fl.feature_id)
        if not limits:
            logger.warning(
                "qpEbW returned data but no limit entries could be parsed "
                "(usage response format may have changed)"
            )
        return limits

    async def get_feature_limit(self, feature: Feature) -> FeatureLimit | None:
        """Get the limit for a specific feature."""
        limits = await self.get_limits()
        for fl in limits:
            if fl.feature_id == feature:
                return fl
        return None

    def _parse_usage_data(self, data: list) -> list[FeatureLimit]:
        """Parse the qpEbW response into FeatureLimit objects.

        Response structure: [[entries_array], ""]
        Each entry: [[2, feature_id, 2], active_flag, used, [reset_secs, nanos], limit, remaining]
        """
        try:
            entries = data[0]
            if not isinstance(entries, list):
                return []
        except (IndexError, TypeError):
            return []

        limits: list[FeatureLimit] = []
        for entry in entries:
            try:
                feature_id = entry[0][1]
                used = entry[2]
                reset_secs = entry[3][0]
                limit = entry[4]
                remaining = entry[5]

                limits.append(FeatureLimit(
                    feature_id=feature_id,
                    used=used,
                    limit=limit,
                    remaining=remaining,
                    reset_timestamp=float(reset_secs),
                ))
            except (IndexError, TypeError, ValueError) as e:
                logger.debug(f"Skipping unparseable limit entry: {e}")
                continue

        limits.sort(key=lambda fl: fl.feature_id)
        return limits
