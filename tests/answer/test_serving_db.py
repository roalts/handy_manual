"""PgServing against the published serving schema (no model calls)."""
import pytest

from copilot_answer.identity import load_identity
from copilot_answer.serving import PgServing

pytestmark = pytest.mark.integration

# FRS-P-0012 (Fresno HCP-350 pump) and its serial match more passages than one search returns,
# most of them with the same match count.
IDS = ["FRS-P-0012", "HCP350-221034"]
OTHER_IDS = [["TAC-C-0142"], ["RTM-H-0007"], ["HCP-500"], ["E-31"], ["P-07"], ["SOP-020"],
             ["NK-600"], ["TAC-C-0143"], ["FRS-P-0031"], ["HCP-350"]]


def test_identifier_search_breaks_ties_by_passage_id_and_does_not_drift(db):
    groups = load_identity("u04").groups
    rows = db.execute("SELECT passage_id, matches FROM serving.identifier_search(%s, %s, 5000)",
                      (sorted(groups), IDS)).fetchall()
    assert len(rows) > 40
    expected = [pid for pid, _ in sorted(rows, key=lambda r: (-r[1], r[0]))[:40]]

    serving = PgServing()
    assert serving.conn.prepare_threshold is None
    first = serving.identifier_search(groups, IDS, 40)
    for ids in OTHER_IDS:
        serving.identifier_search(groups, ids, 40)
    assert first == expected
    assert serving.identifier_search(groups, IDS, 40) == expected
