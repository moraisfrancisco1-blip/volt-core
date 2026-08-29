from app.auth import hash_key


def test_api_key_hash_is_deterministic():
    assert hash_key("volt-secret") == hash_key("volt-secret")


def test_different_api_keys_have_different_hashes():
    assert hash_key("volt-secret-a") != hash_key("volt-secret-b")


def test_plaintext_key_is_not_the_stored_hash():
    assert hash_key("volt-secret") != "volt-secret"
