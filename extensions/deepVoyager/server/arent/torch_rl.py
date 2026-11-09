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

from arent.net import GROUPS, Y_KEY, groups_for
from arent.torch_net import _dist, _joint_batch, _joint_batch_v5

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
    # Итерация по КЛЮЧАМ таблицы (не по фикс. GROUPS): для v2/3/4 таблица = cells/targets/weapons
    # (тот же порядок вставки -> побитово прежняя сумма), для v5 к ней добавляется maneuvers.
    return float(sum(table[group][int(action[yk[group]])] for group in table) - logZ)


@torch.no_grad()
def joint_logpi_of(policy: Any, sample: Dict[str, Any]) -> List[List[List[float]]]:
    """Полное нормированное joint-распределение logπ по допустимому множеству sample.

    Вложенный список [P,T,W] (недопустимые тройки = PAD). Нужен KL-якорю к замороженному
    π_ref: то же правило нормировки, что у act/_eval (_dist + _joint_batch), поэтому_support
    и шкала совпадают с текущей политикой и forward-KL считается на одном legal-множестве.
    """
    state, slots, masks = policy._batch([sample])
    logits, _value = policy._pass(state, slots, masks)
    groups = groups_for(getattr(getattr(policy, "cfg", None), "schema", 2))
    head: Dict[str, torch.Tensor] = {}
    for group in groups:
        _probs, logp = _dist(logits[group], masks[group])
        head[group] = logp
    legal = torch.tensor([sample["legal"]], dtype=torch.float32, device=policy.device)
    if "maneuvers" in head:
        logpi, _logZ = _joint_batch_v5(head["cells"], head["targets"], head["weapons"],
                                       head["maneuvers"], legal)
    else:
        logpi, _logZ = _joint_batch(head["cells"], head["targets"], head["weapons"], legal)
    return logpi[0].tolist()


class PPOAgent:
    """Актёр+критик PPO над одной TorchPolicy: act сэмплит, update оптимизирует суррогат."""

    def __init__(self, policy: Any, clip_eps: float = 0.2, ent_coef: float = 0.01,
                 vf_coef: float = 0.5, ppo_epochs: int = 4, minibatch: int = 32,
                 target_kl: float = 0.03, anchor_coef: float = 0.0):
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
        self.anchor_coef = max(0.0, float(anchor_coef))  # KL(π_θ‖π_ref) к BC-приору (0 = выкл.)

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
        groups = groups_for(getattr(getattr(self.policy, "cfg", None), "schema", 2))
        head: Dict[str, torch.Tensor] = {}
        table: Dict[str, list] = {}
        for group in groups:
            _probs, logp = _dist(logits[group], masks[group])
            head[group] = logp                                            # [1, size]
            table[group] = [float(x) for x in logp[0].tolist()]
        legal = torch.tensor([sample["legal"]], dtype=torch.float32, device=self.policy.device)
        if "maneuvers" in groups:                    # v5: 4D A(s) (pos×target×weapon×maneuver)
            logpi, logZ = _joint_batch_v5(head["cells"], head["targets"], head["weapons"],
                                          head["maneuvers"], legal)
        else:                                        # v2/3/4: прежний 3D-закон (побитово)
            logpi, logZ = _joint_batch(head["cells"], head["targets"], head["weapons"], legal)
        logpi, m = logpi[0], legal[0]                                     # [P,T,W(,M)]
        probs = logpi.exp() * m                                           # точно 0 на недопустимых
        entropy = float(-(probs * (logpi * m)).sum().item())
        idx = int(torch.multinomial(probs.reshape(-1), num_samples=1).item())
        coords = torch.unravel_index(torch.tensor(idx), torch.Size(logpi.shape))
        action: Action = {self.ykey["cells"]: int(coords[0]),
                          self.ykey["targets"]: int(coords[1]),
                          self.ykey["weapons"]: int(coords[2])}
        if "maneuvers" in groups:
            action[self.ykey["maneuvers"]] = int(coords[3])
        return {"action": action,
                "logp": float(logpi.reshape(-1)[idx].item()),
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
        groups = groups_for(getattr(getattr(self.policy, "cfg", None), "schema", 2))
        head: Dict[str, torch.Tensor] = {}
        for group in groups:
            _probs, logp = _dist(logits[group], masks[group])
            head[group] = logp                                            # [B, size]
        legal = torch.tensor([s["legal"] for s in batch], dtype=torch.float32,
                             device=self.policy.device)                   # [B,P,T,W(,M)]
        if "maneuvers" in groups:
            logpi, _logZ = _joint_batch_v5(head["cells"], head["targets"], head["weapons"],
                                           head["maneuvers"], legal)
        else:
            logpi, _logZ = _joint_batch(head["cells"], head["targets"], head["weapons"], legal)
        b = logpi.shape[0]
        ar = torch.arange(b, device=self.policy.device)
        ip = torch.tensor([int(a[self.ykey["cells"]]) for a in actions], dtype=torch.long,
                          device=self.policy.device)
        it = torch.tensor([int(a[self.ykey["targets"]]) for a in actions], dtype=torch.long,
                          device=self.policy.device)
        iw = torch.tensor([int(a[self.ykey["weapons"]]) for a in actions], dtype=torch.long,
                          device=self.policy.device)
        if "maneuvers" in groups:
            im = torch.tensor([int(a[self.ykey["maneuvers"]]) for a in actions], dtype=torch.long,
                              device=self.policy.device)
            logp = logpi[ar, ip, it, iw, im]                              # [B] нормированный logπ
        else:
            logp = logpi[ar, ip, it, iw]                                  # [B] нормированный logπ
        probs = logpi.exp() * legal
        ent = -(probs * (logpi * legal)).reshape(b, -1).sum(1)            # [B] энтропия joint
        return logp, ent, value, logpi, legal

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
        # KL-якорь к замороженному BC-приору: ref-распределения собираются один раз в rollout
        # (collect кладёт ref_logpi только при anchor_coef>0). Без них — чистый PPO (обратная
        # совместимость): anchor_coef>0, но ref_logpi нет => тихо 0, а не падение.
        ref_lp = None
        if self.anchor_coef > 0.0 and all("ref_logpi" in t for t in trajectories):
            ref_lp = torch.tensor([t["ref_logpi"] for t in trajectories],
                                  dtype=torch.float32, device=self.policy.device)
        report: Dict[str, Any] = {}
        for _epoch in range(self.ppo_epochs):
            order = torch.randperm(n, device=self.policy.device)
            stop = False
            for start in range(0, n, self.minibatch):
                mb = order[start:start + self.minibatch]
                mini = [samples[i] for i in mb]
                mact = [actions[i] for i in mb]
                new_logp, ent, value, logpi, legal = self._eval(mini, mact)
                ratio = (new_logp - old_logp[mb]).exp()
                surr1 = ratio * adv[mb]
                surr2 = torch.clamp(ratio, 1.0 - self.clip_eps, 1.0 + self.clip_eps) * adv[mb]
                policy_loss = -torch.min(surr1, surr2).mean()
                value_loss = F.mse_loss(value, ret[mb])
                entropy = ent.mean()
                loss = policy_loss + self.vf_coef * value_loss - self.ent_coef * entropy
                kl_anchor = 0.0
                if ref_lp is not None:
                    # forward reverse-KL(π_θ‖π_ref) на общем legal-множестве: штраф за массу
                    # политики там, где приор ставит мало (удерживает весы у BC-позвола).
                    theta = logpi * legal
                    ref = ref_lp[mb] * legal
                    p_theta = theta.exp() * legal
                    diff = torch.where(legal > 0, theta - ref, torch.zeros_like(theta))
                    kl_anchor = (p_theta * diff).reshape(len(mb), -1).sum(1).mean()
                    loss = loss + self.anchor_coef * kl_anchor
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
                              "anchor_kl": round(float(kl_anchor), 5) if ref_lp is not None else 0.0,
                              "clip_frac": round(float(((ratio - 1).abs() > self.clip_eps)
                                                       .float().mean().item()), 4)}
                if abs(approx_kl) > self.target_kl:
                    stop = True
            if stop:
                break
        report["n"] = n
        return report
