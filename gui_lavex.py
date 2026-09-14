"""
Interface graphique (type terminal) pour le chatbot Lavex.

"""

import os
import sys
import sqlite3
import threading
import queue
from datetime import date

import tkinter as tk
from tkinter import scrolledtext, font as tkfont

from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

try:
    from src import nlu_lavex as nlu
    from src import llm_fallback_lavex as llm_fb
    from src import etl_lavex as etl
except ImportError:
    import nlu_lavex as nlu
    import llm_fallback_lavex as llm_fb
    import etl_lavex as etl

load_dotenv()  # charge GROQ_API_KEY depuis le fichier .env


DATA_SOURCE = "https://docs.google.com/spreadsheets/d/1vAxwpx_tVx6O9wdZqJcjaEnTIeawe6DIHfsD24-E1CQ/export?format=csv&gid=1031922911"


def get_reference_date() -> date:
    conn = sqlite3.connect(nlu.DB_PATH)
    max_date = conn.execute(
        "SELECT MAX(date_iso) FROM releves_production"
    ).fetchone()[0]
    conn.close()
    return date.fromisoformat(max_date) if max_date else date.today()


# Interface

BG = "#ffffff"
FG = "#1a1a1a"
PANEL_BG = "#f4f9f4"
BORDER = "#2e7d32"
PROMPT_COLOR = "#1e7e34"
SOURCE_COLOR = "#2e7d32"
ERROR_COLOR = "#c62828"


class LavexTerminalApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Lavex — Chatbot Production")
        self.geometry("900x600")
        self.configure(bg=BG)
        self.minsize(600, 400)

        mono = tkfont.Font(family="Consolas", size=11)
        if mono.actual("family").lower() != "consolas":
            mono = tkfont.Font(family="Courier New", size=11)
        title_font = tkfont.Font(family=mono.actual("family"), size=13, weight="bold")

        header = tk.Frame(self, bg=BORDER, height=40)
        header.pack(fill="x")
        tk.Label(
            header, text="  Lavex — Chatbot Production", bg=BORDER, fg="#ffffff",
            font=title_font, anchor="w", pady=8,
        ).pack(fill="x")

        # Zone d'affichage (historique question/reponse), lecture seule
        self.output = scrolledtext.ScrolledText(
            self, wrap="word", bg=BG, fg=FG, insertbackground=FG,
            font=mono, borderwidth=0, highlightthickness=0, state="disabled",
        )
        self.output.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        self.output.tag_config("prompt", foreground=PROMPT_COLOR, font=(mono.actual("family"), 11, "bold"))
        self.output.tag_config("source", foreground=SOURCE_COLOR, font=(mono.actual("family"), 10, "italic"))
        self.output.tag_config("error", foreground=ERROR_COLOR)
        self.output.tag_config("answer", foreground=FG)

        tk.Frame(self, bg=BORDER, height=2).pack(fill="x", padx=10)

        entry_frame = tk.Frame(self, bg=PANEL_BG, highlightbackground=BORDER,
                                highlightthickness=1)
        entry_frame.pack(fill="x", padx=10, pady=10, ipady=6)

        self.prompt_label = tk.Label(
            entry_frame, text=">", bg=PANEL_BG, fg=PROMPT_COLOR, font=mono
        )
        self.prompt_label.pack(side="left", padx=(8, 0))

        self.entry = tk.Entry(
            entry_frame, bg=PANEL_BG, fg=FG, insertbackground=FG, font=mono,
            relief="flat", borderwidth=0, highlightthickness=0,
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=(6, 8))
        self.entry.bind("<Return>", self._on_submit)
        self.entry.focus_set()

        self._result_queue = queue.Queue()
        self.after(80, self._poll_queue)
        self._startup_queue = queue.Queue()

        self.reference_date = None
        self._start_startup_sequence()


    def _start_startup_sequence(self):
        self._set_input_enabled(False)
        self._append("Mise à jour de la base en cours...\n", "source")
        thread = threading.Thread(target=self._startup_worker, daemon=True)
        thread.start()
        self.after(80, self._poll_startup_queue)

    def _startup_worker(self):
        try:
            df = etl.load_and_clean(DATA_SOURCE)
            etl.incremental_load(df, etl.DB_PATH)
            status = ("Base à jour.\n", "source")
        except Exception as e:
            status = (
                f"[avertissement] échec de la mise à jour de la base ({e}) "
                "— le chatbot continue avec les données déjà en base.\n",
                "error",
            )
        self._startup_queue.put(status)

    def _poll_startup_queue(self):
        try:
            text, tag = self._startup_queue.get_nowait()
            self._append(text, tag)
            self._load_reference_date()
            self._print_welcome()
            self._set_input_enabled(True)
        except queue.Empty:
            self.after(80, self._poll_startup_queue)

    def _load_reference_date(self):
        try:
            self.reference_date = get_reference_date()
        except Exception as e:
            self.reference_date = date.today()
            self._append(f"[avertissement] impossible de lire la base "
                          f"({e}) — date du jour utilisee.\n", "error")

    def _print_welcome(self):
        self._append(
            "Chatbot Lavex — pose une question sur la production.\n"
            "Tape 'quit' ou ferme la fenetre pour sortir.\n\n",
            "answer",
        )

    # Boucle question / reponse

    def _on_submit(self, event=None):
        question = self.entry.get().strip()
        if not question:
            return
        self.entry.delete(0, tk.END)

        if question.lower() in ("quit", "exit", "q"):
            self.destroy()
            return

        self._append(f"> {question}\n", "prompt")
        self._set_input_enabled(False)
        thread = threading.Thread(
            target=self._compute_answer, args=(question,), daemon=True
        )
        thread.start()

    def _compute_answer(self, question: str):
        try:
            reponse, source = llm_fb.answer(question, self.reference_date)
        except Exception as e:
            reponse, source = f"Erreur pendant le traitement : {e}", "erreur"
        self._result_queue.put((reponse, source))

    def _poll_queue(self):
        try:
            while True:
                reponse, source = self._result_queue.get_nowait()
                self._append(f"[{source}]\n", "source")
                tag = "error" if source == "erreur" else "answer"
                self._append(f"{reponse}\n\n", tag)
                self._set_input_enabled(True)
        except queue.Empty:
            pass
        self.after(80, self._poll_queue)

    def _append(self, text: str, tag: str = None):
        self.output.configure(state="normal")
        self.output.insert(tk.END, text, tag)
        self.output.see(tk.END)
        self.output.configure(state="disabled")

    def _set_input_enabled(self, enabled: bool):
        self.entry.configure(state="normal" if enabled else "disabled")
        if enabled:
            self.entry.focus_set()


if __name__ == "__main__":
    app = LavexTerminalApp()
    app.mainloop()