# arent/env.py — RL-среда: бой как эпизод (state -> reward -> term/trunc) поверх Simulation.
#
# Никакой политики здесь нет: среда отдаёт наблюдение (тот же формат, что играет модель в
# evaluate.fight), принимает тройку индексов (cell/target/weapon) и считает шаг, награду,
# терминаль. Награда — в ОДНОМ месте shape_reward: ОСНОВА это ИСХОД боя (терминальная
# награда за зачистку/смерть), а НЕ сумма очков Скаллера за раунды. Единственная плотная
# добавка — потенциальный shaping gamma*Phi(s')-Phi(s) (Ng 1999): Phi=замороженный V_ref по
# состоянию, Phi(терминал)=0, поэтому shaping не меняет оптимальную стратегию и не фармится
# очками за движение/урон. rounds_cap — техническое УСЕЧЕНИЕ продолжающегося боя (truncated),
# не настоящий конец игры: терминальной награды за него нет, бутстрап V(s') остаётся.
# Среда детерминирована: Simulation считает ожиданием (без дайсов).
from typing import Any, Callable, Dict, Optional, Tuple

from arent import encode, spec
from arent import joint as joint_mod
from arent import legalize as legalize_mod
from arent import slots as slots_mod
from arent.observe import observe
from arent.tactics_ctx import action_outcome, build_step_ctx
from arent.team_reward import TeamReward
from planner.context import BattleContext
from planner.sim import Simulation

Row = Dict[str, Any]
NONE_INDEX = spec.K_WEAPONS           # последний слот группы «не атаковать» (маска разрешает)


def shape_reward(terminal_reward: float, phi_s: float, phi_next: float,
                 terminated: bool, gamma: float) -> float:
    """Награда = исход боя (только на истинном терминале) + потенциальный shaping.

    Phi(терминального следующего состояния) = 0 по определению — иначе телескопическая
    сумма shaping зависела бы от конца эпизода и могла бы смещать оптимальную политику.
    """
    phi_next_eff = 0.0 if terminated else phi_next
    return round(float(terminal_reward) + (gamma * phi_next_eff - phi_s), 6)


class FightEnv:
    """Один бой = эпизод. reset -> наблюдение; step(тройка) -> (next|None, r, terminated, truncated, info)."""

    def __init__(self, rounds_cap: int = 8, clear_bonus: float = 1.0,
                 death_penalty: float = -1.0, gamma: float = 0.98,
                 phi: Optional[Callable[[Dict[str, Any]], float]] = None,
                 team: Optional[TeamReward] = None, schema: int = spec.SCHEMA):
        self.cap = max(1, int(rounds_cap))
        self.clear_bonus = clear_bonus
        self.death_penalty = death_penalty
        self.gamma = gamma
        self.phi = phi
        self.team = team
        self.schema = int(schema)       # 2 = клетка-действие, 3 = move-plan (реализовано в PolyFightEnv)
        self.state: Optional[Simulation] = None
        self.slots: Any = None
        self._ctx: Any = None
        self.t = 0
        self.phi_s = 0.0
        self._last_reason: Optional[str] = None    # причина последней правки legalization (для диагностики)
        self.shaper: Any = None                     # TacticsShaper|None: тактический shaping (train-only)

    def set_shaper(self, shaper: Any) -> None:
        """Пристегнуть тактический shaping; None — выключить (reward == чистый TeamReward)."""
        self.shaper = shaper

    def anneal(self, iter_index: int, total_iters: int) -> None:
        """Пробросить позицию обучения λ(iter) из PPO-цикла в shaper (§1.3)."""
        if self.shaper is not None:
            self.shaper.anneal(iter_index, total_iters)

    def _tactics_addend(self, prev_units, actions, actor_id: str, round_index: int) -> float:
        """Тактический shaping-член шага (0, если shaper не пристёгнут). §1/§11: train-only,
        cap/decay/arena-gate внутри shaper; в eval он record_only и возвращает 0."""
        if self.shaper is None:
            return 0.0
        attacked, target_id = action_outcome(actions)
        target_id = target_id if attacked else None
        units = self.state.units
        cell_after = units[actor_id].cell
        prior = self.shaper.ff.count_on(target_id) if target_id else 0
        prior_targets = self.shaper.ff.targets() if target_id else ()
        ctx = build_step_ctx(self.state, prev_units, units, actor_id, cell_after, target_id,
                             attacked, round_index, self.shaper.hp_max, prior, prior_targets)
        add = self.shaper.addend(ctx)
        if target_id:
            self.shaper.ff.observe(round_index, actor_id, target_id)
        self.shaper.observe_hp(units)
        return add

    def reset(self, payload: Dict[str, Any], start_index: int = 0) -> Dict[str, Any]:
        """Новый бой из снимка сцены; Phi(s0) посчитан. start_index — единая сигнатура
        вызова с PolyFightEnv (WP5), но моноакторный курсор жёстко привязан к герою."""
        self.state = Simulation.of(BattleContext.from_payload(payload))
        self.t = 0
        if self.team is not None:
            self.team.reset()
        if self.shaper is not None:
            self.shaper.reset(self.state.units)
        obs = self._observe()
        self.phi_s = self._phi(obs)
        return obs

    def _observe(self) -> Dict[str, Any]:
        ctx = self.state.context_for(self.state.hero_id)
        obs = observe(ctx)
        self.slots = slots_mod.build(ctx, obs)
        self._ctx = ctx
        sample = encode.observation(ctx, obs, self.slots)
        # множество совместно допустимых троек (для PPO-политики): тот же примитив легальности,
        # что у legalize. Добавляем только в RL-наблюдение (датасет/serve его не несут).
        sample["legal"] = joint_mod.legal_mask(self.slots, ctx, self.schema)
        return sample

    def _phi(self, obs: Dict[str, Any]) -> float:
        return float(self.phi(obs)) if self.phi else 0.0

    def legalize(self, label: Dict[str, int]) -> Dict[str, int]:
        """Полная легальность тройки в ТЕКУЩЕМ состоянии (делегует в arent/legalize.py).

        Головы маскируются независимо, но атака легальна условно (weapon достает цель из
        выбранной клетки/плана). Единый компонент чинит невозможную атаку до NONE и пишет
        причину в self._last_reason; та же функция обслуживает play/evaluate/team_eval.
        """
        action, reason = legalize_mod.legalize(label, self.schema, self.slots, self._ctx)
        self._last_reason = reason
        return action

    def step(self, label: Dict[str, int]) -> Tuple[Optional[Dict[str, Any]], float, bool, bool, Row]:
        """Применить тройку: legalize -> decode -> advance (ход героя + ответ врагов) -> награда."""
        action = self.legalize(label)
        prev_units = dict(self.state.units)
        actions = slots_mod.decode(self.slots, dict(action))
        self.state, value = self.state.advance(actions)
        self.t += 1
        died = bool(self.state.hero_dead)
        cleared = not self.state.foes
        if self.team is not None:            # v2: исход команды + плотные события + окно пата
            base, outcome = self.team.step(prev_units, self.state.units, self.state.hero_id, value)
            terminated = outcome is not None
        else:                                # legacy: одиночный герой (зачистка/смерть), без изменений
            outcome = None
            base = self.death_penalty if died else (self.clear_bonus if cleared else 0.0)
            terminated = died or cleared
        truncated = (not terminated) and self.t >= self.cap
        next_obs = None if terminated else self._observe()
        phi_prev = self.phi_s
        phi_next = 0.0 if terminated or next_obs is None else self._phi(next_obs)
        shaped = shape_reward(base, phi_prev, phi_next, terminated, self.gamma)
        addend = self._tactics_addend(prev_units, actions, self.state.hero_id, self.t)
        reward = round(shaped + addend, 6)
        self.phi_s = phi_next
        potential = round(self.gamma * (0.0 if terminated else phi_next) - phi_prev, 6)
        breakdown = {"base": round(base, 6), "potential": potential,
                     "tactical_applied": round(addend, 6), "outcome": outcome,
                     "tags": (self.shaper.last_diag if self.shaper is not None else None)}
        info = {"value": round(float(value), 4), "survived": not died, "cleared": cleared,
                "outcome": outcome, "terminated": terminated, "truncated": truncated,
                "rounds": self.t, "foes_left": len(self.state.foes), "action": action,
                "legalize_reason": self._last_reason, "reward_breakdown": breakdown,
                "phi": round(phi_prev, 6), "phi_next": round(phi_next, 6)}
        return next_obs, reward, terminated, truncated, info
