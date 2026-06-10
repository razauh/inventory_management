from inventory_management.modules.updater.verifier import parse_expected_sha256


def test_parse_expected_sha256_finds_named_asset():
    digest = "a" * 64
    text = f"{digest}  AlHusnain-Setup-v1.2.3.exe\n"

    assert parse_expected_sha256(text, "AlHusnain-Setup-v1.2.3.exe") == digest


def test_parse_expected_sha256_ignores_other_asset():
    digest = "a" * 64
    text = f"{digest}  other.exe\n"

    assert parse_expected_sha256(text, "AlHusnain-Setup-v1.2.3.exe") is None
