import pytest

from copilot_ingest.acl import can_see


def test_superset_requirement():
    assert can_see(["cert-hv", "family-compressors"], ["region-na", "family-compressors",
                                                       "cert-hv"])
    assert not can_see(["cert-hv", "family-compressors"], ["region-na", "family-compressors"])


def test_empty_rule_is_visible_to_everyone():
    assert can_see([], [])
    assert can_see([], ["region-eu"])


@pytest.mark.integration
def test_sql_semantics_match(db):
    """The serving functions use `required <@ user_groups`; check it agrees with can_see."""
    cases = [([], []), ([], ["a"]), (["a"], ["a", "b"]), (["a", "b"], ["a"]), (["a"], [])]
    for required, groups in cases:
        got = db.execute("SELECT %s::text[] <@ %s::text[]", (required, groups)).fetchone()[0]
        assert got == can_see(required, groups), (required, groups)


@pytest.mark.integration
def test_object_without_alternatives_is_invisible(db):
    assert db.execute("SELECT serving.can_see('passage', 'p_does_not_exist', %s)",
                      (["region-na", "region-eu", "cert-hv", "role-lead"],)).fetchone()[0] \
        is False
