# SPDX-FileCopyrightText: 2026 Mohammadreza Kadivar
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Vault page's routes. The human's vaults and their records: lists carry metadata only, a value leaves through
/vault-reveal alone. A lane never reaches any of them."""

from fastapi import HTTPException


def mount(router):
    from dashboard.cockpit.routes.pages import _act, _guard

    def book():
        pack = _guard()
        from cockpitlib.outbox import human_gate

        _act(lambda: human_gate("the vaults"))
        from cockpitlib.vault_book import VaultBook

        return VaultBook(pack=pack)

    def confirmed(body: dict, expected: str) -> None:
        if not expected or body.get("confirm") != expected:
            raise HTTPException(400, "confirm=<name or id> required")

    @router.get("/vaults")
    def vaults():
        vb = book()
        return _act(lambda: {"vaults": vb.vaults(), **vb.state()})

    @router.get("/vault-records")
    def vault_records(vault: str = "", q: str = "", kind: str = "", tag: str = ""):
        vb = book()
        return _act(lambda: vb.records(vault, q, kind, tag))

    @router.get("/vault-record")
    def vault_record(vault: str = "", id: str = ""):
        vb = book()
        return _act(lambda: vb.record(vault, id))

    @router.post("/vault-create")
    def vault_create(body: dict):
        vb = book()
        return _act(lambda: {"ok": True, "out": vb.create_vault(str(body.get("name") or ""))})

    @router.post("/vault-rename")
    def vault_rename(body: dict):
        vb = book()
        return _act(
            lambda: {"ok": True, "out": vb.rename_vault(str(body.get("name") or ""), str(body.get("to") or ""))}
        )

    @router.post("/vault-delete")
    def vault_delete(body: dict):
        vb = book()
        name = str(body.get("name") or "")
        confirmed(body, name)
        return _act(lambda: {"ok": True, "out": vb.delete_vault(name, bool(body.get("force")))})

    @router.post("/vault-save")
    def vault_save(body: dict):
        vb = book()
        fields = {key: value for key, value in body.items() if key != "vault"}
        return _act(lambda: {"ok": True, **vb.save(str(body.get("vault") or ""), fields)})

    @router.post("/vault-reindex")
    def vault_reindex(body: dict):
        vb = book()
        return _act(lambda: {"ok": True, "out": vb.reindex()})

    @router.post("/vault-record-delete")
    def vault_record_delete(body: dict):
        vb = book()
        record_id = str(body.get("id") or "")
        confirmed(body, record_id)
        return _act(lambda: {"ok": True, "out": vb.delete(str(body.get("vault") or ""), record_id)})

    @router.post("/vault-move")
    def vault_move(body: dict):
        vb = book()
        return _act(
            lambda: {
                "ok": True,
                "out": vb.move(str(body.get("vault") or ""), str(body.get("id") or ""), str(body.get("to") or "")),
            }
        )

    @router.post("/vault-unlock")
    def vault_unlock(body: dict):
        vb = book()
        return _act(lambda: {"ok": True, "out": vb.unlock(str(body.get("secret") or ""))})

    @router.post("/vault-lock")
    def vault_lock(body: dict):
        vb = book()
        return _act(lambda: {"ok": True, "out": vb.lock()})

    @router.post("/vault-reveal")
    def vault_reveal(body: dict):
        vb = book()
        return _act(
            lambda: vb.reveal(
                str(body.get("vault") or ""),
                str(body.get("id") or ""),
                str(body.get("field") or "secret"),
                body.get("index"),
            )
        )
