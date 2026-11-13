# agent/state.py
from typing import TypedDict, Optional, List, Dict, Any

class GamgyulState(TypedDict):
    user_query: str                      # 사용자 질문
    intent: Optional[str]                # price_query / shipment_timing / shipment_status / weather_impact / market_compare / general
    fetched_data: Dict[str, Any]          # 각 API 결과 (키: "jeju_hub", "kamis", "weather" 등)
    analysis: Optional[str]               # analyzer 결과
    final_answer: Optional[str]           # 최종 응답
    errors: List[str]                     # 노드 실행 중 발생한 에러 기록
    retry_count: int                      # 429 등 재시도 횟수