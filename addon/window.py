"""The part of "Ask About Card" that lives inside Anki: menu entries, shortcut and the question window.

All the working out and saving is in core.py. Here the card is only read (never changed), the window is shown
and the request is started in the background so that Anki does not freeze.
"""
from __future__ import annotations

import html
import threading
import traceback
from datetime import datetime
from pathlib import Path

from aqt import mw
from aqt.qt import (QComboBox, QDialog, QHBoxLayout, QKeySequence, QLabel, QPlainTextEdit, QPushButton,
                    QShortcut, Qt, QVBoxLayout)
from aqt.utils import restoreGeom, saveGeom, tooltip
from aqt.webview import AnkiWebView

from . import core

ADDON = __name__.split(".")[0]
LOG = Path(__file__).resolve().parent / "user_files" / "errors.log"
_windows: list["AskWindow"] = []         # keep open windows alive, otherwise Python tidies them away

STYLE = """<style>
body { margin: 12px 16px; font-size: 15px; line-height: 1.5; }
.question { border-left: 3px solid var(--border-strong, #888); padding: 2px 10px; margin: 18px 0 8px; opacity: .85;
            white-space: pre-wrap; }
.question:first-child { margin-top: 4px; }
.mode { font-size: 12px; opacity: .6; margin-bottom: 4px; }
.answer pre { padding: 8px; overflow-x: auto; border: 1px solid var(--border, #ccc); border-radius: 4px; }
.answer table { border-collapse: collapse; } .answer td, .answer th { border: 1px solid var(--border, #ccc); padding: 3px 8px; }
.waiting { opacity: .6; font-style: italic; }
</style>"""
# Anki's MathJax does not typeset by itself (startup.typeset = false), so it is triggered here.
AFTER_LOADING = """<script>
window.addEventListener('load', function () {
  function down() { window.scrollTo(0, document.body.scrollHeight); }
  try {
    if (window.MathJax && MathJax.startup && MathJax.startup.promise) {
      MathJax.startup.promise.then(function () { return MathJax.typesetPromise(); }).then(down, down);
    } else { down(); }
  } catch (e) { down(); }
});
</script>"""


def log(*parts) -> None:
    """Write the add-on's own errors to a file; never show them as a dialog (Anki may be started unattended)."""
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} " + " ".join(str(p) for p in parts) + "\n")
    except Exception:
        pass


def load_settings() -> dict:
    try:
        raw = mw.addonManager.getConfig(ADDON)
    except Exception:
        raw = None
    return core.settings(raw)


def current_card() -> dict | None:
    """The card that is being reviewed right now, as text. None when no card is open."""
    r = mw.reviewer
    c = getattr(r, "card", None)
    if mw.state != "review" or c is None:
        return None
    front, back = core.card_from_html(c.question(), c.answer())
    try:
        selection = core.selection_text(r.web.selectedText())
    except Exception:
        selection = ""
    try:
        deck = core.clean(mw.col.decks.name(c.odid or c.did))
    except Exception:
        deck = ""
    return {"front": front, "back": back, "selection": selection, "deck": deck,
            "nid": c.nid, "cid": c.id, "back_visible": getattr(r, "state", "") == "answer"}


class AskWindow(QDialog):
    def __init__(self, card: dict, s: dict):
        super().__init__(mw, Qt.WindowType.Window)
        self.s = s
        self.folder = core.save_folder(s)
        self.conv = {"card": card, "turns": [], "file": None}
        self.running = False
        self.closed = False
        self.pending: dict | None = None
        self.cancel = threading.Event()

        self.setWindowTitle("Ask About Card")
        about = card["selection"] or card["front"] or "(empty card)"
        head = QLabel(("Highlighted part: " if card["selection"] else "Whole card: ") + " ".join(about.split())[:140])
        head.setWordWrap(True)
        head.setTextFormat(Qt.TextFormat.PlainText)
        self.web = AnkiWebView(self, title="Ask About Card")
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Your question about the card …   (Ctrl+Enter sends it; ⌘↩ on a Mac)")
        self.input.setFixedHeight(84)
        self.input.setTabChangesFocus(True)
        self.mode = QComboBox()
        for key, name in core.MODES.items():
            self.mode.addItem(name, key)
        self.button = QPushButton("Ask")
        self.button.setDefault(False)
        self.button.setAutoDefault(False)
        self.button.clicked.connect(self.button_pressed)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)

        bottom = QHBoxLayout()
        bottom.addWidget(self.mode)
        bottom.addStretch(1)
        bottom.addWidget(self.button)
        everything = QVBoxLayout(self)
        everything.addWidget(head)
        everything.addWidget(self.web, 1)
        everything.addWidget(self.input)
        everything.addLayout(bottom)
        everything.addWidget(self.status)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.send)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self.send)
        self.resize(640, 620)
        restoreGeom(self, "askAboutCard")
        self.show_conversation()
        self.input.setFocus()

    # ---------------------------------------------------------------- display
    def show_conversation(self) -> None:
        parts = []
        for turn in self.conv["turns"]:
            parts.append(f'<div class="question">{html.escape(turn["question"])}</div>'
                         f'<div class="mode">{html.escape(core.MODES.get(turn["mode"], ""))}</div>'
                         f'<div class="answer">{core.answer_html(turn["answer"])}</div>')
        if self.pending:
            parts.append(f'<div class="question">{html.escape(self.pending["question"])}</div>'
                         '<div class="waiting">Codex is answering …</div>')
        if not parts:
            where = (f"The answer appears here and is saved in “{html.escape(str(self.folder))}”."
                     if self.folder is not None else "The answer appears here. Conversations are not saved.")
            parts.append(f'<div class="waiting">Ask your question below. {where}</div>')
        self.web.stdHtml(STYLE + "".join(parts) + AFTER_LOADING,
                         js=["js/mathjax.js", "js/vendor/mathjax/tex-chtml-full.js"])

    def say(self, text: str) -> None:
        self.status.setText(text)

    # ---------------------------------------------------------------- flow
    def button_pressed(self) -> None:
        if self.running:
            self.cancel.set()
            self.say("Cancelling …")
        else:
            self.send()

    def send(self) -> None:
        question = core.clean(self.input.toPlainText()).strip()
        if self.running or not question:
            return
        mode = self.mode.currentData() or "explain"
        history = [(t["question"], t["answer"]) for t in self.conv["turns"]]
        try:
            prompt = core.build_prompt(question, mode, self.conv["card"], history, self.s["answer_language"])
        except core.Error as e:
            self.say(str(e))
            return
        self.running = True
        self.cancel = threading.Event()
        cancel, s = self.cancel, self.s
        self.pending = {"question": question, "mode": mode}
        self.button.setText("Cancel")
        self.input.setReadOnly(True)
        self.say(f"Codex is working … (at most {s['timeout_seconds']} seconds)")
        self.show_conversation()
        mw.taskman.run_in_background(lambda: core.ask_ai(prompt, s, cancel), self.done_asking, uses_collection=False)

    def done_asking(self, future) -> None:
        """Runs in Anki's main thread again as soon as the answer is there (or an error)."""
        if self.closed:
            return
        try:
            self.running = False
            pending, self.pending = self.pending or {}, None
            self.button.setText("Ask")
            self.input.setReadOnly(False)
            try:
                raw = future.result()
            except core.Error as e:
                self.say(str(e))
                self.show_conversation()
                return
            turn = {"question": pending.get("question", ""), "mode": pending.get("mode", "explain"),
                    "answer": core.clean(raw).strip(), "time": datetime.now()}
            self.conv["turns"].append(turn)
            self.input.clear()
            self.show_conversation()     # show the answer first; saving must never hide it
            self.input.setFocus()
            message = ""
            if self.folder is not None:
                try:
                    path = core.save(self.conv, self.folder)
                    message = f"Saved: {path.name}"
                except core.Error as e:
                    message = str(e)
                except Exception:
                    log("save:", traceback.format_exc())
                    message = "The conversation could not be saved (details in user_files/errors.log)."
            self.say(message)
        except Exception:
            log("done_asking:", traceback.format_exc())
            try:
                self.say("Unexpected error; the details are in the add-on's user_files/errors.log.")
            except Exception:
                pass

    def shut(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.cancel.set()           # end a running request, nobody is waiting for it any more
        try:
            saveGeom(self, "askAboutCard")
        except Exception:
            pass
        if self in _windows:
            _windows.remove(self)
        if self in _auto:
            _auto.remove(self)

    def closeEvent(self, event) -> None:
        self.shut()
        super().closeEvent(event)

    def reject(self) -> None:       # Esc
        self.shut()
        super().reject()


# ---------------------------------------------------------------- entry points from Anki
def open_window(*_args) -> None:
    """Open the question window for the current card. Called from the menu, the right click and the shortcut."""
    try:
        card = current_card()
        if card is None:
            tooltip("“Ask About Card” only works while you are reviewing a card.")
            return
        w = AskWindow(card, load_settings())
        _windows.append(w)
        w.show()
        w.raise_()
        w.activateWindow()
    except Exception:
        log("open_window:", traceback.format_exc())
        try:
            tooltip("“Ask About Card” could not open; details are in the add-on's user_files/errors.log.")
        except Exception:
            pass


# ---------------------------------------------------------------- explain on highlight
_auto: list["AskWindow"] = []            # at most one window that was opened by highlighting


def highlighted() -> None:
    """Text was highlighted on the card: open the window and have that part explained straight away. Follow-up
    questions can be asked in the window. A new highlight replaces the previous highlight window."""
    s = load_settings()
    if not s["explain_on_highlight"]:
        return
    card = current_card()
    if card is None or len(card["selection"]) < s["highlight_min_chars"]:
        return
    for old in list(_auto):
        if (not old.closed and old.conv["card"]["cid"] == card["cid"]
                and old.conv["card"]["selection"] == card["selection"]):
            old.raise_()                 # the same part highlighted again: only bring the window to the front
            return
        old.close()                      # also ends a request that is still running
        if old in _auto:
            _auto.remove(old)
    w = AskWindow(card, s)
    w.setWindowTitle("Ask About Card · highlighted part")
    _windows.append(w)
    _auto.append(w)
    w.show()
    w.raise_()
    w.activateWindow()
    w.input.setPlainText(core.auto_question(card["selection"]))
    w.send()


def add_to_page(web_content, context) -> None:
    """When Anki builds the card page: add the small script that reports a highlight."""
    try:
        if context is not None and context is getattr(mw, "reviewer", None):
            s = load_settings()
            web_content.head += "<script>" + core.highlight_js(s["highlight_min_chars"]) + "</script>"
    except Exception:
        log("add_to_page:", traceback.format_exc())


def js_message(handled, message, context):
    """Messages from the card page. Only the add-on's own ("aac:…") are taken; everything else stays with Anki."""
    if not isinstance(message, str) or not message.startswith("aac:"):
        return handled
    try:
        if message == "aac:highlighted" and context is getattr(mw, "reviewer", None):
            highlighted()
    except Exception:
        log("js_message:", traceback.format_exc())
    return (True, None)


def toggle_highlight(on: bool) -> None:
    """Menu entry with a tick: switch "explain on highlight" on or off and remember it."""
    try:
        conf = dict(mw.addonManager.getConfig(ADDON) or {})
        conf["explain_on_highlight"] = bool(on)
        mw.addonManager.writeConfig(ADDON, conf)
        tooltip("Explain on highlight: " + ("on" if on else "off"))
    except Exception:
        log("toggle_highlight:", traceback.format_exc())


def register() -> None:
    """Once when Anki starts: register the entry points. Opens nothing and starts nothing."""
    from aqt import gui_hooks
    from aqt.qt import QAction

    gui_hooks.reviewer_will_show_context_menu.append(context_menu)
    gui_hooks.state_shortcuts_will_change.append(shortcut)
    gui_hooks.webview_will_set_content.append(add_to_page)
    gui_hooks.webview_did_receive_js_message.append(js_message)
    action = QAction("Ask About Card …", mw)
    action.triggered.connect(open_window)
    mw.form.menuTools.addAction(action)
    tick = QAction("Ask About Card: explain on highlight", mw)
    tick.setCheckable(True)
    tick.setChecked(load_settings()["explain_on_highlight"])
    tick.toggled.connect(toggle_highlight)
    mw.form.menuTools.addAction(tick)


def context_menu(reviewer, menu) -> None:
    try:
        action = menu.addAction("Ask About Card …")
        action.triggered.connect(open_window)
    except Exception:
        log("context_menu:", traceback.format_exc())


def shortcut(state, shortcuts) -> None:
    try:
        key = load_settings()["shortcut"]
        if state == "review" and key:
            shortcuts.append((key, open_window))
    except Exception:
        log("shortcut:", traceback.format_exc())
