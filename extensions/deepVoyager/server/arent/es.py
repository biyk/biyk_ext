# arent/es.py — эволюционный поиск (OpenAI-ES) по ВЕСАМ политики поверх BC-старта.
#
# Почему ES, а не градиентный PPO: диагноз прогонов s3im* показал, что градиентный
# PPO от BC-приора НЕ находит тактику победы над battlecast (гейт vs battlecast
# 0.406 -> 0.382, т.е. деградация), а mix-усреднение маскирует это тем, что random
# бьётся всё лучше. Battlecast — конкретный детерминированный учитель; чтобы победить
# ЕГО, нужен поиск по жёсткой целевой функции «duel win-rate vs battlecast», а не
# гладкий градиент по суррогатной награде. ES (Salimshen et al., 2017) оптимизирует
# ЧЁРНО-ЯЩИЧНУЮ фитнес-мерку напрямую: возмущаем веса -> гоняем бои -> по рангам
# преимуществ обновляем среднее Adam'ом. Градиентов политики не нужно вовсе.
#
# Размерность: схема 2, hidden=96/head=24 -> ~53k весов. Полный CMA-ES (ковариация
# 53k×53k) не влезает, поэтому диагональный OpenAI-ES с Adam (масштаб-инвариантный
# шаг по координате) — канон для нейросетевых весов такого размера.
#
# Транспорт НЕ здесь: es.py считает только математику поиска (возмущения/преимущества/
# Adam). Фитнес (бои) подставляет вызывающий код через callback evaluate(params)->float.
# Так модуль тестируется на CPU без Ray, а боевой прогон живёт в .ray/ray_stage4_es.py.
#
# Детерминизм — фундамент: среда ходит argmax-политикой/plan-учителем, бои воспроизводимы
# бит-в-бит. Значит antithetic-пары (+ε и −ε на ОДНИХ сценах) дают честно сравнимую
# разницу, а повторная оценка чемпиона даёт ровно тот же результат (шум только от
# конечности пула сцен, не от прогонов).
import random
from copy import deepcopy
from dataclasses import asdict, dataclass, fields
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from arent import net


# ------------------------------------------------------------------ флэт-вектор весов
def flatten(params: Dict[str, Any], out: Optional[List[float]] = None) -> List[float]:
    """Вложенный словарь весов -> плоский список float в ДЕТЕРМИНИРОВАННОМ порядке обхода.

    Порядок = порядок ключей dict (json.load/save сохраняют порядок) и порядок элементов
    списков. Тот же обход в unflatten читает вектор назад -> побайтовый roundtrip.
    """
    acc = [] if out is None else out
    if isinstance(params, dict):
        for v in params.values():
            flatten(v, acc)
    elif isinstance(params, (list, tuple)):
        for v in params:
            flatten(v, acc)
    else:
        acc.append(float(params))
    return acc


def _is_numeric_list(obj: Any) -> bool:
    """Список чисел (вектор bias / valueW), а не список строк-матриц (trunk1/headW)."""
    return isinstance(obj, list) and (not obj or not isinstance(obj[0], (list, tuple, dict)))


def unflatten(template: Dict[str, Any], it: "iter") -> Dict[str, Any]:
    """Собрать вложенный словарь той же формы, что template, вычитая листья из итератора it.

    it — итератор по плоскому вектору (тот же порядок обхода, что flatten). Структура
    (длины списков/ключи dict) берётся из template, значения — из it.
    """
    if isinstance(template, dict):
        return {k: unflatten(v, it) for k, v in template.items()}
    if isinstance(template, list):
        if _is_numeric_list(template):
            return [float(next(it)) for _ in template]
        return [unflatten(v, it) for v in template]
    return float(next(it))


# ------------------------------------------------------------------ конфигурация поиска
@dataclass
class ESConfig:
    """Что и как ищем. Дефолты — под BC-старт (компетентная политика) и жёсткую цель battlecast."""
    popsize: int = 32          # индивидов в поколении (парное antithetic => popsize чётный)
    sigma0: float = 0.01       # масштаб шума возмущения весов (~10% типового веса)
    sigma_min: float = 0.002   # пол — ниже шум только мешает
    sigma_decay: float = 0.995 # мультипликативное сжатие шага поиска к концу
    alpha: float = 0.003       # темп Adam в весовом пространстве (шаг среднего)
    beta1: float = 0.9         # момент Adam
    beta2: float = 0.999       # RMS Adam
    adam_eps: float = 1e-8
    seed: int = 13             # детерминизм выборки возмущений
    rank_advantage: bool = True  # ранговые преимущества (робастны к плато/выбросам)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ESConfig":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


# ------------------------------------------------------------------ преимущества по рангам
def rank_advantages(fitness: List[float]) -> np.ndarray:
    """Центрированные нормированные ранги (без учёта масштаба фитнеса) -> A [-1..1]-подобные.

    Ties -> средние ранги. Если все значения равны (std=0) -> нули (обновления нет).
    Ранговый трансформ устойчив к плато win-rate и выбросам сильнее, чем (f-mean)/std.
    """
    f = np.asarray(fitness, dtype=np.float64)
    n = len(f)
    if n < 2:
        return np.zeros(n)
    order = np.argsort(f, kind="mergesort")
    ranks = np.empty(n, dtype=np.float64)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and f[order[j + 1]] == f[order[i]]:
            j += 1
        avg = (i + j) / 2.0                       # средний ранг для группы равных
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    centered = ranks - (n - 1) / 2.0
    sd = centered.std()
    if sd < 1e-12:
        return np.zeros(n)
    return centered / sd


def std_advantages(fitness: List[float]) -> np.ndarray:
    """Простое центрирование по std (для сравнения/отладки вместо rank)."""
    f = np.asarray(fitness, dtype=np.float64)
    sd = f.std()
    if sd < 1e-12:
        return np.zeros(len(f))
    return (f - f.mean()) / sd


# ------------------------------------------------------------------ сам оптимизатор
class ESOptimizer:
    """OpenAI-ES с Adam-обновлением среднего и antithetic-сэмплированием.

    Жизненный цикл поколения:
        cands = opt.ask()            # popsize словарей весов (возмущения среднего)
        fit   = [evaluate(c) ...]    # внешний код считает бои -> win-rate каждого
        rep   = opt.tell(fit)        # преимущества по рангам -> градиент -> Adam -> новое среднее
    mean двигается к более фитнесным возмущениям; champion = лучший встреченный индивид.
    """

    def __init__(self, seed_params: Dict[str, Any], cfg: Optional[ESConfig] = None):
        self.cfg = cfg or ESConfig()
        self.template = deepcopy(seed_params)
        self.theta = np.asarray(flatten(seed_params), dtype=np.float64)
        self.n = int(self.theta.size)
        self.rng = np.random.RandomState(self.cfg.seed)
        self.py_rng = random.Random(self.cfg.seed)
        self.p = int(self.cfg.popsize)
        if self.p % 2:                          # antithetic требует чётности
            self.p += 1
        self.sigma = float(self.cfg.sigma0)
        self.m = np.zeros(self.n)               # 1-й момент Adam
        self.v = np.zeros(self.n)               # 2-й момент Adam
        self.t = 0                              # шаг Adam
        self.generation = 0
        self._deltas: Optional[np.ndarray] = None
        self._cands: Optional[np.ndarray] = None   # точные выборки поколения (pre-update theta+σ·δ)
        # чемпион: лучший индивид по fitness (не среднее) — его и отдаём наружу.
        self.champion_params = deepcopy(seed_params)
        self.champion_fit = -float("inf")
        self.history_best_fit = -float("inf")

    # -------- сэмпл поколения
    def ask(self) -> List[Dict[str, Any]]:
        """popsize словарей весов: среднее ± sigma·N(0,I), antithetic-пары (+ε, −ε)."""
        half = self.p // 2
        eps = self.rng.standard_normal((half, self.n))
        deltas = np.vstack([eps, -eps])                      # [P, n]: ε и его зеркало
        self._deltas = deltas
        cands = self.theta[None, :] + self.sigma * deltas    # [P, n] (до шага среднего)
        self._cands = cands
        out: List[Dict[str, Any]] = []
        for row in cands:
            out.append(unflatten(self.template, iter(row.tolist())))
        return out

    # -------- обновление среднего
    def tell(self, fitness: List[float]) -> Dict[str, Any]:
        """По фитнесу поколения: преимущества -> оценка градиента -> Adam-шаг среднего."""
        assert self._deltas is not None and len(fitness) == self.p, \
            "tell: число фитнесов != popsize или ask не вызван"
        f = np.asarray(fitness, dtype=np.float64)
        A = rank_advantages(f) if self.cfg.rank_advantage else std_advantages(f)
        # оценка градиента: g = Σ_i A_i · δ_i / (P·σ)  (antithetic уже внутри A·δ)
        g = (A @ self._deltas) / (self.p * self.sigma)

        # Adam (масштаб-инвариантный шаг по координате — нужен при разном масштабе весов).
        b1, b2, eps = self.cfg.beta1, self.cfg.beta2, self.cfg.adam_eps
        self.m = b1 * self.m + (1 - b1) * g
        self.v = b2 * self.v + (1 - b2) * (g * g)
        self.t += 1
        mhat = self.m / (1 - b1 ** self.t)
        vhat = self.v / (1 - b2 ** self.t)
        self.theta = self.theta + self.cfg.alpha * mhat / (np.sqrt(vhat) + eps)

        # champion по сырому фитнесу: лучший ВСТРЕЧЕННЫЙ индивид (не среднее) — его отдаём наружу.
        best_i = int(np.argmax(f))
        if f[best_i] > self.champion_fit:
            self.champion_fit = float(f[best_i])
            # ровно тот вектор, что дал f[best_i] (до шага среднего), а не обновлённое mean
            self.champion_params = unflatten(self.template, iter(self._cands[best_i].tolist()))
        self.generation += 1
        self.sigma = max(self.cfg.sigma_min, self.sigma * self.cfg.sigma_decay)

        mean_fit = float(f.mean())
        self.history_best_fit = max(self.history_best_fit, float(f.max()))
        return {"generation": self.generation, "pop": self.p, "sigma": round(self.sigma, 6),
                "fit_mean": round(mean_fit, 4), "fit_max": round(float(f.max()), 4),
                "fit_min": round(float(f.min()), 4),
                "champion_fit": round(self.champion_fit, 4),
                "grad_norm": round(float(np.linalg.norm(g)), 6),
                "mean_norm": round(float(np.linalg.norm(self.theta)), 4)}

    # -------- доступ к среднему/чемпиону
    def mean_params(self) -> Dict[str, Any]:
        return unflatten(self.template, iter(self.theta.tolist()))
