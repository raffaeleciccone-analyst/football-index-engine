"""Chi scrive una riga deve dire di quale stagione e'.

IL DIFETTO, due volte
---------------------
'squadra_calendario' aveva tutte e 1520 le righe a '2025-26', comprese le 760
della 2024-25: l'INSERT di parte4 non nominava la colonna, e la colonna aveva
'DEFAULT '2025-26''. Tolto il default li' il 27 agosto 2026, restava su altre
tre tabelle — 'calendario', 'giocatore_partita', 't_squadra_game_log' — e
'set_up_tpi_pro/aggiorna.py' continuava a ometterla su due. Finche' l'annata in
corso era la 2025-26 scriveva l'anno giusto per caso.

Un DEFAULT con dentro un anno non e' un valore di comodo: e' una risposta
sbagliata pronta per chi non fa la domanda. Adesso le quattro colonne sono NOT
NULL e senza default, quindi il database rifiuta una INSERT smemorata invece di
inventarsi l'annata — ma il rifiuto arriva a runtime, con il giro gia' partito.
Questo test lo anticipa leggendo le INSERT: e' il sorgente l'oggetto della
prova, non un indizio del sorgente.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Le tabelle la cui colonna 'season' e' NOT NULL e senza DEFAULT.
CON_STAGIONE = ("calendario", "giocatore_partita", "t_squadra_game_log",
                "squadra_calendario")


def _inserimenti():
    """(file, tabella, elenco delle colonne) per ogni INSERT del progetto."""
    salta = {"backup", ".venv", "__pycache__", "snapshots", "_archivio"}
    for f in sorted(ROOT.rglob("*.py")):
        if salta & set(f.relative_to(ROOT).parts):
            continue
        testo = f.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"INSERT\s+INTO\s+`?(\w+)`?(.*?)VALUES",
                             testo, re.S | re.I):
            tabella = m.group(1)
            if tabella in CON_STAGIONE:
                yield f.relative_to(ROOT).as_posix(), tabella, m.group(2)


def test_ci_sono_insert_da_controllare():
    """Se il ritrovamento smette di funzionare, il test smette di provare
    qualcosa — e lo farebbe passando, che e' il modo peggiore.

    Nella copia pubblica del motore lo strato di ingestione non c'e', quindi
    le INSERT da controllare sono poche per davvero: la' il test si salta
    dicendolo, invece di fallire per un file che manca di proposito.
    """
    if not (ROOT / "parte4_aggiorna.py").is_file():
        pytest.skip("senza lo strato di ingestione le INSERT da controllare "
                    "sono quelle poche che restano")
    trovati = list(_inserimenti())
    assert len(trovati) >= 4, f"trovate solo {len(trovati)} INSERT: la ricerca non funziona"


@pytest.mark.parametrize("dove", list(_inserimenti()),
                         ids=lambda d: f"{d[0]}:{d[1]}" if isinstance(d, tuple) else str(d))
def test_ogni_insert_nomina_la_stagione(dove):
    f, tabella, colonne = dove
    assert re.search(r"\bseason\b", colonne), (
        f"{f}: l'INSERT su '{tabella}' non nomina 'season'. La colonna e' NOT NULL "
        f"e non ha piu' un default, quindi il giro si ferma li' — e prima che il "
        f"default fosse tolto scriveva 2025-26 su qualunque annata, in silenzio.")
