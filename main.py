"""
Point d'entrée du chatbot Lavex.
"""

import sqlite3
from datetime import date

from dotenv import load_dotenv

from src import nlu_lavex as nlu
from src import llm_fallback_lavex as llm_fb
from src import etl_lavex as etl

load_dotenv()  # charge GROQ_API_KEY depuis le fichier .env

DATA_SOURCE = "https://docs.google.com/spreadsheets/d/1vAxwpx_tVx6O9wdZqJcjaEnTIeawe6DIHfsD24-E1CQ/export?format=csv&gid=1031922911"


def update_database():
    try:
        df = etl.load_and_clean(DATA_SOURCE)
        etl.incremental_load(df, etl.DB_PATH)
    except Exception as e:
        print(f"[attention] échec de la mise à jour de la base : {e}")
        print("[attention] le chatbot continue avec les données déjà en base.\n")


def get_reference_date() -> date:
    conn = sqlite3.connect(nlu.DB_PATH)
    max_date = conn.execute(
        "SELECT MAX(date_iso) FROM releves_production"
    ).fetchone()[0]
    conn.close()
    return date.fromisoformat(max_date) if max_date else date.today()


def main():
    print("Chatbot Lavex — mise à jour de la base en cours...")
    update_database()

    print("Chatbot Lavex — pose une question sur la production (ou 'quit' pour sortir)\n")
    today = get_reference_date()

    while True:
        question = input("> ").strip()
        if question.lower() in ("quit", "exit", "q"):
            break
        if not question:
            continue

        try:
            reponse, source = llm_fb.answer(question, today)
        except Exception as e:
            reponse, source = f"Erreur pendant le traitement : {e}", "erreur"

        print(f"\n[{source}]")
        print(reponse)
        print()


if __name__ == "__main__":
    main()