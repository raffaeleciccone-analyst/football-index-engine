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


def test_la_copia_si_riconosce_su_tutta_la_riga_non_solo_sui_minuti():
    """Due riserve entrate allo stesso minuto avrebbero minuti uguali senza
    essere la stessa persona: da sole non provano niente."""
    for campo in ("minuti", "goal", "assist", "tiri"):
        assert "p2.%s = p1.%s" % (campo, campo) in SORGENTE, (
            "il confronto non guarda %s: e' troppo debole per cancellare" % campo)


def test_si_cancella_solo_chi_e_copia_al_cento_per_cento():
    """Se anche una sola riga e' sua e di nessun altro, non e' una copia."""
    assert "righe_copia = righe_totali" in SORGENTE


def test_di_default_non_scrive():
    assert '"--esegui" in sys.argv' in SORGENTE
    assert "Anteprima soltanto" in SORGENTE


def test_gli_infortuni_seguono_la_persona():
    """Un infortunio appartiene alla persona, non al record che si cancella."""
    assert "UPDATE t_infortuni SET giocatore_id" in SORGENTE
    i_sposta = SORGENTE.index("UPDATE t_infortuni SET giocatore_id")
    i_cancella = SORGENTE.index("DELETE FROM giocatore_partita")
    assert i_sposta < i_cancella, "gli infortuni vanno spostati prima di cancellare"
