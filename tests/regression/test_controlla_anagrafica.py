"""Il controllo dell'anagrafica deve trovare i difetti che conosciamo.

Il 24/9/2026, lanciato sui due database veri, ha risposto zero su tutto. Zero e'
anche quello che risponde un controllo rotto: questi test rimettono ogni
difetto nei dati — nella forma in cui e' successo davvero fra l'8 e il 23/9 — e
pretendono che venga trovato. Un caso pulito, con due omonimi veri, prova che
non grida al lupo.
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from controlla_anagrafica import controlla   # noqa: E402

STAGIONE = "2026-27"


def anagrafica(*righe):
    return pd.DataFrame(righe, columns=["id", "n", "understat_id", "squadra"])


def partite(*righe):
    """(gid, cid, season, minuti); gli altri campi misurati a zero, oppure
    (gid, cid, season, minuti, xg) quando serve che due righe differiscano."""
    piene = [(*r[:4], 0, 0, 1, r[4] if len(r) > 4 else 0.0, 0.0, 0.0, 0.0) for r in righe]
    return pd.DataFrame(piene, columns=["gid", "cid", "season", "minuti", "goal", "assist",
                                        "tiri", "xg", "xa", "xg_chain", "xg_buildup"])


def test_anagrafica_sana_e_pulita():
    ana = anagrafica((1, "Andrew Robertson", 100, "Tottenham"),
                     (2, "Bruno Guimaraes", 200, "Newcastle"))
    rig = partite((1, 10, STAGIONE, 90), (1, 11, "2025-26", 90), (2, 10, STAGIONE, 80))
    assert controlla(ana, rig, STAGIONE).pulito


def test_omonimi_con_id_diversi_non_sono_un_difetto():
    ana = anagrafica((1, "Danilo", 100, "Juventus"), (2, "Danilo", 101, "Bologna"))
    rig = partite((1, 10, STAGIONE, 90), (2, 20, STAGIONE, 90))
    esito = controlla(ana, rig, STAGIONE)
    assert esito.pulito
    assert esito.omonimi_veri == 1


def test_trasferimento_spezzato_si_vede():
    # Il caso del 23/9: il record vecchio col club vecchio e l'id NULL, e
    # accanto la persona nuova creata dall'ingestione.
    ana = anagrafica((1, "Andrew Robertson", None, "Liverpool"),
                     (2, "Andrew Robertson", 100, "Tottenham"))
    rig = partite((1, 11, "2025-26", 90), (2, 10, STAGIONE, 90))
    esito = controlla(ana, rig, STAGIONE)
    assert len(esito.spezzate) == 1
    assert "andrew robertson" in esito.spezzate[0]


def test_cognome_raddoppiato_e_la_stessa_persona():
    # L'anagrafica difettosa di agosto: "Nikola Krstovic Krstovic".
    ana = anagrafica((1, "Nikola Krstovic Krstovic", None, "Lecce"),
                     (2, "Nikola Krstovic", 100, "Atalanta"))
    rig = partite((1, 11, "2025-26", 90), (2, 10, STAGIONE, 90))
    assert len(controlla(ana, rig, STAGIONE).spezzate) == 1


def test_stessa_partita_su_due_record_si_vede():
    ana = anagrafica((1, "Morten Thorsby", 100, "Genoa"),
                     (2, "Morten Thorsby", 101, "Cremonese"))
    rig = partite((1, 10, STAGIONE, 90), (2, 10, STAGIONE, 90))
    esito = controlla(ana, rig, STAGIONE)
    assert esito.righe_doppie == ["morten thorsby: partita 10 su 2 record"]


def test_guscio_accanto_al_record_vero_si_vede():
    # Il caso del 16/9: il doppione vuoto con (nome, club nuovo) che fermava
    # parte4 con un 1062.
    ana = anagrafica((1, "Bruno Guimaraes", 8327, "Newcastle"),
                     (2, "Bruno Guimaraes", None, "Newcastle"))
    rig = partite((1, 10, STAGIONE, 90))
    esito = controlla(ana, rig, STAGIONE)
    assert len(esito.gusci) == 1
    assert "id2" in esito.gusci[0]


def test_una_riga_da_zero_minuti_non_e_una_partita():
    # In panchina senza entrare: la riga esiste, la partita non e' giocata.
    ana = anagrafica((1, "Bruno Guimaraes", 8327, "Newcastle"),
                     (2, "Bruno Guimaraes", None, "Newcastle"))
    rig = partite((1, 10, STAGIONE, 90), (2, 11, STAGIONE, 0))
    assert len(controlla(ana, rig, STAGIONE).gusci) == 1


def test_id_mancante_conta_solo_nella_stagione_in_corso():
    # Estupinan al 24/9: id NULL, ma nessuna partita nella 26/27 — non c'e'
    # un trasferimento da cui spezzarsi.
    ana = anagrafica((1, "Pervis Estupinan", None, "Brighton"),
                     (2, "Pepe Chavarria", None, "Chelsea"))
    rig = partite((1, 11, "2025-26", 90), (2, 10, STAGIONE, 65))
    esito = controlla(ana, rig, STAGIONE)
    assert len(esito.id_mancanti) == 1
    assert "Chavarria" in esito.id_mancanti[0]


def test_copia_con_un_nome_diverso_si_vede():
    # Il caso del 24/9, che i quattro controlli per nome non vedevano.
    ana = anagrafica((3, "Pervis Estupiñán", None, "AC Milan"),
                     (4, "Estupiñán", 5136, "AC Milan"))
    rig = partite(*[(3, c, "2025-26", 90, 0.1 * c) for c in (1, 2, 3)],
                  *[(4, c, "2025-26", 90, 0.1 * c) for c in (1, 2, 3)],
                  (4, 9, STAGIONE, 90))
    esito = controlla(ana, rig, STAGIONE)
    assert len(esito.copie) == 1
    assert "id3" in esito.copie[0].split(":")[0]
    assert not esito.pulito
