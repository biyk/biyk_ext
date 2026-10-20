# arent/pure_net.py — политика на чистом python: тот же граф, что у torch_net.
#
# Нужна ровно для двух вещей: обучить небольшую модель там, где torch не установлен
# (на этой машине), и играть чекпойнтом, собранным на видеокарте: формат параметров
# общий (net.init_params), поэтому файл весов переносится между бэкендами.
# Ствол relu, голова группы = relu([ствол ; вектор слота]) -> скаляр, стоимость —
# линейная по стволу. Градиенты рукописные, шаг — SGD с моментумом.
import math
from typing import Any, Dict, List

from arent import net
from arent.net import GROUPS, Y_KEY, masked_argmax, y_index


def _dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _relu(v: List[float]) -> List[float]:
    return [x if x > 0.0 else 0.0 for x in v]


def _lin(rows: List[List[float]], bias: List[float], x: List[float]) -> List[float]:
    return [b + _dot(row, x) for row, b in zip(rows, bias)]


def _softmax(values: List[float]) -> List[float]:
    top = max(values)
    exps = [math.exp(v - top) for v in values]
    total = sum(exps) or 1.0
    return [e / total for e in exps]


def _zeros_like(obj: Any) -> Any:
    """Зеркало структуры параметров под градиенты и моментум (списки, словари, скаляры)."""
    if isinstance(obj, dict):
        return {k: _zeros_like(v) for k, v in obj.items()}
    if isinstance(obj, list):
        if obj and isinstance(obj[0], list):
            return [[0.0] * len(row) for row in obj]
        return [0.0] * len(obj)
    return 0.0


class PurePolicy:
    """Прямой проход + рукописный backward + SGD с моментумом (батч = сумма градиентов)."""

    name = "pure"

    def __init__(self, cfg: net.Config, params: Dict[str, Any] = None):
        self.cfg = cfg
        self.params = params if params is not None else net.init_params(cfg)
        self.grad = _zeros_like(self.params)
        self.vel = _zeros_like(self.params)

    def forward(self, sample: Dict[str, Any]):
        """Состояние -> (а1, ствол, logits по группам, стоимость). Слоты вне маски не считаем."""
        p = self.params
        a1pre = _lin(p["trunk1"], p["b1"], sample["state"])
        a1 = _relu(a1pre)
        z2 = _lin(p["trunk2"], p["b2"], a1)
        t = _relu(z2)
        logits, cache = {}, {}
        for group in GROUPS:
            rows, bias = p["headW"][group], p["headB"][group]
            head, ub = p["headU"][group], p["headUB"][group]
            allowed, values, kept = [], [], {}
            for i, (vec, ok) in enumerate(zip(sample[group], sample["mask"][group])):
                if not ok:
                    continue
                u_in = t + list(vec)
                h_in = _lin(rows, bias, u_in)
                values.append(ub + _dot(head, _relu(h_in)))
                kept[i] = (u_in, h_in)
                allowed.append(i)
            logits[group] = (allowed, values)
            cache[group] = kept
        value = p["valueB"] + _dot(p["valueW"], t)
        return a1pre, a1, z2, t, logits, cache, value

    def predict(self, sample: Dict[str, Any]) -> Dict[str, Any]:
        *_, logits, _cache, value = self.forward(sample)
        out: Dict[str, Any] = {"value": round(value, 4)}
        for group in GROUPS:
            allowed, values = logits[group]
            best = masked_argmax(values, [1] * len(values)) if allowed else -1
            out[Y_KEY[group]] = allowed[best] if best >= 0 else -1
            out[Y_KEY[group] + "Prob"] = round(_softmax(values)[best], 4) if best >= 0 else 0.0
        return out

    def step_batch(self, batch: List[Dict[str, Any]], lr: float = None) -> Dict[str, Any]:
        """Один шаг оптимизатора по батчу: сумма градиентов, потом обновление."""
        report = {"loss": 0.0, "cell": 0.0, "target": 0.0, "weapon": 0.0, "value": 0.0}
        for sample in batch:
            self._accumulate(sample, report)
        n = max(1, len(batch))
        self._update((lr if lr is not None else self.cfg.lr) / n)
        scaled = {k: round(v / n, 4) for k, v in report.items()}
        scaled["n"] = n
        return scaled

    def _accumulate(self, sample: Dict[str, Any], report: Dict[str, float]) -> None:
        a1pre, a1, z2, t, logits, cache, value = self.forward(sample)
        p, g = self.params, self.grad
        dt = [0.0] * len(t)
        for group in GROUPS:
            allowed, values = logits[group]
            wanted = y_index(sample, group)
            if not allowed or wanted not in allowed:
                continue
            probs = _softmax(values)
            report["loss"] -= math.log(max(probs[allowed.index(wanted)], 1e-12))
            report[Y_KEY[group]] -= math.log(max(probs[allowed.index(wanted)], 1e-12))
            for i, prob in zip(allowed, probs):
                delta = prob - (1.0 if i == wanted else 0.0)
                if delta:
                    self._slot_backward(group, cache[group][i], delta, dt)
        diff = value - float(sample.get("value", 0.0))
        dv = self.cfg.value_w * diff
        report["value"] += abs(diff)
        report["loss"] += 0.5 * self.cfg.value_w * diff * diff
        vw = p["valueW"]
        gv = g["valueW"]
        for j in range(len(vw)):
            gv[j] += dv * t[j]
            dt[j] += dv * vw[j]
        g["valueB"] += dv
        self._trunk_backward(sample["state"], a1pre, a1, z2, dt)

    def _slot_backward(self, group: str, kept: Any, delta: float, dt: List[float]) -> None:
        """Градиенты головы по слоту: dlogit=delta, дальше relu([ствол ; вектор])."""
        u_in, h_in = kept
        p, g = self.params, self.grad
        head, rows = p["headU"][group], p["headW"][group]
        gu, gb, gw = g["headU"][group], g["headB"][group], g["headW"][group]
        g["headUB"][group] += delta
        for r in range(len(h_in)):
            if h_in[r] <= 0.0:
                continue
            dh = delta * head[r]              # dL/d(до relu) слоя головы
            gu[r] += delta * h_in[r]          # dL/d headU[r] = delta * relu(h_in[r])
            gb[r] += dh
            grow, wrow = gw[r], rows[r]
            for c, value in enumerate(u_in):
                grow[c] += dh * value
            for j in range(len(dt)):
                dt[j] += dh * wrow[j]

    def _trunk_backward(self, state, a1pre, a1, z2, dt) -> None:
        p, g = self.params, self.grad
        dz2 = [dt[j] if z2[j] > 0.0 else 0.0 for j in range(len(dt))]
        g2, g1 = g["trunk2"], g["trunk1"]
        da1 = [0.0] * len(a1)
        for r in range(len(g2)):
            if not dz2[r]:
                continue
            grow, wrow = g2[r], p["trunk2"][r]
            g["b2"][r] += dz2[r]
            for c in range(len(grow)):
                grow[c] += dz2[r] * a1[c]
                da1[c] += dz2[r] * wrow[c]
        for r in range(len(g1)):
            d = da1[r] * (1.0 if a1pre[r] > 0.0 else 0.0)
            if not d:
                continue
            g["b1"][r] += d
            grow = g1[r]
            for c in range(len(grow)):
                grow[c] += d * state[c]

    def _update(self, lr: float) -> None:
        p, g, v = self.params, self.grad, self.vel
        wd = self.cfg.weight_decay
        for key in ("trunk1", "trunk2"):
            for i, row in enumerate(p[key]):
                self._sgd(row, g[key][i], v[key][i], lr, wd)
        for key in ("b1", "b2", "valueW"):
            self._sgd(p[key], g[key], v[key], lr, wd)
        for group in GROUPS:
            for i, row in enumerate(p["headW"][group]):
                self._sgd(row, g["headW"][group][i], v["headW"][group][i], lr, wd)
            self._sgd(p["headB"][group], g["headB"][group], v["headB"][group], lr, wd)
            self._sgd(p["headU"][group], g["headU"][group], v["headU"][group], lr, wd)
            p["headUB"][group], v["headUB"][group] = self._sgd_scalar(
                p["headUB"][group], g["headUB"][group], v["headUB"][group], lr, wd)
            g["headUB"][group] = 0.0
        p["valueB"], v["valueB"] = self._sgd_scalar(p["valueB"], g["valueB"], v["valueB"], lr, wd)
        g["valueB"] = 0.0

    def _sgd(self, w: List[float], gw: List[float], vw: List[float], lr: float, wd: float) -> None:
        m = self.cfg.momentum
        for i in range(len(w)):
            vw[i] = m * vw[i] + gw[i] + wd * w[i]
            w[i] -= lr * vw[i]
            gw[i] = 0.0

    def _sgd_scalar(self, w: float, gw: float, vw: float, lr: float, wd: float):
        v = self.cfg.momentum * vw + gw + wd * w
        return w - lr * v, v
