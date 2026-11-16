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
# 저장 데이터 기준 세척당근 1월 1,509원/kg, 2월 1,204원/kg, 변동률 -20.2%

ANSWERS = {
    "좋은 답변 (통과해야 함)": (
        "세척당근은 1월이 더 높았어요(1,509 vs 1,204원/kg, 2월이 20.2% 낮음).\n"
        "흙당근은 1,033원과 1,062원으로 비슷해요.\n"
        "다만 거래일 수가 적어 차이가 우연일 수도 있어요.\n"
        "2026년 1월 1일 ~ 2026년 2월 28일, 테스트용 저장 데이터 기준이에요."
    ),
    "숫자를 지어낸 답변 (실패해야 함)": (
        "세척당근은 1월이 1,850원/kg으로 2월보다 35% 높았어요. 테스트용 저장 데이터 기준이에요."
    ),
    "미래 단정 + 내부 용어 (실패해야 함)": (
        "1월에 내면 무조건 이득이에요. data_status는 mock이에요."
    ),
    "숫자 날짜 (실패해야 함)": (
        "20260101 ~ 20260228 기간 세척당근 평균은 1,230원/kg이에요. 저장된 데이터 기준이에요."
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
