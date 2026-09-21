"""Il blocco sulla stagione in corso: cosa misura, cosa rimanda, cosa non tocca.

Le quindici verifiche girano su una stagione conclusa, e non si discute: quasi
tutte confrontano l'indice di meta' strada con la classifica di fine anno, e su
cinque giornate la "fine" e' la quinta. Ma "quasi tutte" non e' "tutte". Alcune
non guardano avanti — l'accordo coi voti, col valore di mercato, la sensibilita'
ai pesi — e quelle si possono misurare adesso.

Il rischio di questo blocco e' uno solo, e vale la pena scriverlo: che finisca
per **sovrascrivere i numeri veri** con quelli di cinque giornate. E' il danno
che il runbook vieta, ed e' irreversibile — i numeri a stagione intera non si
rifanno finche' la stagione non torna a finire. Il primo test di questo file
serve a quello.

Il secondo rischio e' piu' silenzioso: una verifica che non ha misurato niente
ma sembra aver misurato. Sulla Premier i voti Fantacalcio non esistono e
l'elenco WhoScored e' scritto a mano sui giocatori di Serie A: tornano zero
righe agganciate, e la prima versione di questa pagina ci metteva accanto una
spunta.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


@pytest.fixture
def modulo(monkeypatch, tmp_path):
    pytest.importorskip("scipy")
    import parte3_valida_tpi as v
    monkeypatch.setattr(v, "OUTPUT_DIR", tmp_path)
    (tmp_path / "payload_lista.json").write_text(json.dumps({
        "stagione": "2026-27", "n_giornate": 5, "giornate_totali": 38,
        "players": [{"id": i, "tpi": 1.0} for i in range(40)],
    }), encoding="utf-8")
    return v, tmp_path


def _solo(v, monkeypatch, esiti: dict):
    """Sostituisce le verifiche con esiti finti, senza toccare il resto."""
    registro = []
    for chiave, nome, it, en in v.VERIFICHE_IN_CORSO:
        if chiave in esiti:
            monkeypatch.setattr(v, nome, (lambda r: (lambda players: r))(esiti[chiave]),
                                raising=False)
            registro.append((chiave, nome, it, en))
    monkeypatch.setattr(v, "VERIFICHE_IN_CORSO", registro)


def test_non_tocca_mai_i_numeri_a_stagione_intera(modulo, monkeypatch):
    """Il vincolo che rende tutto il resto accettabile.

    Sovrascrivere `validazione_dati.json` con cinque giornate cancella numeri
    che non si rifanno fino a giugno.
    """
    v, tmp = modulo
    veri = tmp / "validazione_dati.json"
    veri.write_text(json.dumps({"meta": {"stagione": "2025-26"}}), encoding="utf-8")
    prima = veri.read_bytes()
    _solo(v, monkeypatch, {"mercato": {"rho": 0.3, "n": 100}})

    v.valida_in_corso()

    assert veri.read_bytes() == prima, "ha toccato i numeri a stagione intera"
    assert not (tmp / "validazione_sintesi.json").exists()
    assert (tmp / v.IN_CORSO_FILE).is_file(), "non ha scritto il suo file"


def test_scrive_stagione_e_giornata(modulo, monkeypatch):
    """Senza la giornata sopra, questi numeri sarebbero indistinguibili."""
    v, tmp = modulo
    _solo(v, monkeypatch, {"mercato": {"rho": 0.3, "n": 100}})
    fuori = v.valida_in_corso()
    assert fuori["stagione"] == "2026-27"
    assert fuori["giornate"] == 5
    assert fuori["n_giocatori"] == 40


def test_una_verifica_non_applicabile_si_rimanda_col_suo_motivo(modulo, monkeypatch):
    """Chi sa perche' non si applica lo dice meglio di un elenco qui dentro."""
    v, tmp = modulo
    _solo(v, monkeypatch, {"top10": {"non_applicabile": True,
                                     "motivo": "elenco di giocatori di Serie A"}})
    e = v.valida_in_corso()["verifiche"]["top10"]
    assert e["disponibile"] is False
    assert "Serie A" in e["perche"]


def test_zero_righe_agganciate_non_e_una_misura(modulo, monkeypatch):
    """Il caso dei voti Fantacalcio sulla Premier.

    Torna un dizionario pieno di None con n=0: senza questo controllo la
    tabella inglese ci metteva accanto una spunta.
    """
    v, tmp = modulo
    _solo(v, monkeypatch, {"fanta": {"r": None, "p": None, "n": 0, "data": []}})
    e = v.valida_in_corso()["verifiche"]["fanta"]
    assert e["disponibile"] is False
    assert "Serie A" in e["perche"]


def test_il_motivo_dell_attesa_esiste_nelle_due_lingue(modulo, monkeypatch):
    """Il sito e' bilingue: una riga italiana sotto "waiting" e' lo stesso
    difetto che il motore ha passato la giornata a togliere, in piccolo."""
    v, tmp = modulo
    _solo(v, monkeypatch, {"v2": {"has_data": False}})
    e = v.valida_in_corso()["verifiche"]["v2"]
    assert e["perche"] and e["perche_en"]
    assert e["perche"] != e["perche_en"]


def test_una_verifica_che_esplode_non_ferma_le_altre(modulo, monkeypatch):
    """Il PRI non esiste prima dell'ottava giornata e la sua verifica alza
    TypeError: e' una verifica che aspetta, non un giro da buttare."""
    v, tmp = modulo

    def scoppia(players):
        raise TypeError("Column 'pri' has dtype object")

    _solo(v, monkeypatch, {"v2": {}, "mercato": {"rho": 0.3, "n": 100}})
    monkeypatch.setattr(v, "valida_v2_indices", scoppia, raising=False)
    fuori = v.valida_in_corso()
    assert fuori["verifiche"]["v2"]["disponibile"] is False
    assert fuori["verifiche"]["mercato"]["disponibile"] is True
    assert fuori["n_fatte"] == 1


def test_senza_blocco_la_pagina_non_inventa_una_sezione():
    """Nessun file, nessuna sezione: non si pubblica un riquadro vuoto."""
    pytest.importorskip("scipy")
    import parte3_pagina
    assert parte3_pagina._cap_in_corso({}) == ""
    assert parte3_pagina._cap_in_corso({"in_corso": {}}) == ""
