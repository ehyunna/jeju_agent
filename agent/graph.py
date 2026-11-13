# agent/graph.py
from langgraph.graph import StateGraph, END
from agent.state import GamgyulState
from agent.nodes import intent_router, data_fetcher, analyzer, response_generator

def build_graph():
    graph = StateGraph(GamgyulState)

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

def run_agent(user_query: str) -> GamgyulState:
    app = build_graph()
    initial_state: GamgyulState = {
        "user_query": user_query,
        "intent": None,
        "fetched_data": {},
        "analysis": None,
        "final_answer": None,
        "errors": [],
        "retry_count": 0,
    }
    return app.invoke(initial_state)

if __name__ == "__main__":
    result = run_agent("오늘 감귤 출하하면 좋을까?")
    print("\n=== 최종 결과 ===")
    print(result)