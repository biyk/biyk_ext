# arent/torch_rl.py — PPO-математика поверх TorchPolicy: сэмпл хода и clipped-обновление.
#
# Сеть та же, что в BC (три masked-головы cell/target/weapon + голова стоимости), поэтому
# чекпойнт PPO читается обоими бэкендами и размерности не меняются. Здесь только два
# действия: act — собрать тройку из замаскированных распределений (joint logπ = сумма по
# группам), update — PPO-шаг (clipped surrogate + value MSE + entropy-бонус) мини-батчами
# поверх существующего optimizer'а политики. Адвантейджи (GAE) считаются в rl.py: сюда
# приходят уже готовые advantage/return на траекторию. torch обязателен: на pure-бэкенде
# RL вне scope — это явная ошибка, а не тихий fallback.
from typing import Any, Dict, List

import torch
import torch.nn.functional as F

from arent.net import GROUPS, Y_KEY
from arent.torch_net import PAD

Action = Dict[str, int]


def _dist(logits: torch.Tensor, mask: torch.Tensor):
    """Замаскированное распределение: запрещённые слоты → вероятности 0 (после softmax)."""
    masked = logits.masked_fill(mask == 0, PAD)
    logp = F.log_softmax(masked, dim=-1)
    return logp.exp(), logp


def _gather(logp: torch.Tensor, index: torch.Tensor) -> torch.Tensor:
    """logπ выбранного слота по строке [B, total] -> [B]."""
    return logp.gather(1, index.view(-1, 1)).squeeze(1)


def _entropy(probs: torch.Tensor, logp: torch.Tensor) -> torch.Tensor:
    """H = -Σ p·logp по строке; запрещённые слоты дают p=0 и не портят сумму."""
    return -(probs * logp).sum(-1)


def joint_logp(table: Dict[str, list], action: Action, ykey: Dict[str, str] = None) -> float:
    """Joint logπ исполненной тройки из logp_table act(): сумма logπ по группам.

    Индексы action — уже легализованные средой (legalize); все они лежат в маске, поэтому
    gather из таблицы корректен. Это то же logπ, что _eval посчитает на обновлении.
    Ключи действия берутся из ykey (схема 2: cell/target/weapon, схема 3: plan/...).
    """
    yk = ykey or Y_KEY
    return float(sum(table[group][int(action[yk[group]])] for group in GROUPS))


class PPOAgent:
    """Актёр+критик PPO над одной TorchPolicy: act сэмплит, update оптимизирует суррогат."""

    def __init__(self, policy: Any, clip_eps: float = 0.2, ent_coef: float = 0.01,
                 vf_coef: float = 0.5, ppo_epochs: int = 4, minibatch: int = 32,
                 target_kl: float = 0.03):
        if not (hasattr(policy, "_batch") and hasattr(policy, "_pass")
                and hasattr(policy, "optim")):
            raise RuntimeError("PPO требует torch-политику: kind=pure вне scope RL "
                               "(запустите обучение с torch-бэкендом)")
        self.policy = policy
        self.ykey = getattr(policy, "ykey", Y_KEY)      # ключи действия по схеме (v3: plan)
        self.clip_eps = clip_eps
        self.ent_coef = ent_coef
        self.vf_coef = vf_coef
        self.ppo_epochs = max(1, int(ppo_epochs))
        self.minibatch = max(1, int(minibatch))
        self.target_kl = target_kl

    # ------------------------------------------------------------------ сэмпл хода
    @torch.no_grad()
    def act(self, sample: Dict[str, Any]) -> Dict[str, Any]:
        """Один шаг: тройка индексов из masked-распределений + joint logπ, энтропия, V(s).

        Возвращает ещё logp_table — ряд logπ по всем слотам каждой группы: среда после
        выборки может убрать нелегальную атаку (legalize), и тогда logπ берётся от
        ИСПОЛНЕННОГО действия из той же таблицы (joint_logp), без второго прогона сети.
        """
        state, slots, masks = self.policy._batch([sample])
        logits, value = self.policy._pass(state, slots, masks)
        action: Action = {}
        table: Dict[str, list] = {}
        logp_sum, ent_sum = torch.zeros((), device=self.policy.device), torch.zeros(
            (), device=self.policy.device)
        for group in GROUPS:
            probs, logp = _dist(logits[group], masks[group])
            index = torch.multinomial(probs, num_samples=1)         # [1,1] только по легальным
            logp_sum = logp_sum + _gather(logp, index)
            ent_sum = ent_sum + _entropy(probs, logp)
            table[group] = [float(x) for x in logp[0].tolist()]
            action[self.ykey[group]] = int(index.item())
        return {"action": action,
                "logp": float(logp_sum.item()),
                "entropy": float(ent_sum.item()),
                "value": float(value.item()),
                "logp_table": table}

    @torch.no_grad()
    def value_of(self, sample: Dict[str, Any]) -> float:
        """Только V(s) без сэмплирования: бутстрап на усечении не двигает sampling-RNG."""
        state, slots, masks = self.policy._batch([sample])
        _logits, value = self.policy._pass(state, slots, masks)
        return float(value.item())

    # ------------------------------------------------------------------ логп/ценность батча
    def _eval(self, batch: List[Dict[str, Any]], actions: List[Action]):
        """Пересчитать для батча: joint logπ выбранных троек, сумму энтропии, V(s)."""
        state, slots, masks = self.policy._batch(batch)
        logits, value = self.policy._pass(state, slots, masks)
        logp = torch.zeros(state.shape[0], device=self.policy.device)
        ent = torch.zeros(state.shape[0], device=self.policy.device)
        for group in GROUPS:
            probs, lg = _dist(logits[group], masks[group])
            idx = torch.tensor([int(a[self.ykey[group]]) for a in actions], dtype=torch.long,
                               device=self.policy.device)
            logp = logp + _gather(lg, idx)
            ent = ent + _entropy(probs, lg)
        return logp, ent, value

    # ------------------------------------------------------------------ PPO-обновление
    def update(self, trajectories: List[Dict[str, Any]]) -> Dict[str, Any]:
        """K эпох мини-батчами: clipped surrogate + value MSE + entropy, стоп по target_kl.

        Каждая запись trajectories: {sample, action, logp (старый joint), adv, ret}.
        Advantages/returns приходят из rl.py (GAE); здесь — только суррогат и критик.
        """
        n = len(trajectories)
        if n == 0:
            return {"n": 0, "loss": 0.0, "policy_loss": 0.0, "value_loss": 0.0,
                    "entropy": 0.0, "kl": 0.0, "clip_frac": 0.0}
        samples = [t["sample"] for t in trajectories]
        actions = [t["action"] for t in trajectories]
        old_logp = torch.tensor([float(t["logp"]) for t in trajectories],
                                dtype=torch.float32, device=self.policy.device)
        adv = torch.tensor([float(t["adv"]) for t in trajectories],
                           dtype=torch.float32, device=self.policy.device)
        ret = torch.tensor([float(t["ret"]) for t in trajectories],
                           dtype=torch.float32, device=self.policy.device)
        report: Dict[str, Any] = {}
        for _epoch in range(self.ppo_epochs):
            order = torch.randperm(n, device=self.policy.device)
            stop = False
            for start in range(0, n, self.minibatch):
                mb = order[start:start + self.minibatch]
                mini = [samples[i] for i in mb]
                mact = [actions[i] for i in mb]
                new_logp, ent, value = self._eval(mini, mact)
                ratio = (new_logp - old_logp[mb]).exp()
                surr1 = ratio * adv[mb]
                surr2 = torch.clamp(ratio, 1.0 - self.clip_eps, 1.0 + self.clip_eps) * adv[mb]
                policy_loss = -torch.min(surr1, surr2).mean()
                value_loss = F.mse_loss(value, ret[mb])
                entropy = ent.mean()
                loss = policy_loss + self.vf_coef * value_loss - self.ent_coef * entropy
                self.policy.optim.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.policy.layers.parameters(), 0.5)
                self.policy.optim.step()
                with torch.no_grad():
                    approx_kl = (old_logp[mb] - new_logp).mean().item()
                    report = {"loss": round(float(loss.item()), 4),
                              "policy_loss": round(float(policy_loss.item()), 4),
                              "value_loss": round(float(value_loss.item()), 4),
                              "entropy": round(float(entropy.item()), 4),
                              "kl": round(approx_kl, 5),
                              "clip_frac": round(float(((ratio - 1).abs() > self.clip_eps)
                                                       .float().mean().item()), 4)}
                if abs(approx_kl) > self.target_kl:
                    stop = True
            if stop:
                break
        report["n"] = n
        return report
