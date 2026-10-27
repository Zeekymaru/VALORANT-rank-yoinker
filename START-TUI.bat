@echo off
:: Starts the Textual TUI. Pass --demo to see a fake lobby without VALORANT running.
cd /d "%~dp0"
if exist "venv-tui\Scripts\python.exe" (
    "venv-tui\Scripts\python.exe" "tui.py" %*
) else (
    echo venv-tui not found. Create it first, see "TUI (experimental)" in README.md
)
pause
