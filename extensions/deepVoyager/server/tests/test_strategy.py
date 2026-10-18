# tests/test_strategy.py — перебор кандидатов StrategyEnumerator (пункт 4).
from conftest import make_npc, make_scene_payload, make_weapon
from planner.context import BattleContext
from planner.strategy import PATH_MODES, StrategyEnumerator


def ctx_of(**over):
    return BattleContext.from_payload({**make_scene_payload(), **over})


def candidates_of(ctx):
    return list(StrategyEnumerator(ctx).enumerate())


def test_two_modes_per_enemy():
    candidates = candidates_of(ctx_of())  # один враг B
    assert [c.kind for c in candidates] == list(PATH_MODES)
    assert all(c.target_id == "B" for c in candidates)


def test_no_hostiles_no_candidates():
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("N", 450, 0, disposition=0)]
    ctx = BattleContext.from_payload({**make_scene_payload(npcs=npcs), "token": None})
    assert candidates_of(ctx) == []


def test_direct_path_truncated_to_speed_and_scored():
    direct = next(c for c in candidates_of(ctx_of()) if c.kind == "direct")
    moves = [a for a in direct.actions if a.action == "move"]
    assert len(moves) == 6                       # speed 30 = 6 клеток
    assert direct.actions[0].action == "target" and direct.actions[0].conf == {"id": "B"}
    assert direct.score == 6.0                   # 9 -> 3 клетки по прямой
    assert not any(a.action == "use" for a in direct.actions)  # оружия нет — атаки нет


def test_attack_appended_when_final_cell_reaches_target():
    # B соседом (клетка (0,1)); quin ведёт ровно 1 шаг right — вставать на цель
    # нельзя, шаг срезается; атака возможна с места: 0 сближения + 30
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("B", 50, 0, disposition=1)]
    ctx = BattleContext.from_payload(
        {**make_scene_payload(npcs=npcs, weapons=[make_weapon("sword")]), "speed": 50})
    direct = next(c for c in candidates_of(ctx) if c.kind == "direct")
    assert [a.action for a in direct.actions] == ["target", "use"]
    assert direct.actions[-1].conf == {"itemId": "sword"}
    assert direct.score == 30.0


def test_diagonal_neighbour_is_within_melee_reach():
    # B по диагонали (клетка (1,1)): после двух шагов прямая 0 — атака возможна
    npcs = [make_npc("A", 0, 0, disposition=-1), make_npc("B", 50, 50, disposition=1)]
    ctx = BattleContext.from_payload(
        {**make_scene_payload(npcs=npcs, weapons=[make_weapon("sword")]), "speed": 50})
    direct = next(c for c in candidates_of(ctx) if c.kind == "direct")
    assert direct.actions[-1].action == "use"


def test_candidates_are_generated_lazily():
    # enumerate — генератор: потребитель вправе остановиться до конца перебора
    gen = StrategyEnumerator(ctx_of()).enumerate()
    first = next(gen)
    assert first.kind == "direct"
    assert next(gen).kind == "los"
