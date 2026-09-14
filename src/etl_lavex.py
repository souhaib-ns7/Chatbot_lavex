"""
ETL Lavex : Excel -> SQLite
"""

import sys
import pandas as pd
import sqlite3

EXCEL_PATH = sys.argv[1] if len(sys.argv) > 1 else "https://docs.google.com/spreadsheets/d/1vAxwpx_tVx6O9wdZqJcjaEnTIeawe6DIHfsD24-E1CQ/export?format=csv&gid=1031922911"
DB_PATH = "lavex_releves.db"
TABLE = "releves_production"

RENAME = {
    "Date reception": "date_reception",
    "Type detecte": "type_detecte",
    "Date": "date",
    "Shift": "shift",
    "Heure": "heure",
    "Cumul HM": "cumul_hm",
    "Cumul CAD (TSM)": "cumul_cad_tsm",
    "Cumul SL3 (TSM)": "cumul_sl3_tsm",
    "Rythme previsionnel fin shift (TSM)": "rythme_previsionnel_fin_shift_tsm",
    "RP (%)": "rp_pct",
    "Coarse Reject (TSM)": "coarse_reject_tsm",
    "Taux Coarse Reject (%)": "taux_coarse_reject_pct",
    "Cumul Stockage ST110 (THC)": "cumul_stockage_st110_thc",
    "Cumul Destockage RL2 (T)": "cumul_destockage_rl2_t",
    "POST 1 (THC)": "post1_thc",
    "POST 2 (THC)": "post2_thc",
    "POST 3 (THC)": "post3_thc",
    "Total (THC)": "total_thc",
    "Message brut": "message_brut",
    "Turbidity (mg/L)": "turbidity_mgl",
    "Debit Soutirage Decanteur (m3/h)": "debit_soutirage_decanteur_m3h",
    "Pompe Process Water (m3/h)": "pompe_process_water_m3h",
}

NUM_COLS = [
    "cumul_cad_tsm", "cumul_sl3_tsm", "rythme_previsionnel_fin_shift_tsm", "rp_pct",
    "coarse_reject_tsm", "taux_coarse_reject_pct", "cumul_stockage_st110_thc",
    "cumul_destockage_rl2_t", "post1_thc", "post2_thc", "post3_thc", "total_thc",
    "turbidity_mgl", "debit_soutirage_decanteur_m3h", "pompe_process_water_m3h",
]


def load_and_clean(source: str) -> pd.DataFrame:
    if source.startswith("http://") or source.startswith("https://"):
        df = pd.read_csv(source)
    else:
        df = pd.read_excel(source)
    df = df.rename(columns=RENAME)
    for c in NUM_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date_iso"] = pd.to_datetime(df["date"], dayfirst=True).dt.strftime("%Y-%m-%d")
    df["heure_str"] = df["heure"].astype(str)
    df["date_reception"] = df["date_reception"].astype(str)
    return df


def ensure_table(conn: sqlite3.Connection, df: pd.DataFrame):
    cur = conn.cursor()
    cur.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{TABLE}'")
    if cur.fetchone() is None:
        df.head(0).to_sql(TABLE, conn, index=False)
        conn.execute(f"CREATE UNIQUE INDEX idx_date_reception ON {TABLE}(date_reception)")
        conn.execute(f"CREATE INDEX idx_date_iso ON {TABLE}(date_iso)")
        conn.execute(f"CREATE INDEX idx_type ON {TABLE}(type_detecte)")
        conn.commit()


def incremental_load(df: pd.DataFrame, db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    ensure_table(conn, df)

    existing = pd.read_sql(f"SELECT date_reception FROM {TABLE}", conn)
    known = set(existing["date_reception"])

    new_rows = df[~df["date_reception"].isin(known)]
    if len(new_rows) == 0:
        print("Aucune nouvelle ligne à ajouter — base déjà à jour.")
    else:
        new_rows.to_sql(TABLE, conn, if_exists="append", index=False)
        print(f"{len(new_rows)} nouvelle(s) ligne(s) ajoutée(s) "
              f"(base totale : {len(known) + len(new_rows)} lignes).")

    conn.close()


if __name__ == "__main__":
    data = load_and_clean(EXCEL_PATH)
    incremental_load(data)