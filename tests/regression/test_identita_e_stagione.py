"""Il nome del sito e la stagione visibile arrivano dalla configurazione.

I due difetti che questi test bloccano, tutti e due invisibili fino al primo
giro dopo il cambio di annata:

1. **Il nome.** Il sito della Premier e' stato rinominato "Premier League
   Index" a mano su ventisei pagine nel repo pubblicato. Il motore continuava a
   comporre "Premier League Scout": la prima rigenerazione avrebbe rimesso il
   vecchio nome ovunque, in silenzio. Il nome per intero e il marchio della
   barra adesso si dichiarano in `config.IDENTITA_LEGA`, e nessuno riscrive a
   mano la parola "Index".

2. **La stagione.** "25/26" era battuto a mano nella barra, nel piede e nella
   filigrana delle immagini scaricabili. Adesso viene da `INDEX_SEASON`, e
   se i dati dicono un'altra stagione il giro si ferma invece di pubblicare una
   classifica con l'etichetta sbagliata.
"""
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402


def _config_di(lega: str, stagione: str, monkeypatch):
    """config ricaricato come se lo avesse importato un giro su quella lega."""
    monkeypatch.setenv("SERIE_A_LEGA", lega)
    monkeypatch.setenv("INDEX_SEASON", stagione)
    return importlib.reload(config)


@pytest.fixture(autouse=True)
def config_pulito():
    """Ogni test lascia il modulo com'era: gli altri lo importano gia' carico."""
    yield
    importlib.reload(config)


# ── Il nome del sito ────────────────────────────────────────────────────────

def test_il_sito_della_premier_si_chiama_premier_league_index(monkeypatch):
    c = _config_di("ENG-Premier League", "2026-27", monkeypatch)
    assert c.SITO_NOME == "Premier League Index"
    # nella barra ci sta per intero: "Premier League" da solo e' il campionato
    assert c.SITO_MARCHIO == "Premier League Index"


def test_il_sito_della_serie_a_non_cambia_nome(monkeypatch):
    c = _config_di("ITA-Serie A", "2025-26", monkeypatch)
    assert c.SITO_NOME == "Serie A Scout Index"
    assert c.SITO_MARCHIO == "Serie A Scout"


@pytest.mark.parametrize("lega", list(config.IDENTITA_LEGA))
def test_nessun_nome_finisce_con_index_due_volte(lega, monkeypatch):
    """Le pagine scrivono il nome cosi' com'e': "Index" non si riattacca."""
    c = _config_di(lega, "2025-26", monkeypatch)
    assert c.SITO_NOME.endswith("Index")
    assert not c.SITO_NOME.endswith("Index Index")


def test_il_titolo_dell_eroe_spezza_il_nome_senza_riscriverlo(monkeypatch):
    """L'ultima parola va in corsivo sotto: si prende, non si ribatte."""
    _config_di("ENG-Premier League", "2026-27", monkeypatch)
    import pagina_home
    importlib.reload(pagina_home)
    assert pagina_home._titolo_hero() == "Premier League<br><em>Index</em>"

    _config_di("ITA-Serie A", "2025-26", monkeypatch)
    importlib.reload(pagina_home)
    assert pagina_home._titolo_hero() == "Serie A Scout<br><em>Index</em>"


# ── La stagione visibile ────────────────────────────────────────────────────

@pytest.mark.parametrize("season, lunga, breve", [
    ("2025-26", "2025/26", "25/26"),
    ("2026-27", "2026/27", "26/27"),
    ("2030-31", "2030/31", "30/31"),
])
def test_l_etichetta_della_stagione_si_calcola(season, lunga, breve):
    assert config.etichetta_stagione(season) == lunga
    assert config.etichetta_stagione(season, breve=True) == breve


def test_una_stagione_scritta_male_si_mostra_com_e():
    """Meglio una stagione scritta male di una inventata."""
    assert config.etichetta_stagione("boh") == "boh"


def test_la_barra_segue_la_stagione_senza_toccare_il_codice(monkeypatch):
    c = _config_di("ENG-Premier League", "2026-27", monkeypatch)
    import pagina_stile
    importlib.reload(pagina_stile)
    barra = pagina_stile.nav("index.html")
    assert ">Premier League Index <small>26/27</small><" in barra
    assert "25/26" not in barra
    assert 'title="Premier League Index"' in barra


# ── I dati e l'etichetta parlano della stessa stagione ──────────────────────

def test_una_stagione_diversa_da_quella_dichiarata_ferma_il_giro(monkeypatch):
    c = _config_di("ENG-Premier League", "2025-26", monkeypatch)
    with pytest.raises(SystemExit) as e:
        c.pretendi_stagione_coerente("2026-27", "payload.json")
    assert "2026-27" in str(e.value) and "2025-26" in str(e.value)


def test_la_stagione_che_coincide_non_dice_niente(monkeypatch):
    c = _config_di("ENG-Premier League", "2026-27", monkeypatch)
    assert c.pretendi_stagione_coerente("2026-27") is None
    # un payload che non dichiara la stagione e' un payload vecchio, non un errore
    assert c.pretendi_stagione_coerente(None) is None


# ── I nomi delle variabili d'ambiente ───────────────────────────────────────
# Le cinque variabili del motore si chiamavano `SERIE_A_*`, un prefisso nato
# quando la Serie A era l'unico campionato. Con due campionati e' una bugia, e
# `SERIE_A_LEGA` — quella che decide se stai generando la Premier o la Serie A —
# e' la piu' pericolosa. Rinominarle di colpo sarebbe stato peggio del nome: un
# `SERIE_A_SEASON=2026-27` gia' esportato verrebbe ignorato in silenzio e il
# default tornerebbe buono, cioe' il sito uscirebbe sulla stagione sbagliata
# senza che niente si lamenti.

def test_il_nome_nuovo_si_legge(monkeypatch):
    monkeypatch.delenv("SERIE_A_SEASON", raising=False)
    monkeypatch.setenv("INDEX_SEASON", "2031-32")
    assert config.leggi_env("SEASON", "x") == "2031-32"


def test_il_nome_vecchio_funziona_ancora(monkeypatch):
    """Chi ha una shell aperta con il nome vecchio non deve vedere il default."""
    monkeypatch.delenv("INDEX_SEASON", raising=False)
    monkeypatch.setenv("SERIE_A_SEASON", "2031-32")
    assert config.leggi_env("SEASON", "x") == "2031-32"


def test_il_nome_vecchio_lo_dice(monkeypatch, capsys):
    monkeypatch.delenv("INDEX_SEASON", raising=False)
    monkeypatch.setenv("SERIE_A_SEASON", "2031-32")
    config.leggi_env("SEASON", "x")
    detto = capsys.readouterr().err
    assert "SERIE_A_SEASON" in detto and "INDEX_SEASON" in detto


def test_fra_i_due_vince_il_nuovo(monkeypatch):
    monkeypatch.setenv("SERIE_A_SEASON", "2024-25")
    monkeypatch.setenv("INDEX_SEASON", "2031-32")
    assert config.leggi_env("SEASON", "x") == "2031-32"


def test_senza_nessuno_dei_due_resta_il_default(monkeypatch):
    monkeypatch.delenv("INDEX_SEASON", raising=False)
    monkeypatch.delenv("SERIE_A_SEASON", raising=False)
    assert config.leggi_env("SEASON", "difetto") == "difetto"


def test_l_audit_non_si_dichiara_piu_la_stagione():
    """Era `os.environ.get("SERIE_A_SEASON", "2025-26")` dentro l'audit: la
    stessa costante in due punti, cioe' due valori che possono divergere."""
    testo = (ROOT / "audit" / "lib" / "checks.py").read_text(encoding="utf-8")
    righe = [r for r in testo.splitlines()
             if "SEASON" in r and "environ" in r and not r.strip().startswith("#")]
    assert not righe, "l'audit legge la stagione per conto suo: %s" % righe


# ── La squadra di un giocatore ──────────────────────────────────────────────

def test_la_squadra_non_si_prende_dall_anagrafica():
    """Viene dalle partite, che non cambiano quando due record si uniscono.

    L'8/9/2026, unendo i cinquanta record spezzati del database Premier, e'
    sopravvissuto il record piu' vecchio — che in anagrafica porta il club
    vecchio. Robertson, che gioca nel Tottenham, e' uscito "Liverpool"; Fatawu
    "Leicester" invece di "Ipswich". Nella stessa pagina la classifica diceva una
    squadra e le partite un'altra. E non era solo un'etichetta: `squadra_id`
    finisce nei raggruppamenti a valle.
    """
    sorgente = (ROOT / "parte1_analisi.py").read_text(encoding="utf-8")
    i = sorgente.index("def load_players")
    blocco = sorgente[i:i + 6000]
    assert "squadra_dalle_partite" in blocco, (
        "la squadra non si ricava piu' dalle partite: torna a dipendere da "
        "g.squadra_id, che una fusione di record invalida")
    assert "COALESCE(sq_vera.nome, sq.nome)" in blocco, (
        "il nome della squadra non passa piu' dal ripiego sull'anagrafica")
