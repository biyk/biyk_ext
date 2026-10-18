# planner/action.py — модель действия токена.
#
# Соответствует JS-контракту extensions/deepVoyager/actions/api.js:
# список [{"action": ..., "conf": {...}}], где action ∈ move|target|use|message.
from dataclasses import dataclass, field
from typing import Any, Dict

ACTION_MOVE = "move"
ACTION_TARGET = "target"
ACTION_USE = "use"
ACTION_MESSAGE = "message"

VALID_ACTIONS = (ACTION_MOVE, ACTION_TARGET, ACTION_USE, ACTION_MESSAGE)

# 8 направлений, принимаемых move.js на стороне Foundry
DIRECTIONS = (
    "up", "down", "left", "right",
    "upleft", "upright", "downleft", "downright",
)


@dataclass(frozen=True)
class Action:
    """Одно действие из плана хода. conf: {direction} | {id} | {itemId} | {language, text}."""
    action: str
    conf: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.action not in VALID_ACTIONS:
            raise ValueError(f"Недопустимый тип действия: {self.action!r}")
        # защитная копия: внешний dict не должен менять уже созданное действие
        object.__setattr__(self, "conf", dict(self.conf))

    def to_dict(self) -> Dict[str, Any]:
        return {"action": self.action, "conf": dict(self.conf)}


def move_action(direction: str) -> Action:
    if direction not in DIRECTIONS:
        raise ValueError(f"Недопустимое направление: {direction!r}")
    return Action(ACTION_MOVE, {"direction": direction})


def target_action(token_id: str) -> Action:
    return Action(ACTION_TARGET, {"id": token_id})


def use_action(item_id: str) -> Action:
    return Action(ACTION_USE, {"itemId": item_id})
