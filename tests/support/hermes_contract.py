# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Call a plugin hook the way the recorded Hermes version does. The shapes are data in tests/contract/."""

import inspect
import json
import os

CONTRACT = json.load(
    open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "contract", "hermes-hooks.json"),
        encoding="utf-8",
    )
)


def payload(event: str, **values) -> dict:
    spec = CONTRACT["events"][event]
    unknown = set(values) - set(spec["kwargs"])
    if unknown:
        raise KeyError(f"{event} does not send {sorted(unknown)}")
    data = {key: "" for key in spec["kwargs"]}
    data.update(spec.get("defaults") or {})
    data["telemetry_schema_version"] = CONTRACT["telemetry_schema_version"]
    data.update(values)
    return data


def call(fn, event: str, **values):
    """Keyword-only, like Hermes. A callback without **kwargs gets only the keys it names."""
    data = payload(event, **values)
    params = inspect.signature(fn).parameters
    if not any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()):
        data = {key: value for key, value in data.items() if key in params}
    return fn(**data)


def block_message(result):
    """The text Hermes would show for this block, or None when Hermes would ignore it."""
    if not isinstance(result, dict) or result.get("action") != "block":
        return None
    message = result.get("message")
    return message if isinstance(message, str) and message else None


def as_hermes_process(monkeypatch) -> None:
    """Run the rest of a test as if inside Hermes's process, where the plugin's hooks run: Hermes's modules
    (here the recorded fakes) import."""
    import os
    import sys

    fake = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fake_hermes")
    monkeypatch.syspath_prepend(fake)
    for name in [name for name in sys.modules if name == "agent" or name.startswith("agent.")]:
        monkeypatch.delitem(sys.modules, name)


def seat_secret(home: str, label: str) -> dict:
    """What a seat's Hermes store holds under this label, read with the recorded store (test assertions only)."""
    import importlib.util
    import os

    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fake_hermes", "agent", "vault_store.py"
    )
    spec = importlib.util.spec_from_file_location("recorded_vault_store", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    store = module.VaultStore(base_dir=os.path.join(home, "vault"))
    item = next(item for item in store.list_items() if item.label == label)
    return {**item.to_dict(), **store.resolve_secret(item.id)}
