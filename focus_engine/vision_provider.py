from __future__ import annotations

from typing import Any, Protocol

import numpy as np

from .config import AnalyzerConfig
from .models import GoalProfile
from .siliconflow_vlm import SiliconFlowVlmScorer


class VisionScorer(Protocol):
    """原型所需的最小视觉评分接口。"""

    def status(self) -> dict[str, Any]: ...

    def vision_ready_message(self) -> tuple[bool, str]: ...

    def analyze(
        self,
        profile: GoalProfile,
        filename: str,
        image_bgr: np.ndarray,
        thumbnail_hash: str,
        *,
        bypass_cache: bool = False,
    ) -> dict[str, Any]: ...

    def generate_session_summary(self, goal: str, summary_stats: dict) -> str: ...


class BailianVlmScorer(SiliconFlowVlmScorer):
    """阿里云百炼 OpenAI 兼容接口；评分协议与硅基流动保持一致。"""

    def __init__(self, config: AnalyzerConfig) -> None:
        super().__init__(config)
        self.provider_name = "bailian"
        self.api_key = config.bailian_api_key
        self.base_url = config.bailian_base_url
        self.model = config.bailian_model


def create_vision_scorer(config: AnalyzerConfig) -> VisionScorer:
    if config.vision_provider == "bailian":
        return BailianVlmScorer(config)
    return SiliconFlowVlmScorer(config)
