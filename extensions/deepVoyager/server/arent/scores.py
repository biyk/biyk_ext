# arent/scores.py — метрики качества политика и разбивка по состояниям.
#
# Вынесено из train.py, чтобы сам цикл обучения оставался компактным. Тесты и отчёты
# ссылаются на них как на train.metrics / train.by_source (re-export в train.py).
#
# ЭТАП 8: семантика метрик согласована с objective и serving. BC минимизирует joint NLL
# (logπ по A(s)), serving выбирает joint argmax по A(s) — значит и отбор чекпойпта меряет
# ЭТИ же величины по ВСЕЙ выборке (не по последнему батчу):
#  • joint_nll                  — средняя -logπ правильного действия по совместному закону
#                                 (logZ по A(s) минус сумма masked log-softmax голов);
#                                 МЕНЬШЕ = ЛУЧШЕ, основной критерий отбора;
#  • joint_decode_accuracy      — доля примеров, где ДЕТЕТЕРМИНИРОВАННЫЙ joint argmax по
#                                 A(s) (тот же joint.argmax, что играет в serving) угадал
#                                 метку; БОЛЬШЕ = ЛУЧШЕ, сопутствующая метрика;
#  • independent_baseline_accuracy — старый «joint» = все три НЕЗАВИСИМЫЙ argmax голов
#                                 одновременно равны метке. Чистая диагностика: serving
#                                 так больше не выбирает, по этому числу чекпойпт НЕ судят;
#  • value_mse / value_mae      — стоимость отдельно от action loss (в критерий не входит);
#  • cell/target/weapon         — по-slotовая accuracy независимых голов (диагностика).
from typing import Any, Dict, List

from arent import joint, net
from arent.net import GROUPS, y_index


def _joint_bits(model: Any, sample: Dict[str, Any], schema: int):
    """(joint_nll, decode_угадал) для одного примера — единая формула для метрик и тестов."""
    ip, it, iw = joint.ensure_jointly_legal(sample, schema)
    lcs, lts, lws, _v = model.head_logp(sample)
    legal = sample["legal"]
    nll = joint.logz(legal, lcs, lts, lws) - (lcs[ip] + lts[it] + lws[iw])
    pick = joint.argmax(legal, lcs, lts, lws, schema)
    yk = net.y_key(schema)
    ok = int(pick[yk["cells"]] == ip and pick["target"] == it and pick["weapon"] == iw)
    return nll, ok


def metrics(model: Any, samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Метрики по ВСЕМУ набору: joint NLL/decode-accuracy + независимый baseline + value.

    Ключ метки группы клеток зависит от схемы (cell в v2, plan в v3), но имена метрик
    стабильны. joint_* считаются только если модель отдаёт head_logp, а пример несёт
    совместную маску legal (её пишет encode для обеих схем с Этапа 2); для моделей без
    head_logp joint-поля остаются None — отбор чекпойпта тогда невозможен и train.py
    сообщит об этом явно, ничего не подменяя молча.
    """
    schema = getattr(getattr(model, "cfg", None), "schema", net.SCHEMA)
    yk = net.y_key(schema)
    has_joint = hasattr(model, "head_logp")
    hits = {group: 0 for group in GROUPS}
    indep = decode_ok = nj = 0
    jnll = vae = vse = 0.0
    for sample in samples:
        out = model.predict(sample)                    # независимый argmax каждой головы
        good = []
        for group in GROUPS:
            same = out[yk[group]] == y_index(sample, group, schema)
            good.append(same)
            hits[group] += 1 if same else 0
        indep += 1 if all(good) else 0                 # старый «joint»: диагностика, не выбор
        value = float(out["value"])
        target = float(sample.get("value", 0.0))
        vae += abs(value - target)
        vse += (value - target) ** 2
        if has_joint and sample.get("legal"):
            nll, ok = _joint_bits(model, sample, schema)
            jnll += nll
            decode_ok += ok
            nj += 1
    n = max(1, len(samples))
    return {"cell": round(hits["cells"] / n, 3), "target": round(hits["targets"] / n, 3),
            "weapon": round(hits["weapons"] / n, 3),
            "independent_baseline_accuracy": round(indep / n, 3),
            "joint_decode_accuracy": round(decode_ok / nj, 3) if nj else None,
            "joint_nll": round(jnll / nj, 5) if nj else None,
            "value_mae": round(vae / n, 4), "value_mse": round(vse / n, 6),
            "n": len(samples), "n_joint": nj}


def batches(order: List[Dict[str, Any]], size: int) -> List[List[Dict[str, Any]]]:
    return [order[i:i + max(1, size)] for i in range(0, len(order), max(1, size))]


def sample_joint_nll(model: Any, sample: Dict[str, Any]) -> float:
    """Joint NLL одного примера: logZ по A(s) минус сумма masked-логхедов на метке.

    Ровно тот член, который минимизирует BC-шаг (pure_net._accumulate report["loss"],
    torch_net.step_batch action_loss) без value-добавки: -logπ_joint(a*|s). Требует
    model.head_logp и sample["legal"]; метка проходит ensure_jointly_legal.
    Общий примитив для метрик и тестов: формула живёт в одном месте.
    """
    schema = int(sample.get("schema", getattr(getattr(model, "cfg", None), "schema", net.SCHEMA)))
    return _joint_bits(model, sample, schema)[0]


def epoch_loss(reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Средний loss эпохи по ВСЕМ батчам с весом по размеру (не «последний батч»).

    step_batch уже возвращает СРЕДНЕЕ по своему батчу и его размер n; взвешивание по n
    даёт точное среднее по всем обработанным примерам, не зависящее от разбиения.
    """
    num = den = 0.0
    for rep in reports:
        lv = rep.get("loss")
        if lv is None:
            continue
        k = max(1, int(rep.get("n", 1)))
        num += float(lv) * k
        den += k
    return {"loss": round(num / den, 4) if den else None, "n_samples": int(den)}


def by_source(model: Any, samples: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Метрики по имени состояния (meta.arena, иначе meta.src): проверка на забывание.

    После дообучения сравнивают эти строчки между прогонами: если joint_nll старой арены
    вырос, новые примеры затёрли прежний навык, и датасет надо мешать.
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for sample in samples:
        meta = sample.get("meta") or {}
        name = str(meta.get("arena") or meta.get("src") or "?")
        groups.setdefault(name, []).append(sample)
    return {name: metrics(model, chunk) for name, chunk in sorted(groups.items())}
