"""I duplicati di anagrafica si trovano dai dati, non da un elenco di nomi.

Due record con lo stesso nome sono due cose opposte, con cure opposte:

  * **carriera spezzata** — le partite non si sovrappongono mai, sono due meta'.
    Si UNISCONO (`unisci_record_doppioni.py`).
  * **copia** — le righe del secondo sono le stesse del primo. Si CANCELLA.
    Unirla raddoppierebbe i minuti di quelle giornate.

`ripara_anagrafica_duplicati.py` fa il secondo caso. Conosceva Estupinan e Soule,
trovati a mano ad agosto 2026: un elenco di nomi che invecchia, ed era invecchiato
— a settembre i duplicati erano Morten Thorsby e Tommaso Baldanzi, e Thorsby era
pubblicato due volte nella classifica 2025-26, "Genoa" 128esimo e "Cremonese"
143esimo, come se fossero due persone.

E' lo stesso difetto dei `ruolo_override`: un nome scritto a mano oggi e' una
misura, fra un anno e' una trappola.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SORGENTE = (ROOT / "ripara_anagrafica_duplicati.py").read_text(encoding="utf-8")


def _codice() -> str:
    """Il sorgente senza il docstring: li' i nomi sono spiegazione, non dati."""
    fine = SORGENTE.index('"""', SORGENTE.index('"""') + 3) + 3
    return SORGENTE[fine:]


def test_nessun_nome_di_giocatore_nel_codice():
    for nome in ("Estupinan", "Estupiñán", "Soule", "Thorsby", "Baldanzi", "Pervis"):
        assert nome not in _codice(), (
            "%r e' scritto nel codice: l'elenco a mano e' il difetto, non la cura" % nome)


def test_nessun_id_di_record_nel_codice():
    """Erano `MAP = {10: 3915, 429: 4345}`. Gli id valgono su un database solo."""
    codice = _codice()
    assert "MAP = {" not in codice
    for numero in re.findall(r"\b\d{3,7}\b", codice):
        assert numero in ("2026", "8", "1062"), (
            "%s sembra l'id di un record scritto a mano" % numero)


# Da qui i test provano il comportamento su righe costruite, non il sorgente.
# Le due prove che c'erano prima cercavano stringhe SQL nel file: sono passate
# per tutto settembre mentre Estupinan restava pubblicato due volte.

import pandas as pd                                        # noqa: E402

from ripara_anagrafica_duplicati import copie_complete     # noqa: E402

CAMPI = ["gid", "cid", "minuti", "goal", "assist", "tiri", "xg", "xa",
         "xg_chain", "xg_buildup"]


def _righe(*r):
    return pd.DataFrame(r, columns=CAMPI)


def _partita(gid, cid, minuti=90, goal=0, xg=0.0):
    return (gid, cid, minuti, goal, 0, 1, xg, 0.0, xg, 0.0)


def test_copia_con_un_nome_diverso_si_trova():
    """Il caso del 24/9: "Pervis Estupiñán" dall'anagrafica, "Estupiñán" da
    Understat. Il record vecchio e' la copia; il nuovo ha anche la 2026-27."""
    stagione = [_partita(1, c, xg=0.1 * c) for c in (1, 2, 3, 4)]
    nuovo = [_partita(2, c, xg=0.1 * c) for c in (1, 2, 3, 4)] + [_partita(2, 9)]
    esito = copie_complete(_righe(*stagione, *nuovo),
                           {1: "Pervis Estupiñán", 2: "Estupiñán"})
    assert list(esito.copia) == [1]
    assert list(esito.resta) == [2], "resta chi ha piu' righe, non l'id piu' basso"


def test_copia_a_vicenda_resta_il_piu_antico():
    """Thorsby, 8/9: tredici righe su tredici da tutte e due le parti."""
    a = [_partita(5, c, xg=0.2) for c in (1, 2, 3)]
    b = [_partita(7, c, xg=0.2) for c in (1, 2, 3)]
    esito = copie_complete(_righe(*a, *b), {5: "Morten Thorsby", 7: "Morten Thorsby"})
    assert list(zip(esito.copia, esito.resta)) == [(7, 5)]


def test_compagni_di_squadra_con_righe_uguali_non_sono_copie():
    """Portiere e difensore a 90' senza un tiro: righe identiche, due persone.
    Sui database veri sono migliaia di coppie."""
    portiere = [_partita(1, c) for c in (1, 2, 3)]
    difensore = [_partita(2, c) for c in (1, 2, 3)] + [_partita(2, 4, goal=1)]
    esito = copie_complete(_righe(*portiere, *difensore),
                           {1: "Jordan Pickford", 2: "James Tarkowski"})
    assert esito.empty


def test_righe_uguali_a_compagni_diversi_non_sono_una_copia():
    """Tre righe uguali a tre record diversi non sono la copia di nessuno."""
    a = [_partita(1, c) for c in (1, 2, 3)]
    altri = [_partita(10 + c, c) for c in (1, 2, 3)]
    nomi = {1: "Danilo", 11: "Danilo", 12: "Danilo", 13: "Danilo"}
    assert copie_complete(_righe(*a, *altri), nomi).empty


def test_una_riga_sua_basta_a_non_essere_una_copia():
    a = [_partita(1, c, xg=0.3) for c in (1, 2, 3)] + [_partita(1, 4, goal=1)]
    b = [_partita(2, c, xg=0.3) for c in (1, 2, 3)]
    esito = copie_complete(_righe(*a, *b), {1: "Morten Thorsby", 2: "Morten Thorsby"})
    assert list(esito.copia) == [2], "b e' copia di a, a non e' copia di b"


def test_una_differenza_negli_xg_basta_a_non_essere_copia():
    """Minuti, gol e tiri uguali non bastano: prima si guardavano solo quelli."""
    a = [_partita(1, c, xg=0.3) for c in (1, 2, 3)]
    b = [_partita(2, c, xg=0.3) for c in (1, 2)] + [_partita(2, 3, xg=0.5)]
    assert copie_complete(_righe(*a, *b), {1: "Leo Ostigard", 2: "Leo Ostigard"}).empty


def test_sotto_tre_partite_giocate_non_si_decide():
    a = [_partita(1, c) for c in (1, 2)]
    b = [_partita(2, c) for c in (1, 2, 3)]
    assert copie_complete(_righe(*a, *b), {1: "Estupiñán", 2: "Estupiñán"}).empty


def test_di_default_non_scrive():
    assert '"--esegui" in sys.argv' in SORGENTE
    assert "Anteprima soltanto" in SORGENTE


def test_gli_infortuni_seguono_la_persona():
    """Un infortunio appartiene alla persona, non al record che si cancella."""
    assert "UPDATE t_infortuni SET giocatore_id" in SORGENTE
    i_sposta = SORGENTE.index("UPDATE t_infortuni SET giocatore_id")
    i_cancella = SORGENTE.index("DELETE FROM giocatore_partita")
    assert i_sposta < i_cancella, "gli infortuni vanno spostati prima di cancellare"
