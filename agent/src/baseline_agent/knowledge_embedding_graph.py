from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from baseline_agent.knowledge_embedding import configured_encoder, load_model_protocol


class EmbeddingState(TypedDict, total=False):
    requested_by: str
    texts: list[str]
    kind: str
    embeddings: list[list[float]]
    revision: str


def embed(state: EmbeddingState) -> EmbeddingState:
    if state.get("requested_by") != "spring" or state.get("kind") not in ("QUERY", "DOCUMENT"):
        raise ValueError("编码服务只接受 Spring 的明确编码请求")
    return {
        "embeddings": configured_encoder().encode(state["texts"], query=state["kind"] == "QUERY"),
        "revision": load_model_protocol()["revision"],
    }


builder = StateGraph(EmbeddingState)
builder.add_node("embed", embed)
builder.add_edge(START, "embed")
builder.add_edge("embed", END)
graph = builder.compile()
