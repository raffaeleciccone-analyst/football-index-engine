"""La validazione si rimisura da sola, ma solo quando c'e' motivo.

Due regole che si contraddicono solo in apparenza, e che finora vivevano una
nel codice e una nel runbook.

**Non si rimisura a ogni giornata.** Le quindici verifiche confrontano l'indice
di meta' strada con la classifica di fine stagione: su cinque giornate la
"fine" e' la quinta, e ognuna misurerebbe se stessa. Ne uscirebbe una pagina di
numeri altissimi e senza senso, sopra quelli veri.

**Ma una volta l'anno si rimisura.** Quando una stagione finisce, esiste una
stagione intera nuova da guardare, e i numeri pubblicati diventano quelli
dell'annata prima. Era un passo a mano dentro il runbook del cambio stagione —
cioe' esattamente il posto dove i passi a mano si perdono: gli infortuni sono
rimasti fermi quattro mesi per la stessa ragione.

La condizione che distingue i due casi e' in `aggiorna()`: la stagione del
campione contro quella dichiarata dall'ultima misurazione. Questi test
verificano la decisione, non il backtest — che e' lungo e qui non serve.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def valida(monkeypatch, tmp_path):
    """Il modulo, con campione e misurazione finti sotto controllo."""
    pytest.importorskip("scipy")
    import parte3_valida_tpi as v

    campione = tmp_path / "payload_full.json"
    dati = tmp_path / "validazione_dati.json"
    monkeypatch.setattr(v, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(v, "payload_corrente", lambda: campione)

    chiamate = []
    monkeypatch.setattr(v, "main", lambda: chiamate.append("main"))
    monkeypatch.setattr(v, "solo_pagina", lambda: chiamate.append("solo_pagina"))

    def prepara(stagione_campione, stagione_misurata):
        campione.write_text(json.dumps({"stagione": stagione_campione}), encoding="utf-8")
        if stagione_misurata is not None:
            dati.write_text(json.dumps({"meta": {"stagione": stagione_misurata}}),
                            encoding="utf-8")
        return chiamate

    return v, prepara


def test_stessa_stagione_non_rimisura(valida):
    """Il caso di tutti i giorni: i numeri sono gia' quelli giusti."""
    v, prepara = valida
    fatte = prepara("2025-26", "2025-26")
    v.aggiorna()
    assert fatte == ["solo_pagina"], "ha rimisurato senza motivo"


def test_stagione_nuova_rimisura(valida):
    """Il cambio stagione: il campione e' dell'annata appena conclusa."""
    v, prepara = valida
    fatte = prepara("2026-27", "2025-26")
    v.aggiorna()
    assert fatte == ["main"], "non ha rimisurato quando doveva"


def test_senza_misurazione_precedente_rimisura(valida):
    """Prima volta su una lega nuova: non c'e' niente da riscrivere."""
    v, prepara = valida
    fatte = prepara("2026-27", None)
    v.aggiorna()
    assert fatte == ["main"]


def test_campione_illeggibile_non_rimisura(valida):
    """Nel dubbio si riscrive e basta: rimisurare sovrascrive i numeri veri.

    Il danno e' asimmetrico. Non rimisurare quando si doveva lascia la pagina
    ferma a un'annata, e si vede: la stagione e' scritta sopra. Rimisurare
    quando non si doveva cancella i numeri buoni con quelli di cinque
    giornate, e quelli non tornano piu'.
    """
    v, prepara = valida
    fatte = prepara("2026-27", "2025-26")
    (v.OUTPUT_DIR / "payload_full.json").write_text("{ rotto", encoding="utf-8")
    v.aggiorna()
    assert fatte == ["solo_pagina"]


def test_la_sequenza_usa_la_strada_che_decide():
    """`pubblica.py` non deve tornare a chiamare `--solo-pagina` fisso."""
    testo = (ROOT / "pubblica.py").read_text(encoding="utf-8")
    righe = [r for r in testo.splitlines() if "parte3_valida_tpi.py" in r]
    assert righe, "il passo di validazione non c'e' piu'"
    for r in righe:
        assert "--aggiorna" in r, f"la sequenza non rimisurerebbe mai -> {r.strip()}"


def test_la_pagina_dichiara_la_stagione_dei_numeri():
    """Il numero senza la sua stagione e' il difetto peggiore su questa pagina.

    Diceva "il TPI ordina i 356 giocatori qualificati" al presente, mentre la
    classifica accanto ne mostrava 315: due numeri veri di due annate diverse.
    """
    testo = (ROOT / "parte3_pagina.py").read_text(encoding="utf-8")
    assert 'meta.get("stagione")' in testo, "la pagina non legge la stagione dal meta"
    assert "Misurate sulla stagione" in testo, "la pagina non dichiara la stagione"
