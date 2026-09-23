"""Restituisce l'understat_id ai record che non ce l'hanno.

COSA SUCCEDE (23/09/2026)
-------------------------
'parte4' riconosce una persona per due chiavi: (nome, squadra_id) e
'understat_id'. La seconda e' l'identita' vera, la prima e' un indirizzo — e
quando un giocatore cambia maglia l'indirizzo cambia. Se il record in tabella
ha 'understat_id' NULL, nessuna delle due chiavi lo raggiunge piu': NULL in un
indice unico non collide con niente, e l'ingestione crea una persona nuova.

Non e' un'ipotesi. L'unione dell'8/9 ha lasciato i canonici senza id (quel pezzo
e' arrivato il 16/9), e alla giornata 4 trentasette carriere si sono rispezzate
da sole, con le prime giornate scritte da tutte e due le parti. Due giocatori
sono finiti due volte nell'elenco pubblicato della Premier, quindici in quello
della Serie A.

La correzione '3a2e522' — 'understat_id' dentro la INSERT e dentro la UPDATE —
guarisce solo chi l'upsert riesce ancora a raggiungere: chi e' rimasto dov'era.
Chi se n'e' andato resta un fantasma in attesa del proprio prossimo
trasferimento. Questo passo va a cercarli prima che succeda.

LA REGOLA
---------
Un id si scrive solo se valgono tutte, altrimenti il record non si tocca:

  1. il record ha 'understat_id' NULL e almeno una partita giocata — senza
     partite non c'e' niente con cui dimostrare chi sia;
  2. il nome sta su Understat sotto UN SOLO player_id: se ne ha due sono due
     persone, e sceglierne una a caso e' il bug degli omonimi rifatto da capo;
  3. e' l'unico record con quel nome: se ce ne sono due e' una carriera
     spezzata, e quella la ricuce 'unisci_record_doppioni.py', non questo;
  4. nessun altro record porta gia' quel player_id;
  5. TEST DI ACCETTAZIONE: ogni partita che il database attribuisce al record
     deve essere una partita che Understat attribuisce a quel player_id. E' lo
     stesso metro dell'unione, ed e' cio' che distingue la persona giusta da un
     omonimo che ha lasciato il campionato.

Se la cache Understat e' vuota il passo non fa niente e lo dice. Prova assente
non e' prova contraria: e' lo stesso motivo per cui l'unione si rifiuta di
girare su una cache che ha la sola stagione in corso.

Sta nella sequenza PRIMA di 'parte4', perche' dopo non servirebbe: il record
nuovo e' gia' nato.

USO
    python allinea_understat_id.py            # mostra e basta
    python allinea_understat_id.py --esegui   # scrive davvero
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

import config
from ripara_righe_omonimi import carica_understat
from unisci_record_doppioni import chiave_nome

REGISTRO = Path(__file__).resolve().parent / "logs"


def piano_allineamento(ana: pd.DataFrame, per_g: dict, us: tuple) -> tuple[list, list]:
    """Chi prende quale id, e chi resta fuori con il motivo scritto."""
    per_id, _per_nome, id_per_nome = us
    gia_presi = {int(u) for u in ana.understat_id.dropna()}
    quanti_per_nome: dict[str, int] = {}
    for _, r in ana.iterrows():
        quanti_per_nome[chiave_nome(r.n)] = quanti_per_nome.get(chiave_nome(r.n), 0) + 1

    piano, fuori = [], []
    for _, r in ana.iterrows():
        if not pd.isna(r.understat_id):
            continue
        rid = int(r.id)
        partite = per_g.get(rid) or set()
        if not partite:
            continue                       # i gusci non sono affar suo
        nome = chiave_nome(r.n)
        candidati = id_per_nome.get(nome, set())
        if len(candidati) != 1:
            fuori.append(f"{nome}: {len(candidati)} player_id su Understat, non si sceglie")
            continue
        pid = int(next(iter(candidati)))
        if quanti_per_nome.get(nome, 0) > 1:
            fuori.append(f"{nome}: {quanti_per_nome[nome]} record con questo nome, "
                         f"prima va unito")
            continue
        if pid in gia_presi:
            fuori.append(f"{nome}: il player_id {pid} e' gia' di un altro record")
            continue
        estranee = partite - set(per_id.get(pid, {}))
        if estranee:
            fuori.append(f"{nome}: {len(estranee)} partite che Understat non "
                         f"attribuisce a {pid}, non e' lui")
            continue
        piano.append((rid, pid, nome, len(partite)))
    return piano, fuori


def main() -> None:
    esegui = "--esegui" in sys.argv
    us = carica_understat()
    if not us[0]:
        print("cache Understat vuota: non c'e' niente con cui dimostrare "
              "un'identita', quindi non si scrive niente.")
        return

    eng = create_engine(config.db_url())
    with eng.connect() as cx:
        ana = pd.read_sql(text(
            "SELECT g.id, TRIM(CONCAT_WS(' ',g.nome,g.cognome)) n, g.understat_id "
            "FROM giocatori g"), cx)
        rig = pd.read_sql(text(
            "SELECT gp.giocatore_id gid, c.game_id_understat gu "
            "FROM giocatore_partita gp JOIN calendario c ON c.id = gp.calendario_id "
            "WHERE gp.minuti > 0 AND c.game_id_understat IS NOT NULL"), cx)
    per_g = rig.groupby("gid").gu.apply(lambda s: {int(x) for x in s}).to_dict()

    senza = int(ana.understat_id.isna().sum())
    piano, fuori = piano_allineamento(ana, per_g, us)
    print(f"record senza understat_id : {senza}")
    print(f"da allineare              : {len(piano)}")
    print(f"lasciati stare            : {len(fuori)}")
    for r in fuori[:15]:
        print(f"   {r}")
    if len(fuori) > 15:
        print(f"   ... e altri {len(fuori) - 15}")
    for rid, pid, nome, n in piano[:10]:
        print(f"   id{rid:<8} -> understat {pid:<7} {nome:26} {n:3d} partite")
    if len(piano) > 10:
        print(f"   ... e altri {len(piano) - 10}")

    if not esegui:
        print("\nAnteprima soltanto. Rilancia con --esegui per scrivere.")
        return
    if not piano:
        print("\nNiente da fare.")
        return

    REGISTRO.mkdir(exist_ok=True)
    # col database dentro il nome: le due leghe girano nello stesso minuto
    reg = REGISTRO / f"allinea_understat_id_{config.DB_NAME}_{datetime.now():%Y%m%d_%H%M}.csv"
    pd.DataFrame(piano, columns=["giocatore_id", "understat_id", "nome", "partite"]
                 ).to_csv(reg, index=False, encoding="utf-8")
    with eng.begin() as cx:
        for rid, pid, _nome, _n in piano:
            cx.execute(text("UPDATE giocatori SET understat_id=:u WHERE id=:i "
                            "AND understat_id IS NULL"), {"u": pid, "i": rid})
    print(f"\n{len(piano)} record allineati. Per tornare indietro: {reg}")


if __name__ == "__main__":
    main()
