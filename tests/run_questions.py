# tests/run_questions.py
# 테스트 질문 일괄 실행.
#   python -W ignore -m tests.run_questions          → 의도 분류만 검사 (빠르고 저렴)
#   python -W ignore -m tests.run_questions --full   → 전체 흐름 실행 (검증 통과/재시도, 답변 확인)
# 결과는 tests/results.csv 로 저장됨 (엑셀로 열어 기획서·결과 설명자료에 사용)
import csv
import sys
import time
from pathlib import Path

from tests.questions import QUESTIONS

OUT = Path(__file__).resolve().parent / "results.csv"


def check_params(case, params):
    """질문에 명시된 품목·월·시장이 제대로 추출됐는지. 틀린 항목 문자열 목록 반환"""
    bad = []
    if case.get("product") and params.get("product") != case["product"]:
        bad.append(f"product={params.get('product')}")
    if case.get("months") and sorted(params.get("months") or []) != sorted(case["months"]):
        bad.append(f"months={params.get('months')}")
    if case.get("market") and params.get("market") != case["market"]:
        bad.append(f"market={params.get('market')}")
    return bad


def main():
    full = "--full" in sys.argv
    if full:
        from agent.graph import run_agent
    else:
        from agent.nodes import _classify_intent

    rows, ok_intent, ok_params = [], 0, 0
    for i, case in enumerate(QUESTIONS, 1):
        q = case["q"]
        row = {"번호": i, "질문": q, "기대의도": case["intent"]}
        try:
            if full:
                r = run_agent(q)
                intent, params = r.get("intent"), r.get("params") or {}
                v = r.get("validation") or {}
                row.update({
                    "검증": "통과" if v.get("passed") else "실패",
                    "재시도": r.get("retry_count", 0),
                    "오류": " | ".join(r.get("errors") or []),
                    "답변": (r.get("final_answer") or "").replace("\n", " "),
                })
            else:
                res = _classify_intent(q)
                intent, params = res.intent, res.params.model_dump()
        except Exception as e:  # noqa: BLE001
            intent, params = "ERROR", {}
            row["오류"] = str(e)

        accepted = [case["intent"]] + case.get("also_ok", [])
        intent_ok = intent in accepted
        bad = check_params(case, params)
        ok_intent += intent_ok
        ok_params += not bad
        row.update({
            "실제의도": intent,
            "의도결과": "O" if intent_ok else "X",
            "파라미터결과": "O" if not bad else "X " + ", ".join(bad),
            "추출파라미터": str(params),
            "비고": case.get("note", ""),
        })
        rows.append(row)
        print(f"{i:>2}. [{'O' if intent_ok else 'X'}] {q}  → {intent}"
              + (f"  (파라미터 불일치: {', '.join(bad)})" if bad else ""))
        time.sleep(0.5)  # 무료 티어 429 방지

    n = len(QUESTIONS)
    print(f"\n의도 정확도 {ok_intent}/{n}, 파라미터 정확도 {ok_params}/{n}")

    fields = list(dict.fromkeys(k for r in rows for k in r))
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"결과 저장: {OUT}")


if __name__ == "__main__":
    main()
