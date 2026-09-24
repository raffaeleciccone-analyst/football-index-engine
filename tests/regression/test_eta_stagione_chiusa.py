"""L'eta' di una stagione chiusa non deve dipendere dal giorno in cui la si rigenera.

COSA E' SUCCESSO (24/09/2026)
-----------------------------
L'archivio 2025-26 della Serie A, rifatto il 24/9 per togliere una copia di
Estupinan, aveva l'eta' spostata di +0,01 per un quarto dei giocatori rispetto
a quello del 23/9. La causa era `date.today()`: una stagione conclusa a maggio
misurava l'eta' a settembre, e rifatta fra un anno li avrebbe resi tutti di un
anno piu' vecchi — dentro `eta_index`, cioe' dentro il TPI esteso.

Questi test chiamano la funzione vera, su un database SQLite in memoria, e
guardano il numero che esce.
"""
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from parte1_analisi import CFG, data_riferimento_eta, load_age_physical_data  # noqa: E402

NATO = date(2000, 5, 10)


def _db():
    eng = create_engine("sqlite://")
    with eng.begin() as cx:
        cx.execute(text("CREATE TABLE giocatori (id INTEGER, data_nascita DATE)"))
        cx.execute(text("INSERT INTO giocatori VALUES (1, :d)"), {"d": NATO.isoformat()})
    return eng


def _partite(*date_partite):
    return pd.DataFrame({
        "giocatore_id": 1, "squadra_id": 7, "minuti": 90,
        "giornata": range(1, len(date_partite) + 1),
        "data": pd.to_datetime(list(date_partite)),
    })


def _eta(df_gp):
    df_pa = pd.DataFrame({"giocatore_id": [1], "is_winter": [False]})
    return load_age_physical_data(_db(), df_pa, df_gp, CFG).loc[0, "eta"]


def test_stagione_chiusa_misura_l_eta_all_ultima_partita():
    eta = _eta(_partite("2025-08-23", "2026-01-10", "2026-05-24"))
    assert eta == round((date(2026, 5, 24) - NATO).days / 365.25, 2)   # 26.04


def test_la_stessa_stagione_da_la_stessa_eta_in_ogni_giorno():
    """Non puo' dipendere da oggi: con date.today() questo numero cresceva."""
    eta = _eta(_partite("2024-08-18", "2025-05-25"))
    assert eta == 25.04
    assert eta < round((date.today() - NATO).days / 365.25, 2)


def test_il_vintage_ha_l_eta_della_sua_giornata():
    """Il backtest a giornata 2 guarda i dati fino alla giornata 2."""
    fino_alla_2 = _partite("2025-08-23", "2025-08-30")
    assert _eta(fino_alla_2) == round((date(2025, 8, 30) - NATO).days / 365.25, 2)


def test_la_data_sono_le_partite_anche_con_orario():
    df = _partite("2026-05-24 20:45:00", "2026-05-10 18:00:00")
    assert data_riferimento_eta(df) == date(2026, 5, 24)


def test_senza_date_si_torna_a_oggi():
    df = pd.DataFrame({"giocatore_id": [1], "giornata": [1], "minuti": [90]})
    assert data_riferimento_eta(df) == date.today()
