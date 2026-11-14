"""제주데이터허브 「농산물 품종별 일일 거래 정보」 API 클라이언트"""
import time
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


def _request(cultivar, start, end, tries=5):
    """허브 서버가 502를 자주 내서 실패하면 1, 2, 3...초 기다렸다 재시도"""
    url = f"{JEJU_HUB_TRADE_URL}/{JEJU_HUB_KEY}"
    params = {"startDate": start, "endDate": end, "cultivar": cultivar}
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=15)
            if r.status_code == 200:
                return r.json().get("data", [])
        except (requests.RequestException, ValueError):
            pass
        time.sleep(1 + i)
    raise ConnectionError(f"허브 API {tries}회 실패: {cultivar} {start}~{end}")


def _to_df(rows):
    if not rows:
        return pd.DataFrame(columns=list(COLS.values()))
    df = pd.DataFrame(rows).rename(columns=COLS)[list(COLS.values())]
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
    for c in ["price", "volume_ton", "amount_mil"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _save_snapshot(cultivar, df):
    if df.empty:
        return
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{cultivar}.csv"
    if path.exists():
        df = pd.concat([pd.read_csv(path), df])
    df = df.drop_duplicates(["date", "market", "corporation"], keep="last").sort_values(["date", "market"])
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