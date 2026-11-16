# agent/analyzer.py
# C 담당: 질문 유형별 분석
#
# nodes.py의 analyzer 노드가 이 파일의 analyze(state)를 자동으로 불러 씀.
# 입력: state["fetched_data"]  (B의 get_daily_trades / get_forecast 결과)
#       state["params"]["period"], state["intent"]
# 출력: dict  → app.py 화면(metrics, chart, table)과 응답 프롬프트(facts, caveats, weather)에 쓰임
#
# 표기: Yᵢ = i번째 관측값, Ȳ = 표본평균, S = 표본표준편차, n = 표본 수
# 가격은 모두 "거래량 가중평균"(Σ 가격ᵢ×거래량ᵢ / Σ 거래량ᵢ)으로 계산.
#   같은 날 같은 시장에 법인별로 여러 행이 있고, 소량 거래 가격이 극단적인 경우가 많아서.

import json
import math
from typing import Optional

import pandas as pd

# ---------------------------------------------------------------
# 설정값
# ---------------------------------------------------------------
MIN_MARKET_VOLUME = 0.1      # 시장별 표에 넣을 최소 거래량(톤)
LOW_VOLUME_TON = 5           # 기간 총 거래량이 이보다 적으면 "대표성 낮음"
RELIABLE_MARKET_DAYS = 3     # 시장 비교 때 거래일이 이보다 적으면 "참고용"
RELIABLE_MARKET_TON = 1.0    # 시장 비교 때 거래량(톤)이 이보다 적으면 "참고용"
SIMILAR_PCT = 5              # 차이가 이보다 작으면 "비슷해요" (응답 프롬프트 규칙 10과 같게)
MIN_PAIRS = 5                # 세척·흙 짝 비교에 필요한 최소 짝 수
RECENT_DAYS = 14             # "최근 흐름" 비교 기간

STATUS_KO = {
    "cache": "API 연결이 불안정해 저장된 데이터",
    "mock": "테스트용 저장 데이터",
}

# t분포 97.5% 분위수 (95% 신뢰구간용). scipy 없이 쓰려고 표로 둠
_T975 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
         2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
         2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042]


# ---------------------------------------------------------------
# 통계 도우미
# ---------------------------------------------------------------
def t_crit(df: float) -> float:
    """자유도 df의 t 97.5% 분위수 (근사)"""
    if df < 1:
        return float("nan")
    if df <= 30:
        return _T975[int(df) - 1]
    if df <= 40:
        return 2.021
    if df <= 60:
        return 2.000
    if df <= 120:
        return 1.980
    return 1.960


def mean_ci(values) -> dict:
    """Ȳ, S, n, 95% 신뢰구간 (Ȳ ± t·S/√n)"""
    y = pd.Series(values, dtype=float).dropna()
    n = len(y)
    if n == 0:
        return {"n": 0}
    ybar = float(y.mean())
    if n == 1:
        return {"n": 1, "mean": ybar}
    s = float(y.std(ddof=1))
    half = t_crit(n - 1) * s / math.sqrt(n)
    return {"n": n, "mean": ybar, "sd": s, "ci_low": ybar - half, "ci_high": ybar + half}


def welch_diff(a, b) -> dict:
    """두 집단 평균 차이 Ȳa − Ȳb와 95% 신뢰구간 (Welch 방법, 등분산 가정 안 함)"""
    a = pd.Series(a, dtype=float).dropna()
    b = pd.Series(b, dtype=float).dropna()
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return {"na": na, "nb": nb}
    va, vb = a.var(ddof=1) / na, b.var(ddof=1) / nb
    diff = float(a.mean() - b.mean())
    se = math.sqrt(va + vb)
    if se == 0:
        return {"na": na, "nb": nb, "diff": diff}
    df = (va + vb) ** 2 / (va ** 2 / (na - 1) + vb ** 2 / (nb - 1))
    half = t_crit(df) * se
    return {"na": na, "nb": nb, "diff": diff, "ci_low": diff - half, "ci_high": diff + half}


def verdict(diff_pct: Optional[float], ci_low=None, ci_high=None) -> str:
    """차이를 쉬운 말로 판정. 5% 미만이면 비슷, 신뢰구간이 0을 포함하면 불확실"""
    if diff_pct is None:
        return "비교할 데이터가 부족해요"
    if abs(diff_pct) < SIMILAR_PCT:
        return "비슷해요"
    if ci_low is not None and ci_high is not None and ci_low <= 0 <= ci_high:
        return "차이가 있어 보이지만 날마다 가격 변동이 커서 우연일 수도 있어요"
    return "뚜렷한 차이가 있어요"


def pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """(a − b) / b × 100"""
    if a is None or b is None or b == 0:
        return None
    return (a - b) / b * 100


def r0(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x)


def r1(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, 1)


# ---------------------------------------------------------------
# 데이터 정리
# ---------------------------------------------------------------
def records_df(result: Optional[dict]) -> pd.DataFrame:
    """get_daily_trades 결과 → DataFrame (가격 없는 행 제거, 거래량 0 처리)"""
    df = pd.DataFrame((result or {}).get("records") or [])
    if df.empty:
        return df
    df = df.dropna(subset=["price"]).copy()
    df["volume_ton"] = pd.to_numeric(df["volume_ton"], errors="coerce").fillna(0)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["date"] = df["date"].astype(str).str[:10]
    df["pv"] = df["price"] * df["volume_ton"]
    return df


def wavg(df: pd.DataFrame) -> Optional[float]:
    """거래량 가중평균 가격"""
    if df.empty:
        return None
    vol = df["volume_ton"].sum()
    return float(df["pv"].sum() / vol) if vol > 0 else None


def daily_prices(df: pd.DataFrame, by_market: bool = False) -> pd.DataFrame:
    """일별(또는 일별·시장별) 가중평균 가격. 컬럼: date, (market), price, volume_ton"""
    keys = ["date", "market"] if by_market else ["date"]
    g = df.groupby(keys)[["pv", "volume_ton"]].sum()
    g = g[g["volume_ton"] > 0]
    g["price"] = g["pv"] / g["volume_ton"]
    return g[["price", "volume_ton"]].reset_index()


def market_summary(df: pd.DataFrame) -> pd.DataFrame:
    """시장별 가중평균가, 거래량, 거래일수"""
    g = df.groupby("market").agg(pv=("pv", "sum"), volume_ton=("volume_ton", "sum"), days=("date", "nunique"))
    g = g[g["volume_ton"] >= MIN_MARKET_VOLUME]
    g["price"] = g["pv"] / g["volume_ton"]
    return g.sort_values("volume_ton", ascending=False)


def fmt_date(yyyymmdd: Optional[str]) -> Optional[str]:
    """20261101 → 2026년 11월 1일"""
    if not yyyymmdd or len(str(yyyymmdd)) != 8:
        return yyyymmdd
    s = str(yyyymmdd)
    return f"{int(s[:4])}년 {int(s[4:6])}월 {int(s[6:])}일"


# ---------------------------------------------------------------
# 공통 분석: 품목별 요약 (모든 질문 유형에서 기본으로 실행)
# ---------------------------------------------------------------
def summarize_cultivars(fetched: dict, out: dict) -> dict:
    """품목별 가중평균가·거래량·전년 대비. 품목별 DataFrame을 돌려줌"""
    frames = {}
    for cultivar, result in (fetched.get("jeju_hub") or {}).items():
        df = records_df(result)
        if df.empty:
            out["caveats"].append(f"{cultivar}: 조회 기간에 거래 데이터가 없어요.")
            continue
        frames[cultivar] = df

        avg = wavg(df)
        prev_df = records_df((fetched.get("jeju_hub_prev") or {}).get(cultivar))
        prev_avg = wavg(prev_df) if not prev_df.empty else None
        change = pct(avg, prev_avg)
        total_vol = float(df["volume_ton"].sum())

        out["facts"][cultivar] = {
            "가중평균가(원/kg)": r0(avg),
            "총거래량(톤)": r1(total_vol),
            "거래일수": int(df["date"].nunique()),
            "거래 시장 수": int(df["market"].nunique()),
        }
        if prev_avg:
            out["facts"][cultivar]["전년 같은 기간 가중평균가(원/kg)"] = r0(prev_avg)
            out["facts"][cultivar]["전년 대비 변동률(%)"] = r1(change)
            out["facts"][cultivar]["전년 대비 판정"] = verdict(change)

        if total_vol < LOW_VOLUME_TON:
            out["caveats"].append(f"{cultivar}: 조회 기간 총 거래량이 적어(5톤 미만) 가격의 대표성이 낮아요.")

        if avg:
            out["metrics"].append({
                "label": f"{cultivar} 가중평균가",
                "value": f"{avg:,.0f}원/kg",
                "delta": f"{change:+.1f}% (전년 대비)" if change is not None else None,
            })
    return frames


def daily_chart(frames: dict) -> Optional[dict]:
    """품목별 일별 가중평균 가격 추이 (선 그래프)"""
    parts = []
    for cultivar, df in frames.items():
        d = daily_prices(df)
        d["cultivar"] = cultivar
        parts.append(d)
    if not parts:
        return None
    pivot = pd.concat(parts).pivot_table(index="date", columns="cultivar", values="price").round().reset_index()
    return {
        "title": "일별 가중평균 가격 (원/kg)", "x": "date", "type": "line",
        "y": [c for c in pivot.columns if c != "date"],
        "data": json.loads(pivot.to_json(orient="records")),
    }


def market_table(frames: dict, top: int = 8) -> list:
    rows = []
    for cultivar, df in frames.items():
        for market, row in market_summary(df).head(top).iterrows():
            rows.append({
                "품목": cultivar, "시장": market,
                "가중평균가(원/kg)": r0(row["price"]),
                "거래량(톤)": r1(row["volume_ton"]),
                "거래일수": int(row["days"]),
            })
    return rows


# ---------------------------------------------------------------
# 질문 유형별 분석
# ---------------------------------------------------------------
def analyze_price(frames: dict, out: dict):
    """가격 조회: 최근 14일 vs 그 이전 기간의 흐름"""
    for cultivar, df in frames.items():
        d = daily_prices(df)
        if d["date"].nunique() < 4:
            continue
        last = pd.to_datetime(d["date"]).max()
        cut = (last - pd.Timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
        recent, before = df[df["date"] > cut], df[df["date"] <= cut]
        if recent.empty or before.empty:
            continue
        ra, ba = wavg(recent), wavg(before)
        change = pct(ra, ba)
        diff = welch_diff(daily_prices(recent)["price"], daily_prices(before)["price"])
        out["facts"][cultivar]["최근 흐름"] = {
            f"최근 {RECENT_DAYS}일 가중평균가(원/kg)": r0(ra),
            "그 이전 기간 가중평균가(원/kg)": r0(ba),
            "변동률(%)": r1(change),
            "판정": verdict(change, diff.get("ci_low"), diff.get("ci_high")),
        }


def analyze_market(frames: dict, out: dict, target_market: Optional[str]):
    """시장 비교: 시장별 가중평균가, 믿을 만한 시장끼리의 차이"""
    chart_rows = {}
    for cultivar, df in frames.items():
        ms = market_summary(df)
        ok = (ms["days"] >= RELIABLE_MARKET_DAYS) & (ms["volume_ton"] >= RELIABLE_MARKET_TON)
        reliable = ms[ok]
        info = {
            "시장별 가중평균가(원/kg)": {m: r0(p) for m, p in ms["price"].head(8).items()},
            "거래일·거래량이 적어 참고용인 시장": list(ms.index[~ok])[:8],
        }
        if len(reliable) >= 2:
            hi, lo = reliable["price"].idxmax(), reliable["price"].idxmin()
            gap = reliable.loc[hi, "price"] - reliable.loc[lo, "price"]
            info["가장 비싼 시장"] = {"시장": hi, "가중평균가(원/kg)": r0(reliable.loc[hi, "price"])}
            info["가장 싼 시장"] = {"시장": lo, "가중평균가(원/kg)": r0(reliable.loc[lo, "price"])}
            info["두 시장 차이(원/kg)"] = r0(gap)
            info["두 시장 차이(%)"] = r1(pct(reliable.loc[hi, "price"], reliable.loc[lo, "price"]))
            # 날마다 들쭉날쭉한지: 두 시장의 일별 가격으로 차이 신뢰구간
            dm = daily_prices(df, by_market=True)
            diff = welch_diff(dm[dm["market"] == hi]["price"], dm[dm["market"] == lo]["price"])
            info["판정"] = verdict(info["두 시장 차이(%)"], diff.get("ci_low"), diff.get("ci_high"))
        else:
            out["caveats"].append(
                f"{cultivar}: 거래일 {RELIABLE_MARKET_DAYS}일·거래량 {RELIABLE_MARKET_TON:g}톤 이상인 시장이 2곳 미만이라 시장 비교의 신뢰도가 낮아요."
            )

        if target_market:
            hits = [m for m in ms.index if target_market.replace("시장", "") in m]
            if hits:
                m = hits[0]
                others = df[df["market"] != m]
                info["요청한 시장"] = {
                    "시장": m, "가중평균가(원/kg)": r0(ms.loc[m, "price"]),
                    "나머지 시장 가중평균가(원/kg)": r0(wavg(others)),
                    "차이(%)": r1(pct(ms.loc[m, "price"], wavg(others))),
                }
            else:
                out["caveats"].append(f"{cultivar}: 조회 기간에 '{target_market}' 거래가 없어요.")

        out["facts"][cultivar]["시장 비교"] = info
        for m, p in ms["price"].head(8).items():
            chart_rows.setdefault(m, {"market": m})[cultivar] = r0(p)

    if chart_rows:
        out["chart"] = {
            "title": "시장별 가중평균 가격 (원/kg, 거래량 많은 순)", "x": "market", "type": "bar",
            "y": list(frames.keys()), "data": list(chart_rows.values()),
        }


def analyze_wash_vs_soil(frames: dict, out: dict):
    """세척·흙 비교: 같은 날·같은 시장끼리 짝지어 가격 차이 (시장·날짜 차이에 따른 왜곡 제거)"""
    if "세척당근" not in frames or "흙당근" not in frames:
        out["caveats"].append("세척당근과 흙당근 중 한쪽 데이터가 없어 비교할 수 없어요.")
        return
    w = daily_prices(frames["세척당근"], by_market=True)
    s = daily_prices(frames["흙당근"], by_market=True)
    pairs = w.merge(s, on=["date", "market"], suffixes=("_wash", "_soil"))

    wa, sa = wavg(frames["세척당근"]), wavg(frames["흙당근"])
    info = {
        "세척당근 전체 가중평균가(원/kg)": r0(wa),
        "흙당근 전체 가중평균가(원/kg)": r0(sa),
        "전체 기준 차이(원/kg)": r0(wa - sa) if wa and sa else None,
        "같은 날·같은 시장 짝 수": int(len(pairs)),
    }
    if len(pairs) >= MIN_PAIRS:
        d = pairs["price_wash"] - pairs["price_soil"]          # Yᵢ = 짝별 가격 차이
        st = mean_ci(d)                                        # Ȳ, S, 95% CI
        diff_pct = pct(pairs["price_wash"].mean(), pairs["price_soil"].mean())
        info["짝 비교 평균 차이(원/kg)"] = r0(st["mean"])
        info["짝 비교 차이 표준편차(원/kg)"] = r0(st.get("sd"))
        info["짝 비교 95% 신뢰구간(원/kg)"] = [r0(st.get("ci_low")), r0(st.get("ci_high"))]
        info["짝 비교 차이(%)"] = r1(diff_pct)
        info["판정"] = verdict(diff_pct, st.get("ci_low"), st.get("ci_high"))
        info["해석 기준"] = "전체 평균은 시장·날짜 구성 차이가 섞여 있어, 같은 날·같은 시장 짝 비교 결과를 우선으로 봐요."
        out["metrics"].append({
            "label": "세척 − 흙 (같은 날·시장)",
            "value": f"{st['mean']:+,.0f}원/kg",
            "delta": f"{diff_pct:+.1f}%" if diff_pct is not None else None,
        })
    else:
        info["판정"] = "같은 날·같은 시장에서 둘 다 거래된 경우가 적어 전체 평균끼리만 비교했어요"
        out["caveats"].append(
            f"세척·흙당근이 같은 날 같은 시장에서 함께 거래된 경우가 {len(pairs)}건뿐이라 비교 신뢰도가 낮아요."
        )
    info["주의"] = "세척 비용·운송비는 데이터에 없어서 실제 수익 차이는 농가 비용을 함께 따져야 해요."
    out["facts"]["세척·흙 비교"] = info


def analyze_months(frames: dict, out: dict):
    """출하 시기: 월별 가중평균가 비교 (일별 가격으로 차이의 불확실성까지)"""
    chart_rows = {}
    for cultivar, df in frames.items():
        df = df.assign(ym=df["date"].str[:7])
        months = sorted(df["ym"].unique())
        if len(months) < 2:
            continue
        monthly = {m: r0(wavg(df[df["ym"] == m])) for m in months}
        info = {"월별 가중평균가(원/kg)": monthly}
        for m, p in monthly.items():
            chart_rows.setdefault(m, {"month": m})[cultivar] = p

        if len(months) == 2:   # "1월 vs 2월" 같은 두 달 비교
            a, b = months
            da = daily_prices(df[df["ym"] == a])["price"]
            db = daily_prices(df[df["ym"] == b])["price"]
            diff = welch_diff(db, da)
            change = pct(monthly[b], monthly[a])
            info["두 달 비교"] = {
                "앞 달": a, "뒤 달": b,
                "뒤 달 − 앞 달(원/kg)": r0(monthly[b] - monthly[a]) if monthly[a] and monthly[b] else None,
                "변동률(%)": r1(change),
                "판정": verdict(change, diff.get("ci_low"), diff.get("ci_high")),
                "비교에 쓴 거래일 수": {"앞 달": diff.get("nb", 0), "뒤 달": diff.get("na", 0)},
            }
        out["facts"][cultivar]["출하 시기"] = info

    if chart_rows:
        out["chart"] = {
            "title": "월별 가중평균 가격 (원/kg)", "x": "month", "type": "bar",
            "y": list(frames.keys()), "data": list(chart_rows.values()),
        }
    out["caveats"].append("과거 같은 시기의 가격 흐름이며, 올해 가격이 같게 움직인다는 보장은 없어요.")


def analyze_volume(frames: dict, fetched: dict, out: dict):
    """거래량 현황: 하루 평균 거래량, 전년 대비, 최근 흐름"""
    for cultivar, df in frames.items():
        per_day = df.groupby("date")["volume_ton"].sum()
        st = mean_ci(per_day)
        info = {
            "거래일 하루 평균 거래량(톤)": r1(st.get("mean")),
            "하루 거래량 표준편차(톤)": r1(st.get("sd")),
            "가장 많이 거래된 날": {"날짜": per_day.idxmax(), "거래량(톤)": r1(per_day.max())} if len(per_day) else None,
        }
        prev_df = records_df((fetched.get("jeju_hub_prev") or {}).get(cultivar))
        if not prev_df.empty:
            prev_total, total = float(prev_df["volume_ton"].sum()), float(df["volume_ton"].sum())
            change = pct(total, prev_total)
            info["전년 같은 기간 총거래량(톤)"] = r1(prev_total)
            info["전년 대비 거래량 변동률(%)"] = r1(change)
            info["판정"] = verdict(change)
        out["facts"][cultivar]["거래량"] = info

    parts = []
    for cultivar, df in frames.items():
        d = df.groupby("date")["volume_ton"].sum().rename(cultivar)
        parts.append(d)
    if parts:
        v = pd.concat(parts, axis=1).fillna(0).round(2).reset_index()
        out["chart"] = {
            "title": "일별 거래량 (톤)", "x": "date", "type": "bar",
            "y": list(frames.keys()), "data": json.loads(v.to_json(orient="records")),
        }


def analyze_weather(fetched: dict, out: dict):
    """기상 예보 요약과 출하 위험일"""
    weather = fetched.get("weather")
    if not weather:
        return
    risks = []
    for d in weather.get("daily", []):
        if d.get("wind_max", 0) >= 10:
            risks.append(f"{d['date']} 강풍 주의 (최대 {d['wind_max']}m/s)")
        if d.get("pop_max", 0) >= 60 and d.get("rain_hours", 0) >= 5:
            risks.append(f"{d['date']} 비 예보 (강수확률 {d['pop_max']}%, 약 {d['rain_hours']}시간)")
        if d.get("tmp_min") is not None and d["tmp_min"] <= 0:
            risks.append(f"{d['date']} 영하권 추위 (최저 {d['tmp_min']}℃)")
    out["weather"] = {"location": weather.get("location"), "daily": weather.get("daily"), "risks": risks}
    out["caveats"].append("날씨가 가격을 얼마나 바꾸는지는 이 데이터로 확인할 수 없어요. 예보는 앞으로 약 4일 범위예요.")


# ---------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------
def analyze(state: dict) -> dict:
    fetched = state.get("fetched_data") or {}
    params = state.get("params") or {}
    period = params.get("period") or {}
    intent = state.get("intent") or "general"

    out = {"metrics": [], "table": [], "facts": {}, "caveats": [], "intent": intent}
    if period:
        out["data_period"] = f"{fmt_date(period.get('start'))} ~ {fmt_date(period.get('end'))}"
        if period.get("prev_start"):
            out["compare_period"] = f"{fmt_date(period.get('prev_start'))} ~ {fmt_date(period.get('prev_end'))}"

    frames = summarize_cultivars(fetched, out)

    if frames:
        out["chart"] = daily_chart(frames)
        out["table"] = market_table(frames)

        if intent == "price_query":
            analyze_price(frames, out)
        elif intent == "market_compare":
            analyze_market(frames, out, params.get("market"))
        elif intent == "wash_vs_soil":
            analyze_wash_vs_soil(frames, out)
        elif intent == "shipment_timing":
            analyze_months(frames, out)
        elif intent == "volume_status":
            analyze_volume(frames, fetched, out)

    analyze_weather(fetched, out)

    if period.get("note"):
        out["caveats"].append(period["note"])

    # 데이터 상태: live가 아니면 화면·답변에 안내
    statuses = {r.get("data_status") for k in ("jeju_hub", "jeju_hub_prev") for r in (fetched.get(k) or {}).values()}
    if fetched.get("weather"):
        statuses.add(fetched["weather"].get("data_status"))
    statuses -= {"live", None}
    if statuses:
        names = ", ".join(STATUS_KO.get(s, s) for s in sorted(statuses))
        out["caveats"].append(f"실시간 데이터가 아니라 {names} 기준이에요.")
    out["data_status"] = sorted(statuses) or ["live"]

    if out.get("chart") is None:
        out.pop("chart", None)
    return out
