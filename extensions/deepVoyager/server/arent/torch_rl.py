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
from arent.torch_net import _dist, _joint_batch

Action = Dict[str, int]


def joint_logp(table: Dict[str, list], action: Action, ykey: Dict[str, str] = None,
               logZ: float = 0.0) -> float:
    """Joint logπ тройки из logp_table act(): сумма logπ по группам минус нормировка logZ.

    Без logZ (по умолчанию) — прежнее ненормированное произведение голов (низкоуровневый
    примитив; используется внешними вызовами и тестом суммы по группам). С logZ из act()
    — честный logπ совместного распределения по допустимому множеству: то же значение,
    что пересчитает _eval на PPO-обновлении для того же (состояние, действие, политики).
    Индексы action — легализованные средой; для корректного выбора они уже в допустимом
    множестве, поэтому gather из таблицы корректен и legalization — тождество.
    """
    yk = ykey or Y_KEY
    return float(sum(table[group][int(action[yk[group]])] for group in GROUPS) - logZ)


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
        """Один шаг: тройка из СОВМЕСТНО допустимого распределения + его joint logπ/энтропия.

        Головы дают замаскированные log-softmax; над ними — нормированное произведение по
        множеству допустимых троек sample["legal"] (arent/joint.py: то же правило легальности,
        что у legalize). Сэмплируем ровно из этого закона, поэтому выбранная тройка уже
        совместна и legalization в среде — тождество (предложение не правится постфактум).
        logπ и энтропия считаются от того же распределения, что и update (_eval): отношение
        важности PPO честное. logp_table/logZ — те же ряды logπ по слотам, что позволяют
        rollout пересчитать logπ исполненного действия без второго прогона сети.
        """
        state, slots, masks = self.policy._batch([sample])
        logits, value = self.policy._pass(state, slots, masks)
        head: Dict[str, torch.Tensor] = {}
        table: Dict[str, list] = {}
        for group in GROUPS:
            _probs, logp = _dist(logits[group], masks[group])
            head[group] = logp                                            # [1, size]
            table[group] = [float(x) for x in logp[0].tolist()]
        legal = torch.tensor([sample["legal"]], dtype=torch.float32, device=self.policy.device)
        logpi, logZ = _joint_batch(head["cells"], head["targets"], head["weapons"], legal)
        logpi, m = logpi[0], legal[0]                                     # [P,T,W]
        probs = logpi.exp() * m                                           # точно 0 на недопустимых
        entropy = float(-(probs * (logpi * m)).sum().item())
        idx = int(torch.multinomial(probs.reshape(-1), num_samples=1).item())
        p_n, t_n, w_n = logpi.shape
        p = idx // (t_n * w_n); rem = idx % (t_n * w_n); t = rem // w_n; w = rem % w_n
        action: Action = {self.ykey["cells"]: p, self.ykey["targets"]: t, self.ykey["weapons"]: w}
        return {"action": action,
                "logp": float(logpi[p, t, w].item()),
                "entropy": entropy,
                "value": float(value.item()),
                "logp_table": table, "logZ": float(logZ[0].item())}

    @torch.no_grad()
    def value_of(self, sample: Dict[str, Any]) -> float:
        """Только V(s) без сэмплирования: бутстрап на усечении не двигает sampling-RNG."""
        state, slots, masks = self.policy._batch([sample])
        _logits, value = self.policy._pass(state, slots, masks)
        return float(value.item())

    # ------------------------------------------------------------------ логп/ценность батча
    def _eval(self, batch: List[Dict[str, Any]], actions: List[Action]):
        """Пересчитать joint logπ выбранных троек (тот же закон, что act), энтропию, V(s).

        Совместное распределение строится заново из текущих весов поверх того же множества
        допустимых троек batch[i]["legal"]. Поэтому new_logp — logπ того же закона, из
        которого act сэмплировал действие: rollout и update считаются согласованно.
        """
        state, slots, masks = self.policy._batch(batch)
        logits, value = self.policy._pass(state, slots, masks)
        head: Dict[str, torch.Tensor] = {}
        for group in GROUPS:
            _probs, logp = _dist(logits[group], masks[group])
            head[group] = logp                                            # [B, size]
        legal = torch.tensor([s["legal"] for s in batch], dtype=torch.float32,
                             device=self.policy.device)                   # [B,P,T,W]
        logpi, _logZ = _joint_batch(head["cells"], head["targets"], head["weapons"], legal)
        b = logpi.shape[0]
        ar = torch.arange(b, device=self.policy.device)
        ip = torch.tensor([int(a[self.ykey["cells"]]) for a in actions], dtype=torch.long,
                          device=self.policy.device)
        it = torch.tensor([int(a[self.ykey["targets"]]) for a in actions], dtype=torch.long,
                          device=self.policy.device)
        iw = torch.tensor([int(a[self.ykey["weapons"]]) for a in actions], dtype=torch.long,
                          device=self.policy.device)
        logp = logpi[ar, ip, it, iw]                                      # [B] нормированный logπ
        probs = logpi.exp() * legal
        ent = -(probs * (logpi * legal)).reshape(b, -1).sum(1)            # [B] энтропия joint
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
