"""Controlla che l'anagrafica sia sana, su tutti e due i database. Non scrive niente.

PERCHE' ESISTE (24/09/2026)
---------------------------
Fra l'8 e il 23 settembre la stessa classe di difetto e' tornata tre volte, in
tre forme: carriere spezzate in due record, gusci vuoti che fermavano `parte4`
con un 1062, righe della stessa partita scritte su due record della stessa
persona. Ogni volta lo si e' scoperto a valle — un giro fermo, un nome
pubblicato due volte — e ogni volta con query scritte al momento.

Questo le mette in fila e le rende ripetibili. Si lancia dopo un'ingestione
(la prima vera prova delle correzioni del 23/9 e' la giornata 6) e risponde in
pochi secondi se l'anagrafica e' rimasta intera.

SENZA LA CACHE DI UNDERSTAT, APPOSTA
------------------------------------
Gli script di riparazione la pretendono, e la cache si assottiglia da sola: il
23/9 era tornata alla sola stagione in corso e ha bloccato tutto per mezz'ora.
Un controllo che non parte quando serve non controlla niente. Qui il metro e'
`understat_id`: l'indice unico garantisce che due record con due id diversi
sono due persone, quindi due omonimi con l'id sono omonimi veri, e il sospetto
cade solo dove l'id manca. E' lo stesso buco da cui passano i trasferimenti
(NULL non collide con niente), quindi e' proprio li' che si guarda.

I CINQUE CONTROLLI
-----------------
  1. carriere spezzate — due o piu' record con lo stesso nome e con partite,
     almeno uno senza `understat_id`;
  2. righe doppie — la stessa partita giocata da due record con lo stesso nome:
     la stessa persona contata due volte (o due omonimi nella stessa partita,
     che va guardato a mano comunque);
  3. gusci — un record senza nessuna partita accanto a un omonimo che ne ha:
     e' la forma che l'8/9 ha fermato `parte4`;
  4. id mancanti — record con partite nella stagione in corso e
     `understat_id` NULL: al prossimo trasferimento si spezzano;
  5. copie — un record le cui righe sono TUTTE uguali a quelle di un altro,
     anche con un nome diverso. I primi quattro raggruppano per nome, e il
     24/9 e' uscito il caso che il nome non vede: "Pervis Estupiñán"
     dall'anagrafica e "Estupiñán" da Understat, stesse 19 partite, pubblicato
     due volte nella 2025-26. La regola e' quella di
     `ripara_anagrafica_duplicati.py`, che e' anche la cura.

Gli omonimi veri (tutti con l'id, tutti diversi) si contano ma non sono un
difetto.

USO
    python controlla_anagrafica.py                  # entrambe le leghe
    python controlla_anagrafica.py --lega premier   # una sola

Esce con 1 se trova qualcosa, 0 se e' tutto pulito.
"""
from __future__ import annotations

import argparse
import sys
import warnings
from dataclasses import dataclass, field

warnings.filterwarnings("ignore")
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

import config
from ripara_anagrafica_duplicati import CAMPI, copie_complete
from unisci_record_doppioni import chiave_nome

LEGHE = {"premier": "ENG-Premier League", "serie-a": "ITA-Serie A"}


@dataclass
class Esito:
    spezzate: list[str] = field(default_factory=list)
    righe_doppie: list[str] = field(default_factory=list)
    gusci: list[str] = field(default_factory=list)
    id_mancanti: list[str] = field(default_factory=list)
    copie: list[str] = field(default_factory=list)
    omonimi_veri: int = 0

    @property
    def pulito(self) -> bool:
        return not (self.spezzate or self.righe_doppie or self.gusci or self.id_mancanti
                    or self.copie)


def _senza_id(v) -> bool:
    return v is None or pd.isna(v)


def controlla(ana: pd.DataFrame, righe: pd.DataFrame, stagione: str) -> Esito:
    """I quattro controlli, sui dati gia' letti.

    `ana`:   id, n (nome), understat_id, squadra
    `righe`: gid, cid, season e i CAMPI misurati — una riga per giocatore e partita
    """
    esito = Esito()
    ana = ana.assign(chiave=ana.n.map(chiave_nome))
    giocate = righe[righe.minuti > 0]
    con_partite = set(giocate.gid.astype(int))
    in_corso = set(giocate[giocate.season == stagione].gid.astype(int))
    idx = ana.set_index("id")

    def chi(gid: int) -> str:
        r = idx.loc[gid]
        uid = "id NULL" if _senza_id(r.understat_id) else f"us {int(r.understat_id)}"
        return f"id{gid} {r.squadra or '?'} ({uid})"

    for chiave, gruppo in ana.groupby("chiave"):
        ids = [int(i) for i in gruppo.id]
        giocano = [i for i in ids if i in con_partite]
        vuoti = [i for i in ids if i not in con_partite]
        if len(giocano) >= 2:
            if any(_senza_id(idx.loc[i].understat_id) for i in giocano):
                esito.spezzate.append(
                    f"{chiave}: " + ", ".join(chi(i) for i in giocano))
            else:
                esito.omonimi_veri += 1
        if giocano and vuoti:
            esito.gusci.append(
                f"{chiave}: vuoti " + ", ".join(chi(i) for i in vuoti)
                + " accanto a " + ", ".join(chi(i) for i in giocano))

    # La stessa partita su due record con lo stesso nome.
    g = giocate.merge(ana[["id", "chiave"]], left_on="gid", right_on="id")
    doppie = g.groupby(["cid", "chiave"]).gid.nunique()
    for (cid, chiave), n in doppie[doppie > 1].items():
        esito.righe_doppie.append(f"{chiave}: partita {cid} su {n} record")

    for gid in sorted(in_corso):
        if _senza_id(idx.loc[gid].understat_id):
            esito.id_mancanti.append(f"{idx.loc[gid].n}: {chi(gid)}")

    copie = copie_complete(righe, dict(zip(ana.id.astype(int), ana.n)))
    for r in copie.itertuples(index=False):
        esito.copie.append(f"{idx.loc[r.copia].n} {chi(int(r.copia))}: {r.righe_copia} righe "
                           f"tutte uguali a {idx.loc[r.resta].n} {chi(int(r.resta))}")
    return esito


def leggi(database: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    url = make_url(config.db_url()).set(database=database)
    eng = create_engine(url)
    with eng.connect() as cx:
        ana = pd.read_sql(text(
            "SELECT g.id, TRIM(CONCAT_WS(' ', g.nome, g.cognome)) n, g.understat_id, "
            "sq.nome squadra FROM giocatori g LEFT JOIN squadre sq ON sq.id = g.squadra_id"), cx)
        righe = pd.read_sql(text(
            "SELECT giocatore_id gid, calendario_id cid, season, " + ", ".join(CAMPI)
            + " FROM giocatore_partita"), cx)
    eng.dispose()
    return ana, righe


def stampa(nome: str, database: str, esito: Esito, stagione: str) -> None:
    print(f"\n=== {nome} ({database}, stagione {stagione})")
    for titolo, voci in (("carriere spezzate", esito.spezzate),
                         ("righe doppie", esito.righe_doppie),
                         ("gusci", esito.gusci),
                         ("id mancanti nella stagione in corso", esito.id_mancanti),
                         ("copie (anche con un nome diverso)", esito.copie)):
        print(f"  {titolo:38}: {len(voci)}")
        for v in voci[:15]:
            print(f"      {v}")
        if len(voci) > 15:
            print(f"      ... e altri {len(voci) - 15}")
    print(f"  {'omonimi veri (id diversi, non difetto)':38}: {esito.omonimi_veri}")
    print("  -> pulito" if esito.pulito else "  -> DA GUARDARE")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lega", choices=sorted(LEGHE), help="una lega sola")
    ap.add_argument("--stagione", default=config.SEASON_CORRENTE)
    args = ap.parse_args()

    tutto_pulito = True
    for nome in ([args.lega] if args.lega else sorted(LEGHE)):
        database = config.DATABASE_LEGA[LEGHE[nome]]
        ana, righe = leggi(database)
        esito = controlla(ana, righe, args.stagione)
        stampa(nome, database, esito, args.stagione)
        tutto_pulito &= esito.pulito
    return 0 if tutto_pulito else 1


if __name__ == "__main__":
    sys.exit(main())
