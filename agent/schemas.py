conda# agent/schemas.py
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Intent = Literal[
    "price_query",
    "shipment_timing",
    "volume_status",
    "weather_impact",
    "market_compare",
    "wash_vs_soil",
    "general",
]


class QueryParams(BaseModel):
    product: Literal["세척당근", "흙당근", "both"] = Field(
        default="both", description="품목. 언급 없거나 '당근'만 말하면 both"
    )
    months: List[str] = Field(
        default_factory=list,
        description="YYYYMM 형식 월 목록. '1월이랑 2월'이면 둘 다. 연도 불명확하면 오늘 날짜 기준으로 추정",
    )
    compare_year: Optional[int] = Field(default=None, description="'작년' 등 비교 대상 연도")
    market: Optional[str] = Field(default=None, description="도매시장명 (예: 가락시장). 없으면 null")
    region: str = Field(default="제주", description="산지. 기본 제주")


class IntentClassification(BaseModel):
    intent: Intent = Field(description="사용자 질문의 의도 분류")
    params: QueryParams = Field(default_factory=QueryParams, description="질문에서 추출한 파라미터")
    reason: str = Field(description="이 의도로 분류한 이유 (한 문장)")
