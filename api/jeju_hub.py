"""제주데이터허브 「농산물 품종별 일일 거래 정보」 API 클라이언트"""
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from config import JEJU_HUB_KEY, JEJU_HUB_TRADE_URL, USE_MOCK_DATA

SOURCE = "제주데이터허브 「농산물 품종별 일일 거래 정보」 (원출처: aT 도매유통정보시스템)"
SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshot"
COLS = {
    "baseDate": "date", "cultivar": "cultivar", "wholesaleMarket": "market",
    "corporation": "corporation", "wholesalePrice": "price",
    "transactionVolume": "volume_ton", "transactionAmount": "amount_mil",
}


PAGE_LIMIT = 100  # 허브는 limit 없이 요청하면 10건만 주고, 200 이상은 서버 오류(500/502)가 남


def _call(cultivar, start, end, tries=5):
    """허브 서버가 502를 자주 내서 실패하면 1, 2, 3...초 기다렸다 재시도. 응답 JSON 전체를 반환"""
    url = f"{JEJU_HUB_TRADE_URL}/{JEJU_HUB_KEY}"
    params = {"startDate": start, "endDate": end, "cultivar": cultivar, "limit": PAGE_LIMIT}
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=15)
            if r.status_code == 200:
                return r.json()
        except (requests.RequestException, ValueError):
            pass
        time.sleep(1 + i)
    raise ConnectionError(f"허브 API {tries}회 실패: {cultivar} {start}~{end}")


def _request(cultivar, start, end, tries=5):
    """기간 내 전체 거래 기록. 응답에 hasMore=True면 기간을 반으로 나눠 나머지도 모두 가져옴"""
    j = _call(cultivar, start, end, tries)
    data = j.get("data", [])
    if j.get("hasMore") and start < end:
        s = datetime.strptime(start, "%Y%m%d")
        e = datetime.strptime(end, "%Y%m%d")
        mid = s + (e - s) / 2
        mid = datetime(mid.year, mid.month, mid.day)
        left_end = mid.strftime("%Y%m%d")
        right_start = (mid + timedelta(days=1)).strftime("%Y%m%d")
        return _request(cultivar, start, left_end, tries) + _request(cultivar, right_start, end, tries)
    return data


def _to_df(rows):
    if not rows:
        return pd.DataFrame(columns=list(COLS.values()))
    df = pd.DataFrame(rows).rename(columns=COLS)[list(COLS.values())]
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
    for c in ["price", "volume_ton", "amount_mil"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # 같은 날·시장·법인이라도 가격·거래량이 다르면 별개 거래라 모두 남기고, 모든 값이 같은 행만 하나로 합침
    return df.drop_duplicates()


def _save_snapshot(cultivar, df):
    if df.empty:
        return
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{cultivar}.csv"
    if path.exists():
        df = pd.concat([pd.read_csv(path), df])
    # 같은 날·시장·법인에 거래가 여러 건일 수 있으므로 모든 값이 같은 행만 중복으로 제거
    df = df.drop_duplicates(list(COLS.values()), keep="last").sort_values(["date", "market"])
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _load_snapshot(cultivar, start, end):
    path = SNAPSHOT_DIR / f"{cultivar}.csv"
    if not path.exists():
        return pd.DataFrame(columns=list(COLS.values()))
    df = pd.read_csv(path)
    s, e = f"{start[:4]}-{start[4:6]}-{start[6:]}", f"{end[:4]}-{end[4:6]}-{end[6:]}"
    return df[(df["date"] >= s) & (df["date"] <= e)]


def get_daily_trades(cultivar: str, start: str, end: str) -> dict:
    """품종의 시장·법인별 일일 거래 기록. start, end는 'YYYYMMDD'"""
    status = "live"
    if USE_MOCK_DATA:
        df, status = _load_snapshot(cultivar, start, end), "mock"
    else:
        try:
            df = _to_df(_request(cultivar, start, end))
            _save_snapshot(cultivar, df)
        except ConnectionError:
            df, status = _load_snapshot(cultivar, start, end), "cache"
    return {
        "cultivar": cultivar,
        "start": start,
        "end": end,
        "unit": {"price": "원/kg", "volume_ton": "톤", "amount_mil": "백만원"},
        "records": df.to_dict("records"),
        "source": SOURCE,
        "data_status": status,   # live: 실시간 / cache: API 실패로 저장본 사용 / mock: 테스트
    }
