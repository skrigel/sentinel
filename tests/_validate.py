"""Smoke-validate the scenario suite contract and print the summary table.

Imports every scenario's SCENARIO dict (cheap; numpy/redis stay lazy), checks the
file contract from README.md, and verifies resolvable blamed-ops exist as
module-level functions. Run: python tests/_validate.py
"""

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).parent
FOLDERS = ["test1", "test2", "test3"]

REQUIRED_KEYS = {
    "name", "tier", "expected_symptom", "expected_subcause", "expected_blamed_op",
    "expected_outcome", "expected_min_rss_growth_mb", "expected_min_cpu_pct",
    "decline_reason_keywords", "description",
}
RESOLVABLE_SUBCAUSES = {
    "unbounded_collection", "cache_without_ttl", "large_object_retention",
    "event_loop_blocking", "sync_io_in_async_loop",
}
DECLINE_SUBCAUSES = {"native_memory_growth", "redis_queue_backlog", "benign_plateau"}


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    rows = []
    errors = []
    counts = {}
    declines = set()

    for folder in FOLDERS:
        files = sorted((ROOT / folder).glob("*.py"))
        if len(files) != 4:
            errors.append(f"{folder}: expected 4 files, found {len(files)}")
        resolvable_subs = set()
        decline_in_folder = 0
        for path in files:
            mod = load(path)
            s = getattr(mod, "SCENARIO", None)
            if s is None:
                errors.append(f"{path.name}: missing SCENARIO")
                continue
            missing = REQUIRED_KEYS - set(s)
            if missing:
                errors.append(f"{path.name}: missing keys {missing}")
            if not callable(getattr(mod, "run", None)):
                errors.append(f"{path.name}: missing run()")

            if s["tier"] == "resolvable":
                resolvable_subs.add(s["expected_subcause"])
                counts[s["expected_subcause"]] = counts.get(s["expected_subcause"], 0) + 1
                op = s["expected_blamed_op"]
                if not op:
                    errors.append(f"{path.name}: resolvable must name a blamed_op")
                elif not callable(getattr(mod, op, None)):
                    errors.append(f"{path.name}: blamed_op '{op}' is not a module-level function")
            else:
                decline_in_folder += 1
                declines.add(s["expected_subcause"])
                if s["expected_blamed_op"] is not None:
                    errors.append(f"{path.name}: decline must have expected_blamed_op=None")
                if not s["decline_reason_keywords"]:
                    errors.append(f"{path.name}: decline must list decline_reason_keywords")

            rows.append((folder, path.name, s["tier"], s["expected_symptom"],
                         s["expected_subcause"], s["expected_blamed_op"], s["expected_outcome"]))

        if len(resolvable_subs) < 2:
            errors.append(f"{folder}: needs >=2 distinct resolvable subcauses, got {resolvable_subs}")
        if decline_in_folder != 1:
            errors.append(f"{folder}: needs exactly 1 decline, got {decline_in_folder}")

    # Print table.
    w = (7, 38, 17, 13, 23, 28, 18)
    hdr = ("folder", "file", "tier", "symptom", "subcause", "blamed_op", "outcome")
    line = "  ".join(h.ljust(width) for h, width in zip(hdr, w))
    print(line)
    print("-" * len(line))
    for r in rows:
        print("  ".join(str(c).ljust(width) for c, width in zip(r, w)))

    print("\nResolvable subcause counts:")
    for sub in sorted(RESOLVABLE_SUBCAUSES):
        print(f"  {sub:<24} {counts.get(sub, 0)}")
    print(f"Decline subcauses present: {sorted(declines)}")
    missing_declines = DECLINE_SUBCAUSES - declines
    if missing_declines:
        errors.append(f"missing decline scenarios: {missing_declines}")

    print("\n" + ("VALIDATION: OK" if not errors else "VALIDATION FAILED:"))
    for e in errors:
        print("  - " + e)


if __name__ == "__main__":
    main()
