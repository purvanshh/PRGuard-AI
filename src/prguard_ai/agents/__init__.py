"""Agent package for PRGuard AI."""

from prguard_ai.agents.base_agent import BaseAgent
from prguard_ai.agents.style_agent import StyleAgent
from prguard_ai.agents.logic_agent import LogicAgent
from prguard_ai.agents.security_agent import SecurityAgent


def get_agent_by_name(name: str):
    """Retrieve the agent class by its string name."""
    name = name.lower()
    if name == "style":
        return StyleAgent
    elif name == "logic":
        return LogicAgent
    elif name == "security":
        return SecurityAgent
    else:
        raise ValueError(f"Unknown agent: {name}")


__all__ = ["BaseAgent", "StyleAgent", "LogicAgent", "SecurityAgent", "get_agent_by_name"]
