# tests/questions.py
# 테스트 질문 20개 (11/17 일괄 실행용 초안)
#   q       : 사용자 질문
#   intent  : 기대하는 의도
#   also_ok : 애매한 질문이라 이 의도로 나와도 정답으로 인정하는 목록 (선택)
#   product : 기대하는 품목 "세척당근" / "흙당근" (질문에 품목이 있을 때만)
#   months  : 기대하는 월 YYYYMM 목록 (질문에 월이 있을 때만)
#   market  : 기대하는 시장명 (질문에 시장이 있을 때만)
#   note    : 무엇을 보려는 질문인지

QUESTIONS = [
    # --- price_query (3) ---
    {"q": "요즘 제주 당근 가격 작년보다 어때?", "intent": "price_query", "note": "전년 대비 비교(compare_year)"},
    {"q": "세척당근 이번 달 시세 알려줘", "intent": "price_query", "product": "세척당근", "note": "품목 지정"},
    {"q": "흙당근 지난달이랑 비교하면 값이 올랐어?", "intent": "price_query", "product": "흙당근",
     "months": ["202610", "202611"], "note": "전월 대비: 지난달과 이번 달 둘 다 뽑아야 비교 가능"},

    # --- shipment_timing (4) ---
    {"q": "1월이랑 2월 중에 언제 출하하는 게 나아?", "intent": "shipment_timing", "months": ["202701", "202702"],
     "note": "아직 안 온 달 → 지난해 같은 기간으로 대체되는지"},
    {"q": "다음 주에 출하해도 괜찮을까?", "intent": "shipment_timing", "note": "날씨 + 가격 같이 필요"},
    {"q": "12월 말에 세척당근 내보내면 어때?", "intent": "shipment_timing", "product": "세척당근", "months": ["202612"]},
    {"q": "이번 주 비 오는데 출하 미루는 게 좋을까?", "intent": "shipment_timing", "also_ok": ["weather_impact"],
     "note": "출하 시기와 날씨가 섞인 애매한 질문"},

    # --- volume_status (3) ---
    {"q": "요즘 당근 거래량 많은 편이야?", "intent": "volume_status", "note": "거래량 수준"},
    {"q": "흙당근 반입량이 작년보다 줄었어?", "intent": "volume_status", "product": "흙당근", "note": "전년 대비 거래량"},
    {"q": "이번 달 세척당근 물량 얼마나 돼?", "intent": "volume_status", "product": "세척당근"},

    # --- weather_impact (3) ---
    {"q": "이번 주 한파 오면 당근 값에 영향 있어?", "intent": "weather_impact", "note": "예보 최저기온으로 한파 여부 답해야 함"},
    {"q": "태풍 오면 당근 가격 오를까?", "intent": "weather_impact", "note": "데이터로 확인 불가한 부분을 솔직히 말하는지"},
    {"q": "이번 주 강풍 예보 있어?", "intent": "weather_impact", "note": "날씨 위주 질문"},

    # --- market_compare (3) ---
    {"q": "가락시장이랑 다른 시장 중에 어디가 더 비싸?", "intent": "market_compare", "note": "시장 간 가격 비교"},
    {"q": "대구북부도매 가격은 다른 시장이랑 비교하면 어때?", "intent": "market_compare", "market": "대구북부도매"},
    {"q": "어느 시장에 내면 제일 유리해?", "intent": "market_compare", "note": "거래량이 적은 시장의 튀는 가격을 걸러내는지"},

    # --- wash_vs_soil (2) ---
    {"q": "세척당근이랑 흙당근 중에 뭐가 더 유리해?", "intent": "wash_vs_soil"},
    {"q": "세척하면 값을 더 받을 수 있어?", "intent": "wash_vs_soil", "note": "비용 데이터는 없다는 한계를 밝히는지"},

    # --- general (2) ---
    {"q": "오늘 점심 뭐 먹지?", "intent": "general", "note": "범위 밖 질문"},
    {"q": "감귤 가격 알려줘", "intent": "general", "note": "다른 품목 → 당근 도우미 범위 밖 안내"},
]
