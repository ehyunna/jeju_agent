# agent/graph.py
from langgraph.graph import END, StateGraph

from agent.nodes import analyzer, data_fetcher, intent_router, response_generator
from agent.state import CarrotState


def build_graph():
    graph = StateGraph(CarrotState)

    graph.add_node("intent_router", intent_router)
    graph.add_node("data_fetcher", data_fetcher)
    graph.add_node("analyzer", analyzer)
    graph.add_node("response_generator", response_generator)

    graph.set_entry_point("intent_router")
    graph.add_edge("intent_router", "data_fetcher")
    graph.add_edge("data_fetcher", "analyzer")
    graph.add_edge("analyzer", "response_generator")
    graph.add_edge("response_generator", END)

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
