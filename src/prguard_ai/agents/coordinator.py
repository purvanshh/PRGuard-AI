from __future__ import annotations

import logging
from prguard_ai.schemas.context import ReviewContext

logger = logging.getLogger(__name__)


class CoordinatorAgent:
    """Agent that moderates the multi-agent debate and checks stopping conditions."""

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

        # If we have dialogue history, check the latest round of turns (one per active agent)
        num_agents = len(context.agent_outputs)
        if num_agents > 0 and len(context.dialogue) >= num_agents:
            last_turns = context.dialogue[-num_agents:]
            if all(not turn.message.strip() for turn in last_turns):
                logger.info("Coordinator: All agents are silent in the latest round. Converged. Stopping.")
                return True

        return False
