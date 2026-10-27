# arent/team_reward.py — командная награда v3: ОСНОВНАЯ метрика — нанесённый урон.
#
# Смысл бойца — наносить урон: чем больше снял HP, тем ценнее. Награда за шаг =
# damage_dealt · (снятый с врагов HP) − damage_taken · (потерянный свой HP). Штраф за
# полученный урон чуть мягче награды за нанесённый (0.9 < 1.0), чтобы ближники не боялись
# размена. Терминальные добавки: победа +50 (абсолютный показатель), убийство +5 (побочная
# цель — кончать), поражение/ничья/взаимное = 0 (смерть пока не штраф). Старые событийные
# члены hit/living_cost обнулены (награда теперь по ВЕЛИЧИНЕ урона, а не по числу попаданий).
# Выживаемость вырастает сама: дольше живёшь — больше ходов — больше урона — выше награда.
# Пат (draw_window раундов без урона) и таймаут cap судим по очкам = dealt − taken (_decide):
# выжить-с-преимуществом = победа. reward_scale/raw_weight — сырой подмес значения симуляции,
# по умолчанию 0.0 (выкл., см. env.py) — к новой шкале не относится.
from collections import deque
from typing import Dict, Mapping, Optional, Tuple

from planner.initiative import Unit, side_of

REWARD_SCALE = 100.0                    # сырое значение симуляции (raw_weight, по умолч. выкл.)
WIN, LOSS, DRAW, MUTUAL = 50.0, 0.0, 0.0, 0.0     # победа абсолютна; поражение/ничья — не штраф
KILL = 5.0                              # побочная цель: кончать врага
HIT, LIVING_COST = 0.0, 0.0            # deprecated: урон считается величиной, не числом попаданий
DAMAGE_DEALT, DAMAGE_TAKEN = 1.0, 0.9  # награда за 1 HP врага; штраф за 1 свой HP (мягче размен)
DRAW_WINDOW = 4                         # раундов подряд без событий -> пат (судим по очкам)

OUTCOMES = ("win", "loss", "draw", "mutual")
BASE_KEYS = ("win", "loss", "draw", "mutual", "kill", "hit", "living_cost",
             "damage_dealt", "damage_taken")


class TeamReward:
    """Командная награда по состоянию бойцов: исход + плотные события + окно пата."""

    def __init__(self, draw_window: int = DRAW_WINDOW, reward_scale: float = REWARD_SCALE,
                 raw_weight: float = 0.0, win: float = WIN, loss: float = LOSS,
                 draw: float = DRAW, mutual: float = MUTUAL, kill: float = KILL,
                 hit: float = HIT, living_cost: float = LIVING_COST,
                 damage_dealt: float = DAMAGE_DEALT, damage_taken: float = DAMAGE_TAKEN):
        self.draw_window = max(1, int(draw_window))
        self.reward_scale = reward_scale or REWARD_SCALE
        self.raw_weight = raw_weight
        self.points = {"win": win, "loss": loss, "draw": draw, "mutual": mutual,
                       "kill": kill, "hit": hit, "living_cost": living_cost,
                       "damage_dealt": damage_dealt, "damage_taken": damage_taken}
        self.reset()

    @classmethod
    def from_base(cls, draw_window: int = DRAW_WINDOW, reward_scale: float = REWARD_SCALE,
                  raw_weight: float = 0.0,
                  base: Optional[Mapping[str, float]] = None) -> "TeamReward":
        """TeamReward из конфигурируемой базы (points.json tactics.base, уже сведённой к числам
        через tactics_config: enabled=False -> 0.0). Пустая база == прежние константы; неизвестные
        ключи молча игнорируются (за валидацию ключей отвечает tactics_config)."""
        b = base or {}
        over = {k: float(b[k]) for k in BASE_KEYS if k in b}
        return cls(draw_window=draw_window, reward_scale=reward_scale,
                   raw_weight=raw_weight, **over)

    def reset(self) -> None:
        """Новый бой: окно событий пусто (пат считается заново), внутрираундовый флаг чист.
        Счётчики «очков» (нанесённый/полученный урон) обнуляются — на них решается бой по
        истечении cap и глухая ничья (выжить-с-преимуществом = победа по очкам)."""
        self._recent: deque = deque(maxlen=self.draw_window)
        self._pending = False
        self._dealt = 0.0        # суммарно HP, снятое с врагов (наши «очки»)
        self._taken = 0.0        # суммарно HP, потерянное собой (очки противника)

    def _alive(self, units: Dict[str, Unit], hero_id: str, side: int) -> Dict[str, Unit]:
        return {u.id: u for u in units.values()
                if u.is_alive and side_of(u, hero_id) == side}

    @staticmethod
    def _removed(before: Dict[str, Unit], nxt: Dict[str, Unit]) -> float:
        """Суммарный HP, снятый с этих бойцов за шаг (реальная потеря, overkill не считаем:
        не больше, чем у бойца оставалось; если труп исчез из nxt — считаем всё его до-HP)."""
        total = 0.0
        for uid, u in before.items():
            after = nxt.get(uid)
            rem = u.hp - (max(0.0, after.hp) if after is not None else 0.0)
            if rem > 0.0:
                total += rem
        return total

    def _outcome(self, foes: Dict[str, Unit], own: Dict[str, Unit]) -> Optional[str]:
        """Итог по живым после шага: кто ещё может драться. Пат — вне этого (по окну)."""
        if not foes and not own:
            return "mutual"
        if not foes:
            return "win"
        if not own:
            return "loss"
        return None

    def _decide(self, foes: Dict[str, Unit], own: Dict[str, Unit]) -> str:
        """Нейтрализация не случилась, но бой надо закрыть (таймаут cap или глухой пат):
        решаем ПО ОЧКАМ = нанесённый урон минус полученный. Кто снял больше HP — тот и победил
        (выжить-с-преимуществом = победа). При точном равенстве очков — ничья по роли: побеждает
        «тот, кого гоняли» — сторона с большей средней дальностью атаки (дальник/кайтер, которого
        мили-охотник не догнал). Если и дальность равна — честная ничья."""
        eps = 1e-9
        points = self._dealt - self._taken
        if points > eps:
            return "win"
        if points < -eps:
            return "loss"
        own_reach = sum(u.reach_cells for u in own.values()) / len(own) if own else 0.0
        foe_reach = sum(u.reach_cells for u in foes.values()) / len(foes) if foes else 0.0
        if own_reach > foe_reach + eps:
            return "win"
        if foe_reach > own_reach + eps:
            return "loss"
        return "draw"

    def step(self, prev: Dict[str, Unit], nxt: Dict[str, Unit], hero_id: str,
             raw_value: float = 0.0, tick: bool = True,
             at_cap: bool = False) -> Tuple[float, Optional[str]]:
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
        # величина урона за шаг (в HP); overkill не считаем — максимум то, что у цели осталось
        dealt_amt = self._removed(foes_before, nxt)
        taken_amt = self._removed(own_before, nxt)
        self._dealt += dealt_amt
        self._taken += taken_amt
        # ОСНОВНАЯ награда: по ВЕЛИЧИНЕ урона (нанёс — плюс, получил — минус, чуть мягче)
        dense = (self.points["kill"] * kills
                 + self.points["damage_dealt"] * dealt_amt
                 - self.points["damage_taken"] * taken_amt)
        eventful = bool(kills) or dealt_amt > 1e-9 or taken_amt > 1e-9
        if tick:
            self._recent.append(eventful or self._pending)
            self._pending = False
        else:
            self._pending = self._pending or eventful
        outcome = self._outcome(foes_after, own_after)
        if tick and outcome is None and len(self._recent) == self.draw_window \
                and not any(self._recent):
            outcome = self._decide(foes_after, own_after)         # пат: решаем по очкам/роли, не −4 вслепую
        if outcome is None and at_cap:
            outcome = self._decide(foes_after, own_after)          # таймаут cap: выжить-с-преимуществом = победа
        if outcome:
            dense += self.points[outcome]
        dense += self.raw_weight * float(raw_value) / self.reward_scale   # сырой подмес (выкл.)
        return round(dense, 6), outcome

    def to_dict(self) -> Dict[str, float]:
        """Параметры награды для манифеста (воспроизводимость шкалы без чтения кода)."""
        return {"reward_scale": self.reward_scale, "raw_weight": self.raw_weight,
                "draw_window": self.draw_window, **{f"r_{k}": v for k, v in self.points.items()}}


def configured_team(draw_window: int = DRAW_WINDOW, reward_scale: float = REWARD_SCALE,
                    raw_weight: float = 0.0) -> TeamReward:
    """TeamReward из единого места управления: базовые числа берутся из tactics.base
    действующего points.json (hot-reload через tactics_config.config()); нет секции base ->
    константы этого модуля (обратная совместимость)."""
    from arent.tactics_config import config          # лениво: без цикла импортов на старте
    return TeamReward.from_base(draw_window, reward_scale, raw_weight, config().base)
