# agent/utils.py
# 외부 라이브러리 없이 쓰는 간단한 재시도 헬퍼 (A: LLM 429, B: 허브 502 공용)
import time
from typing import Callable, TypeVar

from config import RETRY_TRIES, RETRY_BASE_SECONDS

T = TypeVar("T")


def with_retry(fn: Callable[[], T], tries: int = RETRY_TRIES, base: float = RETRY_BASE_SECONDS) -> T:
    """fn()을 실패 시 base*2^i 초 쉬며 최대 tries번 시도. 마지막 실패는 그대로 raise."""
    for i in range(tries):
        try:
            return fn()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(base * 2 ** i)
    raise RuntimeError("unreachable")
