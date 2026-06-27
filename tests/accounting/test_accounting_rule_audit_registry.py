from modules.accounting.audit.rules import RULE_REGISTRY


def test_rule_registry_has_unique_indexed_rules():
    assert len(RULE_REGISTRY) == 111
    assert set(RULE_REGISTRY) == {f"ACC-RULE-{i:03d}" for i in range(1, 112)}


def test_rule_registry_fields_are_review_ready():
    expected_areas = {
        "validation",
        "bank",
        "purchase",
        "sales",
        "customer",
        "vendor",
        "inventory",
        "expense",
        "reporting",
    }
    for rule in RULE_REGISTRY.values():
        assert rule.name
        assert rule.area in expected_areas
        assert rule.version
        assert rule.source_file
