# agent/nodes.py
import os
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential
from langchain_google_genai import ChatGoogleGenerativeAI
from agent.state import GamgyulState
from agent.schemas import IntentClassification

load_dotenv()

llm = ChatGoogleGenerativeAI(
    model="gemini-3.5-flash-lite",   # gemini-3.8-flash 대신
    temperature=0,
    google_api_key=os.getenv("GEMINI_API_KEY"),
    timeout=15,
)




structured_llm = llm.with_structured_output(IntentClassification)

INTENT_PROMPT = """당신은 제주 감귤 농가를 위한 AI 에이전트의 의도 분류기입니다.
사용자의 질문을 아래 6가지 중 하나로 분류하세요.

- price_query: 가격 조회
- shipment_timing: 출하 시기 (언제 출하하면 좋을지)
- shipment_status: 출하 현황 (물량, 출하량)
- weather_impact: 날씨 영향
- market_compare: 시장 비교 (어느 시장이 유리한지)
- general: 그 외 일반 질문

사용자 질문: {query}
"""

@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, min=2, max=20),
    reraise=True,
)
def _classify_intent(query: str):
    return structured_llm.invoke(INTENT_PROMPT.format(query=query))

def intent_router(state: GamgyulState) -> GamgyulState:
    try:
        result = structured_llm.invoke(INTENT_PROMPT.format(query=state["user_query"]))
        state["intent"] = result.intent
        print(f"[intent_router] 분류: {result.intent} ({result.reason})")
    except Exception as e:
        state["retry_count"] = state.get("retry_count", 0) + 1
        state["errors"].append(f"intent_router 오류: {e}")
        state["intent"] = "general"
        print(f"[intent_router] 오류 발생, general로 폴백: {e}")
    return state

def data_fetcher(state: GamgyulState) -> GamgyulState:
    print("[data_fetcher] 실행됨")
    state["fetched_data"] = {}    # TODO: B 작업물 연결 예정
    return state

def analyzer(state: GamgyulState) -> GamgyulState:
    print("[analyzer] 실행됨")
    state["analysis"] = "분석 결과 placeholder"
    return state

def response_generator(state: GamgyulState) -> GamgyulState:
    print("[response_generator] 실행됨")
    state["final_answer"] = "최종 응답 placeholder"
    return state