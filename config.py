# config.py
# 공통 설정값 (모델명, 재시도 횟수 등). 환경변수로 덮어쓸 수 있음.
import os

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
LLM_TIMEOUT = 15

# 재시도 설정 (agent/utils.py의 with_retry에서 사용)
RETRY_TRIES = 3
RETRY_BASE_SECONDS = 2

# 검증 실패 시 전체 흐름을 다시 도는 최대 횟수 (11/16 작업에서 사용)
MAX_FLOW_RETRIES = 2

PRODUCTS = ["세척당근", "흙당근"]

load_dotenv()  # .env 파일 읽기

# API 키 (.env에서 읽어옴)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

JEJU_HUB_KEY = os.getenv("JEJU_HUB_KEY")
DATA_GO_KR_KEY = os.getenv("DATA_GO_KR_KEY")   # 기상청 단기예보

# true면 API 대신 저장된 데이터(data/snapshot) 사용
USE_MOCK_DATA = os.getenv("USE_MOCK_DATA", "false").lower() == "true"

# 분석 대상 품목
TARGET_CULTIVARS = ["세척당근", "흙당근"]

# 허브 API 주소
JEJU_HUB_TRADE_URL = "https://open.jejudatahub.net/api/proxy/1tb1t233D16Da1b3333tttb266ba11D3"
