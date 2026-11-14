import os, time, requests
from dotenv import load_dotenv

load_dotenv()
KEY = os.getenv("JEJU_HUB_KEY")
URL = f"https://open.jejudatahub.net/api/proxy/1tb1t233D16Da1b3333tttb266ba11D3/{KEY}"

def call(cultivar, s, e, tries=5):
    for i in range(tries):
        try:
            r = requests.get(URL, params={"startDate": s, "endDate": e, "cultivar": cultivar}, timeout=15)
            if r.status_code == 200:
                return r.json().get("totCnt", "?")
        except requests.RequestException:
            pass
        time.sleep(1 + i)   # 1초, 2초, 3초... 기다렸다 재시도
    return "실패"

cultivars = ["깐마늘", "월동무", "당근", "세척당근", "흙당근", "양배추", "브로콜리",
             "감자", "대파", "비트", "콜라비", "감귤", "한라봉"]
periods = [("20231101", "20231130"), ("20240201", "20240229"), ("20250201", "20250228"),
           ("20251101", "20251130"), ("20261001", "20261031"), ("20261101", "20261112")]

print("품목      | " + "  ".join(s[:6] for s, _ in periods))
for c in cultivars:
    row = [str(call(c, s, e)).rjust(6) for s, e in periods]
    print(f"{c:6s} | " + "  ".join(row))