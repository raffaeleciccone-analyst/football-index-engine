"""Riunisce i record di `giocatori` che descrivono la stessa persona.

COSA SUCCEDE (20/08/2026)
------------------------
Ottantuno giocatori esistono due volte in anagrafica: una volta col cognome
raddoppiato ("Nikola Krstovic Krstovic", id sotto 5000) e una volta col nome
pulito ("Nikola Krstovic", id sopra il milione). Sono i cambi di maglia:
l'import di una stagione ha creato un record nuovo invece di riconoscere quello
che c'era gia'.

Le partite non si sovrappongono mai — verificato su tutte e 81 le coppie, zero
partite in comune — quindi NON c'e' doppio conteggio: c'e' una carriera tagliata
in due meta', una per club.

COSA ROMPE, E COSA NO
---------------------
Le classifiche di stagione singola sono giuste: dentro una stagione ogni meta'
contiene tutte le partite che servono. E' l'aggregato a sbagliare, perche' li'
le due meta' andrebbero sommate e invece restano separate:

  - nella vista "Due stagioni" 36 giocatori compaiono DUE VOLTE, uno per maglia,
    con due TPI diversi (Krstovic Atalanta 0.79 e Krstovic Lecce 0.49);
  - "Sopra le attese" confronta la stagione con la base storica dello stesso
    id: per questi 81 la base e' mezza, quindi il confronto e' senza senso.

LA REGOLA
---------
Due record si uniscono solo se valgono tutte:

  1. il gruppo di nome ha esattamente due record con righe partita (tre o piu'
     si lasciano stare: vanno guardati a mano);
  2. le partite in comune, se ci sono, devono essere le STESSE RIGHE scritte
     due volte — identiche su ogni campo misurato. Una riga in comune che
     porta numeri diversi non e' un doppione: sono due persone, e si ferma;
  3. il nome non e' ambiguo su Understat (un solo player_id), altrimenti si
     rischia di fondere due persone diverse — cioe' di rifare il bug che
     `ripara_righe_omonimi.py` ha appena finito di togliere;
  4. TEST DI ACCETTAZIONE: nell'unione non deve finire NIENTE di estraneo,
     cioe' nessuna partita che Understat non attribuisca a quel giocatore.

LE RIGHE SCRITTE DUE VOLTE (23/09/2026)
---------------------------------------
La regola 2 nasceva "zero partite in comune", e con quella questo script
rifiutava trentatre' coppie su trentaquattro. A guardarle, le partite in comune
non erano di due persone: erano le STESSE righe, identiche su tutte e sedici le
colonne, scritte una volta sul canonico e una sul record nuovo.

Le fa l'unione stessa. L'8/9 il canonico ha ricevuto le partite fino alla
giornata 3 e NON ha ricevuto l'`understat_id` (quel pezzo e' arrivato il 16/9);
restato invisibile all'upsert, alla giornata 4 si e' visto rinascere accanto un
record nuovo, che da Understat ha ripreso la stagione dall'inizio. Le tre
giornate stanno quindi da tutte e due le parti.

Una riga in comune e' una domanda, non una risposta: se i numeri coincidono e'
la stessa partita contata due volte e se ne tiene una; se differiscono sono due
persone e non si tocca niente. La differenza si misura, non si assume — e' lo
stesso metro di `ripara_anagrafica_duplicati.py`, dove una copia si cancella
solo se e' identica al cento per cento.

Il primo tentativo pretendeva invece che l'unione fosse anche COMPLETA, e cosi'
si rifiutava di unire chi, oltre a essere sdoppiato, aveva pure delle partite
mancanti: dieci coppie restavano separate per un difetto che con lo sdoppiamento
non c'entra. E' lo stesso errore che aveva bloccato Venturino e Luperto nel
primo script — due difetti diversi misurati con un test solo — ripetuto qui.
Qui pero' costava di piu': con le due meta' ancora separate,
`importa_partite_mancanti.py` le avrebbe riempite tutte e due, inventando un
doppio conteggio che prima non esisteva. Va lanciato prima questo, poi quello.

Le righe vengono spostate sul record canonico (quello con l'id piu' basso, che
e' l'anagrafica principale), e il doppione si CANCELLA.

Prima restava in tabella senza partite: "il motore lo ignora da solo". Il motore
si', `parte4` no (16/09/2026). Il doppione porta (nome, club nuovo), che e' la
chiave `uq_nome_squadra` che l'ingestione urta per prima; la UPDATE gli scrive
`understat_id`, che e' gia' del canonico, e il giro si ferma con un 1062. Se il
doppione ha l'`understat_id` e il canonico no, l'id passa al canonico: e' lui la
persona, e senza id al prossimo trasferimento tornerebbe a spezzarsi. Per
tornare indietro, le righe cancellate stanno in `giocatori_cancellati.csv`
accanto alla mappa.

USO
    python unisci_record_doppioni.py            # mostra e basta
    python unisci_record_doppioni.py --esegui   # scrive davvero
"""
from __future__ import annotations

import collections
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import bindparam, create_engine, text

import config
from ripara_righe_omonimi import _nm, carica_understat

# Il nome del database dentro la cartella, e non e' un vezzo: le due leghe si
# uniscono una dopo l'altra, quindi cadono nello stesso minuto e senza questo
# la seconda cancellava la mappa della prima — cioe' proprio il foglio con cui
# si torna indietro. Successo il 23/9/2026.
BACKUP = (Path(r"C:\dev")
          / f"_backup_unione_doppioni_{config.DB_NAME}_{datetime.now():%Y%m%d_%H%M}")


def chiave_nome(nome: str) -> str:
    """Il nome vero, tolto il cognome raddoppiato.

    L'anagrafica difettosa scrive "Lorenzo Colombo Colombo": il primo tentativo
    prendeva i primi due token, che va bene per i nomi di due parole e sbaglia
    su tutti gli altri. "Koni de Winter Winter" diventava "koni de", che su
    Understat non esiste, e quella coppia veniva rifiutata per il motivo
    sbagliato. Meglio togliere la ripetizione in coda e tenere il nome intero.
    """
    t = _nm(nome).split()
    while len(t) >= 2 and t[-1] == t[-2]:
        t.pop()
    return " ".join(t)


CAMPI_RIGA = ("season", "ruolo", "minuti", "goal", "assist", "tiri", "xg", "xa",
              "gialli", "rossi", "npxg", "npg", "xg_chain", "xg_buildup")


def misura_righe(tutte: pd.DataFrame) -> dict[int, dict[int, tuple]]:
    """Ogni riga partita ridotta a cio' che si puo' confrontare.

    Serve a rispondere a una domanda sola: due righe sulla stessa partita sono
    la stessa riga scritta due volte, oppure no? Quindi entrano TUTTI i campi
    misurati, non i soli minuti — la stessa strettezza di
    `ripara_anagrafica_duplicati.py`, dove i soli minuti non bastavano a
    dichiarare una copia.

    I float si arrotondano perche' arrivano da colonne FLOAT: 0.187 e
    0.18700000000000001 sono lo stesso valore misurato, e farli sembrare
    diversi qui vorrebbe dire rifiutare l'unione per un difetto che non c'e'.
    """
    fuori: dict[int, dict[int, tuple]] = collections.defaultdict(dict)
    for r in tutte.itertuples(index=False):
        valori = []
        for campo in CAMPI_RIGA:
            v = getattr(r, campo)
            if v is None or (isinstance(v, float) and pd.isna(v)):
                valori.append(None)
            elif isinstance(v, float):
                valori.append(round(v, 4))
            else:
                valori.append(v)
        fuori[int(r.gid)][int(r.cid)] = tuple(valori)
    return fuori


def confronta_righe(ra: dict[int, tuple], rb: dict[int, tuple]) -> tuple[set, list]:
    """Le partite che i due record hanno in comune, e quelle su cui litigano.

    Una partita in comune e' una domanda: se i due portano gli stessi numeri e'
    la stessa riga scritta due volte, se ne portano di diversi sono due persone.
    """
    collisioni = set(ra) & set(rb)
    return collisioni, sorted(c for c in collisioni if ra[c] != rb[c])


def main() -> None:
    esegui = "--esegui" in sys.argv
    eng = create_engine(config.db_url())
    per_id, per_nome, id_per_nome = carica_understat()
    if not per_id:
        raise SystemExit("cache Understat vuota o assente")

    with eng.connect() as cx:
        ana = pd.read_sql(text(
            "SELECT g.id, TRIM(CONCAT_WS(' ',g.nome,g.cognome)) n, g.squadra_id, "
            "g.understat_id, sq.nome squadra FROM giocatori g "
            "LEFT JOIN squadre sq ON sq.id = g.squadra_id"), cx)
        rig = pd.read_sql(text(
            "SELECT gp.giocatore_id gid, gp.calendario_id cid, c.game_id_understat gu "
            "FROM giocatore_partita gp JOIN calendario c ON c.id = gp.calendario_id "
            "WHERE gp.minuti > 0 AND c.game_id_understat IS NOT NULL"), cx)
        # Tutte le righe, anche quelle da zero minuti, e con dentro i numeri.
        # Servono due letture perche' rispondono a due domande diverse: `rig`
        # dice quali partite il giocatore ha giocato (e i minuti a zero non sono
        # partite giocate), questa dice quali RIGHE esistono — e una riga da
        # zero minuti occupa lo stesso la chiave `uq_gp` (giocatore, partita),
        # quindi spostarla addosso a una gemella farebbe fallire l'unione.
        tutte = pd.read_sql(text(
            "SELECT giocatore_id gid, calendario_id cid, season, ruolo, minuti, "
            "goal, assist, tiri, xg, xa, gialli, rossi, npxg, npg, xg_chain, "
            "xg_buildup FROM giocatore_partita"), cx)

    per_g = rig.groupby("gid").gu.apply(lambda s: set(int(x) for x in s)).to_dict()
    righe = misura_righe(tutte)
    gruppi: dict[str, list] = collections.defaultdict(list)
    for _, r in ana.iterrows():
        if per_g.get(int(r.id)):
            gruppi[chiave_nome(r.n)].append(r)

    piano: list[tuple[int, int, str]] = []
    doppie: dict[int, list[int]] = {}
    saltati: list[str] = []
    resta: list[str] = []
    for chiave, recs in sorted(gruppi.items()):
        if len(recs) < 2:
            continue
        if len(recs) > 2:
            saltati.append(f"{chiave}: {len(recs)} record, da guardare a mano")
            continue
        if len(id_per_nome.get(chiave, ())) > 1:
            saltati.append(f"{chiave}: nome ambiguo su Understat, non si fonde")
            continue
        a, b = sorted(recs, key=lambda r: int(r.id))       # canonico = id piu' basso
        ga, gb = per_g[int(a.id)], per_g[int(b.id)]
        # Le righe che i due record hanno sulla stessa partita. Si guardano per
        # calendario_id e non per game_id_understat, perche' e' quella la chiave
        # che il database fa rispettare: due righe sulla stessa partita non
        # possono stare sullo stesso giocatore, e l'unione le sposterebbe una
        # sull'altra.
        ra, rb = righe.get(int(a.id), {}), righe.get(int(b.id), {})
        collisioni, diverse = confronta_righe(ra, rb)
        if diverse:
            saltati.append(f"{chiave}: {len(diverse)} partite in comune con numeri "
                           f"diversi, non e' una carriera spezzata")
            continue
        us = set(per_nome.get(chiave, {}))
        unione = ga | gb
        if not us:
            saltati.append(f"{chiave}: nessun riscontro Understat")
            continue
        # Il test giusto e' che l'unione non contenga NIENTE DI ESTRANEO.
        # Pretendere anche che sia completa rifiutava di unire chi in piu' ha
        # delle partite mancanti — e quelle sono l'altro difetto, non un motivo
        # per lasciare una persona spezzata in due. Era la stessa confusione fra
        # i due difetti che aveva bloccato Venturino e Luperto nel primo script,
        # rifatta qui; e qui costava piu' cara, perche' con le meta' separate
        # importa_partite_mancanti.py le riempie tutt'e due e inventa un doppio
        # conteggio che prima non c'era.
        estranee = unione - us
        if estranee:
            saltati.append(f"{chiave}: {len(estranee)} partite che Understat non "
                           f"gli attribuisce, non si fonde")
            continue
        if unione != us:
            resta.append(f"{chiave}: unito, ma restano {len(us - unione)} partite "
                         f"da importare a parte")
        if collisioni:
            doppie[int(b.id)] = sorted(collisioni)
        piano.append((int(b.id), int(a.id), chiave))

    print(f"coppie esaminate : {sum(1 for v in gruppi.values() if len(v) > 1)}")
    print(f"da unire         : {len(piano)}")
    if doppie:
        print(f"di cui con righe scritte due volte: {len(doppie)} coppie, "
              f"{sum(len(v) for v in doppie.values())} righe da cancellare")
    print(f"lasciate stare   : {len(saltati)}")
    for r in saltati[:20]:
        print(f"   {r}")
    if len(saltati) > 20:
        print(f"   ... e altre {len(saltati) - 20}")
    if resta:
        print("uniti, ma con partite ancora da importare:")
        for r in resta:
            print(f"   {r}")

    if piano:
        idx = ana.set_index("id")
        print(f"\nprime dieci unioni (le righe passano da -> a):")
        for da, a, chiave in piano[:10]:
            dd = len(doppie.get(da, ()))
            print(f"   {chiave:26} id{da} '{idx.loc[da].squadra}' {len(per_g[da]):3d}p"
                  f"  ->  id{a} '{idx.loc[a].squadra}' {len(per_g[a]):3d}p"
                  f"   = {len(per_g[da] | per_g[a]):3d}p"
                  + (f"   ({dd} righe doppie cancellate)" if dd else ""))

    if not esegui:
        print("\nAnteprima soltanto. Rilancia con --esegui per scrivere.")
        return
    if not piano:
        print("\nNiente da fare.")
        return

    BACKUP.mkdir(parents=True, exist_ok=True)
    mappa = pd.DataFrame(piano, columns=["da_giocatore_id", "a_giocatore_id", "nome"])
    mappa.to_csv(BACKUP / "mappa_unioni.csv", index=False, encoding="utf-8")
    rig[rig.gid.isin(mappa.da_giocatore_id)].to_csv(
        BACKUP / "righe_spostate.csv", index=False, encoding="utf-8")

    ana[ana.id.isin(mappa.da_giocatore_id)].to_csv(
        BACKUP / "giocatori_cancellati.csv", index=False, encoding="utf-8")

    if doppie:
        coppie = [(g, c) for g, cs in doppie.items() for c in cs]
        tutte.merge(pd.DataFrame(coppie, columns=["gid", "cid"]),
                    on=["gid", "cid"]).to_csv(
            BACKUP / "righe_doppie_cancellate.csv", index=False, encoding="utf-8")

    with eng.begin() as cx:
        righe_tolte = 0
        for da, a, chiave in piano:
            # Prima le righe che il canonico ha gia'. Spostarle significherebbe
            # portargli addosso una seconda riga sulla stessa partita: la chiave
            # `uq_gp` la rifiuta, e se non ci fosse sarebbe un doppio conteggio.
            # Sono identiche a quelle che restano, quindi non si perde niente —
            # e il confronto che lo dimostra e' la condizione per arrivare qui.
            cid = doppie.get(da)
            if cid:
                cx.execute(text("DELETE FROM giocatore_partita WHERE giocatore_id=:d "
                                "AND calendario_id IN :c").bindparams(
                                    bindparam("c", expanding=True)),
                           {"d": da, "c": cid})
                righe_tolte += len(cid)
            cx.execute(text("UPDATE giocatore_partita SET giocatore_id=:a WHERE giocatore_id=:d"),
                       {"a": a, "d": da})
            us = cx.execute(text("SELECT understat_id FROM giocatori WHERE id=:d"),
                            {"d": da}).scalar()
            if us is not None:
                cx.execute(text("UPDATE giocatori SET understat_id=NULL WHERE id=:d"), {"d": da})
                cx.execute(text("UPDATE giocatori SET understat_id=COALESCE(understat_id, :u) "
                                "WHERE id=:a"), {"u": us, "a": a})
            cx.execute(text("DELETE FROM giocatori WHERE id=:d"), {"d": da})
        print(f"\n{len(piano)} record uniti, doppioni cancellati"
              + (f", {righe_tolte} righe scritte due volte tolte." if righe_tolte else "."))
    print(f"backup della mappa -> {BACKUP}")
    print("Ora rigenera i payload: l'aggregato a due stagioni cambia.")


if __name__ == "__main__":
    main()
