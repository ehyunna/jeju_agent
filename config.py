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
