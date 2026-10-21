# arent/torch_net.py — тот же политик, что pure_net, но на torch (CUDA на машине с 4060).
#
# Граф повторяет pure_net слой в слой, поэтому чекпойнт net.save читается обоими
# бэкендами: обучил на видеокарте — играет машина без torch. Пакет torch импортируется
# только когда он реально установлен (backend проверяет это сам).
from typing import Any, Dict, List

import torch
import torch.nn.functional as F

from arent import net
from arent.net import GROUPS, y_index

PAD = -1e30                      # вместо -inf: он остаётся конечным и не ломает sum


def _module(cfg: net.Config) -> torch.nn.Module:
    """Ствол по состоянию + по голове на группу слотов + линейная голова стоимости."""
    d = net.dims_for(cfg.schema)
    layers = torch.nn.ModuleDict({
        "trunk1": torch.nn.Linear(d["state"], cfg.hidden),
        "trunk2": torch.nn.Linear(cfg.hidden, cfg.head),
        "heads": torch.nn.ModuleDict({g: torch.nn.Linear(cfg.head + net.slot_size(g, cfg.schema), cfg.head)
                                      for g in GROUPS}),
        "score": torch.nn.ModuleDict({g: torch.nn.Linear(cfg.head, 1) for g in GROUPS}),
        "value": torch.nn.Linear(cfg.head, 1),
    })
    return layers


class TorchPolicy:
    """Батчевый обучаемый политик: logits по группам (маскированные) + стоимость линии."""

    name = "torch"

    def __init__(self, cfg: net.Config, params: Dict[str, Any] = None, device: str = None):
        self.cfg = cfg
        self.dims = net.dims_for(cfg.schema)
        self.ykey = net.y_key(cfg.schema)
        cuda = torch.cuda.is_available()
        want = (device or "auto")
        self.device = torch.device("cuda" if want in ("auto", "cuda") and cuda else "cpu")
        torch.manual_seed(cfg.seed)
        self.layers = _module(cfg).to(self.device)
        self.optim = torch.optim.Adam(self.layers.parameters(), lr=cfg.lr,
                                      weight_decay=cfg.weight_decay)
        if params is not None:
            self.set_params(params)

    # ------------------------------------------------------------------ параметры
    def set_params(self, params: Dict[str, Any]) -> None:
        """Веса из формата net.init_params (rows x cols — как у torch.Linear)."""
        with torch.no_grad():
            self.layers["trunk1"].weight.copy_(_t(params["trunk1"]))
            self.layers["trunk1"].bias.copy_(_t(params["b1"]))
            self.layers["trunk2"].weight.copy_(_t(params["trunk2"]))
            self.layers["trunk2"].bias.copy_(_t(params["b2"]))
            self.layers["value"].weight.copy_(_t([params["valueW"]]))
            self.layers["value"].bias.copy_(_s(params["valueB"]))
            for group in GROUPS:
                self.layers["heads"][group].weight.copy_(_t(params["headW"][group]))
                self.layers["heads"][group].bias.copy_(_t(params["headB"][group]))
                self.layers["score"][group].weight.copy_(_t([params["headU"][group]]))
                self.layers["score"][group].bias.copy_(_s(params["headUB"][group]))

    @property
    def params(self) -> Dict[str, Any]:
        """Те же списки, что пишет/читает pure_net (float32 -> float, детачим)."""
        with torch.no_grad():
            out = {"trunk1": _l(self.layers["trunk1"].weight), "b1": _l(self.layers["trunk1"].bias),
                   "trunk2": _l(self.layers["trunk2"].weight), "b2": _l(self.layers["trunk2"].bias),
                   "valueW": _l(self.layers["value"].weight)[0],
                   "valueB": float(self.layers["value"].bias.item()),
                   "headW": {}, "headB": {}, "headU": {}, "headUB": {}}
            for group in GROUPS:
                out["headW"][group] = _l(self.layers["heads"][group].weight)
                out["headB"][group] = _l(self.layers["heads"][group].bias)
                out["headU"][group] = _l(self.layers["score"][group].weight)[0]
                out["headUB"][group] = float(self.layers["score"][group].bias.item())
        return out

    # ------------------------------------------------------------------ прямой проход
    def _batch(self, samples: List[Dict[str, Any]]):
        state = torch.tensor([s["state"] for s in samples], dtype=torch.float32,
                             device=self.device)
        slots = {g: torch.tensor([s[g] for s in samples], dtype=torch.float32,
                                 device=self.device) for g in GROUPS}
        masks = {g: torch.tensor([s["mask"][g] for s in samples], dtype=torch.float32,
                                 device=self.device) for g in GROUPS}
        return state, slots, masks

    def _pass(self, state, slots, masks):
        stem = F.relu(self.layers["trunk2"](F.relu(self.layers["trunk1"](state))))
        logits = {}
        for group in GROUPS:
            wide = stem.unsqueeze(1).expand(-1, slots[group].size(1), -1)
            hit = F.relu(self.layers["heads"][group](torch.cat([wide, slots[group]], dim=2)))
            raw = self.layers["score"][group](hit).squeeze(2)
            logits[group] = raw.masked_fill(masks[group] == 0, PAD)
        return logits, self.layers["value"](stem).squeeze(1)

    def predict(self, sample: Dict[str, Any]) -> Dict[str, Any]:
        state, slots, masks = self._batch([sample])
        with torch.no_grad():
            logits, value = self._pass(state, slots, masks)
            out: Dict[str, Any] = {"value": round(float(value.item()), 4)}
            for group in GROUPS:
                row, ok = logits[group][0], sample["mask"][group]
                index = int(torch.argmax(row).item())
                allowed = index < len(ok) and ok[index]
                out[self.ykey[group]] = index if allowed else -1
                prob = F.softmax(row, dim=0)[index] if allowed else 0.0
                out[self.ykey[group] + "Prob"] = round(float(prob.item()), 4)
        return out

    def step_batch(self, batch: List[Dict[str, Any]], lr: float = None) -> Dict[str, Any]:
        if lr is not None:
            for group_ in self.optim.param_groups:
                group_["lr"] = lr
        state, slots, masks = self._batch(batch)
        targets = {g: torch.tensor([y_index(s, g, self.cfg.schema) for s in batch], dtype=torch.long,
                                   device=self.device) for g in GROUPS}
        wanted = torch.tensor([float(s.get("value", 0.0)) for s in batch], dtype=torch.float32,
                              device=self.device)
        self.optim.zero_grad(set_to_none=True)
        logits, value = self._pass(state, slots, masks)
        parts, total = {}, torch.zeros((), device=self.device)
        for group in GROUPS:
            loss = F.cross_entropy(logits[group], targets[group])
            parts[self.ykey[group]] = float(loss.item())
            total = total + loss
        value_loss = F.mse_loss(value, wanted)
        # 0.5 — чтобы градиент был value_w * diff, как в pure_net._accumulate: иначе на
        # torch стоимость давит вдвое сильнее и метрики двух бэкендов несопоставимы.
        total = total + 0.5 * self.cfg.value_w * value_loss
        total.backward()
        self.optim.step()
        report = {"loss": round(float(total.item()), 4), "value": round(float(value_loss.item()), 4)}
        report.update(parts)
        report["n"] = len(batch)
        return report


def _t(rows: List[Any]) -> torch.Tensor:
    """Вложенный список -> 2D-тензор, плоский список -> 1D (bias), скаляр -> _s."""
    if isinstance(rows, list) and rows and not isinstance(rows[0], list):
        return torch.tensor([float(x) for x in rows], dtype=torch.float32)
    return torch.tensor([[float(x) for x in row] for row in rows], dtype=torch.float32)


def _s(value: Any) -> torch.Tensor:
    """Скалярный параметр формата -> тензор из одного элемента (bias у Linear(.,1))."""
    return torch.tensor([float(value)], dtype=torch.float32)


def _l(tensor: torch.Tensor) -> List[Any]:
    """Тензор -> вложенные списки float (1D остаётся 1D)."""
    rows = tensor.detach().cpu().tolist()
    return rows if rows and isinstance(rows[0], list) else rows
