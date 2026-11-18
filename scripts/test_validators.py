# scripts/test_validators.py
# validators.py 단독 테스트: 저장 데이터로 분석 결과를 만들고, 좋은 답변·나쁜 답변을 검사
# 실행: py scripts/test_validators.py
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from agent.analyzer import analyze
from agent.validators import retry_hint, validate
from test_analyzer import CASES, build_state

analysis = analyze(build_state("shipment_timing", CASES["shipment_timing"]))

# 좋은 답변은 현재 저장 데이터의 분석 결과 숫자로 만듦 (데이터가 바뀌어도 테스트가 맞게)
w = analysis["facts"]["세척당근"]["출하 시기"]
s = analysis["facts"]["흙당근"]["출하 시기"]
w1, w2 = w["월별 가중평균가(원/kg)"]["2026-01"], w["월별 가중평균가(원/kg)"]["2026-02"]
s1, s2 = s["월별 가중평균가(원/kg)"]["2026-01"], s["월별 가중평균가(원/kg)"]["2026-02"]
w_pct = abs(w["두 달 비교"]["변동률(%)"])

ANSWERS = {
    "좋은 답변 (통과해야 함)": (
        f"세척당근은 1월 {w1:,}원/kg, 2월 {w2:,}원/kg으로 {w_pct}% 차이가 났어요.\n"
        f"흙당근은 1월 {s1:,}원/kg, 2월 {s2:,}원/kg이에요.\n"
        "다만 날마다 가격 변동이 커서 차이가 우연일 수도 있어요.\n"
        "2026년 1월 1일 ~ 2026년 2월 28일, 테스트용 저장 데이터 기준이에요."
    ),
    "숫자를 지어낸 답변 (실패해야 함)": (
        f"세척당근은 1월이 {w1 + 777:,}원/kg으로 2월보다 35% 높았어요. 테스트용 저장 데이터 기준이에요."
    ),
    "미래 단정 + 내부 용어 (실패해야 함)": (
        "1월에 내면 무조건 이득이에요. data_status는 mock이에요."
    ),
    "틀린 연도 (실패해야 함)": (
        f"세척당근은 지난해 같은 기간(2025년) 1월 {w1:,}원/kg이었어요. 우연일 수도 있어요. 테스트용 저장 데이터 기준이에요."
    ),
    "숫자 날짜 (실패해야 함)": (
        f"20260101 ~ 20260228 기간 세척당근 1월 평균은 {w1:,}원/kg이에요. 저장된 데이터 기준이에요."
    ),
}

if __name__ == "__main__":
    for name, ans in ANSWERS.items():
        v = validate(ans, analysis)
        mark = "✅ 통과" if v["passed"] else "❌ 실패"
        print(f"\n[{name}] → {mark} (숫자 {v['checked_numbers']}개 검사)")
        for i in v["issues"]:
            print(f"  - 문제: {i}")
        for w in v["warnings"]:
            print(f"  - 참고: {w}")
        if not v["passed"]:
            print("  재생성 힌트:\n    " + retry_hint(v).replace("\n", "\n    "))
