# diagnostics/stage6_build.py — ЭТАП 6 (часть 2): собрать малый стратифицированный v3-датасет.
#
# Отдельный рабочий каталог (paths.set_workspace -> server/stage6_out), чтобы НЕ трогать
# боевые arent/data и arent/runs. Все примеры собраны НОВОЙ версией признаков (feat_version=2,
# cell_feat=21); old-format в выборку не примешивается (dataset.assert_compatible при load-back).
# Стоп-условия внутри: метка вне A(s) -> падение (не чиним и не отбрасываем молча); отсутствие
# примеров с отходом (attack_cell!=end_cell) -> падение; несовместимая версия -> падение.
import hashlib
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))     # server/
sys.path.insert(0, _HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from arent import dataset, joint, net, paths, spec3      # noqa: E402
from stage6_common import SEED, TRAIN_ARENAS              # noqa: E402
from stage6_qc import combine_teachers, qc_tables          # noqa: E402

OUT_WS = os.path.join(os.path.dirname(_HERE), "stage6_out")
DATASET_NAME = "stage6_v3"


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_contract(records) -> None:
    """Жёсткая проверка контракта новой v3-выборки (стоп на любом нарушении)."""
    want = spec3.dims3()
    retreat_seen = 0
    for r in records:
        s = r["sample"]
        if int(s.get("schema", 0)) != spec3.SCHEMA:
            raise RuntimeError(f"пример не схемы 3: schema={s.get('schema')}")
        if s.get("feat_version") != spec3.FEATURES_VERSION:
            raise RuntimeError(f"пример со СТАРЫМИ признаками: feat_version="
                               f"{s.get('feat_version')}, ждём {spec3.FEATURES_VERSION}")
        if len(s["cells"][0]) != want["cell_feat"]:
            raise RuntimeError(f"ширина клеток {len(s['cells'][0])} != {want['cell_feat']}")
        legal = s.get("legal")
        if legal is None or len(legal) != want["cells"]:
            raise RuntimeError("нет точной legal-маски нужной глубины")
        # метка обязана лежать в A(s): ensure_jointly_legal не чинит, а бросает на отказе.
        # Возвращает КАНОНИЧЕСКИЕ (pos,target,weapon) через net.y_index: -1 («без атаки/огня»)
        # схлопывается в последний NONE-слот группы — ровно тот же порядок вариантов, что у
        # legal-маски и плановых слотов. Проверяем, что каноническая тройка в границах dims
        # (общий порядок y/slots/legal), а не сырой y (там легитимный sentinel -1).
        ip, it, iw = joint.ensure_jointly_legal(s, spec3.SCHEMA)
        if not (0 <= ip < want["cells"] and 0 <= it < want["targets"]
                and 0 <= iw < want["weapons"]):
            raise RuntimeError(f"каноническая метка вне порядок-границ: (pos={ip}," 
                               f"target={it},weapon={iw}), y={s['y']}")
        # план (позиция) обязан быть РЕАЛЬНЫМ (активным) слотом, а не padded NONE-клеткой:
        # иначе пример не исполним. mask.cells[i]==1 ровно для реальных планов (encode_v3).
        # target/weapon могут быть NONE-слоем (действие без атаки) — это легально.
        if not s["mask"]["cells"][ip]:
            raise RuntimeError(f"план-метка ссылается на padded NONE-клетку: ip={ip}, "
                               f"маска={s['mask']['cells']}")
        if r["tags"]["retreat"]:
            retreat_seen += 1
    if retreat_seen == 0:
        raise RuntimeError("в выборке нет ни одного плана с отходом (attack_cell!=end_cell)")
    print(f"  контракт OK: {len(records)} примеров, все feat_version="
          f"{spec3.FEATURES_VERSION}/cell_feat={want['cell_feat']}, в A(s); "
          f"примеров с отходом: {retreat_seen}")


def main() -> int:
    prev = paths.workspace()
    paths.set_workspace(OUT_WS)                     # изолированный каталог
    try:
        records, accounting = combine_teachers()
        _check_contract(records)
        samples = [r["sample"] for r in records]
        # групповой split (для манифеста; полный QC — часть 3)
        from arent import splitting
        train, val, split_report = splitting.split_grouped(samples, frac=0.85, seed=SEED,
                                                           strict=True)
        tables = qc_tables(records, split_report, accounting)

        # провенанс-сайдкар пишется dataset.save как <name>.jsonl.meta.json
        stats = {"schema": spec3.SCHEMA, "feat_version": spec3.FEATURES_VERSION,
                 "seed": SEED, "per_src": 6, "rounds_max": 3, "teachers": ["greedy", "battlecast"],
                 "cell_feat": spec3.dims3()["cell_feat"], "note": "stage6 small v3 pipeline test"}
        path = dataset.save(samples, DATASET_NAME, stats)

        # back-load: конвейер обязан принять свежую выборку и отвергнуть старый формат
        back = dataset.load(DATASET_NAME)
        assert len(back) == len(samples), "load-back потерял примеры"

        manifest = {
            "manifest_schema": 1, "stage": 6, "purpose": "v3 pipeline validation (small dataset)",
            "versions": {"schema_action_semantics": spec3.SCHEMA,
                         "features_version": spec3.FEATURES_VERSION,
                         "cell_feat_new": spec3.dims3()["cell_feat"],
                         "cell_feat_old_rejected": spec3.CELL_FEAT_V1,
                         "dims_for_v3": net.dims_for(3)},
            "provenance": {"seed": SEED, "per_src": 6, "rounds_max": 3,
                           "teachers": ["greedy", "battlecast"],
                           "scenario_sources": 12, "arena_sources": TRAIN_ARENAS,
                           "workspace": os.path.abspath(OUT_WS)},
            "counts": {"examples": len(samples), "train": len(train), "val": len(val),
                       "unique_scenarios": tables["uniqueness"]["unique_scenarios"],
                       "unique_states": tables["uniqueness"]["unique_states"]},
            "checksums": {"dataset_sha256": _sha256(path), "bytes": os.path.getsize(path)},
            "label_distributions": {
                "attacks_vs_noattack": tables["attacks_vs_noattack"],
                "plan_cell_geometry": tables["plan_cell_geometry"],
                "weapon_types": tables["weapon_types"],
                "target_selection": tables["target_selection"],
                "team_and_role": tables["team_and_role"],
                "admissibility": tables["admissibility"]},
            "split": {k: split_report[k] for k in ("groups_total", "train_groups", "val_groups",
                       "train_samples", "val_samples", "group_overlap", "exact_state_overlap",
                       "warnings")},
            "constraints_met": {
                "all_new_feature_version": True, "exact_legal_mask": True,
                "attack_labels_in_As": tables["admissibility"]["out_As"] == 0,
                "no_illegal_silently_fixed": True,
                "retreat_examples_present": tables["plan_cell_geometry"]["attack_retreat"] > 0,
                "no_old_format_mixed": True,
                "group_split_no_intersection": not split_report["group_overlap"]
                and not split_report["exact_state_overlap"]},
        }
        mpath = os.path.join(OUT_WS, "stage6_dataset_manifest.json")
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)

        print(f"  датасет: {path} ({len(samples)} примеров, {manifest['checksums']['bytes']} б)")
        print(f"  sha256:  {manifest['checksums']['dataset_sha256']}")
        print(f"  манифест: {mpath}")
        print(f"  split: train={len(train)} val={len(val)}, пересечения групп="
              f"{split_report['group_overlap'] or 'НЕТ'}, состояний="
              f"{split_report['exact_state_overlap'] or 'НЕТ'}")
        all_ok = all(manifest["constraints_met"].values())
        print(f"  ВСЕ ОГРАНИЧЕНИЯ ВЫПОЛНЕНЫ: {all_ok}")
        return 0 if all_ok else 1
    finally:
        paths.set_workspace(prev)


if __name__ == "__main__":
    raise SystemExit(main())
