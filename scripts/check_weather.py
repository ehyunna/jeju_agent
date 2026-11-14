import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.weather import get_forecast, latlon_to_grid

print("구좌읍 격자:", latlon_to_grid(33.5226, 126.8540))
res = get_forecast("구좌읍")
print("발표 시각:", res["base"], "| 상태:", res["data_status"])
for d in res["daily"]:
    print(d)