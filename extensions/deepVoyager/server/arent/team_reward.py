# arent/team_reward.py — командная награда v2 (коммит №4): нормализованная шкала ±5.
#
# Награда мерит ИСХОД команды, а не сумму очков Скаллера: победа +5, поражение −5,
# ничья (пат) −4.0, взаимное уничтожение 0. Плотные добавки мелкие и направляют к делу:
# убийство врага +0.5, попадание +0.01, а « living » — издержки за каждый живой враг на
# закрытии раунда −0.01 (пинать неубитых, кончать быстрее). Пат ловим окном из
# draw_window последних раундов: если ни в одном не было попаданий/убийств — бой встал,
# это DRAW (терминал), а не бесконечное усечение. reward_scale=100 переводит сырое
# значение хода симуляции (шкала сотен) в ту же полосу ±5, когда его решают подмешать
# (raw_weight>0); по умолчанию 0.0 — сырые очки в награду не текут (см. env.py).
from collections import deque
from typing import Dict, Optional, Tuple

from planner.initiative import Unit, side_of

REWARD_SCALE = 100.0                    # сырое значение симуляции -> полоса ±5
WIN, LOSS, DRAW, MUTUAL = 5.0, -5.0, -4.0, 0.0
KILL, HIT, LIVING_COST = 0.5, 0.01, -0.01
DRAW_WINDOW = 4                         # раундов подряд без событий -> пат (DRAW)

OUTCOMES = ("win", "loss", "draw", "mutual")


class TeamReward:
    """Командная награда по состоянию бойцов: исход + плотные события + окно пата."""

    def __init__(self, draw_window: int = DRAW_WINDOW, reward_scale: float = REWARD_SCALE,
                 raw_weight: float = 0.0, win: float = WIN, loss: float = LOSS,
                 draw: float = DRAW, mutual: float = MUTUAL, kill: float = KILL,
                 hit: float = HIT, living_cost: float = LIVING_COST):
        self.draw_window = max(1, int(draw_window))
        self.reward_scale = reward_scale or REWARD_SCALE
        self.raw_weight = raw_weight
        self.points = {"win": win, "loss": loss, "draw": draw, "mutual": mutual,
                       "kill": kill, "hit": hit, "living_cost": living_cost}
        self.reset()

    def reset(self) -> None:
        """Новый бой: окно событий пусто (пат считается заново), внутрираундовый флаг чист."""
        self._recent: deque = deque(maxlen=self.draw_window)
        self._pending = False

    def _alive(self, units: Dict[str, Unit], hero_id: str, side: int) -> Dict[str, Unit]:
        return {u.id: u for u in units.values()
                if u.is_alive and side_of(u, hero_id) == side}

    def _outcome(self, foes: Dict[str, Unit], own: Dict[str, Unit]) -> Optional[str]:
        """Итог по живым после шага: кто ещё может драться. Пат — вне этого (по окну)."""
        if not foes and not own:
            return "mutual"
        if not foes:
            return "win"
        if not own:
            return "loss"
        return None

    def step(self, prev: Dict[str, Unit], nxt: Dict[str, Unit], hero_id: str,
             raw_value: float = 0.0, tick: bool = True) -> Tuple[float, Optional[str]]:
        """(награда за шаг, исход-терминал|None). События: убили/попали/живые враги/пат.

        tick=False — ход актёра в середине раунда (WP3/WP4): плотные события считаем сразу,
        а окно пата двигаем только на закрытии раунда (tick=True), иначе draw_window
        считался бы в ходах, а не в раундах. Событием раунда считается урон ЛЮБОЙ стороне
        (командный бой: нас бьют — тоже движение, а не пат).
        """
        foes_before = self._alive(prev, hero_id, 1)
        foes_after = self._alive(nxt, hero_id, 1)
        own_after = self._alive(nxt, hero_id, 0)
        own_before = self._alive(prev, hero_id, 0)
        kills = sum(1 for uid in foes_before if uid not in foes_after)
        hits = sum(1 for uid, u in foes_before.items()
                   if uid in nxt and nxt[uid].hp < u.hp)
        own_hits = sum(1 for uid, u in own_before.items()
                       if uid in nxt and nxt[uid].hp < u.hp)
        dense = (self.points["kill"] * kills + self.points["hit"] * hits
                 + self.points["living_cost"] * len(foes_after))
        eventful = bool(kills or hits or own_hits)
        if tick:
            self._recent.append(eventful or self._pending)
            self._pending = False
        else:
            self._pending = self._pending or eventful
        outcome = self._outcome(foes_after, own_after)
        if tick and outcome is None and len(self._recent) == self.draw_window \
                and not any(self._recent):
            outcome = "draw"                                 # пат: окно тихих раундов
        if outcome:
            dense += self.points[outcome]
        dense += self.raw_weight * float(raw_value) / self.reward_scale   # сырой подмес (выкл.)
        return round(dense, 6), outcome

    def to_dict(self) -> Dict[str, float]:
        """Параметры награды для манифеста (воспроизводимость шкалы без чтения кода)."""
        return {"reward_scale": self.reward_scale, "raw_weight": self.raw_weight,
                "draw_window": self.draw_window, **{f"r_{k}": v for k, v in self.points.items()}}
