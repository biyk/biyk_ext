# arent/rollout.py — данные для PPO: гиперпараметры цикла, сбор траекторий средой, GAE(λ).
#
# Отделено от rl.py (оркестрация/чекпойнты) ради одного места за наградо-адвантейдж
# математикой: RlConfig — тюнинг PPO (не размеры сети), collect — rollout round-robin по
# сценам через arent.env, gae — адвантейджи/возвраты. Никакого torch здесь нет: это чистые
# структуры данных поверх act/value_of агента, поэтому тестируются синтетикой.
#
# Ключевые свойства (по замечаниям консультанта):
#  • исполняемое действие = легализованное средой (info["action"]); logπ берётся от НЕГО,
#    поэтому PPO учится ровно на том действии, что исполняет среда (нет расхождения propose/act);
#  • терминал vs усечение: на terminated next_value=0 (эпизод кончился по правилам боя),
#    на truncated (rounds_cap) next_value=V(s') — бутстрап продолжающегося боя, цепочка GAE
#    обрывается (alive=0), терминальной награды за усечение нет;
#  • Phi — замороженный V_ref из env; collect складывает распределения Phi/shaping/reward/adv
#    в diag для проверки потенциальности (rl пишет shaping_diagnostics.json).
import random
from dataclasses import asdict, dataclass, fields
from typing import Any, Dict, List, Optional, Tuple

from arent import env, polyenv
from arent.team_reward import TeamReward
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
    """Командная награда по конфигу (None, если use_team_reward выкл. — остаётся legacy-путь)."""
    if not cfg.use_team_reward:
        return None
    return TeamReward(draw_window=cfg.draw_window, reward_scale=cfg.reward_scale)


def _make_env(cfg: RlConfig, team: Optional[TeamReward],
              phi: Optional[Any] = None) -> env.FightEnv:
    """Среда rollout: полиакторный обход (WP3, основной путь) или legacy-мон.actor для A/B."""
    klass = polyenv.PolyFightEnv if cfg.polyactor else env.FightEnv
    return klass(cfg.rounds_cap, cfg.clear_bonus, cfg.death_penalty, cfg.gamma, phi, team=team)


def collect(agent: PPOAgent, scenarios: List[Tuple[str, Dict[str, Any]]], cfg: RlConfig,
            rng: random.Random, phi: Optional[Any] = None,
            diag: Optional[List[Row]] = None) -> List[Row]:
    """rollout_steps шагов round-robin по сценам; исполненное действие и его logπ в буфере.

    Шаг — ход текущего актёра по инициативе (обе стороны одной политикой: self-play),
    поэтому observation/logπ берутся с лица того, кто реально сейчас ходит.
    """
    environment = _make_env(cfg, _team_reward(cfg), phi)
    order = list(range(len(scenarios)))
    rng.shuffle(order)
    pointer, sample = 0, environment.reset(scenarios[order[0]][1])
    samples, actions, logps, values, rewards, next_values, alive = \
        [], [], [], [], [], [], []
    for _ in range(cfg.rollout_steps):
        proposal = agent.act(sample)
        nxt, reward, terminated, truncated, info = environment.step(proposal["action"])
        action = info["action"]                                  # то, что реально исполнила среда
        logp = joint_logp(proposal["logp_table"], action)
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
            sample = environment.reset(scenarios[order[pointer]][1])
        else:
            sample = nxt
    adv, ret = gae(rewards, values, next_values, alive, cfg.gamma, cfg.gae_lambda)
    adv = normalize(adv)
    return [{"sample": samples[i], "action": actions[i], "logp": logps[i],
             "adv": adv[i], "ret": ret[i]} for i in range(len(samples))]
