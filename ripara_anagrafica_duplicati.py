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

IL NOME NON E' LA PROVA (24/09/2026)
------------------------------------
Passando dall'elenco ai dati, la ricerca aveva tenuto una condizione di
comodo: i due record dovevano avere lo stesso `nome`. Estupinan e' rimasto
fuori proprio per quella — "Pervis Estupiñán" dall'anagrafica heXI, e
"Estupiñán" e basta da Understat, che per lui usa un nome solo — e la
classifica 2025-26 della Serie A lo pubblicava due volte, con gli stessi numeri.
Nell'anagrafica ci sono quasi quattrocento record con nome o cognome vuoto.

E non era il solo filtro a lasciarlo fuori: il record che resta era sempre
quello con l'id piu' basso. Qui la copia era il record VECCHIO, e quello
nuovo aveva in piu' le partite della 2026-27: tenere il vecchio avrebbe
cancellato la stagione in corso.

Ora la prova sono le righe, coppia per coppia: TUTTE le righe della copia
identiche a quelle di UN SOLO altro record, su tutti i campi misurati (xg e
xa compresi, non piu' solo minuti/gol/assist/tiri), con almeno tre partite
giocate. Il nome resta solo come conferma debole: basta una parola in comune.
Tolto il nome, le righe identiche fra compagni di squadra sono migliaia —
portiere e difensore a 90' senza un tiro — ma nessuna coppia le ha TUTTE:
misurato su entrambi i database, la sola era Estupinan, 19 su 19; la seconda
11 su 75. Resta il record con piu' righe; a pari righe, il piu' antico.

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
CAMPI = ("minuti", "goal", "assist", "tiri", "xg", "xa", "xg_chain", "xg_buildup")

# Sotto questa soglia "tutte le righe uguali" non prova niente: una riserva
# con due spezzoni da zero tiri e' identica a mezza panchina.
MIN_GIOCATE = 3


def _firma(r) -> tuple:
    """La riga ridotta a cio' che si confronta. I float si arrotondano: arrivano
    da colonne FLOAT, e due letture dello stesso valore possono differire
    all'ultima cifra senza che sia una differenza."""
    fuori = [int(r.cid)]
    for campo in CAMPI:
        v = getattr(r, campo)
        if v is None or pd.isna(v):
            fuori.append(None)
        elif isinstance(v, float):
            fuori.append(round(v, 4))
        else:
            fuori.append(v)
    return tuple(fuori)


def copie_complete(righe: pd.DataFrame, nomi: dict[int, str]) -> pd.DataFrame:
    """I record le cui righe sono TUTTE uguali a quelle di un solo altro record.

    `righe`: gid, cid e i CAMPI, una riga per giocatore e partita (anche quelle
    da zero minuti: una riga che solo la copia ha la rende non-copia).
    `nomi`:  id -> nome completo.
    """
    from unisci_record_doppioni import chiave_nome

    firme: dict[int, set] = {}
    giocate: dict[int, int] = {}
    chi_ha: dict[tuple, set] = {}
    for r in righe.itertuples(index=False):
        gid, f = int(r.gid), _firma(r)
        firme.setdefault(gid, set()).add(f)
        chi_ha.setdefault(f, set()).add(gid)
        if r.minuti and r.minuti > 0:
            giocate[gid] = giocate.get(gid, 0) + 1

    parole = {gid: set(chiave_nome(n).split()) for gid, n in nomi.items()}
    uscita = []
    for a, fa in firme.items():
        if giocate.get(a, 0) < MIN_GIOCATE:
            continue
        # Chi ha TUTTE le righe di `a`: l'intersezione, non l'unione — tre
        # righe uguali a tre compagni diversi non sono una copia di nessuno.
        candidati = set.intersection(*(chi_ha[f] for f in fa)) - {a}
        for b in sorted(candidati):
            if not (parole.get(a, set()) & parole.get(b, set())):
                continue
            # Resta chi ha piu' righe; a pari righe (copia a vicenda) il piu'
            # antico. L'id da solo non decide: il vecchio puo' essere la copia.
            if len(firme[b]) == len(fa) and a < b:
                continue
            uscita.append((a, b, nomi.get(a, "?"), len(fa), len(fa)))
            break
    return pd.DataFrame(uscita, columns=["copia", "resta", "nome",
                                         "righe_copia", "righe_totali"])


def trova_copie(eng) -> pd.DataFrame:
    righe = pd.read_sql(
        "SELECT giocatore_id gid, calendario_id cid, " + ", ".join(CAMPI)
        + " FROM giocatore_partita", eng)
    ana = pd.read_sql(
        "SELECT id, TRIM(CONCAT_WS(' ', nome, cognome)) n FROM giocatori", eng)
    return copie_complete(righe, dict(zip(ana.id.astype(int), ana.n)))


def main() -> None:
    esegui = "--esegui" in sys.argv
    eng = create_engine(config.db_url())
    copie = trova_copie(eng)

    if copie.empty:
        print("Nessun record duplicato: ogni riga partita appartiene a uno solo.")
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
