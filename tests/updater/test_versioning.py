from inventory_management.modules.updater.versioning import is_newer, parse_version


def test_parse_version_accepts_semver_with_v_prefix():
    parsed = parse_version("v1.2.3")

    assert parsed is not None
    assert parsed.normalized == "1.2.3"


def test_is_newer_rejects_same_older_invalid_and_prerelease_by_default():
    assert is_newer("v1.2.4", "1.2.3") is True
    assert is_newer("v1.2.3", "1.2.3") is False
    assert is_newer("v1.2.2", "1.2.3") is False
    assert is_newer("latest", "1.2.3") is False
    assert is_newer("v1.3.0-beta.1", "1.2.3") is False


def test_is_newer_can_include_prerelease():
    assert is_newer("v1.3.0-beta.1", "1.2.3", include_prerelease=True) is True
