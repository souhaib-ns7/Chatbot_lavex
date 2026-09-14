"""
Jeu de tests pour la couche NLU
"""

import sys
import os
import sqlite3
from datetime import date

# 1. CONFIGURATION DES CHEMINS
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")

if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

# 2. IMPORTER nlu_lavex
try:
    import nlu_lavex as nlu
    print("[OK] Import reussi")
except ImportError as e:
    print(f"[ERREUR] Erreur d'import : {e}")
    print(f"[INFO] SRC_PATH : {SRC_PATH}")
    print(f"[INFO] Fichiers dans src : {os.listdir(SRC_PATH) if os.path.exists(SRC_PATH) else 'dossier inexistant'}")
    sys.exit(1)

# 3. VERIFIER LA BASE
print(f"[INFO] DB_PATH (nlu) : {nlu.DB_PATH}")
print(f"[INFO] Existe ? {os.path.exists(nlu.DB_PATH)}")

def ensure_database():
    """Verifie que la base existe et contient la table"""
    if not os.path.exists(nlu.DB_PATH):
        print(f"[ERREUR] Base introuvable : {nlu.DB_PATH}")
        print("[INFO] Executez : python -m src.etl_lavex src/lavex-historique.xlsx")
        return False

    conn = sqlite3.connect(nlu.DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='releves_production'")
    table_exists = cursor.fetchone() is not None
    conn.close()

    if not table_exists:
        print("[ERREUR] Table 'releves_production' introuvable")
        return False

    print(f"[OK] Base prete : {nlu.DB_PATH}")
    return True

# 4. TESTS
TEST_QUESTIONS = [
    ("c'est quoi le cumul CAD de la derniere semaine ?", True),
    ("cumul CAD aujourd'hui ?", True),
    ("CAD d'hier", True),
    ("cumul SL3 de cette semaine", True),
    ("et le SL3 avant-hier ?", True),
    ("quel est le RP de la derniere semaine ?", True),
    ("le rendement d'aujourd'hui", True),
    ("coarse reject de cette semaine", True),
    ("taux coarse reject d'hier", True),
    ("cumul stockage ST110 de la derniere semaine", True),
    ("destockage RL2 aujourd'hui", True),
    ("turbidite de la semaine derniere", True),
    ("debit soutirage decanteur hier", True),
    ("pompe process water aujourd'hui", True),
    ("cumul CAD le 24/07/2026", True),
    ("comment ca marche l'installation ?", False),
    ("compare le CAD et le SL3 sur les deux dernieres semaines", False),
    ("pourquoi le rendement a baisse mardi ?", False),
    ("cumul CAD le mois dernier", True),
    ("le rendement du mois passe", True),
    ("combien de tonnes bleues sur mars ?", False),

    # --- Comparaisons : deux metriques, une seule periode ---
    ("compare le cumul CAD et le cumul SL3 de cette semaine", True),
    ("compare la turbidite et le debit soutirage decanteur aujourd'hui", True),
    ("quelle est la difference entre le rendement et le taux coarse reject d'hier ?", True),
    ("ecart entre le cumul CAD et le cumul SL3 le 24/07/2026", True),

    # --- Comparaisons : une seule metrique, deux periodes ---
    ("quel est l'ecart entre le cumul CAD d'hier et d'avant-hier ?", True),
    ("compare le rendement d'aujourd'hui et de la semaine derniere", True),
    ("compare le cumul SL3 de cette semaine et de la semaine derniere", True),
    ("compare le rendement du mois dernier et de la semaine derniere", True),

    # --- Comparaisons incompletes -> doivent basculer vers le fallback LLM ---
    ("compare le CAD et le SL3", False),  # 2 metriques mais aucune periode
    ("compare le rendement", False),  # 1 metrique, aucune periode, rien a comparer
    ("compare la production d'hier", False),  # 1 periode mais aucune metrique reconnue
]

def test_run():
    """Test principal de la NLU"""
    print("\n" + "=" * 60)
    print("Lancement des tests NLU")
    print("=" * 60)

    if not ensure_database():
        print("[ERREUR] Test ignore")
        return False

    # Recuperer la derniere date
    conn = sqlite3.connect(nlu.DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(date_iso) FROM releves_production")
    result = cursor.fetchone()
    conn.close()

    if result is None or result[0] is None:
        print("[ERREUR] Aucune donnee")
        return False

    today = date.fromisoformat(result[0])
    print(f"[INFO] Date de reference : {today}")

    n_regles = 0
    n_fallback = 0
    n_mismatch = 0

    print(f"\n{'Question':55} {'Attendu':10} {'Obtenu':10} {'OK?'}")
    print("-" * 90)

    for question, expected_regles in TEST_QUESTIONS:
        rep = nlu.parse_question(question, today)
        got_regles = rep is not None
        ok = got_regles == expected_regles
        n_regles += got_regles
        n_fallback += (not got_regles)
        n_mismatch += (not ok)
        status = "OK" if ok else "KO"
        print(f"{question[:53]:55} {'regles' if expected_regles else 'fallback':10} "
              f"{'regles' if got_regles else 'fallback':10} {status}")

    total = len(TEST_QUESTIONS)
    print("-" * 90)
    print(f"[STATS] Total: {total}")
    print(f"[STATS] Regles: {n_regles} ({n_regles/total:.0%})")
    print(f"[STATS] Fallback: {n_fallback} ({n_fallback/total:.0%})")
    print(f"[STATS] Ecarts: {n_mismatch}")
    print("=" * 60)

    return n_mismatch == 0


# 5. TESTS DEDIES A LA COMPARAISON

COMPARISON_DETECTION_CASES = [
    ("compare le cumul CAD et le cumul SL3 de cette semaine", "comparison", 2, 1),
    ("quel est l'ecart entre le cumul CAD d'hier et d'avant-hier ?", "comparison", 1, 2),
    ("compare le rendement d'aujourd'hui et de la semaine derniere", "comparison", 1, 2),
    ("cumul CAD aujourd'hui ?", "statistic", 1, 1),
    ("le rendement de la derniere semaine", "statistic", 1, 1),
]


def test_intent_detection():
    print("\n" + "=" * 60)
    print("Tests de detection d'intention / metriques / periodes")
    print("=" * 60)

    today = date(2026, 8, 13)
    n_mismatch = 0

    for question, expected_intent, expected_n_metrics, expected_n_periods in COMPARISON_DETECTION_CASES:
        intent = nlu.resolve_intent(question)
        metrics = nlu.resolve_metrics(question)
        periods = nlu.resolve_periods(question, today)

        ok = (intent == expected_intent
              and len(metrics) == expected_n_metrics
              and len(periods) == expected_n_periods)
        n_mismatch += (not ok)
        status = "OK" if ok else "KO"
        print(f"{status}  {question[:60]:60} "
              f"intent={intent} (attendu {expected_intent}), "
              f"metrics={len(metrics)} (attendu {expected_n_metrics}), "
              f"periods={len(periods)} (attendu {expected_n_periods})")

    print("-" * 60)
    print(f"[STATS] Ecarts detection : {n_mismatch}")
    return n_mismatch == 0


def test_comparison_content():
    print("\n" + "=" * 60)
    print("Tests de contenu des reponses de comparaison")
    print("=" * 60)

    if not ensure_database():
        print("[ERREUR] Test ignore")
        return False

    conn = sqlite3.connect(nlu.DB_PATH)
    max_date = conn.execute("SELECT MAX(date_iso) FROM releves_production").fetchone()[0]
    conn.close()
    if max_date is None:
        print("[ERREUR] Aucune donnee")
        return False
    today = date.fromisoformat(max_date)

    comparison_questions = [
        "compare le cumul CAD et le cumul SL3 de cette semaine",
        "quel est l'ecart entre le cumul CAD d'hier et d'avant-hier ?",
        "compare le rendement d'aujourd'hui et de la semaine derniere",
    ]

    n_mismatch = 0
    for question in comparison_questions:
        rep = nlu.parse_question(question, today)
        ok = rep is not None and "Comparaison" in rep and (
            "Ecart" in rep or "Impossible de calculer l'ecart" in rep
        )
        n_mismatch += (not ok)
        status = "OK" if ok else "KO"
        print(f"{status}  {question}")
        if not ok:
            print(f"     -> reponse obtenue : {rep!r}")

    print("-" * 60)
    print(f"[STATS] Ecarts contenu : {n_mismatch}")
    return n_mismatch == 0

if __name__ == "__main__":
    ok_regles = test_run()
    ok_detection = test_intent_detection()
    ok_content = test_comparison_content()

    success = ok_regles and ok_detection and ok_content

    print("\n" + "=" * 60)
    print("RESUME GLOBAL")
    print("=" * 60)
    print(f"  Reconnaissance regles/fallback : {'OK' if ok_regles else 'KO'}")
    print(f"  Detection intention/metriques/periodes : {'OK' if ok_detection else 'KO'}")
    print(f"  Contenu des reponses de comparaison : {'OK' if ok_content else 'KO'}")
    print(f"  => {'TOUS LES TESTS PASSENT' if success else 'DES TESTS ONT ECHOUE'}")

    sys.exit(0 if success else 1)