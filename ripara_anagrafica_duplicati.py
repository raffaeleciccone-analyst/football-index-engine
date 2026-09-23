"""Cancella i record di anagrafica che sono COPIE di un altro, non meta' di esso.

LA DIFFERENZA CHE CONTA
-----------------------
Due record con lo stesso nome possono essere due cose opposte, e la cura e'
opposta:

  * **una carriera spezzata** — le partite dei due record non si sovrappongono
    mai, perche' sono due meta' (di solito due maglie). Vanno UNITE, e lo fa
    `unisci_record_doppioni.py`.
  * **una copia** — le righe del secondo record sono le STESSE del primo:
    stessa giornata, stessi minuti, stessi gol. Va CANCELLATA. Unirla
    raddoppierebbe i minuti di quelle giornate.

Sbagliare cura e' peggio che non fare niente, quindi qui la condizione e'
stretta: si cancella solo un record le cui righe sono **tutte** duplicate, e
identiche anche nei numeri, non solo nei minuti. Se anche una sola riga e' sua e
di nessun altro, non e' una copia e lo script la lascia stare.

IL DANNO CHE RIPARA
-------------------
Non e' statistico, e' di elenco: il fantasma compare come una seconda persona.
L'8/9/2026 Morten Thorsby era pubblicato due volte nella classifica 2025-26 —
"Genoa" 128esimo con TPI 0.129 e "Cremonese" 143esimo con 0.058 — e chi leggeva
vedeva due giocatori con lo stesso nome e due punteggi diversi.

PERCHE' NON HA PIU' DEI NOMI DENTRO
-----------------------------------
La prima versione conosceva Estupinan e Soule, trovati a mano ad agosto. Un
elenco di nomi scritto a mano invecchia: a settembre i duplicati erano altri due
e nessuno lo sapeva. Adesso li trova dai dati, quindi vale anche per quelli
della prossima stagione, che oggi non esistono ancora.

USO
---
    python ripara_anagrafica_duplicati.py            # mostra e basta
    python ripara_anagrafica_duplicati.py --esegui   # scrive davvero

Dopo, va rigenerato il payload: i fantasmi spariscono dagli elenchi.
"""
from __future__ import annotations

import sys
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")
import pandas as pd
from sqlalchemy import create_engine, text

import config

BACKUP = Path(r"C:\dev") / ("_backup_anagrafica_" + datetime.now().strftime("%Y%m%d_%H%M"))

# Una riga e' "la stessa" se coincide su tutto cio' che descrive la prestazione.
# Solo i minuti non basterebbero: due riserve entrate allo stesso minuto nella
# stessa partita avrebbero minuti uguali senza essere la stessa persona.
STESSA_RIGA = """p2.calendario_id = p1.calendario_id
              AND p2.minuti = p1.minuti AND p2.goal = p1.goal
              AND p2.assist = p1.assist AND p2.tiri = p1.tiri"""


def trova_copie(eng) -> pd.DataFrame:
    """I record le cui righe sono TUTTE copie di quelle di un altro omonimo."""
    return pd.read_sql(f"""
        SELECT  p1.giocatore_id                AS copia,
                MIN(p2.giocatore_id)           AS resta,
                g1.nome                        AS nome,
                COUNT(DISTINCT p1.id)          AS righe_copia,
                (SELECT COUNT(*) FROM giocatore_partita x
                  WHERE x.giocatore_id = p1.giocatore_id) AS righe_totali
        FROM        giocatore_partita p1
        JOIN        giocatore_partita p2 ON {STESSA_RIGA}
                                        AND p2.giocatore_id <> p1.giocatore_id
        JOIN        giocatori g1 ON g1.id = p1.giocatore_id
        JOIN        giocatori g2 ON g2.id = p2.giocatore_id AND g2.nome = g1.nome
        GROUP BY    p1.giocatore_id, g1.nome
        HAVING      righe_copia = righe_totali
    """, eng)


def main() -> None:
    esegui = "--esegui" in sys.argv
    eng = create_engine(config.db_url())
    copie = trova_copie(eng)

    if copie.empty:
        print("Nessun record duplicato: ogni riga partita appartiene a uno solo.")
        return

    # Chi ha piu' righe non e' una copia di chi ne ha meno: si tiene il record
    # piu' completo. Se due si dichiarassero copia a vicenda (righe identiche in
    # numero uguale) resterebbe quello con l'id piu' basso, cioe' il piu' antico.
    copie = copie[copie.copia > copie.resta]
    if copie.empty:
        print("Trovate sovrapposizioni, ma nessuna e' una copia completa: "
              "non si cancella niente.")
        return

    print("Record che sono copie complete di un altro:\n")
    for _, r in copie.iterrows():
        print("   %-24s copia id=%-9s (%s righe, tutte duplicate)  ->  resta id=%s"
              % (r.nome, r.copia, r.righe_copia, r.resta))

    dup = tuple(int(x) for x in copie.copia)
    segno = "(%s)" % ",".join(str(x) for x in dup)
    inf = pd.read_sql(f"SELECT * FROM t_infortuni WHERE giocatore_id IN {segno}", eng)
    print("\ninfortuni da spostare sul record che resta: %d" % len(inf))
    print("(un infortunio appartiene alla persona, non al record: non si butta via)")

    if not esegui:
        print("\nAnteprima soltanto. Rilancia con --esegui per scrivere.")
        return

    BACKUP.mkdir(parents=True, exist_ok=True)
    for tabella, sql in (
        ("giocatori", f"SELECT * FROM giocatori WHERE id IN {segno}"),
        ("giocatore_partita", f"SELECT * FROM giocatore_partita WHERE giocatore_id IN {segno}"),
        ("t_infortuni", f"SELECT * FROM t_infortuni WHERE giocatore_id IN {segno}"),
    ):
        pd.read_sql(sql, eng).to_csv(BACKUP / (tabella + ".csv"), index=False, encoding="utf-8")
    print("backup -> %s" % BACKUP)

    with eng.begin() as c:
        for _, r in copie.iterrows():
            c.execute(text("UPDATE t_infortuni SET giocatore_id=:n WHERE giocatore_id=:v"),
                      {"n": int(r.resta), "v": int(r.copia)})
        c.execute(text(f"DELETE FROM giocatore_partita WHERE giocatore_id IN {segno}"))
        c.execute(text(f"DELETE FROM giocatori WHERE id IN {segno}"))

    rimasti = pd.read_sql(f"SELECT COUNT(*) c FROM giocatori WHERE id IN {segno}", eng).iloc[0, 0]
    orfane = pd.read_sql(
        f"SELECT COUNT(*) c FROM giocatore_partita WHERE giocatore_id IN {segno}", eng).iloc[0, 0]
    print("\n%d record cancellati. Rimasti: %s. Righe orfane: %s." % (len(copie), rimasti, orfane))
    print("Ora rigenera i payload.")


if __name__ == "__main__":
    main()
