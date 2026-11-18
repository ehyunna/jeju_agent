"""실시간(live) 조회와 저장본(snapshot)이 같은 결과를 주는지 비교.
저장본은 건드리지 않음 (실시간 결과를 저장하지 않고 비교만 함)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.jeju_hub import _request, _to_df, _load_snapshot

CASES = [
    ("세척당근", "20260101", "20260131"),
    ("세척당근", "20261001", "20261031"),
    ("흙당근", "20260101", "20260131"),
    ("흙당근", "20261001", "20261031"),
]


def summary(df):
    if df.empty:
        return 0, 0.0, 0.0
    vol = df["volume_ton"].sum()
    wavg = (df["price"] * df["volume_ton"]).sum() / vol if vol else 0.0
    return len(df), round(vol, 1), round(wavg)


print(f"{'품종':6} {'기간':19} | {'저장본 건수·거래량·가중평균':28} | {'실시간 건수·거래량·가중평균':28} | 일치")
ok_all = True
for cultivar, s, e in CASES:
    snap = summary(_load_snapshot(cultivar, s, e))
    try:
        live = summary(_to_df(_request(cultivar, s, e)))
    except ConnectionError as err:
        print(f"{cultivar:6} {s}~{e} | 실시간 조회 실패: {err}")
        ok_all = False
        continue
    same = snap == live
    ok_all &= same
    fmt = lambda t: f"{t[0]:>5}건 {t[1]:>8}톤 {t[2]:>6}원/kg"
    print(f"{cultivar:6} {s}~{e} | {fmt(snap):28} | {fmt(live):28} | {'O' if same else 'X'}")

print("\n결과:", "모두 일치" if ok_all else "차이 있음 (위 표 확인)")
