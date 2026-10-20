"""
    python extractor.py carpeta --salida resultados
"""
import argparse
import csv
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

MIN_CRITERIOS = 3  # minimo de criterios para entrar al ranking

CRITERIOS = {
    "sensitivity": ["sensitivity", "sensitivities", "sensing response", "sensor response",
                    "response magnitude", "sensibilidad"],
    "lod": ["limit of detection", "limits of detection", "detection limit", "detection limits",
            "lod", "lowest detectable concentration", "limite de deteccion"],
    "response_time": ["response time", "response times", "t90", "rise time",
                      "tiempo de respuesta"],
    "recovery_time": ["recovery time", "recovery times", "recovery", "decay time",
                      "tiempo de recuperacion"],
    "operational_stability": ["operational stability", "long term stability", "stability",
                              "reproducibility", "repeatability", "cycling", "cycles", "cycle",
                              "estabilidad", "ciclos"],
}

# unidad -> (unidad estandar, factor)
UNIDADES = {
    "ppm": ("ppm", 1.0), "ppb": ("ppm", 1e-3), "ppt": ("ppm", 1e-6),
    "ms": ("s", 1e-3), "s": ("s", 1.0), "sec": ("s", 1.0), "second": ("s", 1.0),
    "seconds": ("s", 1.0), "min": ("s", 60.0), "mins": ("s", 60.0),
    "minute": ("s", 60.0), "minutes": ("s", 60.0),
    "cycle": ("cycles", 1.0), "cycles": ("cycles", 1.0),
    "%": ("%", 1.0),
}
_TIEMPO = {"ms", "s", "sec", "second", "seconds", "min", "mins", "minute", "minutes"}
UNIDADES_POR_CRITERIO = {
    "sensitivity": {"%"},
    "lod": {"ppm", "ppb", "ppt"},
    "response_time": _TIEMPO,
    "recovery_time": _TIEMPO,
    "operational_stability": {"cycle", "cycles"},
}
# "50% RH", "5% CO2" no son respuestas en %
SUFIJOS_NO_RESPUESTA = {"rh", "relative", "humidity", "co2", "o2", "n2", "ppm", "vol", "v"}

GASES_EXCLUIDOS = {"CO2", "CO", "O2", "N2", "H2", "H2O", "NO2", "NH3", "CH4"}
PALABRAS_IGNORADAS = {"IS", "OF", "ON", "IN", "AS", "AT", "BE", "BY", "SO", "NO", "UV", "CV",
                      "ISO", "SI", "HI", "OS", "US"}
ELEMENTOS_SOLOS = {"Cu", "Ag", "Au", "Pt", "Pd", "Zn", "Fe", "Ni", "Sn", "Ti", "Mn", "Ru",
                   "Ir", "Rh", "Cd"}
NOMBRES_MATERIALES = ["graphene oxide", "reduced graphene oxide", "graphene", "carbon nanotube",
                      "carbon nanotubes", "mxene", "zeolite", "perovskite",
                      "metal organic framework", "polyaniline", "polypyrrole", "activated carbon"]
ELEMENTOS = set(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn "
    "Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La "
    "Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po "
    "At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr".split()
)

PATRON_FORMULA = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Z][a-z]?\d*(?:\.\d+)?|\((?:[A-Z][a-z]?\d*)+\)\d*)+(?![A-Za-z0-9])")
PATRON_FIN_ORACION = re.compile(
    r"(?<!\bFig)(?<!\bal)(?<!e\.g)(?<!i\.e)(?<!\bvs)(?<!\bEq)(?<!\bRef)(?<!\bNo)"
    r"[.!?]\s+(?=[A-Z0-9(\[])")
PATRON_REFERENCIAS = re.compile(
    r"^[ \t]*(?:(?:\d+|[ivx]+)[\.\):]?[ \t]+)?"
    r"(?:references?|bibliography|literature[ \t]+cited|referencias|bibliografia)"
    r"[ \t]*:?(?:[ \t]*$|[ \t]+\[1\])", re.IGNORECASE | re.MULTILINE)
PATRON_TOKEN = re.compile(r"\d+(?:\.\d+)?|%|[a-z]+\d*")
PATRON_NUMERO = re.compile(r"\d+(?:\.\d+)?")
MARCA_FIN, PREFIJO_MAT = "zzfin", "zzmat"


def es_formula_material(f):
    if f.strip("()") in GASES_EXCLUIDOS or f in GASES_EXCLUIDOS or f.upper() in PALABRAS_IGNORADAS:
        return False
    elementos = re.findall(r"[A-Z][a-z]?", f)
    if not elementos or any(e not in ELEMENTOS for e in elementos):
        return False
    return len(elementos) >= 2 or f in ELEMENTOS_SOLOS


def preparar_texto(raw):
    t = "".join(c for c in unicodedata.normalize("NFKD", raw) if not unicodedata.combining(c))
    t = re.sub(r"\r\n?", "\n", t)
    # quitar referencias (solo si el encabezado aparece despues del 30% del texto)
    for m in PATRON_REFERENCIAS.finditer(t):
        if m.start() > 0.3 * len(t):
            t = t[:m.start()]
            break
    t = re.sub(r"[\u00b5\u03bc](?=[A-Za-z])", "u", t)
    t = re.sub(r"([a-z])-[ \t]*\n[ \t]*([a-z])", r"\1\2", t)
    t = re.sub(r"\n\s*\n", f" {MARCA_FIN} ", t)
    t = PATRON_FIN_ORACION.sub(f" {MARCA_FIN} ", t)

    mapa, ids = {}, {}

    def sustituir(m):
        f = m.group(0)
        if not es_formula_material(f):
            return f
        if f not in ids:
            ids[f] = f"{PREFIJO_MAT}{len(ids)}"
            mapa[ids[f]] = f
        return f" {ids[f]} "

    t = PATRON_FORMULA.sub(sustituir, t).lower()
    t = re.sub(r"[-_\u2010-\u2015]", " ", t)
    t = re.sub(r"(?<=\d),(?=\d)", ".", t)
    return re.sub(r"\s+", " ", t).strip(), mapa


def tokenizar(texto):
    return PATRON_TOKEN.findall(texto)


def extraer_valores(tokens):
    """Numero seguido de unidad conocida."""
    valores = []
    for k, tok in enumerate(tokens):
        if tok not in UNIDADES or k == 0 or not PATRON_NUMERO.fullmatch(tokens[k - 1]):
            continue
        if tok == "%" and k + 1 < len(tokens) and tokens[k + 1] in SUFIJOS_NO_RESPUESTA:
            continue
        estandar, factor = UNIDADES[tok]
        valores.append({"pos": k - 1, "unidad": tok,
                        "texto": f"{tokens[k - 1]} {tok}",
                        "std": f"{float(tokens[k - 1]) * factor:g} {estandar}"})
    return valores


def indexar(frases):
    indice = defaultdict(list)
    for clave, lista in frases:
        for frase in lista:
            toks = tuple(tokenizar(unicodedata.normalize("NFKD", frase.lower())))
            if toks:
                indice[toks[0]].append((clave, toks))
    for lst in indice.values():
        lst.sort(key=lambda x: len(x[1]), reverse=True)
    return indice


def detectar_materiales(tokens, mapa, indice_nombres):
    menciones, i = [], 0
    while i < len(tokens):
        if tokens[i] in mapa:
            menciones.append((i, mapa[tokens[i]]))
        else:
            for nombre, toks in indice_nombres.get(tokens[i], []):
                if tuple(tokens[i:i + len(toks)]) == toks:
                    menciones.append((i, nombre))
                    break
        i += 1
    return menciones


def asociar_material(menciones, sent, pos, ventana):
    """Mismo oracion: el mas cercano. Si no, el mas reciente de oraciones previas."""
    mejor = None
    for p, nombre in menciones:
        d = abs(p - pos)
        if d > ventana or (p > pos and sent[p] != sent[pos]):
            continue
        clave = (0, d) if sent[p] == sent[pos] else (1, d)
        if mejor is None or clave < mejor[0]:
            mejor = (clave, nombre)
    return mejor[1] if mejor else None


def procesar(ruta, indice_kw, indice_nombres, ventana, ventana_mat):
    try:
        raw = ruta.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = ruta.read_text(encoding="latin-1")
    texto, mapa = preparar_texto(raw)
    tokens = tokenizar(texto)

    sent, sid = [], 0
    for t in tokens:
        if t == MARCA_FIN:
            sid += 1
        sent.append(sid)

    valores = extraer_valores(tokens)
    menciones = detectar_materiales(tokens, mapa, indice_nombres)
    conteo_menciones = defaultdict(int)
    for _, nombre in menciones:
        conteo_menciones[nombre] += 1

    # (criterio, posicion del valor) -> (distancia, texto)
    mejores = {}
    for i, tok in enumerate(tokens):
        for criterio, toks in indice_kw.get(tok, []):
            if tuple(tokens[i:i + len(toks)]) != toks:
                continue
            j = i + len(toks)
            if criterio == "sensitivity" and j < len(tokens) and tokens[j] in ("time", "times"):
                continue  # "sensor response time" es un tiempo
            cand = []
            for v in valores:
                if v["unidad"] not in UNIDADES_POR_CRITERIO[criterio]:
                    continue
                d = v["pos"] - j if v["pos"] >= j else i - (v["pos"] + 2)
                if 0 <= d <= ventana:
                    cand.append((d, 0 if v["pos"] >= j else 1, v))
            if cand:
                d, _, v = min(cand, key=lambda x: (x[0], x[1]))
                clave = (criterio, v["pos"])
                if clave not in mejores or d < mejores[clave][0]:
                    mejores[clave] = (d, v["texto"], i)
            break

    por_material = defaultdict(lambda: {c: [] for c in CRITERIOS})
    for (criterio, _), (_, texto_valor, pos_kw) in mejores.items():
        mat = asociar_material(menciones, sent, pos_kw, ventana_mat)
        if mat and texto_valor not in por_material[mat][criterio]:
            por_material[mat][criterio].append(texto_valor)
    return por_material, conteo_menciones


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("carpeta", type=Path, help="Carpeta con los archivos .txt")
    ap.add_argument("--salida", default="resultados", help="Prefijo del archivo de salida")
    ap.add_argument("--ventana", type=int, default=10, help="Tokens maximos keyword-valor")
    ap.add_argument("--ventana-material", type=int, default=30, help="Tokens maximos valor-material")
    args = ap.parse_args()

    archivos = sorted(args.carpeta.rglob("*.txt"))
    if not archivos:
        raise SystemExit(f"No se encontraron .txt en {args.carpeta}")

    indice_kw = indexar(CRITERIOS.items())
    indice_nombres = indexar([(n, [n]) for n in NOMBRES_MATERIALES])

    with open(f"{args.salida}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["documento", "material", "n_menciones", *CRITERIOS, "n_criterios", "rankable"])
        for ruta in archivos:
            por_material, menciones = procesar(ruta, indice_kw, indice_nombres,
                                               args.ventana, args.ventana_material)
            print(f"{ruta.name}: {len(por_material)} material(es) con mediciones")
            for mat, datos in por_material.items():
                n = sum(1 for v in datos.values() if v)
                w.writerow([ruta.name, mat, menciones.get(mat, 0),
                            *["; ".join(datos[c]) for c in CRITERIOS], n, n >= MIN_CRITERIOS])
    print(f"\nGuardado: {args.salida}.csv")


if __name__ == "__main__":
    main()
