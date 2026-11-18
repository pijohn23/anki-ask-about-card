"""Ask About Card: ask a question about the Anki card you are reviewing; the Codex CLI on this computer answers.
Never changes a card.

When Anki starts, only one thing happens here: the menu entries, the right-click entry, the shortcut and the
highlight reporting are registered (window.register). No window, no internet, no program is started. If
something goes wrong, it is written to `user_files/errors.log` and Anki starts normally.
"""

try:
    import aqt

    if getattr(aqt, "mw", None) is not None:   # do nothing outside Anki (tests)
        from . import window

        window.register()
except Exception:
    try:
        import traceback
        from datetime import datetime
        from pathlib import Path

        target = Path(__file__).resolve().parent / "user_files" / "errors.log"
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} start: {traceback.format_exc()}\n")
    except Exception:
        pass
