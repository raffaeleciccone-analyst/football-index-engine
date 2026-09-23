"""I percorsi di heXI seguono la lega e la stagione, e l'assenza non e' un guasto.

Due difetti, uno dentro l'altro.

Il primo: i tre script che leggono heXI avevano il percorso scritto a mano, con
`SA` e l'annata dentro. L'uscita invece seguiva gia' la lega — quindi con la
Premier selezionata `estrai_contratti_transfermarkt.py` avrebbe scritto
`contratti_premier_league_2026-27.json` leggendo le venti squadre italiane. E'
la forma piu' insidiosa del difetto di oggi, perche' il file *sembra* giusto:
porta il nome della lega che ci si aspetta.

Il secondo: il feed Sportmonks di una stagione heXI lo pubblica quando lo
pubblica, e fino ad allora lo script moriva con un errore. Un passo che muore
ferma la sequenza, quindi il file non poteva stare in `pubblica.py` e restava
da lanciare a mano una volta l'anno — che e' il modo in cui il file del 2025-26
e' rimasto l'unico mai prodotto.
"""
import importlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

LETTORI_HEXI = ["anagrafica_da_hexi.py", "estrai_contratti_transfermarkt.py",
                "estrai_xg_concessi_hexi.py"]


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


@pytest.mark.parametrize("lega,sigla", [
    ("ITA-Serie A", "SA"),
    ("ENG-Premier League", "PL"),
])
def test_ogni_lega_legge_il_proprio_file(lega, sigla, monkeypatch):
    cfg = _con(lega, "2026-27", monkeypatch)
    assert cfg.hexi_rosa().name == f"{sigla}_2026-2027.json"
    assert cfg.hexi_lineups().name == f"lineups_{sigla}_2026_2027.json"


def test_le_due_leghe_non_leggono_lo_stesso_file(monkeypatch):
    ita = _con("ITA-Serie A", "2026-27", monkeypatch).hexi_rosa()
    eng = _con("ENG-Premier League", "2026-27", monkeypatch).hexi_rosa()
    assert ita != eng, "con lo stesso file una lega leggerebbe le squadre dell'altra"


def test_la_stagione_entra_nel_percorso(monkeypatch):
    ora = _con("ITA-Serie A", "2026-27", monkeypatch).hexi_rosa()
    prima = _con("ITA-Serie A", "2025-26", monkeypatch).hexi_rosa()
    assert ora != prima


def test_heXI_scrive_gli_anni_per_intero(monkeypatch):
    """La rosa usa il trattino, il feed l'underscore: due forme, dichiarate."""
    cfg = _con("ITA-Serie A", "2026-27", monkeypatch)
    assert cfg.stagione_hexi() == "2026-2027"
    assert cfg.stagione_hexi(sep="_") == "2026_2027"


@pytest.mark.parametrize("modulo", LETTORI_HEXI)
def test_nessuno_si_scrive_il_percorso_a_mano(modulo):
    """Il percorso lo chiede a config: se torna a essere una costante, qui si vede."""
    f = ROOT / modulo
    if not f.is_file():
        pytest.skip(f"{modulo} non presente in questa copia del motore")
    testo = f.read_text(encoding="utf-8")
    # Un'annata vera nel percorso, non un segnaposto: la prosa che descrive la
    # forma del nome (`<LEGA>_<stagione>.json`) e' documentazione, non una
    # costante, e non va confusa con quello che si sta bloccando qui.
    concreto = re.compile(r"heXI.*(19|20)\d\d.*\.json|(19|20)\d\d.*heXI.*\.json")
    colpevoli = [r.strip() for r in testo.splitlines() if concreto.search(r)]
    assert not colpevoli, f"{modulo}: percorso di heXI scritto a mano -> {colpevoli}"


def _lancia_estrattore(tmp_path, stagione: str):
    """Lo script, con una cartella heXI finta al posto di quella vera.

    Il test non deve dipendere da dove sta heXI su questa macchina: la prima
    versione lo faceva, e passava qui e falliva in CI, dove `C:\dev\heXI`
    ovviamente non esiste e lo script prendeva — giustamente — il ramo "manca
    la cartella". Una cartella vuota creata al momento isola il caso vero: la
    fonte c'e', il file di quella stagione no.
    """
    script = ROOT / "estrai_xg_concessi_hexi.py"
    if not script.is_file():
        pytest.skip("estrai_xg_concessi_hexi.py non presente in questa copia")
    finta = tmp_path / "heXI"
    (finta / "data" / "raw" / "external" / "sportmonks" / "_raw_lineups").mkdir(parents=True)
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT), capture_output=True, text=True,
        env={**os.environ, "INDEX_SEASON": stagione,
             "INDEX_LEGA": "ITA-Serie A", "INDEX_HEXI_DIR": str(finta)},
    )


def test_un_feed_non_ancora_pubblicato_non_ferma_la_sequenza(tmp_path):
    """Nessun feed per quella stagione: il passo esce bene, senza scrivere.

    Serve che sia cosi' perche' il passo vive dentro `pubblica.py`, che si
    ferma al primo codice di uscita diverso da zero.
    """
    esito = _lancia_estrattore(tmp_path, "2099-00")
    assert esito.returncode == 0, esito.stderr[-400:]
    assert "non ancora pubblicato" in esito.stdout
    assert not (ROOT / "dati_esterni" / "xg_concessi_serie_a_2099-00.json").exists()


def test_la_fonte_che_non_c_e_proprio_invece_si_fa_sentire(tmp_path):
    """Cartella di heXI assente: quello si', e' da sistemare, e si ferma.

    Le due assenze non vanno confuse. Se tacesse anche questa, una fonte
    spostata si leggerebbe per mesi come "la stagione non e' ancora uscita".
    """
    script = ROOT / "estrai_xg_concessi_hexi.py"
    if not script.is_file():
        pytest.skip("estrai_xg_concessi_hexi.py non presente in questa copia")
    esito = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT), capture_output=True, text=True,
        env={**os.environ, "INDEX_SEASON": "2099-00", "INDEX_LEGA": "ITA-Serie A",
             "INDEX_HEXI_DIR": str(tmp_path / "cartella-che-non-esiste")},
    )
    assert esito.returncode != 0
    assert "non e' dove dovrebbe" in esito.stderr
