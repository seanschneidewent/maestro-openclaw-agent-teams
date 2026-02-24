from __future__ import annotations

from maestro_solo.solo_license import issue_solo_license, verify_solo_license_key


def test_issue_and_verify_license_roundtrip():
    issued = issue_solo_license(
        purchase_id="pur_test_001",
        plan_id="solo_test_monthly",
        email="test@example.com",
    )
    status = verify_solo_license_key(issued["license_key"])
    assert status["valid"] is True
    assert status["purchase_id"] == "pur_test_001"
    assert status["plan_id"] == "solo_test_monthly"
