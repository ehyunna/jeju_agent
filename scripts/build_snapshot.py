import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from api.jeju_hub import get_daily_trades

for cultivar in ["세척당근", "흙당근", "월동무"]:
    for m in pd.period_range("2023-11", "2026-11", freq="M"):
        start, end = m.start_time.strftime("%Y%m%d"), m.end_time.strftime("%Y%m%d")
        res = get_daily_trades(cultivar, start, end)
        print(cultivar, m, len(res["records"]), res["data_status"])