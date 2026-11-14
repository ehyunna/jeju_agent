# agent/state.py
from typing import Any, Dict, List, Optional, TypedDict


class CarrotState(TypedDict, total=False):
    user_query: str                  # 사용자 질문
    intent: Optional[str]            # price_query / shipment_timing / volume_status / weather_impact / market_compare / wash_vs_soil / general
    params: Dict[str, Any]           # 의도 분류 때 추출한 파라미터 (product, months, compare_year, market, region)
    fetched_data: Dict[str, Any]     # 각 API 결과 (키: "jeju_hub", "weather" 등)
    analysis: Optional[Any]          # analyzer 결과 (str 또는 dict)
    final_answer: Optional[str]      # 최종 응답
    validation: Optional[Dict[str, Any]]  # {"passed": bool, "issues": [...]}
    sources: List[str]               # 출처 목록
    errors: List[str]                # 노드 실행 중 발생한 에러 기록
    retry_count: int                 # 검증 실패 후 흐름 재시도 횟수
