"""Genera `dashboard_pro.html`: la classifica con i cinque modulatori scout.

    python pagina_pro.py          # la lega selezionata da config

**Perche' esiste questo file.** La pagina Pro e' l'ultima nata a mano: l'8
agosto 2026 e' stata scritta direttamente dentro `serie-a-index`, cioe' nel
repo del sito, e da allora modificata li' undici volte. E' la stessa posizione
da cui e' stato tolto il caso di mercato: quel repo contiene il sito, non il
motore che lo scrive. Finche' il campionato era uno solo non dava fastidio; al
secondo, l'unico modo per avere la pagina inglese era copiarla e tradurla a
mano — cioe' due file da tenere allineati per sempre, che e' la prima cosa che
questo progetto rifiuta.

**Cosa cambia da una lega all'altra, e cosa no.** I numeri no: la pagina Pro e'
l'unica del sito che non se li porta dentro, li chiede a `payload.json` con
`fetch` a ogni apertura. Quindi si aggiornava gia' da sola. Quello che era
inchiodato e' il guscio — il titolo della scheda, il marchio nella barra,
l'occhiello, il piede, e i link alla classifica, che porta il nome della lega.
Quei punti nel modello sono segnaposto e li riempie `config`, come per tutte le
altre pagine.

**Il modello.** `modello_pro.html` e' la pagina pubblicata l'ultima volta, con
sei segnaposto al posto dei nomi. Non e' un rifacimento: generando la Serie A
si riottiene la pagina che c'e' online, byte per byte — e` il controllo che
questo file non abbia perso niente per strada, e lo fa `tests/regression/
test_pagina_pro.py`.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import config
from pagina_stile import assicura_css, bi, testo_base

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("pagina_pro")

BASE_DIR = Path(__file__).parent
MODELLO = BASE_DIR / "modello_pro.html"
OUTPUT_DIR = config.cartella_uscita(BASE_DIR)
# Il repo del sito di QUESTA lega, come per le altre pagine: la Premier scritta
# dentro `serie-a-index` e' il difetto per cui `REPO_PUBBLICAZIONE` esiste.
DEMO_DIR = config.cartella_pubblicazione(BASE_DIR.parent)

USCITA = "dashboard_pro.html"


def nav_extra() -> str:
    """Le voci in piu' della lega, tolta questa pagina.

    Sulla Serie A e' il caso di mercato; sulla Premier non c'e' niente, e la
    fila si chiude sul Metodo. Il link a una pagina che quella lega non ha
    sarebbe un link morto in cima a ogni schermata: e' lo stesso motivo per cui
    `PAGINE_EXTRA` esiste.
    """
    return "".join(
        '<a class="nav-link" href="{h}" {b}>{it}</a>'.format(h=h, b=bi(it, en), it=it)
        for h, it, en in config.PAGINE_LEGA
        if h != USCITA
    )


def genera() -> str:
    """Il modello con i nomi di questa lega dentro."""
    html = MODELLO.read_text(encoding="utf-8")
    for segnaposto, valore in (
        ("{{LINGUA}}", config.LINGUA),
        ("{{SITO_NOME}}", config.SITO_NOME),
        ("{{SITO_MARCHIO}}", config.SITO_MARCHIO),
        ("{{SLUG}}", config.LEGA_SLUG),
        ("{{NAV_EXTRA}}", nav_extra()),
    ):
        html = html.replace(segnaposto, valore)

    # Un segnaposto rimasto sarebbe visibile sulla pagina pubblicata, scritto
    # com'e' — meglio fermarsi qui che stamparlo addosso a un lettore.
    if "{{" in html:
        avanzo = html[html.index("{{"):html.index("{{") + 40]
        raise SystemExit(f"Segnaposto non riempito nel modello: {avanzo!r}")

    # Il testo a schermo passa alla lingua del sito. Sulla Serie A non fa
    # niente; sulla Premier evita che la pagina si apra in italiano nell'attimo
    # prima che i18n.js parta, e davanti a chi lo script non lo esegue.
    return testo_base(html)


def main() -> None:
    if not MODELLO.is_file():
        raise SystemExit(f"Modello assente: {MODELLO}")

    html = genera()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    assicura_css(OUTPUT_DIR, DEMO_DIR)
    (OUTPUT_DIR / USCITA).write_text(html, encoding="utf-8")
    log.info(f"OK → {OUTPUT_DIR / USCITA}  ({config.LEGA_NOME})")

    if DEMO_DIR.is_dir():
        (DEMO_DIR / USCITA).write_text(html, encoding="utf-8")
        log.info(f"OK → {DEMO_DIR / USCITA}  (copia per il repo del sito)")
    else:
        log.warning(f"Repo del sito assente: {DEMO_DIR}")


if __name__ == "__main__":
    main()
