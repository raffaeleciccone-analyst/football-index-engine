"""I file di `dati_esterni/` portano la lega e la stagione nel nome.

Il difetto che questi test bloccano: `contratti_2025-26.json` e
`xg_concessi_SA_2025-26.json` avevano la stagione battuta a mano, e il nome era
scritto due volte — una in chi produce il file, una in chi lo legge. Il guasto
non e' il file che manca, e' il file che resta: il 20/9/2026 il sito pubblicava
la stagione 2026-27 con i contratti del 2025-26 addosso a 85 giocatori su 100,
perche' il nome cercato era ancora quello e il file era ancora li'.

Un file assente lo raccoglie il ripiego, che e' dichiarato e si vede nei log.
Un file vecchio no: passa per buono.
"""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PRODUTTORI = {
    "estrai_contratti_transfermarkt.py": "contratti",
    "estrai_xg_concessi_hexi.py": "xg_concessi",
}


def _con(lega: str, stagione: str, monkeypatch):
    monkeypatch.setenv("INDEX_LEGA", lega)
    monkeypatch.setenv("INDEX_SEASON", stagione)
    import config
    importlib.reload(config)
    return config


@pytest.fixture(autouse=True)
def _ripristina(monkeypatch):
    yield
    monkeypatch.delenv("INDEX_LEGA", raising=False)
    monkeypatch.delenv("INDEX_SEASON", raising=False)
    import config
    importlib.reload(config)


@pytest.mark.parametrize("lega,stagione,atteso", [
    ("ITA-Serie A", "2026-27", "contratti_serie_a_2026-27.json"),
    ("ITA-Serie A", "2025-26", "contratti_serie_a_2025-26.json"),
    ("ENG-Premier League", "2026-27", "contratti_premier_league_2026-27.json"),
])
def test_il_nome_porta_lega_e_stagione(lega, stagione, atteso, monkeypatch):
    cfg = _con(lega, stagione, monkeypatch)
    assert cfg.file_esterno("contratti") == atteso


def test_due_leghe_non_si_contendono_lo_stesso_file(monkeypatch):
    ita = _con("ITA-Serie A", "2026-27", monkeypatch).file_esterno("xg_concessi")
    eng = _con("ENG-Premier League", "2026-27", monkeypatch).file_esterno("xg_concessi")
    assert ita != eng


def test_due_stagioni_non_si_contendono_lo_stesso_file(monkeypatch):
    ora = _con("ITA-Serie A", "2026-27", monkeypatch).file_esterno("contratti")
    prima = _con("ITA-Serie A", "2025-26", monkeypatch).file_esterno("contratti")
    assert ora != prima


def test_chi_legge_non_si_scrive_il_nome_a_mano():
    """`parte1_analisi` compone i due percorsi da config, non da una costante."""
    testo = (ROOT / "parte1_analisi.py").read_text(encoding="utf-8")
    for nome in ("CONTRATTI", "DIFESE_ESTERNE"):
        righe = [r for r in testo.splitlines() if r.startswith(f"{nome} =")]
        assert righe, f"{nome} non trovata"
        blocco = testo.split(f"{nome} =", 1)[1][:200]
        assert "file_esterno" in blocco, f"{nome}: nome di file scritto a mano"


@pytest.mark.parametrize("modulo,prefisso", PRODUTTORI.items())
def test_chi_scrive_usa_la_stessa_regola(modulo, prefisso):
    """Produttore e lettore devono comporre il nome nello stesso modo.

    Se divergono non si rompe niente: il file viene scritto con un nome che
    nessuno legge, e il motore usa il ripiego per sempre senza lamentarsi.

    I due produttori sono scraper, quindi nella copia pubblica del motore non
    ci sono: li' il controllo si salta invece di fallire, e lo dice.
    """
    f = ROOT / modulo
    if not f.is_file():
        pytest.skip(f"{modulo} non presente in questa copia del motore")
    testo = f.read_text(encoding="utf-8")
    assert f'file_esterno("{prefisso}")' in testo, (
        f"{modulo}: uscita scritta a mano")


def test_nessun_file_vecchio_col_nome_di_prima():
    """I due nomi senza lega non devono tornare: nessuno li leggerebbe piu'."""
    vecchi = [p.name for p in (ROOT / "dati_esterni").glob("*.json")
              if p.name.startswith(("contratti_2", "xg_concessi_SA"))]
    assert not vecchi, f"file col nome vecchio: {vecchi}"
