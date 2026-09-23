import base64
import json
import os
from dataclasses import replace

import pytest
from companion_core.secrets import Keyring, SecretContext, SecretUnavailable


def test_authenticated_context_and_tampering():
    keys = Keyring("first", {"first": os.urandom(32)})
    ctx = SecretContext("owner", "google", "refresh_token")
    record = keys.encrypt("ref", ctx, "fixture-sensitive-value")
    assert keys.decrypt("ref", ctx, record) == "fixture-sensitive-value"
    assert b"fixture-sensitive-value" not in record["ciphertext"]
    for other in [replace(ctx, owner="other"), replace(ctx, provider="smtp"),
                  replace(ctx, purpose="client_secret")]:
        with pytest.raises(SecretUnavailable):
            keys.decrypt("ref", other, record)
    for change in [{"version": 2}, {"key_id": "missing"},
                   {"ciphertext": record["ciphertext"][:-1] + bytes([record["ciphertext"][-1] ^ 1])},
                   {"nonce": os.urandom(12)}]:
        with pytest.raises(SecretUnavailable):
            keys.decrypt("ref", ctx, {**record, **change})
    with pytest.raises(SecretUnavailable):
        keys.decrypt("other-ref", ctx, record)
    with pytest.raises(SecretUnavailable):
        Keyring("first", {"first": os.urandom(32)}).decrypt("ref", ctx, record)


def test_key_file_permissions_and_redacted_failures(tmp_path):
    path = tmp_path / "keyring"
    path.write_text(json.dumps({"active": "one", "keys": {
        "one": base64.b64encode(os.urandom(32)).decode(),
    }}))
    path.chmod(0o600)
    assert Keyring.from_file(str(path)).active == "one"
    path.chmod(0o644)
    with pytest.raises(SecretUnavailable):
        Keyring.from_file(str(path))
    path.chmod(0o600)
    path.write_text("invalid-sensitive-content")
    with pytest.raises(SecretUnavailable) as error:
        Keyring.from_file(str(path))
    assert "invalid-sensitive-content" not in str(error.value)
