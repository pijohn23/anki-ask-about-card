#!/usr/bin/env python3
"""Tests for the Anki part (addon/__init__.py, addon/window.py) with Anki's real Python modules, but without
starting Anki: invisible (Qt "offscreen"), with a rebuilt main window, a stand-in program instead of Codex,
throw-away folders and a dummy instead of the formula view (no second browser engine is started).

Needs Anki's own Python, for example on a Mac:
  "$HOME/Library/Application Support/AnkiProgramFiles/.venv/bin/python" -B tests/test_window.py
With any other Python the tests are skipped.
"""
import importlib.util
import os
import stat
import sys
import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent

try:
    import aqt
    from aqt import gui_hooks
    from aqt.qt import QApplication, QMenu, QWidget
    WITH_ANKI = True
except Exception:                                   # another Python without Anki
    WITH_ANKI = False

sys.path.insert(0, str(ROOT / "tests"))
from test_core import FAKE_CODEX  # noqa: E402

DECK = "Maths::Measure Theory::Chapter 1"
PACKAGE = "ask_about_card"


class Card:
    id, nid, did, odid = 18, 17, 5, 0

    def question(self):
        return "<div>What is a measure?</div>"

    def answer(self):
        return "<div>What is a measure?</div><hr id=answer><div>A σ-additive function \\(\\mu\\).</div>"


class AtOnce:
    """Stand-in for Anki's background helper: runs the task immediately and reports the result."""

    def run_in_background(self, task, on_done=None, uses_collection=True):
        f = Future()
        try:
            f.set_result(task())
        except Exception as e:
            f.set_exception(e)
        self.last_uses_collection = uses_collection
        if on_done:
            on_done(f)


@unittest.skipUnless(WITH_ANKI, "needs Anki's own Python")
class Window(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["test"])
        cls.tmp = tempfile.TemporaryDirectory()
        t = cls.t = Path(cls.tmp.name).resolve()
        cls.saved = t / "Anki Questions"
        codex = t / "codex"
        codex.write_text(FAKE_CODEX, encoding="utf-8")
        codex.chmod(codex.stat().st_mode | stat.S_IXUSR)

        mw = cls.mw = QWidget()
        mw.state = "deckBrowser"
        mw.taskman = AtOnce()
        mw.form = type("Form", (), {})()
        mw.form.menuTools = QMenu(mw)
        mw.col = type("Col", (), {})()
        mw.col.decks = type("Decks", (), {"name": staticmethod(lambda did: DECK)})()
        mw.reviewer = type("Reviewer", (), {})()
        mw.reviewer.card = Card()
        mw.reviewer.state = "answer"
        mw.reviewer.web = type("Web", (), {"selectedText": staticmethod(lambda: " σ-additive ")})()
        cls.config = {"codex_path": str(codex), "save_folder": str(cls.saved)}
        mw.addonManager = type("AM", (), {
            "getConfig": staticmethod(lambda module: dict(cls.config)),
            "writeConfig": staticmethod(lambda module, conf: cls.config.update(conf))})()
        cls.mw_before = aqt.mw
        aqt.mw = mw

        cls.hooks = (gui_hooks.reviewer_will_show_context_menu, gui_hooks.state_shortcuts_will_change,
                     gui_hooks.webview_will_set_content, gui_hooks.webview_did_receive_js_message)
        cls.before = [list(h._hooks) for h in cls.hooks]
        spec = importlib.util.spec_from_file_location(
            PACKAGE, ROOT / "addon" / "__init__.py", submodule_search_locations=[str(ROOT / "addon")])
        package = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE] = package
        spec.loader.exec_module(package)                             # registers itself as when Anki starts
        cls.window = sys.modules[PACKAGE + ".window"]
        cls.core = sys.modules[PACKAGE + ".core"]

        class WebDummy(QWidget):
            def __init__(self, parent=None, title=""):
                super().__init__(parent)
                self.pages = []

            def stdHtml(self, body, css=None, js=None, head="", context=None, default_css=True):
                self.pages.append((body, js))

        cls.tooltips = []
        cls.window.AnkiWebView = WebDummy
        cls.window.tooltip = lambda text, *a, **k: cls.tooltips.append(text)
        cls.window.restoreGeom = lambda *a, **k: None
        cls.window.saveGeom = lambda *a, **k: None
        cls.window.LOG = t / "errors.log"

    @classmethod
    def tearDownClass(cls):
        for h, old in zip(cls.hooks, cls.before):
            h._hooks[:] = old
        aqt.mw = cls.mw_before
        for name in [n for n in sys.modules if n.startswith(PACKAGE)]:
            del sys.modules[name]
        cls.tmp.cleanup()

    def setUp(self):
        self.mw.state = "review"
        self.mw.reviewer.state = "answer"
        del self.tooltips[:]
        self.config.update(explain_on_highlight=True, highlight_min_chars=3, save_folder=str(self.saved))
        self.mw.reviewer.web.selectedText = staticmethod(lambda: " σ-additive ")

    def tearDown(self):
        for w in list(self.window._windows):
            w.close()

    def open(self):
        self.window.open_window()
        self.assertEqual(len(self.window._windows), 1, self.error_log())
        return self.window._windows[-1]

    def error_log(self):
        p = self.t / "errors.log"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def files(self):
        return sorted(self.saved.glob("*.md")) if self.saved.exists() else []

    def test_registration_at_start(self):
        self.assertIn(self.window.context_menu, gui_hooks.reviewer_will_show_context_menu._hooks)
        self.assertIn(self.window.shortcut, gui_hooks.state_shortcuts_will_change._hooks)
        self.assertIn(self.window.add_to_page, gui_hooks.webview_will_set_content._hooks)
        self.assertIn(self.window.js_message, gui_hooks.webview_did_receive_js_message._hooks)
        entries = {a.text(): a for a in self.mw.form.menuTools.actions()}
        self.assertIn("Ask About Card …", entries)
        tick = entries["Ask About Card: explain on highlight"]
        self.assertTrue(tick.isCheckable())
        self.assertFalse(tick.isChecked())                           # off unless the user switches it on
        self.assertEqual(self.window._windows, [])                   # no window opens at start
        self.assertEqual(self.error_log(), "")

    def test_shortcut_only_while_reviewing(self):
        found = []
        self.window.shortcut("deckBrowser", found)
        self.assertEqual(found, [])
        self.window.shortcut("review", found)
        self.assertEqual(found, [("Ctrl+Shift+F", self.window.open_window)])

    def test_right_click_entry(self):
        menu = QMenu()
        self.window.context_menu(self.mw.reviewer, menu)
        self.assertEqual([a.text() for a in menu.actions()], ["Ask About Card …"])

    def test_without_a_card_only_a_note(self):
        self.mw.state = "deckBrowser"
        self.window.open_window()
        self.assertEqual(self.window._windows, [])
        self.assertIn("while you are reviewing a card", self.tooltips[0])

    def test_question_answer_and_saving(self):
        before = len(self.files())
        w = self.open()
        k = w.conv["card"]
        self.assertEqual((k["front"], k["back"]), ("What is a measure?", "A σ-additive function \\(\\mu\\)."))
        self.assertEqual((k["selection"], k["deck"], k["nid"], k["cid"]), ("σ-additive", DECK, 17, 18))
        self.assertTrue(k["back_visible"])
        self.assertIn("Ask your question below", w.web.pages[-1][0])
        self.assertIn("Anki Questions", w.web.pages[-1][0])

        w.input.setPlainText("Why σ-additive and not just finitely additive?")
        w.send()
        self.assertEqual(self.error_log(), "")
        self.assertFalse(self.mw.taskman.last_uses_collection)      # does not block Anki's collection
        self.assertEqual(len(w.conv["turns"]), 1)
        turn = w.conv["turns"][0]
        self.assertEqual(turn["answer"], "Answer to: Why σ-additive and not just finitely additive?")
        self.assertEqual(w.input.toPlainText(), "")
        self.assertFalse(w.running)
        self.assertEqual(w.button.text(), "Ask")
        page, js = w.web.pages[-1]
        self.assertIn("Answer to: Why σ-additive", page)
        self.assertEqual(js, ["js/mathjax.js", "js/vendor/mathjax/tex-chtml-full.js"])
        self.assertEqual(len(self.files()), before + 1)
        path = self.saved / w.conv["file"]
        self.assertIn("> σ-additive", path.read_text(encoding="utf-8"))
        self.assertEqual(w.status.text(), f"Saved: {path.name}")

        w.input.setPlainText("And a counterexample?")                # follow-up: same file
        w.mode.setCurrentIndex(1)
        w.send()
        self.assertEqual([t["mode"] for t in w.conv["turns"]], ["explain", "hint"])
        self.assertEqual(len(self.files()), before + 1)
        self.assertIn("## Follow-up", path.read_text(encoding="utf-8"))

    def test_saving_can_be_switched_off(self):
        self.config["save_folder"] = ""
        before = len(self.files())
        w = self.open()
        self.assertIn("Conversations are not saved", w.web.pages[-1][0])
        w.input.setPlainText("Why?")
        w.send()
        self.assertEqual(len(w.conv["turns"]), 1)
        self.assertEqual(w.status.text(), "")
        self.assertEqual(len(self.files()), before)
        self.assertEqual(self.error_log(), "")

    def test_an_error_leaves_the_question_in_place(self):
        w = self.open()
        w.input.setPlainText("BROKEN please")
        w.send()
        self.assertEqual(w.conv["turns"], [])
        self.assertEqual(w.input.toPlainText(), "BROKEN please")
        self.assertIn("not signed in", w.status.text())
        self.assertFalse(w.running)
        self.assertFalse(w.input.isReadOnly())

    def test_cancel_and_close(self):
        w = self.open()
        w.running = True
        w.button_pressed()                                           # the button then says "Cancel"
        self.assertTrue(w.cancel.is_set())
        w.running = False
        w.close()
        self.assertTrue(w.closed)
        self.assertEqual(self.window._windows, [])
        late = Future()
        late.set_result("too late")
        w.done_asking(late)                                          # answer after closing: nothing happens
        self.assertEqual(w.conv["turns"], [])

    def test_highlighted_formula_with_half_a_character(self):
        self.mw.reviewer.web.selectedText = staticmethod(lambda: "atoms of \ud835 and 𝒜")
        w = self.open()
        self.assertEqual(w.conv["card"]["selection"], "atoms of � and 𝒜")
        w.input.setPlainText("explain")
        w.send()
        self.assertEqual(self.error_log(), "")
        self.assertTrue(w.status.text().startswith("Saved: "))
        self.assertIn("> atoms of � and 𝒜", (self.saved / w.conv["file"]).read_text(encoding="utf-8"))

    def test_a_saving_error_does_not_hide_the_answer(self):
        real = self.core.save

        def broken(*a, **k):
            raise ValueError("disk full")
        self.core.save = broken
        try:
            w = self.open()
            w.input.setPlainText("Why?")
            w.send()
            self.assertIn("Answer to: Why?", w.web.pages[-1][0])     # the answer is there all the same
            self.assertEqual(len(w.conv["turns"]), 1)
            self.assertIn("could not be saved", w.status.text())
            self.assertIn("disk full", self.error_log())
            self.assertFalse(w.running)
        finally:
            self.core.save = real
            (self.t / "errors.log").unlink(missing_ok=True)

    # ---------------------------------------------------------------- explain on highlight
    def highlight(self, text):
        self.mw.reviewer.web.selectedText = staticmethod(lambda: text)
        return self.window.js_message((False, None), "aac:highlighted", self.mw.reviewer)

    def test_highlighting_opens_the_window_and_explains_by_itself(self):
        self.assertEqual(self.highlight("first the union \n{\n2\n,\n3\n,\n4\n}"), (True, None))
        self.assertEqual(self.error_log(), "")
        (w,) = self.window._windows
        self.assertEqual(self.window._auto, [w])
        self.assertEqual(w.windowTitle(), "Ask About Card · highlighted part")
        self.assertEqual(w.conv["card"]["selection"], "first the union {2,3,4}")
        (turn,) = w.conv["turns"]                                    # asked and answered without typing
        self.assertEqual(turn["question"], "Briefly explain the highlighted part: “first the union {2,3,4}”")
        self.assertIn("Answer to: Briefly explain the highlighted part", w.web.pages[-1][0])
        self.assertEqual(w.input.toPlainText(), "")                  # free for a follow-up
        self.assertTrue(w.status.text().startswith("Saved: "))
        w.input.setPlainText("And why the complements?")
        w.send()
        self.assertEqual(len(w.conv["turns"]), 2)

    def test_a_new_highlight_replaces_the_highlight_window(self):
        self.highlight("first part")
        (first,) = self.window._auto
        self.highlight("first part")                                 # same part: no second window, no new request
        self.assertEqual(self.window._auto, [first])
        self.assertEqual(len(first.conv["turns"]), 1)
        self.highlight("second part")
        (second,) = self.window._auto
        self.assertIsNot(second, first)
        self.assertTrue(first.closed)
        self.assertEqual(self.window._windows, [second])
        self.assertEqual(second.conv["card"]["selection"], "second part")

    def test_highlighting_does_nothing_when_off_too_short_or_foreign(self):
        self.assertEqual(self.highlight("ab"), (True, None))         # shorter than highlight_min_chars
        self.assertEqual(self.window._windows, [])
        self.config["explain_on_highlight"] = False
        self.assertEqual(self.highlight("long enough"), (True, None))
        self.assertEqual(self.window._windows, [])
        self.config["explain_on_highlight"] = True
        foreign = object()                                           # message from another Anki window
        self.assertEqual(self.window.js_message((False, None), "aac:highlighted", foreign), (True, None))
        self.assertEqual(self.window._windows, [])
        self.mw.state = "deckBrowser"                                # no card open right now
        self.highlight("long enough")
        self.assertEqual(self.window._windows, [])
        self.assertEqual(self.error_log(), "")

    def test_other_messages_stay_with_anki(self):
        before = (False, None)
        self.assertIs(self.window.js_message(before, "ease3", self.mw.reviewer), before)
        self.assertIs(self.window.js_message(before, "ans", self.mw.reviewer), before)
        self.assertEqual(self.window._windows, [])

    def test_script_goes_only_onto_the_card_page(self):
        page = type("WebContent", (), {"head": "<x>", "body": "", "js": [], "css": []})()
        self.window.add_to_page(page, object())                      # another window (for example the browser)
        self.assertEqual(page.head, "<x>")
        self.window.add_to_page(page, None)
        self.assertEqual(page.head, "<x>")
        self.window.add_to_page(page, self.mw.reviewer)
        self.assertTrue(page.head.startswith("<x><script>(function () {"))
        self.assertIn('pycmd("aac:highlighted")', page.head)
        self.assertIn("s.length < 3", page.head)

    def test_menu_switch_remembers_the_choice(self):
        self.window.toggle_highlight(False)
        self.assertFalse(self.config["explain_on_highlight"])
        self.assertEqual(self.tooltips[-1], "Explain on highlight: off")
        self.highlight("long enough")
        self.assertEqual(self.window._windows, [])
        self.window.toggle_highlight(True)
        self.assertTrue(self.config["explain_on_highlight"])
        self.highlight("long enough")
        self.assertEqual(len(self.window._windows), 1)

    def test_front_only(self):
        self.mw.reviewer.state = "question"
        w = self.open()
        self.assertFalse(w.conv["card"]["back_visible"])


if __name__ == "__main__":
    unittest.main()
