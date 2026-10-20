"""
    python wsm.py resultados.csv --salida ranking --min-criterios 2
"""
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


def valores(celda):
    """Extracts numeric values converted to base units from a text cell."""
    if not celda:
        return []
    out = []
    for parte in celda.split(";"):
        m = re.match(r"\s*([\d.]+)\s*(\S+)", parte)
        if m and m.group(2) in UNIT:
            out.append(float(m.group(1)) * UNIT[m.group(2)])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("entrada")
    ap.add_argument("--salida", default="ranking")
    ap.add_argument("--min-criterios", type=int, default=2)
    a = ap.parse_args()

    # 1) Group by (documento, material) pair so no distinct materials are discarded
    materiales_unicos = {}
    with open(a.entrada, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            clave = (r["documento"], r["material"])
            n_menc = int(r["n_menciones"]) if r.get("n_menciones") else 0

            # If duplicate rows exist for the same (documento, material) pair, keep the one with most mentions
            if clave not in materiales_unicos:
                materiales_unicos[clave] = r
            else:
                prev_menc = (
                    int(materiales_unicos[clave]["n_menciones"])
                    if materiales_unicos[clave].get("n_menciones")
                    else 0
                )
                if n_menc > prev_menc:
                    materiales_unicos[clave] = r

    # 2) Best raw metric value per criterion per material
    filas = []
    for (d, mat), r in materiales_unicos.items():
        mejor = {c: MEJOR[c](v) for c in CRITERIOS if (v := valores(r.get(c, "")))}
        if len(mejor) >= a.min_criterios:
            filas.append({"documento": d, "material": mat, **mejor})

    if not filas:
        raise SystemExit("Ningun material cumple el minimo de criterios.")

    # 3) Min-max normalization per criterion (inverted for smaller-is-better metrics)
    for c in CRITERIOS:
        xs = [x[c] for x in filas if c in x]
        lo, hi = (min(xs), max(xs)) if xs else (0, 0)
        for x in filas:
            if c in x:
                n = 0.5 if hi == lo else (x[c] - lo) / (hi - lo)
                x["n_" + c] = (1 - n) if c in MENOR_MEJOR else n

    # 4) WSM with re-normalized weights over available criteria
    for x in filas:
        disp = [c for c in CRITERIOS if "n_" + c in x]
        x["n_criterios"] = len(disp)
        x["wsm"] = round(sum(x["n_" + c] for c in disp) / len(disp), 4)

    filas.sort(key=lambda x: x["wsm"], reverse=True)

    campos = ["rank", "documento", "material", "n_criterios", "wsm", *CRITERIOS]
    with open(f"{a.salida}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for i, x in enumerate(filas, 1):
            x["rank"] = i
            w.writerow(x)
            print(f"{i:<2}. {x['material']:<12} WSM={x['wsm']:<6} ({x['documento']})")


if __name__ == "__main__":
    main()
