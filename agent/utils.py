# agent/utils.py
# 외부 라이브러리 없이 쓰는 간단한 재시도 헬퍼 (A: LLM 429, B: 허브 502 공용)
import time
from typing import Callable, TypeVar

from config import RETRY_TRIES, RETRY_BASE_SECONDS

T = TypeVar("T")

RATE_LIMIT_WAIT = 10  # 429(한도 초과)일 때 기본 대기 초. 시도마다 늘어남


def _is_rate_limit(e: Exception) -> bool:
    text = str(e)
    return "429" in text or "RESOURCE_EXHAUSTED" in text or "rate limit" in text.lower()


def with_retry(fn: Callable[[], T], tries: int = RETRY_TRIES, base: float = RETRY_BASE_SECONDS) -> T:
    """fn()을 실패 시 base*2^i 초 쉬며 최대 tries번 시도. 마지막 실패는 그대로 raise.
    429(요청 한도 초과)일 때는 10초, 20초... 로 더 오래 기다린다."""
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            delay = base * 2 ** i
            if _is_rate_limit(e):
                delay = max(delay, RATE_LIMIT_WAIT * (i + 1))
                print(f"[retry] 429 감지, {delay:.0f}초 대기 후 재시도 ({i + 1}/{tries - 1})")
            time.sleep(delay)
    raise RuntimeError("unreachable")
