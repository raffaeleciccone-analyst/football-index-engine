"""Toglie i record vuoti lasciati da `unisci_record_doppioni.py`.

COSA SUCCEDE (16/09/2026)
-------------------------
L'unione dell'8/9 spostava le partite sul record canonico e lasciava il
doppione in tabella, senza partite: "il motore lo ignora da solo". Il motore
si', `parte4` no. Il doppione porta (nome, club NUOVO), cioe' esattamente la
chiave `uq_nome_squadra` che l'ingestione urta per prima quando il giocatore
torna da Understat col club nuovo. La UPDATE che segue gli scrive
`understat_id` — che e' gia' del canonico — e il database rifiuta:

    IntegrityError 1062: Duplicate entry '8327' for key 'uq_giocatori_understat_id'

Due correzioni giuste (l'unione, e `understat_id` nell'upsert, `3a2e522`) che
insieme fermano il giro. Tolto il guscio, la INSERT urta il canonico su
`understat_id` e gli aggiorna il club: quello che `3a2e522` voleva fare.

LA REGOLA
---------
Un record si cancella solo se valgono tutte, altrimenti non si tocca niente:

  1. e' un `da_giocatore_id` della mappa salvata dall'unione;
  2. il canonico (`a_giocatore_id`) esiste ancora;
  3. nessuna riga in nessuna colonna che punti a un giocatore
     (`giocatore_partita`, `t_infortuni`, e qualunque altra la trovi);
  4. se il guscio ha `understat_id` il canonico non ne ha uno diverso: in quel
     caso non erano la stessa persona, e ci si ferma.

Se il guscio ha `understat_id` e il canonico no, l'id passa al canonico prima
di cancellare: altrimenti al prossimo giro il trasferimento tornerebbe a
creare un record nuovo, e la carriera si spezzerebbe di nuovo.

C'e' anche il caso rovesciato, lasciato da un'unione piu' vecchia che non ha
salvato la mappa: il guscio ha `understat_id` e il record vero, con tutte le
partite, non ce l'ha (sulla Serie A, 16: Raspadori, Krstovic, Zaniolo...).
L'ingestione urta il record vero su (nome, club), gli scrive l'id e collide
col guscio. Questi si trovano senza mappa, con una regola stretta: guscio con
`understat_id`, zero partite, e UN SOLO altro record con lo stesso nome, che
abbia partite e `understat_id` NULL. L'id passa al record vero, il guscio va.

Tutto in una transazione, dopo un `mysqldump` completo del database.

USO
    python togli_gusci_unione.py --mappa <cartella backup>            # anteprima
    python togli_gusci_unione.py --mappa <cartella backup> --esegui   # scrive
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import bindparam, create_engine, text

import config

MYSQLDUMP = Path(r"C:\Program Files\MySQL\MySQL Workbench 8.0 CE\mysqldump.exe")


def colonne_giocatore(cx) -> list[tuple[str, str]]:
    """Ogni colonna di tabella (non vista) che puo' contenere un id giocatore."""
    return [tuple(r) for r in cx.execute(text(
        "SELECT c.table_name, c.column_name FROM information_schema.columns c "
        "JOIN information_schema.tables t ON t.table_schema = c.table_schema "
        " AND t.table_name = c.table_name AND t.table_type = 'BASE TABLE' "
        "WHERE c.table_schema = DATABASE() AND c.table_name <> 'giocatori' "
        "AND c.column_name IN ('giocatore_id', 'id_giocatore', 'player_id')"))]


def backup(cartella: Path) -> Path:
    if not MYSQLDUMP.is_file():
        raise SystemExit(f"mysqldump non trovato in {MYSQLDUMP}: niente backup, niente scrittura")
    cartella.mkdir(parents=True, exist_ok=True)
    file = cartella / f"{config.DB_NAME}.sql"
    ambiente = dict(os.environ, MYSQL_PWD=config.DB_PASSWORD or "")
    with open(file, "wb") as out:
        esito = subprocess.run(
            [str(MYSQLDUMP), "-h", config.DB_HOST, "-u", config.DB_USER,
             "--single-transaction", "--routines", config.DB_NAME],
            stdout=out, stderr=subprocess.PIPE, env=ambiente)
    if esito.returncode != 0 or file.stat().st_size < 1000:
        raise SystemExit("backup fallito: %s" % esito.stderr.decode(errors="replace").strip())
    print(f"backup -> {file} ({file.stat().st_size / 1e6:.1f} MB)")
    return file


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mappa", required=True, help="cartella con mappa_unioni.csv")
    ap.add_argument("--esegui", action="store_true")
    a = ap.parse_args()

    mappa = pd.read_csv(Path(a.mappa) / "mappa_unioni.csv", encoding="utf-8")
    gusci = [int(x) for x in mappa.da_giocatore_id]
    canonici = [int(x) for x in mappa.a_giocatore_id]
    eng = create_engine(config.db_url())
    print(f"database {config.DB_NAME} — {len(gusci)} unioni nella mappa")

    with eng.connect() as cx:
        tutti = gusci + canonici
        ana = pd.read_sql(text(
            "SELECT id, nome, squadra_id, understat_id FROM giocatori WHERE id IN :ids"
        ).bindparams(bindparam("ids", expanding=True)), cx, params={"ids": tutti}
        ).set_index("id")
        riferimenti = {}
        for tabella, colonna in colonne_giocatore(cx):
            n = cx.execute(text(
                f"SELECT COUNT(*) FROM `{tabella}` WHERE `{colonna}` IN :ids"
            ).bindparams(bindparam("ids", expanding=True)), {"ids": gusci}).scalar()
            riferimenti[f"{tabella}.{colonna}"] = int(n)
        rovesciati = cx.execute(text(
            "SELECT s.id, v.id, s.understat_id, s.nome FROM giocatori s "
            "JOIN giocatori v ON v.nome = s.nome AND v.id <> s.id "
            "WHERE s.understat_id IS NOT NULL AND v.understat_id IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM giocatore_partita p WHERE p.giocatore_id = s.id) "
            "AND EXISTS (SELECT 1 FROM giocatore_partita p WHERE p.giocatore_id = v.id) "
            "AND (SELECT COUNT(*) FROM giocatori o WHERE o.nome = s.nome) = 2"
        )).fetchall()
        rovesciati = [tuple(r) for r in rovesciati if int(r[0]) not in gusci]
        if rovesciati:
            ids = [int(r[0]) for r in rovesciati]
            for tabella, colonna in colonne_giocatore(cx):
                n = cx.execute(text(
                    f"SELECT COUNT(*) FROM `{tabella}` WHERE `{colonna}` IN :ids"
                ).bindparams(bindparam("ids", expanding=True)), {"ids": ids}).scalar()
                riferimenti[f"{tabella}.{colonna}"] += int(n)

    problemi, gia_via, sposta_id, cancella = [], [], [], []
    for da, verso, us, nome in rovesciati:
        sposta_id.append((int(da), int(verso), int(us), nome))
        cancella.append((int(da), nome))
    for da, verso, nome in mappa.itertuples(index=False):
        da, verso = int(da), int(verso)
        if da not in ana.index:
            gia_via.append(nome)
            continue
        if verso not in ana.index:
            problemi.append(f"{nome}: il canonico id{verso} non c'e' piu'")
            continue
        us_g, us_c = ana.loc[da].understat_id, ana.loc[verso].understat_id
        if pd.notna(us_g):
            if pd.notna(us_c) and int(us_c) != int(us_g):
                problemi.append(f"{nome}: understat_id diversi ({int(us_g)} / {int(us_c)})")
                continue
            if pd.isna(us_c):
                sposta_id.append((da, verso, int(us_g), nome))
        cancella.append((da, nome))

    for chi, n in riferimenti.items():
        print(f"righe che puntano ai gusci in {chi:32}: {n}")
        if n:
            problemi.append(f"{chi} ha ancora {n} righe sui gusci")
    print(f"da cancellare       : {len(cancella)} (di cui {len(rovesciati)} rovesciati, senza mappa)")
    print(f"understat_id spostati sul canonico: {len(sposta_id)}")
    for da, verso, us, nome in sposta_id:
        print(f"   {nome}: {us}  id{da} -> id{verso}")
    if gia_via:
        print(f"gia' tolti          : {len(gia_via)}")

    if problemi:
        print("\nMi fermo, non tocco niente:")
        for p in problemi:
            print(f"   {p}")
        return 1
    if not a.esegui:
        print("\nAnteprima soltanto. Rilancia con --esegui per scrivere.")
        return 0
    if not cancella:
        print("\nNiente da fare.")
        return 0

    backup(Path(r"C:\dev") / f"_backup_gusci_{config.DB_NAME}_{datetime.now():%Y%m%d_%H%M}")
    with eng.begin() as cx:
        for da, verso, us, _ in sposta_id:
            cx.execute(text("UPDATE giocatori SET understat_id = NULL WHERE id = :d"), {"d": da})
            cx.execute(text("UPDATE giocatori SET understat_id = :u WHERE id = :v"),
                       {"u": us, "v": verso})
        n = cx.execute(text("DELETE FROM giocatori WHERE id IN :ids").bindparams(
            bindparam("ids", expanding=True)), {"ids": [d for d, _ in cancella]}).rowcount
        if n != len(cancella):
            raise RuntimeError(f"cancellati {n} invece di {len(cancella)}: annullo")
    print(f"\n{n} gusci tolti, {len(sposta_id)} understat_id spostati.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
