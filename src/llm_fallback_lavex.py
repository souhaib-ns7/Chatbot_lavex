"""
Fallback LLM (un seul appel) pour le chatbot Lavex.

"""
import sys
import os
import json
import calendar
from datetime import date, timedelta

from groq import Groq

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")

if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

try:
    import nlu_lavex as nlu
    print("[OK] Import reussi")
except ImportError as e:
    print(f"[ERREUR] Erreur d'import : {e}")
    print(f"[INFO] SRC_PATH : {SRC_PATH}")
    print(f"[INFO] Fichiers dans src : {os.listdir(SRC_PATH) if os.path.exists(SRC_PATH) else 'dossier inexistant'}")
    sys.exit(1)

MODEL = "openai/gpt-oss-120b"  # modèle open-source servi via Groq

METRIC_ENUM = list(nlu.METRIC_LABELS.keys())

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "extraire_requete_production",
            "description": (
                "Extrait la métrique de production demandée et la période "
                "concernée à partir d'une question en français sur les "
                "données de production Lavex."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "enum": METRIC_ENUM,
                        "description": "Colonne de métrique correspondant à la question.",
                    },
                    "period_type": {
                        "type": "string",
                        "enum": ["today", "yesterday", "day_before_yesterday",
                                 "last_week", "this_week", "last_month", "specific_date"],
                        "description": "Type de période demandée.",
                    },
                    "specific_date": {
                        "type": "string",
                        "description": "Date au format JJ/MM/AAAA, uniquement si period_type='specific_date'.",
                    },
                },
                "required": ["metric", "period_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "extraire_comparaison_production",
            "description": (
                "Extrait les parametres necessaires pour comparer deux "
                "valeurs de production (deux metriques, deux periodes, ou "
                "une combinaison des deux) a partir d'une question en "
                "francais qui demande explicitement une comparaison, un "
                "ecart ou une difference entre deux elements."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "metric1": {
                        "type": "string",
                        "enum": METRIC_ENUM,
                        "description": "Premiere metrique de la comparaison.",
                    },
                    "period_type1": {
                        "type": "string",
                        "enum": ["today", "yesterday", "day_before_yesterday",
                                 "last_week", "this_week", "last_month", "specific_date"],
                        "description": "Periode du premier terme de la comparaison.",
                    },
                    "specific_date1": {
                        "type": "string",
                        "description": "Date JJ/MM/AAAA, uniquement si period_type1='specific_date'.",
                    },
                    "metric2": {
                        "type": "string",
                        "enum": METRIC_ENUM,
                        "description": (
                            "Deuxieme metrique de la comparaison. Si la "
                            "question compare une seule metrique sur deux "
                            "periodes, mettre la meme valeur que metric1."
                        ),
                    },
                    "period_type2": {
                        "type": "string",
                        "enum": ["today", "yesterday", "day_before_yesterday",
                                 "last_week", "this_week", "last_month", "specific_date"],
                        "description": (
                            "Periode du deuxieme terme de la comparaison. Si "
                            "la question compare deux metriques sur une "
                            "seule periode, mettre la meme valeur que "
                            "period_type1."
                        ),
                    },
                    "specific_date2": {
                        "type": "string",
                        "description": "Date JJ/MM/AAAA, uniquement si period_type2='specific_date'.",
                    },
                },
                "required": ["metric1", "period_type1", "metric2", "period_type2"],
            },
        },
    },
]


def _period_from_type(period_type: str, specific_date: str, reference_date: date):
    if period_type == "today":
        return [reference_date.isoformat()], "aujourd'hui"
    if period_type == "yesterday":
        d = reference_date - timedelta(days=1)
        return [d.isoformat()], "hier"
    if period_type == "day_before_yesterday":
        d = reference_date - timedelta(days=2)
        return [d.isoformat()], "avant-hier"
    if period_type == "last_week":
        this_monday = reference_date - timedelta(days=reference_date.weekday())
        last_monday = this_monday - timedelta(days=7)
        dates = [(last_monday + timedelta(days=i)).isoformat() for i in range(7)]
        return dates, "la semaine dernière"
    if period_type == "this_week":
        this_monday = reference_date - timedelta(days=reference_date.weekday())
        dates = [(this_monday + timedelta(days=i)).isoformat()
                  for i in range(reference_date.weekday() + 1)]
        return dates, "cette semaine"
    if period_type == "last_month":
        first_this_month = reference_date.replace(day=1)
        last_month_end = first_this_month - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        days_in_month = calendar.monthrange(last_month_start.year, last_month_start.month)[1]
        dates = [(last_month_start + timedelta(days=i)).isoformat() for i in range(days_in_month)]
        return dates, "le mois dernier"
    if period_type == "specific_date" and specific_date:
        dd, mm, yyyy = specific_date.split("/")
        d = date(int(yyyy), int(mm), int(dd))
        return [d.isoformat()], specific_date
    return None, None


def llm_fallback(question: str, reference_date: date, client: Groq = None):
    """Un seul appel API : extraction structurée uniquement.
    Le modèle choisit lui-même l'outil (statistique ou comparaison) selon
    la nature de la question. Le calcul et la réponse restent en Python
    déterministe, quel que soit l'outil choisi.

    """
    client = client or Groq(api_key=os.environ["GROQ_API_KEY"])

    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": question}],
            tools=TOOLS,
            tool_choice="auto",
        )
    except Exception as e:
        return f"Le service de traitement est momentanément indisponible ({e}). Réessaie dans un instant."

    message = resp.choices[0].message

    # Le modèle n'a pas appelé d'outil : il répond en texte libre, en
    # général pour demander une clarification. On relaie ce texte tel
    # quel plutôt que de planter en accédant à tool_calls[0].
    if not message.tool_calls:
        texte = (message.content or "").strip()
        if not texte:
            return "Je n'ai pas compris la question, peux-tu reformuler ?"
        return texte

    tool_call = message.tool_calls[0]
    args = json.loads(tool_call.function.arguments)

    if tool_call.function.name == "extraire_comparaison_production":
        dates1, label1 = _period_from_type(
            args["period_type1"], args.get("specific_date1"), reference_date
        )
        dates2, label2 = _period_from_type(
            args["period_type2"], args.get("specific_date2"), reference_date
        )
        if dates1 is None or dates2 is None:
            return "Je n'ai pas compris une des périodes demandées, peux-tu reformuler ?"

        comparisons = [
            (args["metric1"], dates1, label1),
            (args["metric2"], dates2, label2),
        ]
        results, delta, pct_change = nlu.compute_comparison(comparisons)
        return nlu.format_comparison_response(results, delta, pct_change)

    metric_col = args["metric"]
    dates_iso, period_label = _period_from_type(
        args["period_type"], args.get("specific_date"), reference_date
    )
    if dates_iso is None:
        return "Je n'ai pas compris la période demandée, peux-tu reformuler ?"

    daily, total = nlu.compute(metric_col, dates_iso)
    return nlu.format_response(metric_col, period_label, daily, total)


def answer(question: str, reference_date: date):
    """Pipeline complet : règles d'abord, LLM en secours (1 appel max)."""
    rep = nlu.parse_question(question, reference_date)
    if rep is not None:
        return rep, "regles"
    return llm_fallback(question, reference_date), "llm_fallback"


if __name__ == "__main__":
    conn_max_date = __import__("sqlite3").connect(nlu.DB_PATH)
    max_date = conn_max_date.execute(
        "SELECT MAX(date_iso) FROM releves_production"
    ).fetchone()[0]
    conn_max_date.close()
    today = date.fromisoformat(max_date)

    q = "peux-tu me donner le rendement de la semaine passée ?"
    print("Q:", q)
    rep, source = answer(q, today)
    print(f"[source: {source}]")
    print(rep)
