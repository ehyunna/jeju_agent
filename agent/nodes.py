# agent/nodes.py
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
MIN_DAY_VOLUME = 0.3     # 일별 추이 차트에 넣을 하루 최소 거래량(톤). 소량 거래일의 튀는 가격 제외
WEATHER_KEYWORDS = ["날씨", "기온", "한파", "강풍", "태풍", "예보", "추위", "바람"]
# "많은 편이야?"처럼 기준이 있어야 답할 수 있는 의도: 비교 연도를 말하지 않으면 직전 기간(기준 기간)을 함께 가져온다.
# (전년과 비교하면 2026년 3월부터 허브 집계 범위가 늘어 왜곡되므로, 같은 해 안의 최근 기간을 기준으로 삼음)
AUTO_BASELINE = {"volume_status"}
BASELINE_DAYS = 90
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
    if intent == "shipment_timing":
        # 예보는 앞으로 며칠뿐이라, 질문한 기간이 이번 달(또는 기간 미지정)일 때만 날씨를 가져온다
        months = [str(m) for m in (params.get("months") or [])]
        need_weather = not months or date.today().strftime("%Y%m") in months
    if intent != "general" and any(w in (state.get("user_query") or "") for w in WEATHER_KEYWORDS):
        need_weather = True  # 의도가 섞여도 질문에 날씨 이야기가 있으면 예보를 같이 가져온다
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
        if intent in AUTO_BASELINE and not prev_start:
            base_end = start - timedelta(days=1)
            base_start = start - timedelta(days=BASELINE_DAYS)
            params["period"]["base_start"], params["period"]["base_end"] = _fmt(base_start), _fmt(base_end)
            fetched["jeju_hub_base"] = {}
            for c in cultivars:
                try:
                    fetched["jeju_hub_base"][c] = get_daily_trades(c, _fmt(base_start), _fmt(base_end))
                except Exception as e:  # noqa: BLE001
                    state["errors"].append(f"기준 기간 허브 데이터 조회 실패({c}): {e}")

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
        prev_avg = prev_vol = None
        prev_result = (fetched.get("jeju_hub_prev") or {}).get(cultivar)
        if prev_result:
            prev_df = _records_df(prev_result)
            if not prev_df.empty:
                prev_avg = _wavg(prev_df)
                prev_vol = float(prev_df["volume_ton"].sum())
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
            (m1, a1), (m2, a2) = sorted(monthly.items())[-2:]
            facts[cultivar]["최근 월 대비 변동"] = {"기준": f"{m1} → {m2}", "변동률(%)": round((a2 - a1) / a1 * 100, 1)}
        if prev_vol:
            vol = float(df["volume_ton"].sum())
            facts[cultivar]["전년 같은 기간 총거래량(톤)"] = round(prev_vol, 1)
            facts[cultivar]["전년 대비 거래량 변동률(%)"] = round((vol - prev_vol) / prev_vol * 100, 1)
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

    if "세척당근" in facts and "흙당근" in facts:  # 두 품목 가격 차이는 코드로 계산해 LLM이 틀리지 않게 한다
        w, s = facts["세척당근"].get("가중평균가(원/kg)"), facts["흙당근"].get("가중평균가(원/kg)")
        if w and s:
            pct = (s - w) / w * 100
            verdict = "비슷함(차이 5% 미만)" if abs(pct) < 5 else (
                "흙당근이 세척당근보다 높음" if pct > 0 else "세척당근이 흙당근보다 높음")
            facts["세척-흙 비교"] = {
                "세척당근 가중평균가(원/kg)": w, "흙당근 가중평균가(원/kg)": s,
                "흙당근-세척당근 차이(원/kg)": s - w, "차이율(%) (세척당근 기준)": round(pct, 1),
                "판정": verdict,
            }

    analysis = {
        "metrics": metrics,
        "table": table,
        "facts": facts,
        "data_period": f"{period.get('start')} ~ {period.get('end')}" if period else None,
        "caveats": caveats,
    }

    market = (params.get("market") or "").strip()
    stem = re.sub(r"(도매시장|도매|시장|청과)$", "", market)
    if stem:  # 질문에서 지정한 시장은 거래량이 적어도 따로 보여 준다 (예: '가락시장' → '서울가락도매')
        focus = []
        for cultivar, result in (fetched.get("jeju_hub") or {}).items():
            df = _records_df(result)
            sub = df[df["market"].str.contains(stem, regex=False)] if not df.empty else df
            if sub.empty:
                continue
            avg = _wavg(sub) or float(sub["price"].mean())
            focus.append({
                "품목": cultivar, "시장": ", ".join(sorted(sub["market"].unique())),
                "가중평균가(원/kg)": round(avg), "거래량(톤)": round(float(sub["volume_ton"].sum()), 1),
            })
        analysis["market_focus"] = {
            "요청 시장": market,
            "결과": focus or "조회 기간에 해당 시장의 거래 기록이 없어요",
        }

    if daily_frames:  # 일별 가중평균 추이 차트
        all_df = pd.concat(daily_frames)
        g = all_df.groupby(["date", "cultivar"])[["pv", "volume_ton"]].sum()
        major = g[g["volume_ton"] >= MIN_DAY_VOLUME]
        g = major if not major.empty else g[g["volume_ton"] > 0]  # 전부 소량이면 그대로 표시
        g = g.copy()
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
            f"17. 실시간 데이터가 아니라 {', '.join(STATUS_KO.get(s, s) for s in statuses)} 기준임을 답변 끝에 한 줄로 밝히세요.\n"
            if statuses else ""
        )
        prompt = RESPONSE_PROMPT.format(
            status_note=status_note,
            intent=state.get("intent"),
            query=query,
            analysis=json.dumps(shown, ensure_ascii=False, default=str, indent=1),
        )

    # 검증에 실패해 다시 쓰는 경우: 이전 답변과 문제점을 알려 준다
    validation = state.get("validation") or {}
    if state.get("retry_count", 0) > 0 and validation.get("issues"):
        from agent.validators import retry_hint  # C 담당: 실패 이유를 프롬프트 문장으로 변환
        prompt += f"\n\n[이전 답변]\n{state.get('final_answer') or ''}\n\n{retry_hint(validation)}\n"

    try:
        state["final_answer"] = _text(with_retry(lambda: llm.invoke(prompt)).content).strip()
        print("[response_generator] 완료")
    except Exception as e:  # noqa: BLE001
        state["errors"].append(f"response_generator 오류: {e}")
        state["final_answer"] = _fallback_answer(analysis)
        print(f"[response_generator] 오류, 기본 답변으로 대체: {e}")
    return state


# ---------------------------------------------------------------
# 5) 검증 / 재시도 준비
# ---------------------------------------------------------------
def validator(state: CarrotState) -> CarrotState:
    """답변 검증. C의 validate(답변, 분석 결과) + A의 추가 검사(extra_issues)"""
    state.setdefault("errors", [])
    try:
        from agent.validators import validate  # C 담당
        from agent.validators_extra import extra_issues  # A 담당: 규칙 문장 유출, 분석에 없는 시장 이름
        answer, analysis = state.get("final_answer"), state.get("analysis")
        result = validate(answer, analysis)
        extra = extra_issues(answer, analysis, state.get("user_query"))
        if extra:
            result["issues"] = list(result.get("issues") or []) + extra
            result["passed"] = False
    except Exception as e:  # noqa: BLE001  검증기 자체 오류는 답변을 막지 않고 기록만 남김
        state["errors"].append(f"validator 오류: {e}")
        result = {"passed": True, "issues": [], "warnings": [f"검증기 오류로 검증을 건너뛰었어요: {e}"]}
    state["validation"] = result
    status = "통과" if result.get("passed") else f"실패 {result.get('issues')}"
    print(f"[validator] {status} (retry_count={state.get('retry_count', 0)})")
    return state


def retry_prep(state: CarrotState) -> CarrotState:
    """검증 실패 후 답변을 다시 만들기 전에 재시도 횟수를 올린다"""
    state["retry_count"] = state.get("retry_count", 0) + 1
    print(f"[retry_prep] 답변 재생성 {state['retry_count']}회차")
    return state
