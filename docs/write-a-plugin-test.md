# How do I... write a plugin test

Tests run fully offline. Unit tests hit a plugin's innards directly; the
integration layer drives the real lightbulb/hikari pipeline. Verify
interactive changes there, not just with direct handler calls.

## 1. Unit tests (tests/core or tests/plugins)

Pure logic and repository layers take `db`/`settings` + plain values, so
test them directly:

```python
import pytest

from tests.fakes import FakeRest


async def test_logic(db):
    result = my_logic.calculate(...)
    assert result == expected
```

Service modules must stay framework-agnostic (`tests/core/test_csr_boundary.py`
enforces it).

## 2. Integration tests (tests/integration)

Use the offline driver for slash, buttons and modals:

```python
from tests.driver import run_slash, press_button, submit_modal


async def test_my_flow(full_bot):
    result = await run_slash(full_bot, "badges give", options={...}, user_id=1)
    press = await press_button(full_bot, custom_id="badges:yes", message_id=...)
    modal = await submit_modal(full_bot, custom_id="poll:submit:1", values={...})
```

- `full_bot` (`tests/conftest.py`) boots every plugin — the real path any
  event takes, minus the network.
- Driver helpers: `run_slash`, `press_button`, `submit_modal`,
  `wait_for_menu`, `wait_for_modal`, `attached_buttons`.
- The `counter` flow is the reference: `tests/integration/test_counter_driver.py`.

## 3. What to check

- `full_bot` boots every plugin, so a plugin that fails to load breaks it —
  fix the load, don't delete the test.
- New guild-scoped listeners must use `cazzubot.listeners.guild_listener`
  (`tests/core/test_listeners.py`).
- Run the guard sweep after any command change:
  `tests/core/test_command_guards.py` + `tests/integration/test_guard_driver.py`.

## 4. Run

```sh
uv run pytest                       # whole suite
uv run pytest tests/integration/test_my_plugin_driver.py -k my_flow
```
