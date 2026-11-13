# agent/schemas.py
from pydantic import BaseModel, Field
from typing import Literal

class IntentClassification(BaseModel):
    intent: Literal[
        "price_query",
        "shipment_timing",
        "shipment_status",
        "weather_impact",
        "market_compare",
        "general",
    ] = Field(description="사용자 질문의 의도 분류")
    reason: str = Field(description="이 의도로 분류한 이유 (한 문장)")