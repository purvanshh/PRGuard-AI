from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from pydantic import TypeAdapter, validate_call

from prguard_ai.schemas.context import ReviewContext
from prguard_ai.llm.client import generate_analysis, extract_json_obj_from_llm_response

logger = logging.getLogger(__name__)

# Validator for coordinator LLM response structure
_coordinator_response_adapter: TypeAdapter[dict[str, list[str]]] | None = None


def _get_coordinator_adapter() -> TypeAdapter[dict[str, list[str]]]:
    global _coordinator_response_adapter
    if _coordinator_response_adapter is None:
        _coordinator_response_adapter = TypeAdapter(dict[str, list[str]])
    return _coordinator_response_adapter


class CoordinatorAgent:
    """Agent that moderates the multi-agent debate and checks stopping conditions."""

    @staticmethod
    def convergence_state(context: ReviewContext) -> Dict[str, Any]:
        """Return deterministic debate state used for stopping and observability."""
        outputs = context.agent_outputs
        active_agents = sorted(outputs)
        high_agents = sorted(
            name
            for name, output in outputs.items()
            if any(issue.severity.lower() == "high" for issue in output.issues)
        )
        unresolved_high_disagreement = bool(high_agents) and len(high_agents) < len(active_agents)
        latest_guidance = [item for item in context.coordinator_guidance[-3:] if item.strip()]
        silent_latest_round = False
        if active_agents and len(context.dialogue) >= len(active_agents):
            last_turns = context.dialogue[-len(active_agents):]
            silent_latest_round = all(not turn.message.strip() for turn in last_turns)
        return {
            "active_agents": active_agents,
            "high_severity_agents": high_agents,
            "unresolved_high_disagreement": unresolved_high_disagreement,
            "pending_guidance_count": len(latest_guidance),
            "silent_latest_round": silent_latest_round,
        }

    @staticmethod
    def _fallback_guidance(context: ReviewContext) -> Dict[str, List[str]]:
        critiques: List[str] = []
        steering: List[str] = []
        outputs = context.agent_outputs

        if outputs.get("security") and outputs.get("logic"):
            security_high = any(issue.severity == "high" for issue in outputs["security"].issues)
            logic_high = any(issue.severity == "high" for issue in outputs["logic"].issues)
            if security_high != logic_high:
                critiques.append(
                    "Security Agent: reconcile your severity assessment with Logic Agent and explain whether exploitability depends on runtime context."
                )
                critiques.append(
                    "Logic Agent: respond to Security Agent on whether the changed code can actually be reached with attacker-controlled input."
                )

        if outputs.get("style") and outputs.get("logic"):
            if outputs["style"].issues and not outputs["logic"].issues:
                steering.append("Should the logic review treat the style findings as maintainability risks that hide correctness issues?")
            if outputs["logic"].issues and not outputs["style"].issues:
                steering.append("Does the implementation remain understandable enough for future maintainers despite the logic concerns?")

        if not critiques:
            critiques.append("Each agent: challenge one assumption from another agent and either defend or retract your strongest finding.")
        if not steering:
            steering.append("What single unresolved disagreement would most change the final review if clarified?")
        return {"critiques": critiques[:3], "steering_questions": steering[:3]}

    @classmethod
    def moderate_round(cls, context: ReviewContext) -> Dict[str, List[str]]:
        """Produce targeted critiques and steering questions for the next refinement round."""
        summary = {
            name: [issue.model_dump() for issue in output.issues[:5]]
            for name, output in context.agent_outputs.items()
        }
        prompt = (
            "You are the PRGuard AI coordinator moderating a code-review debate. "
            "Read the per-agent findings and return JSON with two arrays: "
            "`critiques` and `steering_questions`. Each critique must address a specific agent by name. "
            "Be concise and focus on disagreements or evidence gaps.\n\n"
            f"Round: {context.round}\n"
            f"Findings: {json.dumps(summary, indent=2)}\n"
        )
        try:
            text, _usage = generate_analysis(
                prompt,
                max_tokens=400,
                temperature=0.0,
                pr_id=context.repo_metadata.get("pr_id") if context.repo_metadata else context.pr_id,
            )
            data = json.loads(extract_json_obj_from_llm_response(text))
            _get_coordinator_adapter().validate_python(data)
            critiques = [str(item).strip() for item in data.get("critiques", []) if str(item).strip()]
            steering = [str(item).strip() for item in data.get("steering_questions", []) if str(item).strip()]
            if critiques or steering:
                return {"critiques": critiques[:3], "steering_questions": steering[:3]}
        except Exception as exc:
            logger.info("Coordinator fell back to heuristic guidance: %s", exc)
        return cls._fallback_guidance(context)

    @staticmethod
    def should_stop(
        context: ReviewContext,
        max_rounds: int = 3,
        consecutive_no_change_rounds: int = 0,
    ) -> bool:
        """
        Determine if the multi-agent dialogue should terminate.

        Stopping conditions:
        - Max rounds reached.
        - Consecutive rounds without any modifications to agent outputs (consecutive_no_change_rounds >= 2).
        - No active discussion (e.g. all agents sent empty messages in the latest round).
        """
        if context.round >= max_rounds:
            logger.info("Coordinator: Max rounds (%s) reached. Stopping.", max_rounds)
            return True

        if consecutive_no_change_rounds >= 2:
            logger.info("Coordinator: No changes to findings for 2 consecutive rounds. Converged. Stopping.")
            return True

        state = CoordinatorAgent.convergence_state(context)
        if state["unresolved_high_disagreement"] and context.round < max_rounds:
            logger.info("Coordinator: High-severity disagreement remains unresolved. Continuing debate.")
            return False

        unresolved = [g for g in context.coordinator_guidance[-3:] if g.strip()]
        if consecutive_no_change_rounds >= 1 and not unresolved:
            logger.info("Coordinator: No unresolved steering guidance remains. Stopping.")
            return True

        # If we have dialogue history, check the latest round of turns (one per active agent)
        if state["silent_latest_round"]:
            logger.info("Coordinator: All agents are silent in the latest round. Converged. Stopping.")
            return True

        return False
