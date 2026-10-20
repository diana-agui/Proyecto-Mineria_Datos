import argparse
import csv
import re

UNIT = {
    "ppm": 1,
    "ppb": 1e-3,
    "ppt": 1e-6,
    "ms": 1e-3,
    "s": 1,
    "sec": 1,
    "second": 1,
    "seconds": 1,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "cycle": 1,
    "cycles": 1,
    "%": 1,
}

CRITERIOS = [
    "sensitivity",
    "lod",
    "response_time",
    "recovery_time",
    "operational_stability",
]
MENOR_MEJOR = {"lod", "response_time", "recovery_time"}
MEJOR = {c: (min if c in MENOR_MEJOR else max) for c in CRITERIOS}

#helper func for interpreting the csv
def valores(celda):
    """dimensional analysis step"""
    if not celda:
        return []
    out = []
    for parte in celda.split(";"):
        m = re.match(r"\s*([\d.]+)\s*(\S+)", parte)
        if m and m.group(2) in UNIT:
            out.append(float(m.group(1)) * UNIT[m.group(2)]) #group 1 = value, group 2 = measurement
    return out


def dominates(a, b, min_shared=2):
    """Checks if material A Pareto-dominates material B using raw metrics.
    Pareto dominance logic:
    A vector u =
(u1,...,uk) is said to dominate another vector v =(v1,...,vk) (denoted by
u ≼ v) if and only if u is partially less than v, i.e., ∀i ∈ {1,...,k},ui ≤
vi ∧∃i ∈ {1,...,k} : ui <vi.

Executed over the subspace shared
"""
    shared = [c for c in CRITERIOS if c in a and c in b]

    if len(shared) < min_shared: #shared subspace
        return False

    better_in_at_least_one = False #flag for checking dominance

    for c in shared:
        val_a = a[c]
        val_b = b[c]

        if c in MENOR_MEJOR:
            if val_a > val_b:  # A is worse than B
                return False
            if val_a < val_b:  # A is strictly better than B
                better_in_at_least_one = True
        else:
            if val_a < val_b:  # A is worse than B
                return False
            if val_a > val_b:  # A is strictly better than B
                better_in_at_least_one = True

    return better_in_at_least_one #only returns true when better in atleastt one and samebetterin rest


def main():
    ap = argparse.ArgumentParser(description="Pareto Frontier Analysis")
    ap.add_argument("entrada")
    ap.add_argument("--salida", default="pareto_frontier")
    ap.add_argument("--min-criterios", type=int, default=2)
    a = ap.parse_args()

    # 1) Group by (documento, material)
    materiales_unicos = {}
    with open(a.entrada, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            clave = (r["documento"], r["material"])
            n_menc = int(r["n_menciones"]) if r["n_menciones"] else 0

            # If duplicate entries exist for the same material in the same paper, keep highest mentions
            if clave not in materiales_unicos:
                materiales_unicos[clave] = r
            else:
                prev_menc = (
                    int(materiales_unicos[clave]["n_menciones"])
                    if materiales_unicos[clave]["n_menciones"]
                    else 0
                )
                if n_menc > prev_menc:
                    materiales_unicos[clave] = r

    # 2) Extract best raw metric value per criterion per material (some docs report mult of the same metric for a mat
    filas = []
    for (d, mat), r in materiales_unicos.items():
        mejor = {c: MEJOR[c](v) for c in CRITERIOS if (v := valores(r.get(c, "")))}
        if len(mejor) >= a.min_criterios:
            filas.append({
                "documento": d,
                "material": mat,
                "n_criterios": len(mejor),
                **mejor,
            })

    if not filas:
        raise SystemExit("Ningun material cumple el minimo de criterios.")

    # 3)  Pareto Dominance across the full  pool
    #Definition 8 (Pareto Optimal Set [1626, 277, 265]) : For a given
    #MOP, F(x), the Pareto Optimal Set, P∗, is defined as:
    #P∗ := {x ∈ Ω |¬∃ x′ ∈ Ω F(x′
    #) ≼ F(x)}.
    for i, item_a in enumerate(filas):
        dominators = []
        for j, item_b in enumerate(filas):
            if i != j and dominates(item_b, item_a, min_shared=a.min_criterios):
                # Identify dominator by material name and paper source
                dominators.append(f"{item_b['material']} ({item_b['documento']})")

        item_a["is_pareto"] = len(dominators) == 0
        item_a["dominated_by"] = ";".join(dominators) if dominators else "None"

    # Sort: Pareto frontier candidates first, then by number of reported criteria
    filas.sort(key=lambda x: (x["is_pareto"], x["n_criterios"]), reverse=True)

    # 4) Save Output CSV and Print Summary
    campos = [
        "is_pareto",
        "material",
        "documento",
        "n_criterios",
        "dominated_by",
        *CRITERIOS,
    ]

    with open(f"{a.salida}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)

    pareto_count = sum(1 for x in filas if x["is_pareto"])
    print(f"\nTotal Evaluated Materials: {len(filas)}")
    print(f"Pareto Optimal Frontier Count: {pareto_count}\n")

    for i, x in enumerate(filas, 1):
        status = "[PARETO OPTIMAL]" if x["is_pareto"] else "[DOMINATED]     "
        dom_info = (
            "" if x["is_pareto"] else f" | Dominated by: {x['dominated_by']}"
        )
        print(
            f"{i:<2}. {status} {x['material']:<12} ({x['documento'][:20]}...) (Criteria: {x['n_criterios']}){dom_info}"
        )


if __name__ == "__main__":
    main()
