# agent/nodes.py
import os
from datetime import date

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI# agent/nodes.py
import calendar
import importlib.util
import json
import os
import re
from datetime import date, timedelta

import pandas as pd
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

from agent.prompts import GENERAL_PROMPT, INTENT_PROMPT, RESPONSE_PROMPT
from agent.schemas import IntentClassification
from agent.state import CarrotState
from agent.utils import with_retry
from api.jeju_hub import get_daily_trades
from api.weather import LOCATIONS, get_forecast
from config import LLM_TIMEOUT, MODEL_NAME, PRODUCTS

load_dotenv()

llm = ChatGoogleGenerativeAI(
    model=MODEL_NAME,
    temperature=0,
    google_api_key=os.getenv("GEMINI_API_KEY"),
    timeout=LLM_TIMEOUT,
)

structured_llm = llm.with_structured_output(IntentClassification)

# 의도별로 어떤 데이터를 가져올지: (허브 거래 데이터, 기상 예보)
NEEDS = {
    "price_query": (True, False),
    "shipment_timing": (True, True),
    "volume_status": (True, False),
    "weather_impact": (True, True),   # 가격 수준을 같이 보여 주기 위해 거래 데이터도 가져옴
    "market_compare": (True, False),
    "wash_vs_soil": (True, False),
    "general": (False, False),
}
DEFAULT_DAYS = 60  # 월을 지정하지 않았을 때 최근 며칠을 볼지
MIN_MARKET_VOLUME = 0.1  # 시장별 표에 넣을 최소 거래량(톤). 소량 거래의 이상값 제외
STATUS_KO = {
    "cache": "API 연결이 불안정해 저장된 데이터",
    "mock": "테스트용 저장 데이터",
}


# ---------------------------------------------------------------
# 1) 의도 분류
# ---------------------------------------------------------------
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


# ---------------------------------------------------------------
# 2) 데이터 수집
# ---------------------------------------------------------------
def _shift_year(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 2/29
        return d.replace(year=d.year + years, day=28)


def _resolve_period(params: dict):
    """params에서 조회 기간 (start, end, prev_start, prev_end, note)을 계산"""
    today = date.today()
    note = None
    months = [str(m) for m in (params.get("months") or []) if re.fullmatch(r"\d{6}", str(m))]

    if months:
        y1, m1 = int(min(months)[:4]), int(min(months)[4:])
        y2, m2 = int(max(months)[:4]), int(max(months)[4:])
        start = date(y1, m1, 1)
        end = date(y2, m2, calendar.monthrange(y2, m2)[1])
        shifted = 0
        while start > today:  # 아직 오지 않은 달이면 지난해 같은 기간으로 대체
            start, end = _shift_year(start, -1), _shift_year(end, -1)
            shifted += 1
        if shifted:
            note = f"요청한 기간이 아직 오지 않아 {shifted}년 전 같은 기간의 데이터로 확인했어요."
        end = min(end, today)
    else:
        end = today
        start = today - timedelta(days=DEFAULT_DAYS)

    prev_start = prev_end = None
    cy = params.get("compare_year")
    if cy and cy < start.year:
        diff = cy - start.year
        prev_start, prev_end = _shift_year(start, diff), _shift_year(end, diff)

    return start, end, prev_start, prev_end, note


def _target_cultivars(intent: str, params: dict) -> list:
    product = params.get("product", "both")
    if intent == "wash_vs_soil" or product not in PRODUCTS:
        return list(PRODUCTS)
    return [product]


def _fmt(d: date) -> str:
    return d.strftime("%Y%m%d")


def data_fetcher(state: CarrotState) -> CarrotState:
    state.setdefault("errors", [])
    intent = state.get("intent") or "general"
    params = dict(state.get("params") or {})
    need_trade, need_weather = NEEDS.get(intent, (False, False))
    fetched, sources = {}, []

    if need_trade:
        start, end, prev_start, prev_end, note = _resolve_period(params)
        params["period"] = {"start": _fmt(start), "end": _fmt(end), "note": note}
        cultivars = _target_cultivars(intent, params)
        fetched["jeju_hub"] = {}
        for c in cultivars:
            try:
                fetched["jeju_hub"][c] = get_daily_trades(c, _fmt(start), _fmt(end))
            except Exception as e:  # noqa: BLE001
                state["errors"].append(f"허브 데이터 조회 실패({c}): {e}")
        if prev_start:
            params["period"]["prev_start"], params["period"]["prev_end"] = _fmt(prev_start), _fmt(prev_end)
            fetched["jeju_hub_prev"] = {}
            for c in cultivars:
                try:
                    fetched["jeju_hub_prev"][c] = get_daily_trades(c, _fmt(prev_start), _fmt(prev_end))
                except Exception as e:  # noqa: BLE001
                    state["errors"].append(f"전년 허브 데이터 조회 실패({c}): {e}")

    if need_weather:
        region = params.get("region")
        location = region if region in LOCATIONS else "구좌읍"
        try:
            fetched["weather"] = get_forecast(location)
        except Exception as e:  # noqa: BLE001
            state["errors"].append(f"기상 예보 조회 실패: {e}")

    for key in ("jeju_hub", "jeju_hub_prev"):
        for res in fetched.get(key, {}).values():
            if res.get("source") and res["source"] not in sources:
                sources.append(res["source"])
    if fetched.get("weather", {}).get("source"):
        sources.append(fetched["weather"]["source"])

    state["params"] = params
    state["fetched_data"] = fetched
    state["sources"] = sources
    print(f"[data_fetcher] intent={intent} 가져온 데이터={list(fetched.keys())}")
    return state


# ---------------------------------------------------------------
# 3) 분석 (C의 agent/analyzer.py가 생기면 그걸 우선 사용, 없으면 임시 기본 분석)
# ---------------------------------------------------------------
def _records_df(result: dict) -> pd.DataFrame:
    df = pd.DataFrame(result.get("records") or [])
    if df.empty:
        return df
    df = df.dropna(subset=["price"])
    df["volume_ton"] = df["volume_ton"].fillna(0)
    return df


def _wavg(df: pd.DataFrame):
    """거래량 가중평균 가격. 거래량 합이 0이면 None"""
    vol = df["volume_ton"].sum()
    if vol <= 0:
        return None
    return float((df["price"] * df["volume_ton"]).sum() / vol)


def _basic_analysis(state: CarrotState) -> dict:
    fetched = state.get("fetched_data") or {}
    params = state.get("params") or {}
    period = params.get("period") or {}
    metrics, table, facts, caveats = [], [], {}, []
    daily_frames = []

    for cultivar, result in (fetched.get("jeju_hub") or {}).items():
        df = _records_df(result)
        if df.empty:
            caveats.append(f"{cultivar}: 조회 기간에 거래 데이터가 없어요.")
            continue
        avg = _wavg(df)
        prev_avg = None
        prev_result = (fetched.get("jeju_hub_prev") or {}).get(cultivar)
        if prev_result:
            prev_df = _records_df(prev_result)
            if not prev_df.empty:
                prev_avg = _wavg(prev_df)
        change = (avg - prev_avg) / prev_avg * 100 if avg and prev_avg else None

        facts[cultivar] = {
            "가중평균가(원/kg)": round(avg) if avg else None,
            "총거래량(톤)": round(float(df["volume_ton"].sum()), 1),
            "거래일수": int(df["date"].nunique()),
            "전년 같은 기간 가중평균가(원/kg)": round(prev_avg) if prev_avg else None,
            "전년 대비 변동률(%)": round(change, 1) if change is not None else None,
        }
        monthly = {}
        for ym, part in df.groupby(df["date"].str[:7]):
            m_avg = _wavg(part)
            if m_avg:
                monthly[ym] = round(m_avg)
        if len(monthly) > 1:
            facts[cultivar]["월별 가중평균가(원/kg)"] = monthly
        if float(df["volume_ton"].sum()) < 5:
            caveats.append(f"{cultivar}: 조회 기간 총 거래량이 적어(5톤 미만) 가격의 대표성이 낮아요.")

        if avg:
            metrics.append({
                "label": f"{cultivar} 가중평균가",
                "value": f"{avg:,.0f}원/kg",
                "delta": f"{change:+.1f}% (전년 대비)" if change is not None else None,
            })

        df = df.assign(pv=df["price"] * df["volume_ton"])
        by_market = df.groupby("market")[["pv", "volume_ton"]].sum()
        by_market = by_market[by_market["volume_ton"] >= MIN_MARKET_VOLUME].sort_values("volume_ton", ascending=False).head(8)
        for market, row in by_market.iterrows():
            table.append({
                "품목": cultivar, "시장": market,
                "가중평균가(원/kg)": round(row["pv"] / row["volume_ton"]),
                "거래량(톤)": round(float(row["volume_ton"]), 1),
            })
        daily_frames.append(df.assign(cultivar=cultivar))

    analysis = {
        "metrics": metrics,
        "table": table,
        "facts": facts,
        "data_period": f"{period.get('start')} ~ {period.get('end')}" if period else None,
        "caveats": caveats,
    }

    if daily_frames:  # 일별 가중평균 추이 차트
        all_df = pd.concat(daily_frames)
        g = all_df.groupby(["date", "cultivar"])[["pv", "volume_ton"]].sum()
        g = g[g["volume_ton"] > 0]
        g["avg"] = (g["pv"] / g["volume_ton"]).round()
        pivot = g["avg"].unstack("cultivar").reset_index()
        analysis["chart"] = {
            "title": "일별 가중평균 가격 (원/kg)", "x": "date",
            "y": [c for c in pivot.columns if c != "date"], "type": "line",
            "data": json.loads(pivot.to_json(orient="records")),
        }

    if period.get("note"):
        analysis["caveats"].append(period["note"])

    weather = fetched.get("weather")
    if weather:
        risks = []
        for d in weather.get("daily", []):
            if d["wind_max"] >= 10:
                risks.append(f"{d['date']} 강풍 주의 (최대 {d['wind_max']}m/s)")
            if d["pop_max"] >= 60 and d["rain_hours"] >= 5:
                risks.append(f"{d['date']} 비 예보 (강수확률 {d['pop_max']}%, 약 {d['rain_hours']}시간)")
        analysis["weather"] = {"location": weather.get("location"), "daily": weather.get("daily"), "risks": risks}

    statuses = {r.get("data_status") for k in ("jeju_hub", "jeju_hub_prev") for r in (fetched.get(k) or {}).values()}
    if weather:
        statuses.add(weather.get("data_status"))
    statuses.discard("live")
    statuses.discard(None)
    if statuses:
        names = ", ".join(STATUS_KO.get(s, s) for s in sorted(statuses))
        analysis["caveats"].append(f"실시간 데이터가 아니라 {names} 기준이에요.")
    analysis["data_status"] = sorted(statuses) or ["live"]
    return analysis


def analyzer(state: CarrotState) -> CarrotState:
    state.setdefault("errors", [])
    if (state.get("intent") or "general") == "general":
        state["analysis"] = None
        return state
    try:
        if importlib.util.find_spec("agent.analyzer"):
            from agent.analyzer import analyze  # C 담당 모듈
        else:
            analyze = _basic_analysis
        state["analysis"] = analyze(state)
        print("[analyzer] 완료")
    except Exception as e:  # noqa: BLE001
        state["errors"].append(f"analyzer 오류: {e}")
        state["analysis"] = None
        print(f"[analyzer] 오류: {e}")
    return state


# ---------------------------------------------------------------
# 4) 응답 생성
# ---------------------------------------------------------------
def _text(content) -> str:
    """Gemini 응답 content가 문자열이거나 조각 리스트여도 문자열로 변환"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content)


def _fallback_answer(analysis) -> str:
    """LLM 호출이 실패했을 때 분석 결과만으로 만드는 간단한 답변"""
    if not isinstance(analysis, dict) or not analysis.get("metrics"):
        return "데이터를 가져왔지만 답변을 만들지 못했어요. 잠시 후 다시 시도해 주세요."
    lines = ["답변 생성에 문제가 있어 분석 결과만 보여드려요."]
    for m in analysis["metrics"]:
        lines.append(f"- {m['label']}: {m['value']}" + (f" ({m['delta']})" if m.get("delta") else ""))
    return "\n".join(lines)


def response_generator(state: CarrotState) -> CarrotState:
    state.setdefault("errors", [])
    analysis = state.get("analysis")
    query = state["user_query"]

    if (state.get("intent") or "general") == "general" or not analysis:
        prompt = GENERAL_PROMPT.format(query=query)
    else:
        shown = {k: v for k, v in analysis.items() if k != "chart"} if isinstance(analysis, dict) else analysis
        statuses = [s for s in (analysis.get("data_status") or []) if s != "live"] if isinstance(analysis, dict) else []
        status_note = (
            f"13. 실시간 데이터가 아니라 {', '.join(STATUS_KO.get(s, s) for s in statuses)} 기준임을 답변 끝에 한 줄로 밝히세요.\n"
            if statuses else ""
        )
        prompt = RESPONSE_PROMPT.format(
            status_note=status_note,
            intent=state.get("intent"),
            query=query,
            analysis=json.dumps(shown, ensure_ascii=False, default=str, indent=1),
        )

    try:
        state["final_answer"] = _text(with_retry(lambda: llm.invoke(prompt)).content).strip()
        print("[response_generator] 완료")
    except Exception as e:  # noqa: BLE001
        state["errors"].append(f"response_generator 오류: {e}")
        state["final_answer"] = _fallback_answer(analysis)
        print(f"[response_generator] 오류, 기본 답변으로 대체: {e}")
    return state


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
