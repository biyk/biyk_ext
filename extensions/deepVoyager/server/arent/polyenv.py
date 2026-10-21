# arent/polyenv.py — WP3 «универсальный солдат»: RL-среда с обходом по инициативе.
#
# Один шаг = ход ОДНОГО живого актёра (любой команды), затем курсор сам переходит к
# следующему по инициативе. Наблюдение, слоты и легальность — с лица текущего актёра
# (context_for/observe из WP2), ход — Simulation.apply_actor его СОБСТВЕННЫМ оружием.
# Эвристика foes_act живёт только в legacy-среде env.FightEnv (опциональный A/B-бейзлайн),
# здесь её нет: обе стороны ведутся одной политикой (self-play в rollout.collect).
# Терминал — исход команды (TeamReward по живым бойцам), truncated — rounds_cap после
# полного цикла инициативы; смерть якорного «героя» сама по себе бой не заканчивает.
from typing import Any, Callable, Dict, Optional, Tuple

from arent import encode
from arent import slots as slots_mod
from arent.env import FightEnv, shape_reward
from arent.observe import observe
from arent.team_reward import TeamReward
from planner.context import BattleContext
from planner.scoring import Scorer
from planner.sim import Simulation

Row = Dict[str, Any]


class PolyFightEnv(FightEnv):
    """Эпизод = бой до исхода команды; шаг = ход текущего актёра по инициативе."""

    def __init__(self, rounds_cap: int = 8, clear_bonus: float = 1.0,
                 death_penalty: float = -1.0, gamma: float = 0.98,
                 phi: Optional[Callable[[Row], float]] = None,
                 team: Optional[TeamReward] = None):
        super().__init__(rounds_cap, clear_bonus, death_penalty, gamma, phi, team)
        self.actor: Optional[str] = None       # кто ходит сейчас (любая сторона)

    def reset(self, payload: Dict[str, Any], start_index: int = 0) -> Dict[str, Any]:
        """Новый бой: курсор на start_index-м живом по инициативе (WP5 — ротация старта),
        первое наблюдение с его лица; start_index берётся по модулю состава."""
        self.state = Simulation.of(BattleContext.from_payload(payload))
        self.t = 0
        if self.team is not None:
            self.team.reset()
        living = list(self.state.living_in_order)
        self.actor = living[int(start_index) % len(living)] if living else None
        obs = self._observe()
        self.phi_s = self._phi(obs)
        return obs

    def _observe(self) -> Dict[str, Any]:
        ctx = self.state.context_for(self.actor)
        obs = observe(ctx, self.state.initiative_order, self.actor)
        self.slots = slots_mod.build(ctx, obs)
        self._ctx = ctx
        return encode.observation(ctx, obs, self.slots)

    def _next_after(self, actor: str) -> Tuple[Optional[str], bool]:
        """Следующий живой по циклу инициативы; wrapped — хвост пройден, раунд закрыт."""
        order, units = self.state.initiative_order, self.state.units
        pos = order.index(actor) if actor in order else -1
        wrapped = False
        for i in range(1, len(order) + 1):
            if pos + i >= len(order):        # индекс загнулся за хвост — цикл замкнут
                wrapped = True
            uid = order[(pos + i) % len(order)]
            if units[uid].is_alive:
                return uid, wrapped
        return None, True

    def step(self, label: Dict[str, int]) -> Tuple[Optional[Dict[str, Any]], float, bool, bool, Row]:
        """Актёр сыграл тройку: legalize -> apply_actor -> курсор -> награда/терминал команды."""
        actor = self.actor
        action = self.legalize(label)
        prev_units = dict(self.state.units)
        actions = slots_mod.decode(self.slots, dict(action))
        value = Scorer().score(self._ctx, actions)          # сырое значение глазами актёра
        self.state = self.state.apply_actor(actor, actions)
        nxt_actor, wrapped = self._next_after(actor)
        if wrapped:
            self.t += 1
        self.actor = nxt_actor
        died = not self.state.units[self.state.hero_id].is_alive
        cleared = not any(u.hostile_to_hero and u.is_alive for u in self.state.units.values())
        if self.team is not None:            # исход команды + плотные события (терминал — исход)
            base, outcome = self.team.step(prev_units, self.state.units, self.state.hero_id,
                                           value, tick=wrapped)
            terminated = outcome is not None
        else:                                # legacy-бейзлайн: герой-якорь (зачистка/смерть)
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
                "rounds": self.t, "foes_left": sum(1 for u in self.state.units.values()
                                                   if u.hostile_to_hero and u.is_alive),
                "action": action, "actor": actor, "next_actor": nxt_actor,
                "phi": round(phi_prev, 6), "phi_next": round(phi_next, 6)}
        return next_obs, reward, terminated, truncated, info
