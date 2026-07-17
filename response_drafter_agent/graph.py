"""LangGraph-compatible LLM-driven 3-node graph."""

from __future__ import annotations

from typing import Any, Protocol


class InvokableGraph(Protocol):
    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        ...


class SequentialGraph:
    def __init__(self, agent: Any) -> None:
        self.agent = agent

    async def ainvoke(self, state: dict[str, Any]) -> dict[str, Any]:
        for node in (
            self.agent.llm_agent_node,
            self.agent.reflect_node,
            self.agent.render_node,
        ):
            state = await node(state)
        return state


def build_graph(agent: Any) -> InvokableGraph:
    try:
        from langgraph.graph import END, START, StateGraph
    except Exception:
        return SequentialGraph(agent)

    graph = StateGraph(dict)
    graph.add_node("llm_agent", agent.llm_agent_node)
    graph.add_node("reflect", agent.reflect_node)
    graph.add_node("render", agent.render_node)
    graph.add_edge(START, "llm_agent")
    graph.add_edge("llm_agent", "reflect")
    graph.add_edge("reflect", "render")
    graph.add_edge("render", END)
    return graph.compile()

