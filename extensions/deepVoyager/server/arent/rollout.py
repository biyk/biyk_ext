# arent/rollout.py — данные для PPO: гиперпараметры цикла, сбор траекторий средой, GAE(λ).
#
# Отделено от rl.py (оркестрация/чекпойнты) ради одного места за наградо-адвантейдж
# математикой: RlConfig — тюнинг PPO (не размеры сети), _collect — rollout round-robin по
# сценам через arent.env, gae — адвантейджи/возвраты с бутстрапом V(s) на незакрытом конце.
# Никакого torch здесь нет: это чистые структуры данных, поэтому тестируются синтетикой.
import random
from dataclasses import asdict, dataclass, fields
from typing import Any, Dict, List, Tuple

from arent import env
from arent.torch_rl import PPOAgent

Row = Dict[str, Any]


@dataclass
class RlConfig:
    """Гиперпараметры PPO (отделены от размеров сети net.Config)."""
    iters: int = 60
    rollout_steps: int = 256
    gamma: float = 0.98
    gae_lambda: float = 0.95
    clip_eps: float = 0.2
    ent_coef: float = 0.01
    vf_coef: float = 0.5
    ppo_epochs: int = 4
    minibatch: int = 32
    target_kl: float = 0.03
    survive_bonus: float = 1.0
    clear_bonus: float = 1.0
    rounds_cap: int = 8
    replays: int = 3
    eval_every: int = 5
    seed: int = 7
    lr: float = 3e-4

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RlConfig":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


def gae(rewards: List[float], values: List[float], dones: List[bool], gamma: float,
        lam: float, bootstrap: float = 0.0) -> Tuple[List[float], List[float]]:
    """GAE(λ): адвантейджи и возвраты по эпизоду. done обрывает цепочку (V следующего = 0)."""
    adv = [0.0] * len(rewards)
    last = 0.0
    for t in range(len(rewards) - 1, -1, -1):
        next_value = 0.0 if dones[t] else (bootstrap if t == len(rewards) - 1 else values[t + 1])
        delta = rewards[t] + gamma * next_value - values[t]
        last = delta + gamma * lam * (0.0 if dones[t] else 1.0) * last
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


def collect(agent: PPOAgent, scenarios: List[Tuple[str, Dict[str, Any]]], cfg: RlConfig,
            rng: random.Random) -> List[Row]:
    """rollout_steps шагов round-robin по сценам; на done — следующая сцена. GAE поверх буфера."""
    environment = env.FightEnv(cfg.rounds_cap, cfg.survive_bonus, cfg.clear_bonus)
    order = list(range(len(scenarios)))
    rng.shuffle(order)
    pointer, sample = 0, environment.reset(scenarios[order[0]][1])
    samples, actions, logps, values, rewards, dones = [], [], [], [], [], []
    bootstrap = 0.0
    for _ in range(cfg.rollout_steps):
        step = agent.act(sample)
        nxt, reward, done, _info = environment.step(step["action"])
        samples.append(sample); actions.append(step["action"]); logps.append(step["logp"])
        values.append(step["value"]); rewards.append(reward); dones.append(done)
        if done:
            pointer = (pointer + 1) % len(scenarios)
            sample = environment.reset(scenarios[order[pointer]][1])
            bootstrap = 0.0
        else:
            sample = nxt
            bootstrap = agent.act(sample)["value"]
    adv, ret = gae(rewards, values, dones, cfg.gamma, cfg.gae_lambda, bootstrap)
    adv = normalize(adv)
    return [{"sample": samples[i], "action": actions[i], "logp": logps[i],
             "adv": adv[i], "ret": ret[i]} for i in range(len(samples))]
