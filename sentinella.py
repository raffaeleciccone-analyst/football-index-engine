"""Guarda ogni giorno il calendario, e avvisa su Telegram quando si pubblica.

Il cambio di stagione non ha una data: ha una condizione — la giornata 3 in
archivio. Una data segnata sul calendario sbaglia appena una partita viene
rinviata, e un promemoria che arriva quando la condizione non e' vera insegna a
ignorare i promemoria. Quindi questo script non ricorda: legge il calendario.

Da Understat arriva il calendario intero della stagione, con la data di ogni
partita e se e' gia' stata giocata. Da li' escono due cose:

* **quante giornate hanno giocato tutte** — non "quante partite ci sono": con i
  turni infrasettimanali e i rinvii una giornata resta aperta per giorni, e
  pubblicare li' vorrebbe dire mettere in classifica squadre con una partita in
  meno delle altre, cioe' rimettere dentro dal calendario lo sbilanciamento che
  l'indice esiste per correggere;
* **quando si chiude quella che manca** — la data dell'ultima partita di quel
  turno. Serve al preavviso: sapere che domenica si chiude vale piu' di
  scoprirlo lunedi'.

Con `--pubblica` non si limita ad avvisare: fa il giro. E lo fa **a ogni
giornata**, non solo al cambio di stagione — lo stato si segna per giornata, e
finche' si segnava per stagione il sito si aggiornava una volta in agosto e poi
restava fermo nove mesi, mentre il bot continuava ad alzarsi ogni mattina.

Dalla seconda giornata in poi arriva fino in fondo: committa e pusha. Non e' una
distrazione, e' dove passa la riga. Al primo giro di una stagione resta qualcosa
da decidere — il link al CSV nel README, che porta l'annata nel nome — e li' si
ferma. Dopo non cambia piu' niente a mano: sono gli stessi file con numeri
nuovi, e fermarsi ogni settimana vorrebbe dire un sito fermo con un promemoria
in tasca. Se la verifica finale non passa, non pubblica niente e lo scrive.

Uso:
    python sentinella.py --configura          # prepara il bot, la prima volta
    python sentinella.py --tutte --stato      # legge e stampa, non manda niente
    python sentinella.py --tutte              # e se e' ora, scrive
    python sentinella.py --bot                # il bot risponde? come si chiama?
    python sentinella.py --chat-id            # chi gli ha scritto

`--configura` fa tutto da solo: chiede il token a @BotFather, ti cerca fra chi
ha scritto al bot, scrive le due righe in `.env` e manda un messaggio di prova.
A mano sarebbero:
    TELEGRAM_BOT_TOKEN=...   (da @BotFather, comando /newbot)
    TELEGRAM_CHAT_ID=...     (scrivi al bot, poi `python sentinella.py --chat-id`)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent
STATO = BASE_DIR / "logs" / "sentinella.json"

LEGHE = {"premier": "ENG-Premier League", "serie-a": "ITA-Serie A"}
API = "https://api.telegram.org/bot%s/%s"

GIORNI = ["lunedi'", "martedi'", "mercoledi'", "giovedi'", "venerdi'",
          "sabato", "domenica"]
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre"]


def adesso() -> datetime:
    """L'ora, sempre con fuso. Passa da qui perche' i test la sostituiscono."""
    return datetime.now(timezone.utc)


def stagione_da_guardare() -> str:
    """Quale stagione sta giocando adesso, ricavata dal calendario dell'anno.

    NON `config.SEASON_CORRENTE`: quella e' la stagione che il sito *pubblica*,
    ed e' un'altra domanda. Restano diverse per mesi ogni anno — da agosto,
    quando il campionato ricomincia, a quando si rigenera il sito — che e'
    esattamente la finestra in cui questo script serve. Prendendo quella si
    guarderebbe il calendario della stagione conclusa, che ha trentotto
    giornate su trentotto: la sentinella direbbe "si puo' pubblicare" ogni
    mattina, a proposito di una stagione gia' pubblicata a maggio.

    Il taglio a luglio e' comodo e non ambiguo: da luglio in poi la stagione
    che comincia porta l'anno corrente, prima porta quello precedente.
    """
    oggi = adesso()
    inizio = oggi.year if oggi.month >= 7 else oggi.year - 1
    return "%d-%02d" % (inizio, (inizio + 1) % 100)


def quando(momento: datetime) -> str:
    """Una data come la direbbe una persona, nel fuso di chi legge."""
    try:
        from zoneinfo import ZoneInfo
        momento = momento.astimezone(ZoneInfo("Europe/Rome"))
    except Exception:
        pass  # senza i fusi, l'ora resta quella che c'e': meglio di niente
    return "%s %d %s alle %02d:%02d" % (GIORNI[momento.weekday()], momento.day,
                                        MESI[momento.month - 1], momento.hour,
                                        momento.minute)


# ════════════════════════════════════════════════════════════════════════════
#  Telegram
# ════════════════════════════════════════════════════════════════════════════
class NonConfigurato(SystemExit):
    """Manca il token o il destinatario. Non e' un errore: e' il primo giro."""


def _credenziali(serve_chat: bool = True) -> tuple[str, str]:
    import config  # e' lui che carica .env dentro os.environ
    _ = config.DB_HOST
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token:
        raise NonConfigurato(
            "TELEGRAM_BOT_TOKEN non c'e'.\n"
            "  1. su Telegram scrivi a @BotFather, comando /newbot\n"
            "  2. copia il token e mettilo in .env:\n"
            "     TELEGRAM_BOT_TOKEN=123456:AAxxxxxxxx")
    if serve_chat and not chat:
        raise NonConfigurato(
            "TELEGRAM_CHAT_ID non c'e'.\n"
            "  1. manda un messaggio qualsiasi al tuo bot\n"
            "  2. lancia: python sentinella.py --chat-id\n"
            "  3. metti il numero in .env: TELEGRAM_CHAT_ID=...")
    return token, chat


def _chiama(metodo: str, corpo: dict, token: str) -> dict:
    dati = json.dumps(corpo).encode("utf-8")
    richiesta = urllib.request.Request(
        API % (token, metodo), dati, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(richiesta, timeout=20) as r:
            risposta = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            risposta = json.loads(e.read().decode("utf-8"))
        except Exception:
            raise SystemExit("Telegram ha risposto %s" % e.code) from None
    except (urllib.error.URLError, OSError) as e:
        raise SystemExit("Telegram non risponde: %s" % e) from None
    if not risposta.get("ok"):
        raise SystemExit("Telegram ha rifiutato: %s"
                         % risposta.get("description", risposta))
    return risposta.get("result") or {}


def manda(testo: str) -> None:
    """Un messaggio, testo semplice.

    Niente `parse_mode`: i nomi delle squadre e i percorsi di Windows sono
    pieni di `_`, `*`, `[` e barre rovesciate, che in Markdown o in HTML
    fanno rifiutare il messaggio o spariscono dentro la formattazione. Un
    avviso che non arriva e' peggio di un avviso senza grassetto.
    """
    token, chat = _credenziali()
    _chiama("sendMessage", {"chat_id": chat, "text": testo,
                            "disable_web_page_preview": True}, token)


def prova_bot() -> int:
    """Il bot risponde, e come si chiama. Senza mandare niente a nessuno."""
    token, chat = _credenziali(serve_chat=False)
    dati = _chiama("getMe", {}, token)
    print("Bot raggiungibile: @%s (%s)"
          % (dati.get("username", "?"), dati.get("first_name", "")))
    print("Destinatario configurato: %s" % (chat or "NESSUNO — manca TELEGRAM_CHAT_ID"))
    return 0 if chat else 1


TIPI_CHAT = {
    "private": "chat privata — l'avviso arriva solo a te",
    "group": "gruppo",
    "supergroup": "gruppo",
    "channel": "canale — il bot dev'essere amministratore",
}


def chat_disponibili(token: str) -> dict[str, tuple[str, str]]:
    """Le chat che il bot ha visto: id -> (nome, che tipo e').

    Si guardano quattro tipi di aggiornamento e non solo i messaggi: aggiungere
    il bot a un gruppo non produce un messaggio, produce un `my_chat_member`, e
    in un canale i messaggi sono `channel_post`. Guardando solo `message` la
    lista resterebbe vuota proprio nei due casi in cui non c'e' un modo ovvio di
    trovare l'identificativo a mano.
    """
    viste: dict[str, tuple[str, str]] = {}
    for a in _chiama("getUpdates", {"limit": 100}, token) or []:
        chat = None
        for chiave in ("message", "channel_post", "edited_message", "my_chat_member"):
            if a.get(chiave):
                chat = a[chiave].get("chat")
                break
        if not chat or not chat.get("id"):
            continue
        nome = (chat.get("title")
                or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
                or chat.get("username") or "senza nome")
        tipo = chat.get("type", "?")
        viste[str(chat["id"])] = (nome, TIPI_CHAT.get(tipo, tipo))
    return viste


def _spiega_lista_vuota(bot: str) -> None:
    """Un bot non puo' scrivere per primo: e' questo, non un errore."""
    print("Nessuna chat trovata. Non e' un errore di configurazione: un bot "
          "Telegram non puo' scrivere per primo a nessuno.")
    print()
    print("Per ricevere gli avvisi tu:")
    print("  1. su Telegram cerca @%s;" % bot)
    print("  2. premi Avvia (oppure scrivi /start);")
    print("  3. rilancia questo comando.")
    print()
    print("Per farli arrivare in un gruppo:")
    print("  1. aggiungi il bot al gruppo;")
    print("  2. scrivi un messaggio qualsiasi li' dentro;")
    print("  3. rilancia questo comando.")
    print()
    print("Nota: nei gruppi il bot legge solo i messaggi che iniziano con / o "
          "che lo menzionano. Da @BotFather si cambia con /setprivacy -> Disable.")


def stampa_chat_id() -> int:
    """Chi ha scritto al bot: il chat_id Telegram non lo mostra da nessuna parte."""
    token, _ = _credenziali(serve_chat=False)
    bot = _chiama("getMe", {}, token).get("username", "iltuobot")
    viste = chat_disponibili(token)
    if not viste:
        _spiega_lista_vuota(bot)
        return 1
    print("Chat trovate. Copia la riga che ti serve nel file .env:")
    print()
    for id_chat, (nome, tipo) in viste.items():
        print("  TELEGRAM_CHAT_ID=%s" % id_chat)
        print("      %s  (%s)" % (nome, tipo))
        print()
    print("Identificativo positivo = chat personale. Negativo = gruppo o canale.")
    return 0


# ════════════════════════════════════════════════════════════════════════════
#  La configurazione guidata
# ════════════════════════════════════════════════════════════════════════════
ENV = BASE_DIR / ".env"
TESTATA = "# Sentinella: avvisi su Telegram (python sentinella.py --configura)"


def _scrivi_env(valori: dict[str, str]) -> None:
    """Aggiorna .env lasciando intatto tutto il resto.

    Il file contiene anche la password del database: si riscrive riga per riga,
    cambiando solo le chiavi richieste e aggiungendo in fondo quelle che non
    c'erano. Riscriverlo da zero sarebbe un modo di perdere qualcosa che nessuno
    si ricorda di avere messo li'.
    """
    righe = ENV.read_text(encoding="utf-8").splitlines() if ENV.is_file() else []
    rimaste = dict(valori)
    fuori = []
    for riga in righe:
        chiave = riga.split("=", 1)[0].strip()
        if chiave in rimaste:
            fuori.append("%s=%s" % (chiave, rimaste.pop(chiave)))
        else:
            fuori.append(riga)
    if rimaste:
        if fuori and fuori[-1].strip():
            fuori.append("")
        # L'intestazione si scrive una volta sola. Scrivendo le due chiavi in
        # due momenti — il token prima, il destinatario dopo che hai premuto
        # Avvia, che e' proprio come va la configurazione guidata — la stessa
        # riga di commento finiva nel file due volte.
        if TESTATA not in righe:
            fuori.append(TESTATA)
        fuori.extend("%s=%s" % (k, v) for k, v in rimaste.items())
    ENV.write_text("\n".join(fuori) + "\n", encoding="utf-8")


def _chiedi(domanda: str) -> str:
    try:
        return input(domanda).strip()
    except EOFError:
        return ""


def configura() -> int:
    """Prepara il bot passo per passo, e scrive .env da solo.

    I quattro passi erano scritti nel runbook, e fatti a mano: creare il bot,
    incollare il token, farsi trovare, copiare un numero che Telegram non mostra
    da nessuna parte. Sono pochi e sono tutti facili, ed e' esattamente il tipo
    di cosa che si sbaglia una volta e poi si rimanda per due settimane.
    """
    if not sys.stdin.isatty():
        print("--configura chiede delle cose: lanciala da un terminale.")
        return 1

    print("=" * 70)
    print("Sentinella — configurazione del bot Telegram")
    print("=" * 70)

    import config
    _ = config.DB_HOST                      # carica .env
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

    if token:
        print("\nUn token c'e' gia' in .env.")
        if _chiedi("Ne vuoi mettere un altro? [s/N] ").lower().startswith("s"):
            token = ""
    if not token:
        print("\n1. Su Telegram apri una chat con @BotFather")
        print("2. Manda /newbot e segui le istruzioni (nome, poi @username)")
        print("3. BotFather ti risponde con un token, tipo 123456:AAxx...")
        token = _chiedi("\nIncolla qui il token: ").strip()
        if not token:
            print("Niente token, niente bot. Rilancia quando ce l'hai.")
            return 1

    try:
        bot = _chiama("getMe", {}, token)
    except SystemExit as e:
        print("\nTelegram non ha accettato il token: %s" % e)
        return 1
    nome_bot = bot.get("username", "?")
    print("\nBot riconosciuto: @%s (%s)" % (nome_bot, bot.get("first_name", "")))

    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    viste = chat_disponibili(token)
    if chat and chat in viste and not _chiedi(
            "\nGli avvisi vanno gia' a %s (%s). Cambiare? [s/N] "
            % (chat, viste[chat][0])).lower().startswith("s"):
        pass
    else:
        if not viste:
            print("\nOra fatti trovare:")
            print("  apri Telegram, cerca @%s e premi Avvia (o scrivi /start)." % nome_bot)
            _chiedi("\nFatto? Premi Invio per cercarti... ")
            viste = chat_disponibili(token)
        if not viste:
            print()
            _spiega_lista_vuota(nome_bot)
            return 1
        if len(viste) == 1:
            chat, (nome, tipo) = next(iter(viste.items()))
            print("\nTrovato: %s — %s (%s)" % (chat, nome, tipo))
        else:
            print("\nHo trovato piu' di una chat:")
            elenco = list(viste.items())
            for i, (id_chat, (nome, tipo)) in enumerate(elenco, 1):
                print("  %d) %s — %s (%s)" % (i, id_chat, nome, tipo))
            scelta = _chiedi("Quale? [1] ") or "1"
            try:
                chat = elenco[int(scelta) - 1][0]
            except (ValueError, IndexError):
                print("Scelta non valida.")
                return 1

    _scrivi_env({"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": chat})
    os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"] = token, chat
    print("\nScritto in %s (il resto del file non e' stato toccato)." % ENV)

    manda("Sentinella — collegata.\n\n"
          "Da qui ti scrivo quando il campionato ha giocato abbastanza per "
          "pubblicare la stagione nuova, e qualche giorno prima per dirti "
          "quando si chiude la giornata che manca.")
    print("Messaggio di prova mandato: guarda Telegram.")

    print("\nPer farla girare da sola una volta al giorno, da un prompt come")
    print("amministratore:")
    print('  schtasks /create /tn "Sentinella stagione" ^')
    print('    /tr "%s" /sc daily /st 09:00' % (BASE_DIR / "sentinella.bat"))
    print("\nPer vedere subito cosa direbbe:  python sentinella.py --tutte --stato")
    return 0


# ════════════════════════════════════════════════════════════════════════════
#  Il calendario
# ════════════════════════════════════════════════════════════════════════════
@dataclass(slots=True)
class Calendario:
    """Cosa dice il calendario, ridotto alle due cose che servono."""
    complete: int = 0            # giornate giocate da TUTTE le squadre
    partite: int = 0             # partite con un risultato
    chiusura: datetime | None = None   # quando finisce la giornata che manca
    giornata_attesa: int = 0     # quale giornata e' quella che manca
    squadre: int = 0
    errore: str | None = None

    @property
    def ok(self) -> bool:
        return self.errore is None

    def __str__(self) -> str:
        if self.errore:
            return "calendario non letto: %s" % self.errore
        testo = ("%d giornate giocate da tutte le %d squadre, %d partite in archivio"
                 % (self.complete, self.squadre, self.partite))
        if self.chiusura:
            testo += (" — la giornata %d chiude %s"
                      % (self.giornata_attesa, quando(self.chiusura)))
        return testo


def leggi_calendario(lega: str, stagione: str, soglia: int) -> Calendario:
    """Il calendario della stagione, letto una volta sola.

    `read_schedule()` porta tutte e 380 le partite con data, squadre e se sono
    gia' state giocate: da li' si ricava sia quante giornate sono chiuse sia
    quando si chiude la prossima, senza un secondo scaricamento.

    La giornata di una squadra e' la sua ennesima partita in ordine di data, non
    il numero che porta il turno: e' cosi' che si trattano i rinvii, dove il
    numero del turno e l'ordine in cui si gioca non coincidono piu'.
    """
    try:
        # soccerdata racconta a voce alta dove tiene la cache e quale libreria
        # TLS ha caricato: dieci righe per ogni giro, dentro un registro che
        # gira tutti i giorni e che si legge solo quando qualcosa non va.
        import logging
        for nome in ("soccerdata", "root", "tls_requests"):
            logging.getLogger(nome).setLevel(logging.WARNING)

        import soccerdata as sd
        import config

        us = sd.Understat(leagues=lega, seasons=config.anno_understat(stagione),
                          no_cache=True)
        df = us.read_schedule().reset_index()
    except Exception as e:
        return Calendario(errore=str(e))

    if df.empty:
        return Calendario(errore="Understat non ha restituito nessuna partita")
    for colonna in ("date", "home_team", "away_team"):
        if colonna not in df.columns:
            return Calendario(errore="il calendario non ha la colonna %r" % colonna)

    df = df.sort_values("date")
    giocata = (df["is_result"].fillna(False).astype(bool) if "is_result" in df.columns
               else df.get("has_data", False))

    # per ogni squadra: la sua ennesima partita -> (data, gia' giocata)
    partite_di: dict[str, list[tuple[datetime, bool]]] = {}
    for (_, riga), fatta in zip(df.iterrows(), giocata):
        for colonna in ("home_team", "away_team"):
            partite_di.setdefault(str(riga[colonna]), []).append(
                (riga["date"], bool(fatta)))

    if not partite_di:
        return Calendario(errore="nessuna squadra nel calendario")

    complete = 0
    for n in range(1, 1 + min(len(v) for v in partite_di.values())):
        if all(v[n - 1][1] for v in partite_di.values()):
            complete = n
        else:
            break

    esito = Calendario(complete=complete,
                       partite=int(giocata.sum()),
                       squadre=len(partite_di))

    # Quando si chiude la giornata che serve: l'ultima partita di quel turno.
    attesa = max(soglia, complete + 1)
    date_attesa = [v[attesa - 1][0] for v in partite_di.values() if len(v) >= attesa]
    if date_attesa and complete < soglia:
        ultima = max(date_attesa)
        if ultima.tzinfo is None:
            ultima = ultima.replace(tzinfo=timezone.utc)
        esito.chiusura, esito.giornata_attesa = ultima, attesa
    return esito


# ════════════════════════════════════════════════════════════════════════════
#  Lo stato: ogni messaggio una volta sola
# ════════════════════════════════════════════════════════════════════════════
def _leggi_stato() -> dict:
    if not STATO.is_file():
        return {}
    try:
        return json.loads(STATO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Uno stato illeggibile fa mandare un avviso in piu'. Fermarsi qui ne
        # farebbe perdere uno, che e' il danno vero.
        return {}


def _segna(chiave: str, dettaglio: dict) -> None:
    stato = _leggi_stato()
    stato[chiave] = dict(dettaglio, mandato=adesso().isoformat(timespec="seconds"))
    STATO.parent.mkdir(parents=True, exist_ok=True)
    STATO.write_text(json.dumps(stato, indent=1, ensure_ascii=False), encoding="utf-8")


# ════════════════════════════════════════════════════════════════════════════
#  I due messaggi
# ════════════════════════════════════════════════════════════════════════════
def testo_preavviso(lega: str, stagione: str, c: Calendario) -> str:
    return (
        "%s — manca poco.\n\n"
        "La giornata %d si chiude %s: sono %d su %d.\n"
        "Da subito dopo si puo' pubblicare la %s.\n\n"
        "Ti riscrivo quando e' in archivio."
        % (lega, c.giornata_attesa, quando(c.chiusura), c.complete,
           c.giornata_attesa, stagione.replace("-", "/")))


def testo_via_libera(alias: str, lega: str, stagione: str, c: Calendario) -> str:
    return (
        "%s — si puo' pubblicare la %s.\n\n"
        "La giornata %d e' in archivio: l'hanno giocata tutte e %d le squadre "
        "(%d partite).\n\n"
        "cd %s\n"
        "python pubblica.py --lega %s --stagione %s --esegui\n\n"
        "Poi il link al CSV nel README, e il commit.\n"
        "Runbook: docs/runbooks/cambio_stagione.md"
        % (lega, stagione.replace("-", "/"), c.complete, c.squadre, c.partite,
           BASE_DIR, alias, stagione))


# ════════════════════════════════════════════════════════════════════════════
#  Il giro, fatto da sola
# ════════════════════════════════════════════════════════════════════════════
def pubblica_ora(alias: str, stagione: str) -> tuple[int, str, str]:
    """Lancia `pubblica.py` e torna (codice, repo del sito, ultime righe).

    Si ferma dove si ferma `pubblica.py`: le pagine sono scritte e verificate,
    ma il commit e il push no. Chi decide se andare online e' `fai_il_giro`, in
    base a una domanda sola: e' il primo giro di questa stagione, oppure e'
    l'ennesima giornata? Nel primo caso resta qualcosa da fare a mano e ci si
    ferma; nel secondo va online, ma solo perche' la verifica e' passata.

    Il database sta su questa macchina, quindi questo giro puo' girare solo
    qui: e' la ragione per cui la sentinella in cloud, quando la riaccenderai,
    restera' quella che avvisa e basta.
    """
    esito = subprocess.run(
        [sys.executable, "pubblica.py", "--lega", alias,
         "--stagione", stagione, "--esegui"],
        cwd=str(BASE_DIR), capture_output=True, text=True, errors="replace")
    uscita = (esito.stdout or "") + "\n" + (esito.stderr or "")
    righe = [r.rstrip() for r in uscita.splitlines() if r.strip()]
    repo = next((r.split(":", 1)[1].strip() for r in righe
                 if r.startswith("repo:")), str(BASE_DIR))
    return esito.returncode, repo, "\n".join(righe[-12:])


def manda_online(repo: str, lega: str, stagione: str, giornata: int) -> tuple[bool, str]:
    """Committa e pusha il sito. Solo per i giri di aggiornamento, non il primo.

    La distinzione non e' prudenza a caso: al primo giro di una stagione il link
    al CSV nel README cambia, perche' il nome del file porta l'annata dentro, e
    quello lo sistema una persona. Dalla giornata dopo non cambia piu' niente a
    mano — sono gli stessi file con numeri nuovi — e fermarsi li' ogni settimana
    vorrebbe dire un sito fermo con un promemoria in tasca, che e' esattamente il
    contrario di avere un bot.

    Si arriva qui solo se la verifica di `pubblica.py` e' passata: se le pagine
    non dicessero tutte la stessa stagione il giro sarebbe finito prima.
    """
    messaggio = (
        "Giornata %d: dati aggiornati" % giornata
        + "\n\nRicalcolo automatico dopo la chiusura della giornata %d di %s. "
          "Stessi file, numeri nuovi." % (giornata, stagione.replace("-", "/")))
    try:
        stato = subprocess.run(["git", "status", "--porcelain"], cwd=repo,
                               capture_output=True, text=True, errors="replace")
        if not (stato.stdout or "").strip():
            return True, "niente da committare: il sito era gia' aggiornato"
        for comando in (["git", "add", "-A"],
                        ["git", "commit", "-m", messaggio],
                        ["git", "push", "origin", "HEAD"]):
            esito = subprocess.run(comando, cwd=repo, capture_output=True,
                                   text=True, errors="replace")
            if esito.returncode != 0:
                coda = ((esito.stdout or "") + (esito.stderr or "")).strip().splitlines()
                return False, "%s: %s" % (" ".join(comando[:2]),
                                          " / ".join(coda[-3:]) or "codice %d" % esito.returncode)
        return True, "committato e pushato"
    except OSError as e:
        return False, str(e)


def testo_aggiornato(lega: str, giornata: int, esito: str) -> str:
    return (
        "%s — giornata %d online.\n\n"
        "Ho scaricato, ricalcolato e riscritto le pagine; la verifica e' passata "
        "e ho pubblicato: %s.\n\n"
        "Non c'era niente da decidere: stessa stagione, stessi file, numeri "
        "nuovi. Il primo giro di una stagione resta l'eccezione, perche' li' il "
        "link al CSV nel README lo cambi tu." % (lega, giornata, esito))


def testo_push_fermo(lega: str, giornata: int, repo: str, perche: str) -> str:
    return (
        "%s — giornata %d ricalcolata, ma NON pubblicata.\n\n"
        "Le pagine sono scritte e verificate: si e' fermato il push.\n\n%s\n\n"
        "Il lavoro non e' perso, e' li' che aspetta:\n"
        "cd %s\n"
        "git add -A && git commit && git push" % (lega, giornata, perche, repo))


def testo_giro_partito(lega: str, stagione: str, c: Calendario) -> str:
    return (
        "%s — si puo' pubblicare la %s, e ci penso io.\n\n"
        "La giornata %d e' in archivio: l'hanno giocata tutte e %d le squadre "
        "(%d partite). Faccio il giro — scarico, ricalcolo, riscrivo le "
        "pagine. Sono parecchi minuti.\n\n"
        "Ti riscrivo quando ho finito. Il sito non va online da solo: "
        "l'ultimo passo resta tuo."
        % (lega, stagione.replace("-", "/"), c.giornata_attesa, c.squadre,
           c.partite))


def testo_giro_finito(lega: str, stagione: str, repo: str) -> str:
    return (
        "%s — fatto: la %s e' pronta.\n\n"
        "Le pagine sono scritte e la verifica finale e' passata (tutte "
        "dicono la stessa stagione).\n\n"
        "Restano le due cose che decidi tu:\n"
        "1. il link al CSV nel README del sito\n"
        "2. cd %s\n"
        "   git add -A && git commit && git push\n\n"
        "Finche' non fai il push, online c'e' ancora la stagione vecchia."
        % (lega, stagione.replace("-", "/"), repo))


def testo_giro_fermo(alias: str, lega: str, stagione: str,
                     codice: int, coda: str) -> str:
    return (
        "%s — il giro si e' fermato (codice %d).\n\n"
        "Il sito non e' stato toccato. Ultime righe:\n\n%s\n\n"
        "Domani ci riprovo da solo. Per riprenderlo a mano adesso:\n"
        "cd %s\n"
        "python pubblica.py --lega %s --stagione %s --esegui"
        % (lega, codice, coda, BASE_DIR, alias, stagione))


def fai_il_giro(alias: str, lega: str, stagione: str, c: Calendario,
                forza: bool) -> int:
    """Il via libera, ma invece di scriverti il comando lo esegue.

    Lo stato tiene due chiavi separate: il messaggio parte una volta sola, la
    pubblicazione si segna solo se e' andata. Cosi' un giro fallito — Understat
    muto, la rete che cade a meta' — domani si ripete invece di restare li'
    creduto fatto.
    """
    # Lo stato si segna per GIORNATA, non per stagione. Con la vecchia chiave
    # (lega|stagione|pubblicazione) il sito si aggiornava una volta sola, al
    # cambio d'annata, e poi restava fermo per nove mesi: la giornata 4 non
    # arrivava mai, perche' la stagione risultava gia' pubblicata. Il bot
    # avvisava di una cosa che non succedeva piu'.
    chiave = "%s|%s|pubblicazione|g%d" % (lega, stagione, c.complete)
    stato = _leggi_stato()
    gia = stato.get(chiave)

    # La chiave vecchia, senza giornata, vale per la giornata che ha dentro:
    # chi ha gia' pubblicato la 3 con il formato di prima non deve rifarla al
    # primo giro dopo l'aggiornamento. Senza questo, la sentinella avrebbe
    # ricalcolato e ripubblicato una giornata gia' online, annunciandola.
    if gia is None:
        vecchia = stato.get("%s|%s|pubblicazione" % (lega, stagione))
        if vecchia and (vecchia.get("giornate") or 0) >= c.complete:
            gia = vecchia

    if gia and not forza:
        print("          giornata %d gia' pubblicata il %s: sto zitto."
              % (c.complete, (gia.get("mandato") or "")[:10]))
        return 0

    # Prima volta della stagione = nessuna giornata segnata per questa annata.
    # E' l'unico giro che lascia qualcosa da fare a mano.
    inizio = "%s|%s|pubblicazione" % (lega, stagione)
    prima_volta = not any(k.startswith(inizio) for k in stato)

    try:
        manda(testo_giro_partito(lega, stagione, c))
    except NonConfigurato as e:
        # Senza Telegram il giro si fa lo stesso: l'avviso e' un di piu', non
        # un passo della procedura.
        print("          non mandato: %s" % str(e).splitlines()[0])

    print("          faccio il giro: python pubblica.py --lega %s --stagione %s"
          % (alias, stagione))
    codice, repo, coda = pubblica_ora(alias, stagione)

    if codice == 0 and not prima_volta:
        # Giro di aggiornamento: niente da decidere, va online.
        ok, come = manda_online(repo, lega, stagione, c.complete)
        _segna(chiave, {"tipo": "pubblicazione", "giornate": c.complete,
                        "online": bool(ok)})
        if ok:
            testo = testo_aggiornato(lega, c.complete, come)
            print("          giornata %d online: %s" % (c.complete, come))
        else:
            testo = testo_push_fermo(lega, c.complete, repo, come)
            print("          pagine pronte, push fermo: %s" % come)
    elif codice == 0:
        _segna(chiave, {"tipo": "pubblicazione", "giornate": c.complete})
        testo = testo_giro_finito(lega, stagione, repo)
        print("          giro finito: restano il README e il commit.")
    else:
        testo = testo_giro_fermo(alias, lega, stagione, codice, coda)
        print("          giro fermo (codice %d)." % codice)

    try:
        manda(testo)
    except NonConfigurato as e:
        print("          non mandato: %s" % str(e).splitlines()[0])
    return codice


# ════════════════════════════════════════════════════════════════════════════
def controlla(alias: str, stagione: str | None, soglia: int, preavviso_ore: int,
              manda_davvero: bool, forza: bool, pubblica: bool = False) -> int:
    lega = LEGHE[alias]
    stagione = stagione or stagione_da_guardare()

    c = leggi_calendario(lega, stagione, soglia)
    print("%-9s %s: %s" % (alias, stagione, c))
    if not c.ok:
        # Un calendario irraggiungibile non e' un avviso mancato: e' un giro
        # saltato. Non si segna niente, e domani si riprova.
        return 1

    # La soglia vale per il PRIMO giro di una stagione: quante giornate servono
    # perche' pubblicare l'indice abbia senso. Dopo non c'entra piu' niente —
    # una stagione gia' pubblicata si aggiorna a ogni giornata che chiude, e
    # riapplicare la soglia vorrebbe dire tenere il sito fermo ai numeri vecchi
    # per un motivo che riguardava solo il debutto.
    inizio = "%s|%s|pubblicazione" % (lega, stagione)
    gia_pubblicata = any(k.startswith(inizio) for k in _leggi_stato())

    if c.complete >= soglia or gia_pubblicata:
        # Il via libera con le mani in mano, oppure il giro fatto davvero.
        if pubblica:
            if not manda_davvero:
                print("          (--stato) qui farei il giro: "
                      "python pubblica.py --lega %s --stagione %s --esegui"
                      % (alias, stagione))
                return 0
            return fai_il_giro(alias, lega, stagione, c, forza)
        tipo, testo = "via-libera", testo_via_libera(alias, lega, stagione, c)
    elif c.chiusura and c.chiusura - adesso() <= timedelta(hours=preavviso_ore):
        tipo, testo = "preavviso", testo_preavviso(lega, stagione, c)
    else:
        if c.chiusura:
            mancano = (c.chiusura - adesso()) - timedelta(hours=preavviso_ore)
            ore = int(mancano.total_seconds() // 3600)
            print("          preavviso fra %s."
                  % ("%d ore" % ore if ore < 48 else "%d giorni" % (ore // 24)))
        return 0

    chiave = "%s|%s|%s" % (lega, stagione, tipo)
    gia = _leggi_stato().get(chiave)
    if gia and not forza:
        print("          %s gia' mandato il %s: sto zitto."
              % (tipo, (gia.get("mandato") or "")[:10]))
        return 0

    if not manda_davvero:
        print("          (--stato) messaggio che manderei (%s):" % tipo)
        print("\n".join("          | " + r for r in testo.splitlines()))
        return 0

    try:
        manda(testo)
    except NonConfigurato as e:
        print("          non mandato: %s" % str(e).splitlines()[0])
        return 1
    _segna(chiave, {"tipo": tipo, "giornate": c.complete})
    print("          %s mandato." % tipo)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Legge il calendario e avvisa su Telegram quando il "
                    "campionato ha giocato abbastanza per pubblicare.")
    ap.add_argument("--lega", choices=sorted(LEGHE), help="premier | serie-a")
    ap.add_argument("--tutte", action="store_true", help="tutti i campionati")
    ap.add_argument("--stagione",
                    help="es. 2026-27 (default: quella che si sta giocando ora)")
    ap.add_argument("--giornate", type=int, default=6,
                    help="quante giornate servono per il PRIMO giro di una "
                         "stagione (default 6). Dopo non conta: una stagione "
                         "gia' pubblicata si aggiorna a ogni giornata.")
    ap.add_argument("--preavviso", type=int, default=72, metavar="ORE",
                    help="quanto prima avvisare che la giornata sta per "
                         "chiudersi (default 72; 0 = mai)")
    ap.add_argument("--stato", action="store_true",
                    help="legge e stampa, senza mandare niente")
    ap.add_argument("--forza", action="store_true",
                    help="manda anche se l'ha gia' mandato")
    ap.add_argument("--pubblica", action="store_true",
                    help="al via libera non scrive il comando: lo esegue. "
                         "Si ferma prima del commit e del push")
    ap.add_argument("--configura", action="store_true",
                    help="prepara il bot passo per passo e scrive .env")
    ap.add_argument("--bot", action="store_true",
                    help="controlla che il bot risponda, senza mandare messaggi")
    ap.add_argument("--prova", action="store_true",
                    help="manda un messaggio di prova e finisce")
    ap.add_argument("--chat-id", action="store_true",
                    help="stampa i chat_id di chi ha scritto al bot")
    a = ap.parse_args()

    if a.configura:
        return configura()
    if a.bot:
        return prova_bot()
    if a.chat_id:
        return stampa_chat_id()
    if a.prova:
        manda("Sentinella — collegata.\n\n"
              "Da qui ti scrivo quando il campionato ha giocato abbastanza per "
              "pubblicare la stagione nuova, e qualche giorno prima per dirti "
              "quando si chiude la giornata che manca.")
        print("Messaggio di prova mandato.")
        return 0

    if a.tutte:
        alias = sorted(LEGHE)
    elif a.lega:
        alias = [a.lega]
    else:
        ap.error("serve --lega, oppure --tutte")

    peggio = 0
    for nome in alias:
        peggio = max(peggio, controlla(nome, a.stagione, a.giornate, a.preavviso,
                                       manda_davvero=not a.stato, forza=a.forza,
                                       pubblica=a.pubblica))
    return peggio


if __name__ == "__main__":
    sys.exit(main())
