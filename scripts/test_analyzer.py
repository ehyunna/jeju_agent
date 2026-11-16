# scripts/test_analyzer.py
# analyzer.py 단독 테스트: LLM·API 없이 data/snapshot 저장 데이터로 질문 유형별 분석 결과를 출력
# 실행: py scripts/test_analyzer.py            (전체 유형)
#       py scripts/test_analyzer.py wash_vs_soil   (한 유형만)
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd

from agent.analyzer import analyze

SNAP = ROOT / "data" / "snapshot"


def trades(cultivar, start, end, status="mock"):
    """get_daily_trades와 같은 모양으로 저장 데이터를 잘라서 반환"""
    df = pd.read_csv(SNAP / f"{cultivar}.csv")
    s, e = f"{start[:4]}-{start[4:6]}-{start[6:]}", f"{end[:4]}-{end[4:6]}-{end[6:]}"
    df = df[(df["date"] >= s) & (df["date"] <= e)]
    return {"cultivar": cultivar, "records": df.to_dict("records"), "data_status": status,
            "source": "제주데이터허브 (저장 데이터)"}


def weather():
    return json.loads((SNAP / "weather_latest.json").read_text(encoding="utf-8")) | {"data_status": "mock"}


BOTH = ["세척당근", "흙당근"]
CASES = {
    "price_query": dict(cultivars=BOTH, period=("20260901", "20261113"), prev=("20250901", "20251113")),
    "market_compare": dict(cultivars=BOTH, period=("20260101", "20261113"), market="가락시장"),
    "wash_vs_soil": dict(cultivars=BOTH, period=("20250101", "20261113")),
    "shipment_timing": dict(cultivars=BOTH, period=("20260101", "20260228"), weather=True),
    "volume_status": dict(cultivars=BOTH, period=("20260101", "20261113"), prev=("20250101", "20251113")),
    "weather_impact": dict(cultivars=BOTH, period=("20260901", "20261113"), weather=True),
}


def build_state(intent, c):
    s, e = c["period"]
    period = {"start": s, "end": e, "note": None}
    fetched = {"jeju_hub": {k: trades(k, s, e) for k in c["cultivars"]}}
    if c.get("prev"):
        ps, pe = c["prev"]
        period.update(prev_start=ps, prev_end=pe)
        fetched["jeju_hub_prev"] = {k: trades(k, ps, pe) for k in c["cultivars"]}
    if c.get("weather"):
        fetched["weather"] = weather()
    return {"intent": intent, "params": {"period": period, "market": c.get("market")}, "fetched_data": fetched}


if __name__ == "__main__":
    only = sys.argv[1:] or list(CASES)
    for intent in only:
        result = analyze(build_state(intent, CASES[intent]))
        shown = {k: v for k, v in result.items() if k not in ("chart", "table")}
        print(f"\n{'=' * 20} {intent} {'=' * 20}")
        print(json.dumps(shown, ensure_ascii=False, indent=1, default=str))
        if result.get("chart"):
            print(f"[chart] {result['chart']['title']} / {len(result['chart']['data'])}행")
        print(f"[table] {len(result.get('table', []))}행")
