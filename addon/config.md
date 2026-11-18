**Ask About Card** – settings

The answers come from the Codex CLI (OpenAI's command-line program), which must be installed and signed in on
this computer. The add-on only starts that program; it never reads or stores your sign-in.

- `codex_path`: leave empty and the program is searched for. If it is not found, enter its full path here (in a
  terminal, `which codex` prints it).
- `model`: empty = the program's default model.
- `timeout_seconds`: 10 to 1800. After that the request is ended; your question stays in the box.
- `shortcut`: works while reviewing. On a Mac, `Ctrl` means the ⌘ key. Empty = no shortcut.
- `explain_on_highlight`: `true` = highlighting text on a card with the mouse opens the window and explains that
  part by itself. Every highlight then sends a request. Quicker to switch: menu *Tools* →
  "Ask About Card: explain on highlight".
- `highlight_min_chars`: the highlighted part must have at least this many characters (default 3).
- `save_folder`: conversations are saved here as Markdown files. Empty = do not save.
- `answer_language`: for example `"German"`. Empty = the answer is in the language of your question.

Changes apply to the next question window; a new shortcut applies after you next enter review mode.
