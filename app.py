# app.py
# 당근 출하 도우미 - Streamlit 화면
# 실행: streamlit run app.py

import pandas as pd
import streamlit as st

st.set_page_config(page_title="당근 출하 도우미", page_icon="🥕", layout="wide")

# ---------------------------------------------------------------
# 에이전트 불러오기
# (GEMINI_API_KEY가 없거나 패키지가 빠지면 import 단계에서 실패할 수 있어서 화면에 안내)
# ---------------------------------------------------------------
try:
    from agent.graph import run_agent
    AGENT_ERROR = None
except Exception as e:  # noqa: BLE001
    run_agent = None
    AGENT_ERROR = str(e)

INTENT_LABELS = {
    "price_query": "💰 가격 조회",
    "shipment_timing": "⏰ 출하 시기",
    "shipment_status": "📦 거래량 현황",
    "volume_status": "📦 거래량 현황",
    "weather_impact": "🌤 날씨 영향",
    "market_compare": "🏪 시장 비교",
    "wash_vs_soil": "🧼 세척·흙 비교",
    "general": "💬 기타",
}

EXAMPLE_QUESTIONS = [
    "요즘 제주 당근 가격 작년보다 어때?",
    "1월이랑 2월 중에 언제 출하하는 게 나아?",
    "요즘 당근 거래량 많은 편이야?",
    "이번 주 한파 오면 당근 값에 영향 있어?",
    "가락시장이랑 다른 시장 중에 어디가 더 비싸?",
    "세척당근이랑 흙당근 중에 뭐가 더 유리해?",
]


# ---------------------------------------------------------------
# 결과 표시 함수
# analysis가 문자열이어도, dict여도 동작하게 작성
# ---------------------------------------------------------------
def show_analysis(analysis):
    """analyzer 결과를 보여준다. 문자열이면 글로, dict면 숫자 카드·차트·표로."""
    if not analysis:
        return

    if isinstance(analysis, str):
        st.caption(analysis)
        return

    if not isinstance(analysis, dict):
        st.write(analysis)
        return

    # 1) 핵심 숫자 카드: analyzer가 "metrics": [{"label", "value", "delta"}] 형태로 주면 표시
    metrics = analysis.get("metrics") or []
    if metrics:
        cols = st.columns(min(len(metrics), 4))
        for col, m in zip(cols, metrics):
            col.metric(m.get("label", ""), m.get("value", ""), m.get("delta"))

    # 2) 차트: "chart": {"title", "x", "y": [열이름...], "data": [행 dict...], "type": "line"|"bar"}
    chart = analysis.get("chart")
    if chart and chart.get("data"):
        df = pd.DataFrame(chart["data"])
        x = chart.get("x")
        if x and x in df.columns:
            df = df.set_index(x)
        y = chart.get("y")
        if y:
            df = df[[c for c in y if c in df.columns]]
        if chart.get("title"):
            st.markdown(f"**{chart['title']}**")
        if chart.get("type") == "bar":
            st.bar_chart(df)
        else:
            st.line_chart(df)

    # 3) 근거 표: "table": [행 dict...]
    table = analysis.get("table")
    if table:
        st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)

    # 4) 데이터 기간·한계
    if analysis.get("data_period"):
        st.caption(f"📅 데이터 기간: {analysis['data_period']}")
    for c in analysis.get("caveats") or []:
        st.caption(f"⚠️ {c}")


def show_details(result: dict):
    """에이전트가 어떤 과정을 거쳤는지 접이식으로 보여준다."""
    with st.expander("🔍 에이전트가 한 일 보기"):
        intent = result.get("intent")
        st.markdown(f"**질문 유형:** {INTENT_LABELS.get(intent, intent or '-')}")

        fetched = result.get("fetched_data") or {}
        if fetched:
            st.markdown("**불러온 데이터:** " + ", ".join(fetched.keys()))
        else:
            st.markdown("**불러온 데이터:** (아직 연결 전)")

        validation = result.get("validation")
        if validation:
            ok = validation.get("passed") if isinstance(validation, dict) else None
            st.markdown(f"**검증:** {'✅ 통과' if ok else '⚠️ 확인 필요' if ok is False else validation}")
            if isinstance(validation, dict) and validation.get("issues"):
                for issue in validation["issues"]:
                    st.caption(f"- {issue}")

        if result.get("retry_count"):
            st.markdown(f"**재시도 횟수:** {result['retry_count']}")

        for err in result.get("errors") or []:
            st.warning(err)


def show_assistant_message(result: dict):
    st.markdown(result.get("final_answer") or "답변을 만들지 못했어요.")
    show_analysis(result.get("analysis"))

    sources = result.get("sources") or []
    if sources:
        st.caption("📚 출처: " + " · ".join(sources))

    show_details(result)


# ---------------------------------------------------------------
# 사이드바
# ---------------------------------------------------------------
with st.sidebar:
    st.title("🥕 당근 출하 도우미")
    st.write(
        "제주데이터허브의 농산물 거래·기상 데이터를 분석해서 "
        "제주 당근(세척·흙당근)의 출하 시기와 판로 판단을 돕는 AI 에이전트입니다."
    )

    st.subheader("이렇게 물어보세요")
    for q in EXAMPLE_QUESTIONS:
        if st.button(q, use_container_width=True):
            st.session_state.pending_question = q

    st.divider()
    if st.button("대화 지우기", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

    st.caption(
        "※ 과거 데이터 기반 참고 정보이며, 미래 가격을 보장하지 않습니다. "
        "최종 판단은 농가·작목반 상황을 함께 고려하세요."
    )


# ---------------------------------------------------------------
# 본문: 채팅
# ---------------------------------------------------------------
st.header("무엇이든 물어보세요")

if AGENT_ERROR:
    st.error(
        "에이전트를 불러오지 못했어요. `.env`에 GEMINI_API_KEY가 있는지, "
        "`pip install -r requirements.txt`를 했는지 확인해 주세요.\n\n"
        f"상세: {AGENT_ERROR}"
    )

if "messages" not in st.session_state:
    st.session_state.messages = []

# 지난 대화 다시 그리기
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "user":
            st.markdown(msg["content"])
        else:
            show_assistant_message(msg["content"])

# 입력: 채팅창 또는 사이드바 예시 버튼
question = st.chat_input("예: 요즘 제주 당근 가격 작년보다 어때?")
if not question and st.session_state.get("pending_question"):
    question = st.session_state.pop("pending_question")

if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        if run_agent is None:
            result = {"final_answer": "에이전트가 준비되지 않았어요. 위 안내를 확인해 주세요.", "errors": []}
        else:
            with st.spinner("데이터를 찾아보고 분석하는 중이에요..."):
                try:
                    result = run_agent(question)
                except Exception as e:  # noqa: BLE001
                    result = {
                        "final_answer": "분석 중 문제가 생겼어요. 잠시 후 다시 시도해 주세요.",
                        "errors": [f"run_agent 오류: {e}"],
                    }
        show_assistant_message(result)

    st.session_state.messages.append({"role": "assistant", "content": result})
