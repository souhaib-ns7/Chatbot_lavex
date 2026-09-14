"""
Couche NLU classique (sans LLM) pour le chatbot Lavex.

"""

import re
import sqlite3
import unicodedata
import os
import calendar
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "lavex_releves.db")

# 1. Dictionnaire mots-cles -> colonne

METRIC_KEYWORDS = {
    "cad": "cumul_cad_tsm",
    "sl3": "cumul_sl3_tsm",
    "rp": "rp_pct",
    "rendement": "rp_pct",
    "coarse reject": "coarse_reject_tsm",
    "reject": "coarse_reject_tsm",
    "taux coarse reject": "taux_coarse_reject_pct",
    "stockage": "cumul_stockage_st110_thc",
    "st110": "cumul_stockage_st110_thc",
    "destockage": "cumul_destockage_rl2_t",
    "rl2": "cumul_destockage_rl2_t",
    "turbidite": "turbidity_mgl",
    "turbidity": "turbidity_mgl",
    "soutirage": "debit_soutirage_decanteur_m3h",
    "decanteur": "debit_soutirage_decanteur_m3h",
    "process water": "pompe_process_water_m3h",
    "pompe": "pompe_process_water_m3h",
}

METRIC_LABELS = {
    "cumul_cad_tsm": "cumul CAD",
    "cumul_sl3_tsm": "cumul SL3",
    "rp_pct": "RP",
    "coarse_reject_tsm": "coarse reject",
    "taux_coarse_reject_pct": "taux de coarse reject",
    "cumul_stockage_st110_thc": "cumul stockage ST110",
    "cumul_destockage_rl2_t": "cumul destockage RL2",
    "turbidity_mgl": "turbidite",
    "debit_soutirage_decanteur_m3h": "debit soutirage decanteur",
    "pompe_process_water_m3h": "debit pompe process water",
}

CUMUL_METRICS = {"cumul_cad_tsm", "cumul_sl3_tsm", "cumul_stockage_st110_thc",
                  "cumul_destockage_rl2_t"}

RATE_METRICS = {"rp_pct", "taux_coarse_reject_pct", "turbidity_mgl",
                 "debit_soutirage_decanteur_m3h", "pompe_process_water_m3h"}

COMPARISON_KEYWORDS = [
    "compare", "comparaison", "comparer", "versus", " vs ",
    "par rapport a", "difference entre", "differences entre",
    "ecart entre", "evolution entre", "plus que", "moins que",
]


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def resolve_intent(question: str) -> str:
    q = _strip_accents(question.lower())
    for kw in COMPARISON_KEYWORDS:
        if _strip_accents(kw) in q:
            return "comparison"
    return "statistic"


def resolve_metric(question: str):
    q = _strip_accents(question.lower())
    for kw in sorted(METRIC_KEYWORDS, key=len, reverse=True):
        if _strip_accents(kw) in q:
            return METRIC_KEYWORDS[kw]
    return None


def resolve_metrics(question: str):
    q = _strip_accents(question.lower())
    found = []
    for kw in sorted(METRIC_KEYWORDS, key=len, reverse=True):
        kw_norm = _strip_accents(kw)
        idx = q.find(kw_norm)
        if idx != -1:
            found.append((idx, METRIC_KEYWORDS[kw]))
    found.sort(key=lambda x: x[0])
    cols = []
    for _, col in found:
        if col not in cols:
            cols.append(col)
    return cols

DATE_RANGE_RE = re.compile(
    r"(?:de|du|entre)\s+(?:le\s+)?(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})\s+"
    r"(?:a|au|et)\s+(?:le\s+)?(\d{1,2}[/\-]\d{1,2}[/\-]\d{4})"
)


def _parse_ddmmyyyy(s: str) -> date:
    dd, mm, yyyy = re.split(r"[/\-]", s)
    return date(int(yyyy), int(mm), int(dd))


def _date_range(start_str: str, end_str: str):
    """Renvoie la liste des dates ISO entre deux dates JJ/MM/AAAA
    (inclusives), quel que soit l'ordre dans lequel elles sont donnees."""
    d1 = _parse_ddmmyyyy(start_str)
    d2 = _parse_ddmmyyyy(end_str)
    if d2 < d1:
        d1, d2 = d2, d1
    n_days = (d2 - d1).days + 1
    return [(d1 + timedelta(days=i)).isoformat() for i in range(n_days)]


def _last_month_range(reference_date: date):
    """Renvoie la liste des dates ISO du mois calendaire precedent."""
    first_this_month = reference_date.replace(day=1)
    last_month_end = first_this_month - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    days_in_month = calendar.monthrange(last_month_start.year, last_month_start.month)[1]
    return [(last_month_start + timedelta(days=i)).isoformat() for i in range(days_in_month)]


# --- 2. Resolution des expressions de temps -----------------------------

def resolve_period(question: str, reference_date: date):
    """Renvoie (liste_de_dates_iso, libelle_periode) ou None si non reconnu."""
    q = _strip_accents(question.lower())

    if "aujourd" in q:
        d = reference_date
        return [d.isoformat()], "aujourd'hui"

    if "hier" in q and "avant-hier" not in q and "avant hier" not in q:
        d = reference_date - timedelta(days=1)
        return [d.isoformat()], "hier"

    if "avant-hier" in q or "avant hier" in q:
        d = reference_date - timedelta(days=2)
        return [d.isoformat()], "avant-hier"

    if "derniere semaine" in q or "semaine derniere" in q or "semaine passee" in q:
        # semaine calendaire ISO precedente (lundi -> dimanche)
        this_monday = reference_date - timedelta(days=reference_date.weekday())
        last_monday = this_monday - timedelta(days=7)
        dates = [(last_monday + timedelta(days=i)).isoformat() for i in range(7)]
        return dates, "la semaine derniere"

    if "cette semaine" in q or "semaine en cours" in q:
        this_monday = reference_date - timedelta(days=reference_date.weekday())
        dates = [(this_monday + timedelta(days=i)).isoformat()
                  for i in range(reference_date.weekday() + 1)]
        return dates, "cette semaine"

    if "mois dernier" in q or "dernier mois" in q or "mois passe" in q:
        return _last_month_range(reference_date), "le mois dernier"

    m_range = DATE_RANGE_RE.search(q)
    if m_range:
        start_str, end_str = m_range.groups()
        return _date_range(start_str, end_str), f"du {start_str} au {end_str}"

    m = re.search(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", q)
    if m:
        dd, mm, yyyy = m.groups()
        d = date(int(yyyy), int(mm), int(dd))
        return [d.isoformat()], d.strftime("%d/%m/%Y")

    return None


def resolve_periods(question: str, reference_date: date):
    """Version pluriel de resolve_period : renvoie la liste de TOUTES les
    periodes distinctes reperees dans la question (chacune sous forme
    (dates_iso, label)), triees par ordre d'apparition dans le texte.
    Utilise pour les comparaisons entre deux periodes."""
    q = _strip_accents(question.lower())
    candidates = []  # (position, dates_iso, label)

    idx = q.find("aujourd")
    if idx != -1:
        candidates.append((idx, [reference_date.isoformat()], "aujourd'hui"))

    for m in re.finditer(r"hier", q):
        idx = m.start()
        prefix = q[max(0, idx - 7):idx]
        if "avant" in prefix:
            continue
        d = reference_date - timedelta(days=1)
        candidates.append((idx, [d.isoformat()], "hier"))
        break

    idx = -1
    for pat in ("avant-hier", "avant hier"):
        i = q.find(pat)
        if i != -1:
            idx = i
            break
    if idx != -1:
        d = reference_date - timedelta(days=2)
        candidates.append((idx, [d.isoformat()], "avant-hier"))

    idx = -1
    for pat in ("derniere semaine", "semaine derniere", "semaine passee"):
        i = q.find(pat)
        if i != -1:
            idx = i
            break
    if idx != -1:
        this_monday = reference_date - timedelta(days=reference_date.weekday())
        last_monday = this_monday - timedelta(days=7)
        dates = [(last_monday + timedelta(days=i)).isoformat() for i in range(7)]
        candidates.append((idx, dates, "la semaine derniere"))

    idx = -1
    for pat in ("cette semaine", "semaine en cours"):
        i = q.find(pat)
        if i != -1:
            idx = i
            break
    if idx != -1:
        this_monday = reference_date - timedelta(days=reference_date.weekday())
        dates = [(this_monday + timedelta(days=i)).isoformat()
                  for i in range(reference_date.weekday() + 1)]
        candidates.append((idx, dates, "cette semaine"))

    idx = -1
    for pat in ("mois dernier", "dernier mois", "mois passe"):
        i = q.find(pat)
        if i != -1:
            idx = i
            break
    if idx != -1:
        candidates.append((idx, _last_month_range(reference_date), "le mois dernier"))
    range_spans = []
    for m in DATE_RANGE_RE.finditer(q):
        start_str, end_str = m.groups()
        dates = _date_range(start_str, end_str)
        label = f"du {start_str} au {end_str}"
        candidates.append((m.start(), dates, label))
        range_spans.append((m.start(), m.end()))

    for m in re.finditer(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", q):
        if any(s <= m.start() < e for s, e in range_spans):
            continue  # deja couverte par une plage detectee ci-dessus
        dd, mm, yyyy = m.groups()
        d = date(int(yyyy), int(mm), int(dd))
        candidates.append((m.start(), [d.isoformat()], d.strftime("%d/%m/%Y")))

    candidates.sort(key=lambda x: x[0])
    return [(dates, label) for _, dates, label in candidates]


# 3. Calcul sur la base

def daily_value(conn, metric_col: str, date_iso: str):
    cur = conn.cursor()
    if metric_col in CUMUL_METRICS:
        cur.execute(f"""
            SELECT shift, MAX({metric_col}) FROM releves_production
            WHERE date_iso = ? AND {metric_col} IS NOT NULL
            GROUP BY shift
        """, (date_iso,))
        rows = cur.fetchall()
        if not rows:
            return None
        return sum(v for _, v in rows)
    else:
        cur.execute(f"""
            SELECT {metric_col} FROM releves_production
            WHERE date_iso = ? AND {metric_col} IS NOT NULL
            ORDER BY date_reception DESC LIMIT 1
        """, (date_iso,))
        row = cur.fetchone()
        return row[0] if row else None


def compute(metric_col: str, dates_iso: list, db_path: str = None):
    if db_path is None:
        db_path = DB_PATH

    if not os.path.exists(db_path):
        return {}, None

    conn = sqlite3.connect(db_path)
    daily = {}
    for d in dates_iso:
        daily[d] = daily_value(conn, metric_col, d)
    conn.close()
    known_values = [v for v in daily.values() if v is not None]
    if not known_values:
        total = None
    elif metric_col in RATE_METRICS:
        total = sum(known_values) / len(known_values)
    else:
        total = sum(known_values)
    return daily, total


def compute_comparison(comparisons: list, db_path: str = None):
    results = []
    for metric_col, dates_iso, label in comparisons:
        daily, total = compute(metric_col, dates_iso, db_path)
        results.append({
            "metric_col": metric_col,
            "label": label,
            "daily": daily,
            "total": total,
        })

    delta = None
    pct_change = None
    if results[0]["total"] is not None and results[1]["total"] is not None:
        delta = results[1]["total"] - results[0]["total"]
        if results[0]["total"] != 0:
            pct_change = (delta / results[0]["total"]) * 100

    return results, delta, pct_change


# 4. Pipeline complet + reponse en francais

def format_response(metric_col: str, period_label: str, daily: dict, total):
    label = METRIC_LABELS.get(metric_col, metric_col)
    if total is None:
        return f"Je n'ai pas de donnees pour le {label} sur {period_label}."

    is_average = metric_col in RATE_METRICS and len(daily) > 1
    qualif = "moyen " if is_average else ""
    lines = [f"Le {label} {qualif}de {period_label} est de {total:.2f}."]
    lines.append("Detail par jour :")
    for d, v in daily.items():
        v_str = f"{v:.2f}" if v is not None else "pas de donnee"
        lines.append(f"  - {d} : {v_str}")
    return "\n".join(lines)


def format_comparison_response(results: list, delta, pct_change):
    a, b = results[0], results[1]
    label_a = METRIC_LABELS.get(a["metric_col"], a["metric_col"])
    label_b = METRIC_LABELS.get(b["metric_col"], b["metric_col"])

    def fmt(v):
        return f"{v:.2f}" if v is not None else "pas de donnee"

    lines = []
    if a["metric_col"] == b["metric_col"]:
        lines.append(
            f"Comparaison du {label_a} : {a['label']} ({fmt(a['total'])}) "
            f"vs {b['label']} ({fmt(b['total'])})."
        )
    else:
        lines.append(
            f"Comparaison : {label_a} sur {a['label']} ({fmt(a['total'])}) "
            f"vs {label_b} sur {b['label']} ({fmt(b['total'])})."
        )

    if delta is not None:
        sens = "hausse" if delta > 0 else ("baisse" if delta < 0 else "stable")
        pct_str = f" ({pct_change:+.1f}%)" if pct_change is not None else ""
        lines.append(f"Ecart : {delta:+.2f}{pct_str} — {sens}.")
    else:
        lines.append("Impossible de calculer l'ecart (donnees manquantes).")

    for r in results:
        lab = METRIC_LABELS.get(r["metric_col"], r["metric_col"])
        lines.append(f"\nDetail {lab} — {r['label']} :")
        for d, v in r["daily"].items():
            lines.append(f"  - {d} : {fmt(v)}")

    return "\n".join(lines)


def parse_question(question: str, reference_date: date):
    intent = resolve_intent(question)

    if intent == "comparison":
        metrics = resolve_metrics(question)
        periods = resolve_periods(question, reference_date)

        comparisons = None
        if len(metrics) >= 2 and len(periods) >= 1:
            dates_iso, label = periods[0]
            comparisons = [(metrics[0], dates_iso, label),
                            (metrics[1], dates_iso, label)]
        elif len(metrics) >= 1 and len(periods) >= 2:
            comparisons = [(metrics[0], periods[0][0], periods[0][1]),
                            (metrics[0], periods[1][0], periods[1][1])]

        if comparisons is None:
            return None

        results, delta, pct_change = compute_comparison(comparisons)
        return format_comparison_response(results, delta, pct_change)

    # chemin statistique existant (inchange)
    metric_col = resolve_metric(question)
    period = resolve_period(question, reference_date)
    if metric_col is None or period is None:
        return None
    dates_iso, period_label = period
    daily, total = compute(metric_col, dates_iso)
    return format_response(metric_col, period_label, daily, total)


# FONCTION POUR LES TESTS
def get_last_date():
    """Recupere la derniere date disponible dans la base"""
    if not os.path.exists(DB_PATH):
        return None

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(date_iso) FROM releves_production")
    result = cursor.fetchone()
    conn.close()

    if result and result[0]:
        return date.fromisoformat(result[0])
    return None


if __name__ == "__main__":
    # demo avec la derniere date disponible dans la base comme "aujourd'hui"
    if not os.path.exists(DB_PATH):
        print(f"[ERREUR] Base de donnees introuvable : {DB_PATH}")
        print("[INFO] Executez d'abord : python -m src.etl_lavex src/lavex-historique.xlsx")
        exit(1)

    conn = sqlite3.connect(DB_PATH)
    max_date = conn.execute("SELECT MAX(date_iso) FROM releves_production").fetchone()[0]
    conn.close()

    if max_date is None:
        print("[ERREUR] Aucune donnee dans la base")
        exit(1)

    today = date.fromisoformat(max_date)

    tests = [
        "c'est quoi le cumul CAD de la derniere semaine ?",
        "et le cumul SL3 d'hier ?",
        "quel est le RP aujourd'hui ?",
        "combien de tonnes bleues sur mars ?",  # question non reconnue -> fallback
    ]
    for q in tests:
        print("Q:", q)
        rep = parse_question(q, today)
        print(rep if rep else "[non reconnu -> fallback LLM]")
        print()