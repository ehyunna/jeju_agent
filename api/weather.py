"""기상청 단기예보 조회서비스 클라이언트 (당근 주산지 구좌읍 기준)"""
import json
import math
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import requests

from config import DATA_GO_KR_KEY, USE_MOCK_DATA

URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
SOURCE = "기상청 단기예보 조회서비스 (공공데이터포털)"
SNAPSHOT = Path(__file__).resolve().parent.parent / "data" / "snapshot" / "weather_latest.json"
LOCATIONS = {"구좌읍": (33.5226, 126.8540), "제주시": (33.4996, 126.5312), "서귀포시": (33.2541, 126.5600)}


def latlon_to_grid(lat, lon):
    """위경도 → 기상청 격자(nx, ny). 기상청 공식 변환식"""
    RE, GRID, SLAT1, SLAT2, OLON, OLAT, XO, YO = 6371.00877, 5.0, 30.0, 60.0, 126.0, 38.0, 43, 136
    d = math.pi / 180.0
    re = RE / GRID
    slat1, slat2, olon, olat = SLAT1 * d, SLAT2 * d, OLON * d, OLAT * d
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(
        math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5))
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5) ** sn * math.cos(slat1) / sn
    ro = re * sf / math.tan(math.pi * 0.25 + olat * 0.5) ** sn
    ra = re * sf / math.tan(math.pi * 0.25 + lat * d * 0.5) ** sn
    theta = lon * d - olon
    if theta > math.pi:
        theta -= 2 * math.pi
    if theta < -math.pi:
        theta += 2 * math.pi
    theta *= sn
    return int(ra * math.sin(theta) + XO + 0.5), int(ro - ra * math.cos(theta) + YO + 0.5)


def _base_datetime(now=None):
    """가장 최근 발표 시각. 발표는 02,05,08,11,14,17,20,23시이고 10분쯤 뒤에 조회 가능"""
    t = (now or datetime.now()) - timedelta(minutes=15)
    hours = [h for h in (2, 5, 8, 11, 14, 17, 20, 23) if h <= t.hour]
    if not hours:
        t -= timedelta(days=1)
        return t.strftime("%Y%m%d"), "2300"
    return t.strftime("%Y%m%d"), f"{hours[-1]:02d}00"


def _request(nx, ny, base_date, base_time, tries=4):
    params = {"serviceKey": DATA_GO_KR_KEY, "dataType": "JSON", "numOfRows": 1500, "pageNo": 1,
              "base_date": base_date, "base_time": base_time, "nx": nx, "ny": ny}
    for i in range(tries):
        try:
            r = requests.get(URL, params=params, timeout=15)
            j = r.json()   # 키 오류면 XML이 와서 여기서 ValueError
            if j["response"]["header"]["resultCode"] == "00":
                return j["response"]["body"]["items"]["item"]
        except (requests.RequestException, ValueError, KeyError):
            pass
        time.sleep(1 + i)
    raise ConnectionError(f"기상청 API {tries}회 실패: {base_date} {base_time}")


def _daily_summary(items):
    days = defaultdict(lambda: {"pop_max": 0, "rain_hours": 0, "wind_max": 0.0, "tmp_min": None, "tmp_max": None})
    for it in items:
        day, cat, v = days[it["fcstDate"]], it["category"], it["fcstValue"]
        if cat == "POP":                       # 강수확률(%)
            day["pop_max"] = max(day["pop_max"], int(v))
        elif cat == "PTY" and v != "0":        # 강수형태(0=없음)
            day["rain_hours"] += 1
        elif cat == "WSD":                     # 풍속(m/s)
            day["wind_max"] = max(day["wind_max"], float(v))
        elif cat == "TMP":                     # 1시간 기온(℃)
            t = float(v)
            day["tmp_min"] = t if day["tmp_min"] is None else min(day["tmp_min"], t)
            day["tmp_max"] = t if day["tmp_max"] is None else max(day["tmp_max"], t)
    return [{"date": f"{d[:4]}-{d[4:6]}-{d[6:]}", **v} for d, v in sorted(days.items())]


def _load_snapshot():
    if SNAPSHOT.exists():
        return json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    return None


def get_forecast(location: str = "구좌읍") -> dict:
    """앞으로 약 3일의 일별 날씨 요약"""
    if USE_MOCK_DATA:
        saved = _load_snapshot()
        if saved:
            return {**saved, "data_status": "mock"}
    lat, lon = LOCATIONS.get(location, LOCATIONS["구좌읍"])
    nx, ny = latlon_to_grid(lat, lon)
    base_date, base_time = _base_datetime()
    try:
        daily = _daily_summary(_request(nx, ny, base_date, base_time))
    except ConnectionError:
        saved = _load_snapshot()
        if saved:
            return {**saved, "data_status": "cache"}
        raise
    result = {
        "location": location,
        "grid": {"nx": nx, "ny": ny},
        "base": f"{base_date} {base_time}",
        "daily": daily,
        "unit": {"pop_max": "%", "rain_hours": "시간", "wind_max": "m/s", "tmp_min": "℃", "tmp_max": "℃"},
        "source": SOURCE,
        "data_status": "live",
    }
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result