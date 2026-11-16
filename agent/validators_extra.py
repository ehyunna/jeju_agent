# agent/validators_extra.py
# A 담당: C의 validators.py가 보지 않는 두 가지를 추가로 검사한다.
#   1) 프롬프트 규칙 문장이 답변에 그대로 나오는지 (지시문 유출)
#   2) 분석 결과에 없는 도매시장 이름을 지어냈는지
# 반환: 실패 이유 문자열 리스트 (없으면 [])
import json
import re
from typing import Any, List

PROMPT_LEAK = re.compile(r"(\[분석 결과\]|분석 결과에 있는|나란히 보여 주|규칙 ?\d|이 규칙|market_focus)")
MARKET_RE = re.compile(r"[가-힣]{2,8}도매")


def extra_issues(answer: str, analysis: Any) -> List[str]:
    text = (answer or "").strip()
    issues = []

    if PROMPT_LEAK.search(text):
        issues.append("지시문(규칙) 내용이 답변에 그대로 들어갔어요. 농가에게 하는 말로 다시 쓰세요.")

    if isinstance(analysis, dict) and analysis:
        analysis_text = json.dumps(analysis, ensure_ascii=False, default=str)
        for name in sorted(set(MARKET_RE.findall(text))):
            if name not in analysis_text:
                issues.append(f"'{name}'은 분석 결과에 없는 시장이에요. 분석 결과에 나온 시장만 쓰세요.")

    return issues
