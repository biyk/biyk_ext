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
from arent import slots as slots_mod
from arent.observe import observe
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

    def reset(self, payload: Dict[str, Any], start_index: int = 0) -> Dict[str, Any]:
        """Новый бой из снимка сцены; Phi(s0) посчитан. start_index — единая сигнатура
        вызова с PolyFightEnv (WP5), но моноакторный курсор жёстко привязан к герою."""
        self.state = Simulation.of(BattleContext.from_payload(payload))
        self.t = 0
        if self.team is not None:
            self.team.reset()
        obs = self._observe()
        self.phi_s = self._phi(obs)
        return obs

    def _observe(self) -> Dict[str, Any]:
        ctx = self.state.context_for(self.state.hero_id)
        obs = observe(ctx)
        self.slots = slots_mod.build(ctx, obs)
        self._ctx = ctx
        return encode.observation(ctx, obs, self.slots)

    def _phi(self, obs: Dict[str, Any]) -> float:
        return float(self.phi(obs)) if self.phi else 0.0

    def legalize(self, label: Dict[str, int]) -> Dict[str, int]:
        """Полная легальность тройки в ТЕКУЩЕМ состоянии: атака вне дистанции -> «не атаковать».

        Головы маскируются независимо, но атака легальна условно (weapon достает цель из
        выбранной клетки). Если атака недопустима — убираем оружие (NONE), движение и прицел
        остаются: получаем законное действие, на котором и учится logπ (см. rollout.collect).
        """
        cell = int(label.get("cell", 0))
        target = int(label.get("target", spec.NONE_SLOT))
        weapon = int(label.get("weapon", spec.NONE_SLOT))
        n_t, n_w = len(self.slots.targets), len(self.slots.weapons)
        if 0 <= target < n_t and 0 <= weapon < n_w:
            if not slots_mod.attackable(self.slots, self._ctx, cell, target, weapon):
                weapon = NONE_INDEX                 # атака невозможна -> только перемещение/прицел
        return {"cell": cell, "target": target, "weapon": weapon}

    def step(self, label: Dict[str, int]) -> Tuple[Optional[Dict[str, Any]], float, bool, bool, Row]:
        """Применить тройку: legalize -> decode -> advance (ход героя + ответ врагов) -> награда."""
        action = self.legalize(label)
        prev_units = dict(self.state.units)
        self.state, value = self.state.advance(slots_mod.decode(self.slots, dict(action)))
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
        reward = shape_reward(base, phi_prev, phi_next, terminated, self.gamma)
        self.phi_s = phi_next
        info = {"value": round(float(value), 4), "survived": not died, "cleared": cleared,
                "outcome": outcome, "terminated": terminated, "truncated": truncated,
                "rounds": self.t, "foes_left": len(self.state.foes), "action": action,
                "phi": round(phi_prev, 6), "phi_next": round(phi_next, 6)}
        return next_obs, reward, terminated, truncated, info
