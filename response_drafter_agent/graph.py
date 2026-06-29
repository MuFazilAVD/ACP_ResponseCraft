"""LangGraph-compatible Plan-Reason-Act-Reflect graph."""

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
            self.agent.plan_node,
            self.agent.reason_node,
            self.agent.retrieve_node,
            self.agent.act_node,
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
    graph.add_node("plan", agent.plan_node)
    graph.add_node("reason", agent.reason_node)
    graph.add_node("retrieve", agent.retrieve_node)
    graph.add_node("act", agent.act_node)
    graph.add_node("reflect", agent.reflect_node)
    graph.add_node("render", agent.render_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "reason")
    graph.add_edge("reason", "retrieve")
    graph.add_edge("retrieve", "act")
    graph.add_edge("act", "reflect")
    graph.add_edge("reflect", "render")
    graph.add_edge("render", END)
    return graph.compile()
