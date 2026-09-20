"""La pagina Pro esce dal motore, e ogni lega riceve la propria.

Il difetto che questi test bloccano: `dashboard_pro.html` e' stata scritta a
mano dentro `serie-a-index` l'8 agosto 2026 e modificata li' undici volte. Era
l'ultima pagina del sito senza un generatore, quindi esisteva per la Serie A e
basta, e l'unico modo di averla inglese era copiarla e tradurla — due file da
tenere allineati per sempre.

Il rischio del come e' stata portata dentro: il modello e' la pagina
pubblicata con sei segnaposto al posto dei nomi, quindi un segnaposto
dimenticato non rompe niente, si limita a comparire scritto sulla pagina. E un
nome di lega rimasto nel modello non si vede affatto: la pagina inglese si
aprirebbe dicendo "Serie A Scout", che e' il difetto da cui e' nato tutto il
lavoro sulle due leghe.
"""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

MODELLO = ROOT / "modello_pro.html"


def _con_lega(lega: str, monkeypatch):
    monkeypatch.setenv("INDEX_LEGA", lega)
    import config
    importlib.reload(config)
    import pagina_stile
    importlib.reload(pagina_stile)
    import pagina_pro
    importlib.reload(pagina_pro)
    return pagina_pro


@pytest.fixture(autouse=True)
def _ripristina(monkeypatch):
    yield
    monkeypatch.delenv("INDEX_LEGA", raising=False)
    import config
    importlib.reload(config)
    import pagina_stile
    importlib.reload(pagina_stile)


def test_il_modello_non_nomina_nessuna_lega():
    """Il nome della lega sta nei segnaposto, non nel modello.

    Nemmeno nei commenti: il modello viene copiato tale e quale dentro la
    pagina di ogni campionato, quindi una "Serie A" scritta qui finisce nel
    sorgente del sito inglese. Restava in un commento sul CSS della barra —
    non si vedeva a schermo, ma si leggeva aprendo la pagina.
    """
    testo = MODELLO.read_text(encoding="utf-8")
    assert "dashboard_serie_a.html" not in testo
    assert "<title>TPI Pro — {{SITO_NOME}}</title>" in testo
    righe = [(i, r) for i, r in enumerate(testo.splitlines(), 1)
             if any(n in r for n in ("Serie A", "Premier League", "La Liga",
                                     "Bundesliga", "Ligue 1"))]
    assert not righe, f"nome di lega nel modello: {righe}"


@pytest.mark.parametrize("lega,marchio,classifica", [
    ("ITA-Serie A", "Serie A Scout", "dashboard_serie_a.html"),
    ("ENG-Premier League", "Premier League Index", "dashboard_premier_league.html"),
])
def test_ogni_lega_riceve_i_propri_nomi(lega, marchio, classifica, monkeypatch):
    html = _con_lega(lega, monkeypatch).genera()
    assert "{{" not in html, "segnaposto non riempito: finirebbe scritto sulla pagina"
    assert marchio in html
    assert classifica in html


def test_la_premier_non_ha_il_link_al_caso_di_mercato(monkeypatch):
    """La pagina che non esiste non si nomina: sarebbe un link morto in cima."""
    html = _con_lega("ENG-Premier League", monkeypatch).genera()
    assert "caso-mercato.html" not in html
    assert "dashboard_serie_a.html" not in html
    assert 'lang="en"' in html


def test_la_serie_a_ha_il_caso_di_mercato(monkeypatch):
    html = _con_lega("ITA-Serie A", monkeypatch).genera()
    assert "caso-mercato.html" in html
    assert 'lang="it"' in html


def test_il_testo_a_schermo_segue_la_lingua_del_sito(monkeypatch):
    """Sulla Premier la nav si legge in inglese anche senza JavaScript.

    Il testo fra i tag e' la terza copia di ogni etichetta, dopo i due
    attributi: e' quella che si vede nell'istante prima che i18n.js parta, e
    quella che leggono i motori di ricerca.
    """
    html = _con_lega("ENG-Premier League", monkeypatch).genera()
    assert 'data-en="Ranking">Ranking</a>' in html
    assert 'data-en="Ranking">Classifica</a>' not in html


def test_il_repo_di_uscita_lo_decide_config(monkeypatch):
    """Stessa regola degli altri moduli che pubblicano."""
    testo = (ROOT / "pagina_pro.py").read_text(encoding="utf-8")
    righe = [r for r in testo.splitlines()
             if r.strip().startswith("DEMO_DIR") and "=" in r]
    assert righe, "DEMO_DIR non trovata in pagina_pro.py"
    for r in righe:
        assert "cartella_pubblicazione" in r, f"repo scritto a mano -> {r.strip()}"
