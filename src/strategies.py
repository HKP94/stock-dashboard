from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Track = Literal["true", "retrospective"]
SelectorKind = Literal["momentum_12_1", "low_vol", "equal_weight_bh", "latest_factor_basket"]


@dataclass(frozen=True)
class StrategyDefinition:
    name: str
    track: Track
    label: str
    selector_kind: SelectorKind
    description: str
    factor_key: str | None = None


TRUE_STRATEGIES: tuple[StrategyDefinition, ...] = (
    StrategyDefinition(
        name="momentum_12_1",
        track="true",
        label="모멘텀 12-1",
        selector_kind="momentum_12_1",
        description="과거 시점까지의 12-1 모멘텀 상위 종목을 월별 리밸런싱합니다.",
    ),
    StrategyDefinition(
        name="low_vol",
        track="true",
        label="저변동성",
        selector_kind="low_vol",
        description="최근 실현변동성이 낮은 종목을 월별 리밸런싱합니다.",
    ),
    StrategyDefinition(
        name="equal_weight_bh",
        track="true",
        label="동일가중 매수후보유",
        selector_kind="equal_weight_bh",
        description="활성 유니버스를 동일가중으로 한 번 매수 후 보유하는 기준 전략입니다.",
    ),
)


RETROSPECTIVE_STRATEGIES: tuple[StrategyDefinition, ...] = (
    StrategyDefinition(
        name="value",
        track="retrospective",
        label="가치",
        selector_kind="latest_factor_basket",
        factor_key="value",
        description="최신 가치 점수 상위 종목의 과거 성과를 참고용으로 회고합니다.",
    ),
    StrategyDefinition(
        name="quality",
        track="retrospective",
        label="우량성",
        selector_kind="latest_factor_basket",
        factor_key="quality",
        description="최신 우량성 점수 상위 종목의 과거 성과를 참고용으로 회고합니다.",
    ),
    StrategyDefinition(
        name="multifactor",
        track="retrospective",
        label="멀티팩터",
        selector_kind="latest_factor_basket",
        factor_key="composite",
        description="최신 종합 점수 상위 종목의 과거 성과를 참고용으로 회고합니다.",
    ),
)


ALL_STRATEGIES: tuple[StrategyDefinition, ...] = TRUE_STRATEGIES + RETROSPECTIVE_STRATEGIES


STRATEGY_BY_NAME = {s.name: s for s in ALL_STRATEGIES}
