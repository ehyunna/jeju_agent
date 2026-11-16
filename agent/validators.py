# agent/validators.py
# C 담당: LLM 답변 검증 (규칙 기반, LLM 호출 없음)
#
# 사용법 (A의 검증 노드에서):
#   from agent.validators import validate
#   state["validation"] = validate(state["final_answer"], state["analysis"])
#   if not state["validation"]["passed"] and retry_count < MAX_FLOW_RETRIES:
#       → issues를 프롬프트에 붙여 응답을 다시 생성
#
# 반환: {"passed": bool, "issues": [...], "warnings": [...], "checked_numbers": int}
#   issues   = 다시 생성해야 하는 문제 (숫자 지어냄, 금지 표현 등)
#   warnings = 참고용 (재생성까지는 필요 없음)

import re
from typing import Any, Iterable, List, Optional

# 분석 결과에 없는 숫자가 이만큼 이상 나오면 실패
MAX_UNKNOWN_NUMBERS = 0
# 숫자 비교 허용 오차: 반올림·단위 변환 때문에 생기는 작은 차이는 같은 숫자로 봄
REL_TOL = 0.006   # 0.6%
ABS_TOL = 1.0

# 미래를 단정하는 표현 (응답 규칙 4: 미래 가격 단정 금지)
CERTAIN_FUTURE = ["반드시 오를", "반드시 내릴", "확실히 오를", "확실히 내릴", "무조건", "틀림없이",
                  "100%", "보장합니다", "보장해요"]
# 사용자에게 보여주면 안 되는 내부 용어 (응답 규칙 8)
INTERNAL_WORDS = ["cache", "mock", "live", "data_status", "facts", "caveats", "None", "null"]
# 약하게 말했는지 확인할 표현 (대표성 낮음·우연일 수도 있을 때)
HEDGES = ["단정하기 어려", "확실하지", "우연일", "참고", "대표성", "적어서", "적어 ", "가능성", "보이지만", "수도 있"]
STORED_DATA_HINTS = ["저장된 데이터", "저장 데이터", "실시간 데이터가 아니", "실시간이 아니", "테스트용"]
WEATHER_WORDS = ["비 예보", "강수", "강풍", "풍속", "한파", "기온", "날씨"]


# ---------------------------------------------------------------
# 숫자 꺼내기
# ---------------------------------------------------------------
_NUM = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
# 날짜·기간처럼 분석 수치가 아닌 숫자는 검사에서 제외
_SKIP_PATTERNS = [
    r"(?<!\d)20\d{6}(?!\d)",                              # 20260101 (규칙 4에서 따로 검사)
    r"\d{4}\s*년(?:\s*\d{1,2}\s*월)?(?:\s*\d{1,2}\s*일)?",   # 2026년 11월 1일
    r"\d{1,2}\s*월\s*\d{1,2}\s*일",                       # 11월 1일
    r"\d{1,2}\s*월",                                       # 1월
    r"\d{4}-\d{2}(?:-\d{2})?",                             # 2026-01, 2026-01-03
    r"\d+\s*(?:일|시간|주|개월|년)\s*(?:간|동안|전|후|치)?",   # 14일, 4시간, 3년 전
    r"\d+\s*(?:곳|개|건|번|회|가지|위)",                     # 3곳, 7건
    r"[①-⑳]",
]
_SKIP = re.compile("|".join(_SKIP_PATTERNS))


def _to_float(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def numbers_in_answer(text: str) -> List[float]:
    """답변에서 '분석 수치'로 보이는 숫자만 꺼냄 (날짜·개수·기간 제외)"""
    cleaned = _SKIP.sub(" ", text or "")
    nums = []
    for m in _NUM.finditer(cleaned):
        v = _to_float(m.group())
        if v is None:
            continue
        if abs(v) < 10 and "." not in m.group():
            continue   # 0~9 같은 작은 정수는 순서·개수일 때가 많아서 제외
        nums.append(v)
    return nums


def numbers_in_analysis(obj: Any) -> List[float]:
    """분석 결과(dict/list/str)에 들어 있는 모든 숫자"""
    out: List[float] = []
    if obj is None or isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, str):
        out.extend(v for v in (_to_float(m.group()) for m in _NUM.finditer(obj)) if v is not None)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k == "chart":
                continue   # 차트 원자료는 답변 근거로 쓰지 않음
            out.extend(numbers_in_analysis(k))
            out.extend(numbers_in_analysis(v))
    elif isinstance(obj, Iterable):
        for v in obj:
            out.extend(numbers_in_analysis(v))
    return out


def _known(value: float, known: List[float]) -> bool:
    """value가 분석 결과의 어떤 숫자와 (허용 오차 안에서) 같은지.
    부호를 빼고 말하는 경우(-13.3% → 13.3% 낮아요)도 허용."""
    for k in known:
        for v in (value, -value):
            if abs(v - k) <= max(ABS_TOL, abs(k) * REL_TOL):
                return True
    return False


# ---------------------------------------------------------------
# 검증
# ---------------------------------------------------------------
def _contains_any(text: str, words) -> List[str]:
    return [w for w in words if w in text]


def validate(answer: Optional[str], analysis: Any) -> dict:
    issues, warnings = [], []
    text = (answer or "").strip()

    if not text:
        return {"passed": False, "issues": ["답변이 비어 있어요."], "warnings": [], "checked_numbers": 0}

    # 분석 결과가 없는 경우(일반 질문)는 숫자 검사를 하지 않음
    if not isinstance(analysis, dict):
        return {"passed": True, "issues": [], "warnings": [], "checked_numbers": 0}

    # 1) 숫자 근거: 답변의 숫자가 분석 결과에 있는가
    known = numbers_in_analysis(analysis)
    answer_nums = numbers_in_answer(text)
    unknown = [n for n in answer_nums if not _known(n, known)]
    if len(unknown) > MAX_UNKNOWN_NUMBERS:
        shown = ", ".join(f"{n:,.10g}" for n in unknown[:5])
        issues.append(f"분석 결과에 없는 숫자가 있어요: {shown}")

    # 2) 미래 단정 표현
    found = _contains_any(text, CERTAIN_FUTURE)
    if found:
        issues.append(f"미래 가격을 단정하는 표현이 있어요: {', '.join(found)}")

    # 3) 내부 용어 노출
    found = [w for w in INTERNAL_WORDS if re.search(rf"(?<![A-Za-z]){w}(?![A-Za-z])", text)]
    if found:
        issues.append(f"사용자에게 보이면 안 되는 내부 용어가 있어요: {', '.join(found)}")

    # 4) 숫자형 날짜 (20260101) 금지
    if re.search(r"(?<!\d)20\d{6}(?!\d)", text):
        issues.append("날짜를 20260101처럼 숫자로 썼어요. '2026년 1월 1일'처럼 써야 해요.")

    # 5) 날씨 데이터가 없는데 날씨를 언급
    if not analysis.get("weather"):
        found = _contains_any(text, ["비 예보", "강수확률", "강풍", "풍속"])
        if found:
            issues.append(f"날씨 데이터가 없는데 날씨를 언급했어요: {', '.join(found)}")

    # 6) 저장 데이터로 답했으면 그 사실을 밝혔는가
    statuses = analysis.get("data_status") or []
    if isinstance(statuses, str):
        statuses = [statuses]
    if any(s in ("cache", "mock") for s in statuses) and not _contains_any(text, STORED_DATA_HINTS):
        warnings.append("저장된 데이터 기준이라는 안내가 답변에 없어요. (화면 배지로는 표시됨)")

    # 7) 대표성 낮음·우연 가능성이 있는데 단정했는가
    caveats = " ".join(analysis.get("caveats") or [])
    verdicts = " ".join(str(v) for v in _find_values(analysis.get("facts") or {}, "판정"))
    uncertain = "대표성이 낮아요" in caveats or "신뢰도가 낮아요" in caveats or "우연일 수도" in verdicts
    if uncertain and not _contains_any(text, HEDGES):
        warnings.append("분석 결과에 '대표성 낮음/우연일 수도'가 있는데 답변이 단정적으로 보여요.")

    # 8) 너무 긴 답변 (응답 규칙 6: 10줄 이내)
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) > 14:
        warnings.append(f"답변이 {len(lines)}줄로 길어요. (권장 10줄 이내)")

    return {
        "passed": not issues,
        "issues": issues,
        "warnings": warnings,
        "checked_numbers": len(answer_nums),
    }


def _find_values(obj: Any, key: str) -> List[Any]:
    """중첩 dict에서 특정 키의 값을 모두 찾기"""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                found.append(v)
            found.extend(_find_values(v, key))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(_find_values(v, key))
    return found


def retry_hint(validation: dict) -> str:
    """검증 실패 시 응답을 다시 만들 때 프롬프트 끝에 붙일 문장"""
    if not validation or validation.get("passed"):
        return ""
    lines = ["[이전 답변의 문제점 — 반드시 고쳐서 다시 쓰세요]"]
    lines += [f"- {i}" for i in validation.get("issues", [])]
    lines.append("- 숫자는 [분석 결과]에 있는 값만 그대로 쓰세요.")
    return "\n".join(lines)
