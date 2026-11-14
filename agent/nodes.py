# agent/nodes.py
import os
from datetime import date

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

from agent.schemas import IntentClassification
from agent.state import CarrotState
from agent.utils import with_retry
from config import LLM_TIMEOUT, MODEL_NAME

load_dotenv()

llm = ChatGoogleGenerativeAI(
    model=MODEL_NAME,
    temperature=0,
    google_api_key=os.getenv("GEMINI_API_KEY"),
    timeout=LLM_TIMEOUT,
)

structured_llm = llm.with_structured_output(IntentClassification)

INTENT_PROMPT = """당신은 제주 당근(세척당근·흙당근) 농가를 위한 AI 에이전트의 의도 분류기입니다.
사용자의 질문을 아래 7가지 중 하나로 분류하고, 질문에서 파라미터도 함께 추출하세요.

- price_query: 가격·시세 조회, 작년/전월 대비 가격 변화
- shipment_timing: 언제 출하/판매하는 게 나은지 (월 비교 포함)
- volume_status: 거래량·반입량이 많은지/적은지
- weather_impact: 한파·폭우·가뭄 등 날씨가 가격에 미치는 영향
- market_compare: 도매시장(가락시장 등) 간 가격 비교
- wash_vs_soil: 세척당근과 흙당근 비교
- general: 위에 해당하지 않거나 당근과 무관한 질문

규칙:
- 두 품목을 비교하는 질문이면 wash_vs_soil.
- 품목 언급이 없거나 '당근'이라고만 하면 product=both.
- months는 YYYYMM 형식. 연도가 없으면 오늘 날짜 기준으로 추정.

오늘 날짜: {today}
사용자 질문: {query}
"""


def _classify_intent(query: str) -> IntentClassification:
    prompt = INTENT_PROMPT.format(today=date.today().isoformat(), query=query)
    return with_retry(lambda: structured_llm.invoke(prompt))


def intent_router(state: CarrotState) -> CarrotState:
    state.setdefault("errors", [])
    try:
        result = _classify_intent(state["user_query"])
        state["intent"] = result.intent
        state["params"] = result.params.model_dump()
        print(f"[intent_router] 분류: {result.intent} / {state['params']} ({result.reason})")
    except Exception as e:  # noqa: BLE001
        state["errors"].append(f"intent_router 오류: {e}")
        state["intent"] = "general"
        state["params"] = {}
        print(f"[intent_router] 오류 발생, general로 폴백: {e}")
    return state


def data_fetcher(state: CarrotState) -> CarrotState:
    print("[data_fetcher] 실행됨")
    state["fetched_data"] = {}    # TODO: B 작업물 연결 예정
    return state


def analyzer(state: CarrotState) -> CarrotState:
    print("[analyzer] 실행됨")
    state["analysis"] = "분석 결과 placeholder"
    return state


def response_generator(state: CarrotState) -> CarrotState:
    print("[response_generator] 실행됨")
    state["final_answer"] = "최종 응답 placeholder"
    return state
