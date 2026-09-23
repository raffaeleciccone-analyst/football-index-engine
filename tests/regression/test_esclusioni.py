"""Escludere un giocatore e correggergli il ruolo sono due cose diverse.

Erano la stessa. In `ruolo_override` si scriveva "POR" accanto a un giocatore
di movimento e quello spariva dall'indice — non perche' qualcuno lo credesse un
portiere, ma perche' i portieri vengono scartati in `main()`, quattromila righe
piu' giu'. Un interruttore di spegnimento travestito da ruolo, con tre difetti:

1. **Illeggibile.** `"Matteo Darmian": "POR"` non dice se fosse una convinzione
   o una decisione. Misurato il 7/9/2026: dei tredici forzati a POR, cinque
   tiravano e segnavano (Darmian 2022' e 3 gol, Viti 2811', Okereke, Hysaj,
   Iling-Junior). Portieri non erano.
2. **Fragile.** L'esclusione dipendeva da un filtro che sta altrove: il giorno
   che una pagina pubblica anche i portieri, gli spenti si riaccendono da soli,
   con il ruolo sbagliato addosso.
3. **Muto.** Finivano contati nel log fra i portieri veri, e un nome scaduto
   restava in lista fino a diventare l'omonimo di qualcun altro — che e' come
   Leon Bailey, ala dell'Aston Villa, e' diventato un difensore sulla Premier.

Adesso l'esclusione ha un elenco suo, il motivo e' obbligatorio, e un nome che
non trova nessuno viene detto.

**Cosa questi test NON coprono, e chi lo copre.** Provano `applica_esclusioni`,
non la riga di `main()` che la chiama. L'8/9/2026 quella riga passava `cfg` —
che dentro `main()` non esiste, li' la config si chiama `CFG` — e il giro della
Serie A si e' fermato su un `NameError` alle nove del mattino, in automatico,
con questi sei test verdi. Arrivarci da un test vorrebbe dire un `main()` con un
database dietro; scriverne uno che legge la chiamata con l'AST e' stato provato
ed e' risultato inutile, perche' passava anche col difetto rimesso. La rete e'
il gancio `ruff` (`E9,F821,F811`) in `.pre-commit-config.yaml`, che quel nome lo
prende in un secondo: un linter fa meglio di un test scritto a mano il lavoro di
un linter.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from parte1_analisi import CFG, applica_esclusioni  # noqa: E402


def _dati():
    df_pa = pd.DataFrame({"giocatore_id": [1, 2, 3],
                          "giocatore": ["Anna Rossi", "Bruno Verdi", "Carla Blu"],
                          "ruolo": ["DIF", "ATT", "CEN"]})
    df_gp = pd.DataFrame({"giocatore_id": pd.array([1, 1, 2, 3], dtype="Int64"),
                          "minuti": [90, 90, 45, 90]})
    return df_pa, df_gp


def test_esclude_e_porta_via_anche_le_partite():
    df_pa, df_gp = applica_esclusioni(*_dati(), {"Bruno Verdi": "doppione"})
    assert list(df_pa["giocatore"]) == ["Anna Rossi", "Carla Blu"]
    assert 2 not in set(df_gp["giocatore_id"])
    assert len(df_gp) == 3


def test_elenco_vuoto_non_tocca_niente():
    prima_pa, prima_gp = _dati()
    df_pa, df_gp = applica_esclusioni(prima_pa, prima_gp, {})
    assert len(df_pa) == 3 and len(df_gp) == 4


def test_un_nome_che_non_trova_nessuno_lo_dice(caplog):
    """Il silenzio e' il difetto: una riga scaduta deve farsi notare prima di
    diventare l'omonimo di qualcun altro."""
    with caplog.at_level("WARNING"):
        df_pa, _ = applica_esclusioni(*_dati(), {"Chi Non Gioca": "motivo"})
    assert len(df_pa) == 3
    assert "Esclusione senza riscontro" in caplog.text
    assert "Chi Non Gioca" in caplog.text


def test_il_motivo_finisce_nel_log(caplog):
    with caplog.at_level("INFO"):
        applica_esclusioni(*_dati(), {"Anna Rossi": "record sporco in anagrafica"})
    assert "record sporco in anagrafica" in caplog.text


def test_por_non_e_piu_un_interruttore():
    """Nessun giocatore di movimento resta forzato a POR: chi va escluso si
    scrive in `escludi`, e quell'elenco nasce vuoto perche' l'esclusione e' una
    decisione da prendere, non un'eredita' da trascinare."""
    spenti_a_mano = {"Matteo Darmian", "Mattia Viti", "David Okereke",
                     "Elseid Hysaj", "Samuel Iling-Junior",
                     "Branimir Mlacic", "Eddy Kouadio", "Matteo Palma"}
    forzati_por = {n for n, r in CFG.ruolo_override.items() if r == "POR"}
    assert not (forzati_por & spenti_a_mano)
    assert CFG.escludi == {}


# ── Chi un ruolo non ce l'ha ────────────────────────────────────────────────
# Diverso da un'esclusione: nessuno ha deciso niente, manca il dato. Il TPI e'
# standardizzato dentro il ruolo, quindi senza ruolo la riga esce vuota — e in
# un CSV che si presenta come "ogni giocatore qualificato" una riga vuota dice
# che e' qualificato e non dice niente di lui.

from parte1_analisi import scarta_senza_ruolo  # noqa: E402


def _con_un_senza_ruolo(valore):
    df_pa = pd.DataFrame({"giocatore_id": [1, 2],
                          "giocatore": ["Con Ruolo", "Senza Ruolo"],
                          "ruolo": ["DIF", valore]})
    df_gp = pd.DataFrame({"giocatore_id": pd.array([1, 2], dtype="Int64"),
                          "minuti": [90, 65]})
    return df_pa, df_gp


@pytest.mark.parametrize("valore", ["", "  ", None, "nan", "None"])
def test_un_ruolo_vuoto_in_ogni_forma_esce(valore):
    """Il campo arriva dal database e da pandas: vuoto ha cinque facce."""
    df_pa, df_gp = scarta_senza_ruolo(*_con_un_senza_ruolo(valore))
    assert list(df_pa["giocatore"]) == ["Con Ruolo"]
    assert set(df_gp["giocatore_id"]) == {1}


def test_chi_il_ruolo_ce_l_ha_resta():
    df_pa, df_gp = scarta_senza_ruolo(*_con_un_senza_ruolo("ATT"))
    assert len(df_pa) == 2 and len(df_gp) == 2


def test_l_esclusione_si_dice(caplog):
    """Non li ha esclusi un criterio: mancava il dato, e il numero va detto."""
    with caplog.at_level("WARNING"):
        scarta_senza_ruolo(*_con_un_senza_ruolo(""))
    assert "senza ruolo" in caplog.text
    assert "Senza Ruolo" in caplog.text
