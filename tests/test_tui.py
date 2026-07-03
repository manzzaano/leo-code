"""La TUI arranca headless, acepta comandos y el historial ↑ recupera el input."""

import pytest

from leo_code.rag.cli.tui import LeoTUI, PromptInput


@pytest.mark.asyncio
async def test_boot_help_and_history(tmp_path):
    (tmp_path / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    app = LeoTUI(repo=str(tmp_path))
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", PromptInput)
        prompt.value = "/help"
        await pilot.press("enter")
        await pilot.pause()
        assert prompt.value == ""              # input limpiado tras enviar
        assert prompt.history == ["/help"]
        await pilot.press("up")                # historial recupera el último
        assert prompt.value == "/help"
        await pilot.press("down")
        assert prompt.value == ""
