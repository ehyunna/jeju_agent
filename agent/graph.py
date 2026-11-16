# agent/graph.py
from langgraph.graph import END, StateGraph

from agent.nodes import (
    analyzer,
    data_fetcher,
    intent_router,
    response_generator,
    retry_prep,
    validator,
)
from agent.state import CarrotState
from config import MAX_FLOW_RETRIES


def route_after_validate(state: CarrotState) -> str:
    """검증 통과하거나 재시도 한도에 도달하면 종료, 아니면 답변을 다시 만든다"""
    passed = (state.get("validation") or {}).get("passed", True)
    if passed or state.get("retry_count", 0) >= MAX_FLOW_RETRIES:
        return "end"
    return "retry"


def build_graph():
    graph = StateGraph(CarrotState)

    graph.add_node("intent_router", intent_router)
    graph.add_node("data_fetcher", data_fetcher)
    graph.add_node("analyzer", analyzer)
    graph.add_node("response_generator", response_generator)
    graph.add_node("validator", validator)
    graph.add_node("retry_prep", retry_prep)

    graph.set_entry_point("intent_router")
    graph.add_edge("intent_router", "data_fetcher")
    graph.add_edge("data_fetcher", "analyzer")
    graph.add_edge("analyzer", "response_generator")
    graph.add_edge("response_generator", "validator")
    graph.add_conditional_edges("validator", route_after_validate, {"end": END, "retry": "retry_prep"})
    graph.add_edge("retry_prep", "response_generator")

    return graph.compile()


def run_agent(user_query: str) -> CarrotState:
    app = build_graph()
    initial_state: CarrotState = {
        "user_query": user_query,
        "intent": None,
        "params": {},
        "fetched_data": {},
        "analysis": None,
        "final_answer": None,
        "validation": None,
        "sources": [],
        "errors": [],
        "retry_count": 0,
    }
    return app.invoke(initial_state)


if __name__ == "__main__":
    result = run_agent("요즘 제주 세척당근 가격 작년보다 어때?")
    print("\n=== 최종 결과 ===")
    print(result)
