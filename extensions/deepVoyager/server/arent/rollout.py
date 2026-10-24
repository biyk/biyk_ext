# arent/rollout.py — данные для PPO: гиперпараметры цикла, сбор траекторий средой, GAE(λ).
#
# Отделено от rl.py (оркестрация/чекпойнты) ради одного места за наградо-адвантейдж
# математикой: RlConfig — тюнинг PPO (не размеры сети), collect — rollout round-robin по
# сценам через arent.env, gae — адвантейджи/возвраты. Никакого torch здесь нет: это чистые
# структуры данных поверх act/value_of агента, поэтому тестируются синтетикой.
#
# Ключевые свойства (по замечаниям консультанта):
#  • политика сэмплирует из совместного распределения по допустимому множеству (arent/joint.py),
#    поэтому действие уже легально и legalize в среде — тождество: logπ исполненного = logπ
#    выбранного (с той же нормировкой logZ). PPO учится ровно на том законе, что выбирал;
#  • терминал vs усечение: на terminated next_value=0 (эпизод кончился по правилам боя),
#    на truncated (rounds_cap) next_value=V(s') — бутстрап продолжающегося боя, цепочка GAE
#    обрывается (alive=0), терминальной награды за усечение нет;
#  • Phi — замороженный V_ref из env; collect складывает распределения Phi/shaping/reward/adv
#    в diag для проверки потенциальности (rl пишет shaping_diagnostics.json).
import random
from dataclasses import asdict, dataclass, fields
from typing import Any, Dict, List, Optional, Tuple

from arent import env, polyenv, spec, spec3
from arent.tactics_config import TacticsConfig
from arent.tactics_counters import Counters
from arent.tactics_map import allowed_set
from arent.tactics_shaper import TacticsShaper
from arent.team_reward import TeamReward, configured_team
from arent.torch_rl import PPOAgent, joint_logp

Row = Dict[str, Any]


@dataclass
class RlConfig:
    """Гиперпараметры PPO (отделены от размеров сети net.Config). Всё пишется в manifest."""
    iters: int = 60
    rollout_steps: int = 256           # горизонт rollout на итерацию
    gamma: float = 0.98
    gae_lambda: float = 0.95
    clip_eps: float = 0.2
    ent_coef: float = 0.01
    vf_coef: float = 0.5
    ppo_epochs: int = 4                # число update-эпох на собранный буфер
    minibatch: int = 32
    target_kl: float = 0.03
    clear_bonus: float = 1.0           # терминал: зачистил живым (legacy-путь, team выкл.)
    death_penalty: float = -1.0        # терминал: погиб (legacy-путь, team выкл.)
    use_team_reward: bool = True       # WP4: командная награда ±5 — дефолт RL-контура (legacy — по флагу)
    polyactor: bool = True             # WP3: шаг за каждого живого актёра; False — legacy мон.actor+foes_act
    reward_scale: float = 100.0        # сырое значение симуляции -> полоса ±5 (при raw_weight>0)
    draw_window: int = 4               # раундов подряд без событий -> пат (DRAW)
    rounds_cap: int = 8                # техническое усечение (truncated), не конец игры
    replays: int = 3
    eval_every: int = 5
    seed: int = 7
    lr: float = 3e-4
    reset_value_head: bool = True      # warm: ствол+головы из BC, критик заново (калибка BC не годится)
    use_vref: bool = True              # Phi = замороженный V_ref (потенциальный shaping)
    holdout_frac: float = 0.3          # групп сценариев, зарезервированных только под оценку
    val_frac: float = 0.2              # из остатка — под отбор чекпойнта (не под награду)
    variants_per_src: int = 0          # вариантов стартовых состояний на train-сцену (разнообразие rollout)
    schema: int = spec.SCHEMA          # версия задачи среды/политики: 2 = клетка, 3 = move-plan

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RlConfig":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


def gae(rewards: List[float], values: List[float], next_values: List[float],
        alive: List[int], gamma: float, lam: float) -> Tuple[List[float], List[float]]:
    """GAE(λ) по плоскому буферу. next_values[t] уже содержит бутстрап: V(s') для усечения,
    V(s_{t+1}) для продолжения, 0 для истинного терминала. alive[t]=0 на границе эпизода —
    цепочка обрывается, не «протекая» в следующий бой."""
    adv = [0.0] * len(rewards)
    last = 0.0
    for t in range(len(rewards) - 1, -1, -1):
        delta = rewards[t] + gamma * next_values[t] - values[t]
        last = delta + gamma * lam * alive[t] * last
        adv[t] = last
    returns = [adv[t] + values[t] for t in range(len(rewards))]
    return adv, returns


def normalize(advantages: List[float]) -> List[float]:
    """Стандартизация адвантейджей: нулевое среднее, единичный разброс (стабильнее клип)."""
    if not advantages:
        return []
    mean = sum(advantages) / len(advantages)
    var = sum((a - mean) ** 2 for a in advantages) / len(advantages)
    return [(a - mean) / ((var + 1e-8) ** 0.5) for a in advantages]


def _team_reward(cfg: RlConfig) -> Optional[TeamReward]:
    """Командная награда по конфигу (None, если use_team_reward выкл. — остаётся legacy-путь).

    Базовые числа исхода/событий берутся из единого места управления (points.json
    tactics.base), параметры прогона (окно пата/масштаб) — по-прежнему из RlConfig."""
    if not cfg.use_team_reward:
        return None
    return configured_team(draw_window=cfg.draw_window, reward_scale=cfg.reward_scale)


def _make_env(cfg: RlConfig, team: Optional[TeamReward],
              phi: Optional[Any] = None) -> env.FightEnv:
    """Среда rollout: полиакторный обход (WP3, основной путь) или legacy-мон.actor для A/B.

    Схема 3 (move-plan) живёт только в полиакторной среде: legacy-мон.actor складывает ход
    через advance (удар из финальной клетки) и move-plan не исполняет, поэтому v3+mono — ошибка.
    """
    if cfg.polyactor:
        return polyenv.PolyFightEnv(cfg.rounds_cap, cfg.clear_bonus, cfg.death_penalty,
                                    cfg.gamma, phi, team=team, schema=cfg.schema)
    if cfg.schema == spec3.SCHEMA:
        raise RuntimeError("схема 3 (move-plan) поддерживается только полиакторной средой "
                           "(--polyactor); legacy-мон.actor не исполняет отступление")
    return env.FightEnv(cfg.rounds_cap, cfg.clear_bonus, cfg.death_penalty, cfg.gamma, phi, team=team)


def _arena_allowed(name: str, expected: Optional[Dict[str, Any]], shape: TacticsConfig,
                   stage: Optional[str]) -> set:
    """arena-gate §1.4: stage-разрешённые ключи ∩ ожидаемые на этой арене (если известно)."""
    stage_allowed = shape.allowed(stage)
    if expected and name in expected:
        arena = allowed_set(expected[name])
        if arena:
            return stage_allowed & arena
    return stage_allowed


def collect(agent: PPOAgent, scenarios: List[Tuple[str, Dict[str, Any]]], cfg: RlConfig,
            rng: random.Random, phi: Optional[Any] = None,
            diag: Optional[List[Row]] = None, *, counters: Optional[Counters] = None,
            shape: Optional[TacticsConfig] = None, stage: Optional[str] = None,
            expected: Optional[Dict[str, Any]] = None,
            anneal: Tuple[int, int] = (0, 1)) -> List[Row]:
    """rollout_steps шагов round-robin по сценам; исполненное действие и его logπ в буфере.

    Шаг — ход текущего актёра по инициативе (обе стороны одной политикой: self-play),
    поэтому observation/logπ берутся с лица того, кто реально сейчас ходит.

    Тактический shaping — только здесь (train): передан `shape` (включённый TacticsConfig) ->
    к среде пристёгнут TacticsShaper, λ задаётся anneal=(it,total), arena-gate — по `expected`.
    По умолчанию shape=None: shaping выключен, reward == чистый исход (среж для eval-путей).
    """
    environment = _make_env(cfg, _team_reward(cfg), phi)
    if shape is not None and shape.enabled_global:
        environment.set_shaper(TacticsShaper(shape, shape.allowed(stage),
                                             counters if counters is not None else Counters(),
                                             record_only=False))
        environment.anneal(*anneal)
    order = list(range(len(scenarios)))
    rng.shuffle(order)
    episodes: Dict[int, int] = {}        # WP5: сколько боёв сцена сыграна -> следующий старт-актёр

    def _begin(slot: int) -> Row:
        """Reset с ротацией: каждый новый эпизод сцены стартует с следующего актёра."""
        k = episodes.get(slot, 0)
        episodes[slot] = k + 1
        if environment.shaper is not None:
            environment.shaper.allowed = _arena_allowed(scenarios[slot][0], expected, shape, stage)
        return environment.reset(scenarios[slot][1], start_index=k)

    pointer, sample = 0, _begin(order[0])
    samples, actions, logps, values, rewards, next_values, alive = \
        [], [], [], [], [], [], []
    for _ in range(cfg.rollout_steps):
        proposal = agent.act(sample)
        nxt, reward, terminated, truncated, info = environment.step(proposal["action"])
        action = info["action"]                                  # то, что реально исполнила среда
        # logπ исполненного действия = нормированный joint logπ того же совместного закона,
        # из которого act сэмплировал (logZ — знаменитель этого состояния): rollout == update.
        # Выбранная тройка уже легальна, поэтому legalization — тождество и action == proposal.
        logp = joint_logp(proposal["logp_table"], action, agent.ykey, proposal["logZ"])
        if terminated:
            next_value, cont = 0.0, 0
        elif truncated:
            next_value, cont = agent.value_of(nxt), 0            # бутстрап усечённого боя
        else:
            next_value, cont = agent.value_of(nxt), 1
        samples.append(sample); actions.append(action); logps.append(logp)
        values.append(proposal["value"]); rewards.append(reward)
        next_values.append(next_value); alive.append(cont)
        if diag is not None:
            diag.append({"phi": info["phi"], "phi_next": info["phi_next"], "reward": reward,
                         "value": proposal["value"], "next_value": round(next_value, 6),
                         "terminated": terminated, "truncated": truncated})
        if cont == 0:                                            # граница эпизода -> следующий бой
            pointer = (pointer + 1) % len(scenarios)
            sample = _begin(order[pointer])
        else:
            sample = nxt
    adv, ret = gae(rewards, values, next_values, alive, cfg.gamma, cfg.gae_lambda)
    adv = normalize(adv)
    return [{"sample": samples[i], "action": actions[i], "logp": logps[i],
             "adv": adv[i], "ret": ret[i]} for i in range(len(samples))]
