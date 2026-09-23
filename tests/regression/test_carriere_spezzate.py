"""Un trasferimento non deve rispezzare la carriera, e non deve contarla due volte.

COSA E' SUCCESSO (23/09/2026)
-----------------------------
La correzione dell'8/9 metteva 'understat_id' nell'upsert perche' un
trasferimento trovasse la propria riga. Guarisce pero' solo i record che
l'upsert riesce ancora a raggiungere: (nome, squadra_id) raggiunge chi e'
rimasto dov'era. Chi ha cambiato maglia e ha 'understat_id' NULL non e'
raggiunto da nessuna delle due chiavi — NULL non collide con niente — e
l'ingestione gli crea accanto una persona nuova.

Alla giornata 4 e' successo a trentasette giocatori. Le prime giornate sono
finite scritte da tutte e due le parti, e due nomi sulla Premier, quindici sulla
Serie A, sono usciti due volte nell'elenco pubblicato.

Questi test provano le due cose che lo chiudono, e le provano FACENDOLE, non
leggendo il sorgente: un test che cerca una riga nel file passa anche col
difetto rimesso — ne e' gia' stato buttato uno cosi' l'8/9.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from allinea_understat_id import piano_allineamento          # noqa: E402
from unisci_record_doppioni import confronta_righe, misura_righe   # noqa: E402

RIGA = ("2026-27", "casa", 90, 1, 0, 3, 0.42, 0.10, 0, 0, 0.42, 1, 0.31, 0.12)


def anagrafica(righe):
    return pd.DataFrame(righe, columns=["id", "n", "understat_id"])


def understat(per_id):
    """La cache ridotta a cio' che serve: chi ha giocato cosa, e i nomi."""
    per_nome, id_per_nome = {}, {}
    for pid, (nome, partite) in per_id.items():
        id_per_nome.setdefault(nome, set()).add(pid)
    return ({pid: {g: 90 for g in p} for pid, (_n, p) in per_id.items()},
            per_nome, id_per_nome)


# ─────────────────────────── le righe scritte due volte ──────────────────────

def test_la_stessa_riga_su_due_record_non_e_un_litigio():
    ra = {41: RIGA}
    rb = {41: RIGA, 42: RIGA}
    collisioni, diverse = confronta_righe(ra, rb)
    assert collisioni == {41}
    assert diverse == [], ("due righe identiche sulla stessa partita sono la "
                           "stessa riga scritta due volte: si tiene una")


@pytest.mark.parametrize("posizione", range(len(RIGA)))
def test_un_solo_campo_diverso_basta_a_fermare_tutto(posizione):
    """Il metro e' la riga intera, non i soli minuti.

    Se bastassero i minuti, due persone che hanno giocato novanta minuti nella
    stessa partita — succede — verrebbero dichiarate la stessa riga, e unirle
    ne cancellerebbe una.
    """
    altra = list(RIGA)
    v = altra[posizione]
    altra[posizione] = (v + 1) if isinstance(v, (int, float)) else "trasferta"
    _collisioni, diverse = confronta_righe({41: RIGA}, {41: tuple(altra)})
    assert diverse == [41], (f"un {RIGA[posizione]!r} diverso al posto "
                             f"{posizione} non e' stato notato")


def test_i_float_non_si_confrontano_al_bit():
    """Arrivano da colonne FLOAT: 0.187 e 0.18700000000000001 sono lo stesso
    valore misurato, e farli sembrare diversi rifiuterebbe l'unione per un
    difetto che non c'e'."""
    colonne = ["gid", "cid", "season", "ruolo", "minuti", "goal", "assist", "tiri",
               "xg", "xa", "gialli", "rossi", "npxg", "npg", "xg_chain", "xg_buildup"]
    a = misura_righe(pd.DataFrame([[7, 41, "2026-27", "casa", 90, 0, 0, 1,
                                    0.187, 0.0, 0, 0, 0.187, 0, 0.0, 0.0]], columns=colonne))
    b = misura_righe(pd.DataFrame([[8, 41, "2026-27", "casa", 90, 0, 0, 1,
                                    0.18700000000000001, 0.0, 0, 0, 0.187, 0, 0.0, 0.0]],
                                  columns=colonne))
    assert confronta_righe(a[7], b[8])[1] == []


def test_una_riga_senza_numeri_non_manda_in_errore_il_confronto():
    """npxg e xg_chain sono NULL sulle righe piu' vecchie."""
    colonne = ["gid", "cid", "season", "ruolo", "minuti", "goal", "assist", "tiri",
               "xg", "xa", "gialli", "rossi", "npxg", "npg", "xg_chain", "xg_buildup"]
    r = misura_righe(pd.DataFrame([[7, 41, "2026-27", "casa", 90, 0, 0, 1,
                                    0.1, 0.0, 0, 0, None, None, None, None]], columns=colonne))
    assert r[7][41][-1] is None


# ─────────────────────────── l'identita' restituita ──────────────────────────

def test_chi_ha_le_partite_giuste_si_riprende_il_suo_id():
    ana = anagrafica([(1, "Andrea Pinamonti", None)])
    us = understat({4895: ("andrea pinamonti", {10, 11, 12})})
    piano, fuori = piano_allineamento(ana, {1: {10, 11}}, us)
    assert piano == [(1, 4895, "andrea pinamonti", 2)]
    assert fuori == []


def test_un_omonimo_uscito_dal_campionato_non_si_prende_l_id_di_un_altro():
    """E' il test che conta. Il nome da solo direbbe di si'; le partite dicono
    di no, ed e' cosi' che Leon Bailey era diventato un difensore."""
    ana = anagrafica([(1, "Mario Rossi", None)])
    us = understat({999: ("mario rossi", {10, 11})})
    piano, fuori = piano_allineamento(ana, {1: {77, 78}}, us)
    assert piano == []
    assert "non e' lui".replace("'", "'") in fuori[0]


def test_un_nome_con_due_player_id_non_si_sceglie_a_caso():
    ana = anagrafica([(1, "Mario Rossi", None)])
    us = understat({1: ("mario rossi", {10}), 2: ("mario rossi", {11})})
    assert piano_allineamento(ana, {1: {10}}, us)[0] == []


def test_una_carriera_spezzata_la_ricuce_l_unione_non_questo():
    """Due record con lo stesso nome: dare l'id a uno dei due sarebbe scegliere
    quale meta' della persona e' la persona."""
    ana = anagrafica([(1, "Andrea Pinamonti", None), (2, "Andrea Pinamonti", None)])
    us = understat({4895: ("andrea pinamonti", {10, 11, 12})})
    piano, fuori = piano_allineamento(ana, {1: {10}, 2: {11}}, us)
    assert piano == []
    assert all("prima va unito" in f for f in fuori)


def test_un_id_gia_di_qualcun_altro_non_si_riassegna():
    ana = anagrafica([(1, "Andrea Pinamonti", None), (2, "Altro Nome", 4895)])
    us = understat({4895: ("andrea pinamonti", {10, 11})})
    piano, fuori = piano_allineamento(ana, {1: {10}, 2: {11}}, us)
    assert piano == []
    assert "gia'".replace("'", "'") in fuori[0]


def test_un_record_senza_partite_non_si_tocca():
    """Un guscio non ha niente con cui dimostrare chi sia: e' roba di
    'togli_gusci_unione.py', non di questo passo."""
    ana = anagrafica([(1, "Andrea Pinamonti", None)])
    us = understat({4895: ("andrea pinamonti", {10, 11})})
    assert piano_allineamento(ana, {}, us) == ([], [])


def test_chi_l_id_ce_l_ha_gia_non_viene_riconsiderato():
    ana = anagrafica([(1, "Andrea Pinamonti", 4895)])
    us = understat({4895: ("andrea pinamonti", {10, 11})})
    assert piano_allineamento(ana, {1: {10}}, us) == ([], [])


COLONNE = ["gid", "cid", "season", "ruolo", "minuti", "goal", "assist", "tiri",
           "xg", "xa", "gialli", "rossi", "npxg", "npg", "xg_chain", "xg_buildup"]
VALORI = [7, 41, "2026-27", "casa", 90, 1, 1, 3, 0.42, 0.10, 0, 0, 0.42, 1, 0.31, 0.12]


@pytest.mark.parametrize("colonna", [c for c in COLONNE if c not in ("gid", "cid")])
def test_nessun_campo_misurato_resta_fuori_dal_confronto(colonna):
    """Un campo dimenticato qui e' un campo su cui due righe diverse si
    somigliano abbastanza da essere dichiarate una copia — e la copia si
    cancella. La prova gira su tutte le colonne della tabella, cosi' una
    colonna nuova che nessuno aggiunge a CAMPI_RIGA si fa notare qui."""
    base = misura_righe(pd.DataFrame([VALORI], columns=COLONNE))[7][41]
    alterati = list(VALORI)
    i = COLONNE.index(colonna)
    v = alterati[i]
    alterati[i] = (v + 1) if isinstance(v, (int, float)) else "trasferta"
    altra = misura_righe(pd.DataFrame([alterati], columns=COLONNE))[7][41]
    assert base != altra, f"{colonna} non entra nel confronto fra due righe"
