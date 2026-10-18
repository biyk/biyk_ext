# tests/test_action.py — модель действия (JS-контракт move/target/use/message).
import pytest

from planner.action import (
    ACTION_MOVE, ACTION_TARGET, ACTION_USE, DIRECTIONS,
    Action, move_action, target_action, use_action,
)


def test_valid_actions_serialize_to_js_shape():
    assert move_action("up").to_dict() == {"action": "move", "conf": {"direction": "up"}}
    assert target_action("abc").to_dict() == {"action": "target", "conf": {"id": "abc"}}
    assert use_action("xyz").to_dict() == {"action": "use", "conf": {"itemId": "xyz"}}


def test_unknown_action_type_rejected():
    with pytest.raises(ValueError):
        Action("fly", {})


@pytest.mark.parametrize("direction", DIRECTIONS)
def test_all_foundry_directions_accepted(direction):
    assert move_action(direction).conf["direction"] == direction


def test_unknown_direction_rejected():
    with pytest.raises(ValueError):
        move_action("north-east")


def test_conf_is_copied_not_shared():
    conf = {"direction": "up"}
    action = Action(ACTION_MOVE, conf)
    conf["direction"] = "down"
    assert action.to_dict()["conf"]["direction"] == "up"


def test_action_constants():
    assert (ACTION_MOVE, ACTION_TARGET, ACTION_USE) == ("move", "target", "use")
    assert len(DIRECTIONS) == 8
