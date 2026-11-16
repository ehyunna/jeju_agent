# agent/validators.py
# 임시 검증기 (A 작성). C의 validators.py가 올라오면 이 파일을 교체하면 됨.
# 약속: validate(state) -> {"passed": bool, "issues": [str, ...]}
import json
import re

# 숫자 + 단위. 이 단위가 붙은 숫자만 "근거 있는 숫자인지" 검사한다 (날짜·번호 오검출 방지)
NUM_RE = re.compile(r"(\d[\d,]*\.?\d*)\s*(원/kg|원|톤|%|℃|도|m/s)")
# 프롬프트 규칙에 나오는 기준값은 분석 결과에 없어도 허용
ALLOWED = {("%", 5.0), ("℃", 0.0), ("도", 0.0)}
BANNED_CERTAINTY = re.compile(r"(반드시 (오릅|오를|내릴|내립)|확실히 (오|내)|오를 것입니다|내릴 것입니다|틀림없이)")
ENGLISH_STATUS = re.compile(r"\b(cache|mock|live)\b", re.IGNORECASE)
PROMPT_LEAK = re.compile(r"(\[분석 결과\]|분석 결과에 있는|나란히 보여 주|규칙 ?\d|이 규칙|market_focus|facts\b)")
MARKET_RE = re.compile(r"[가-힣]{2,8}도매")
WEATHER_WORDS =re.compile(r"(강풍|풍속|강수|강수확률|비 예보|최저기온|최고기온|기온)")


def _numbers_in(obj, out):
    """분석 결과(dict/list/str)에서 모든 숫자를 모은다."""
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, str):
        for m in re.finditer(r"\d[\d,]*\.?\d*", obj):
            try:
                out.add(float(m.group().replace(",", "")))
            except ValueError:
                pass
    elif isinstance(obj, dict):
        for v in obj.values():
            _numbers_in(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers_in(v, out)


def _supported(value: float, decimals: int, pool: set) -> bool:
    """답변 속 숫자가 pool의 어떤 값을 같은 자릿수로 반올림한 것과 같으면 근거 있음"""
    for c in pool:
        if round(c, decimals) == round(value, decimals):
            return True
        if abs(c - value) <= 0.5 * 10 ** -decimals + 1e-9:
            return True
    return False


def _derived(base: set) -> set:
    """LLM이 두 값에서 계산했을 수 있는 차이와 변동률(%)"""
    vals = sorted(v for v in base if v > 0)[:80]
    out = set()
    for a in vals:
        for b in vals:
            if a != b:
                out.add(abs(a - b))
                out.add(abs(a - b) / b * 100)
    return out


def validate(state) -> dict:
    answer = (state.get("final_answer") or "").strip()
    analysis = state.get("analysis")
    issues = []

    if len(answer) < 20:
        issues.append("답변이 너무 짧거나 비어 있어요.")
        return {"passed": False, "issues": issues}

    if ENGLISH_STATUS.search(answer):
        issues.append("cache/mock/live 같은 영어 상태값이 답변에 그대로 나와요. 한글로 풀어 쓰세요.")
    if BANNED_CERTAINTY.search(answer):
        issues.append("미래 가격을 단정하는 표현이 있어요. 과거 데이터 기반 참고라고만 쓰세요.")
    if PROMPT_LEAK.search(answer):
        issues.append("지시문(규칙) 내용이 답변에 그대로 들어갔어요. 농가에게 하는 말로 다시 쓰세요.")

    # 분석 결과가 있는 질문만 숫자·주의사항 검사
    if isinstance(analysis, dict) and analysis:
        without_chart = {k: v for k, v in analysis.items() if k != "chart"}
        base, pool = set(), set()
        _numbers_in(without_chart, base)
        _numbers_in(analysis, pool)
        pool |= _derived(base)

        for m in NUM_RE.finditer(answer):
            raw, unit = m.group(1), m.group(2)
            try:
                value = float(raw.replace(",", ""))
            except ValueError:
                continue
            if (unit, value) in ALLOWED:
                continue
            decimals = len(raw.split(".")[1]) if "." in raw else 0
            if not _supported(value, decimals, pool):
                issues.append(f"'{m.group(0)}'은 분석 결과에서 확인되지 않는 숫자예요. 분석 결과에 있는 숫자만 쓰세요.")

        caveats = " ".join(analysis.get("caveats") or [])
        if "대표성이 낮아요" in caveats and not re.search(r"(대표성|단정|적어|참고)", answer):
            issues.append("거래량이 적다는 주의가 있는데 답변에 한계 설명이 없어요. 단정하지 말고 한계를 밝히세요.")

        analysis_text = json.dumps(analysis, ensure_ascii=False, default=str)
        for name in sorted(set(MARKET_RE.findall(answer))):
            if name not in analysis_text:
                issues.append(f"'{name}'은 분석 결과에 없는 시장이에요. 분석 결과에 나온 시장만 쓰세요.")

        if "weather" not in analysis and WEATHER_WORDS.search(answer):
            issues.append("날씨 데이터를 가져오지 않았는데 날씨를 언급했어요. 날씨 이야기는 빼세요.")

    return {"passed": not issues, "issues": issues}
