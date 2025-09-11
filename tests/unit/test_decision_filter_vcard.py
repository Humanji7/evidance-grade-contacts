from scripts import decision_filter as df


def test_vcard_title_upgrades_to_c_suite(monkeypatch):
    # Prepare a record with Unknown title and .vcf URL on allowed host
    recs = [
        {
            "person_name": "X",
            "role_title": "Unknown",
            "vcard": "https://example.com/card.vcf",
        }
    ]

    # Mock HEAD and GET
    head_calls = {"n": 0}

    def mock_head(url, timeout_s):
        head_calls["n"] += 1
        return 200, {"content-length": "32"}

    def mock_get(url, timeout_s, max_bytes):
        body = b"TITLE: Managing Director\n"
        return 200, body

    monkeypatch.setattr(df, "_http_head", mock_head)
    monkeypatch.setattr(df, "_http_get", mock_get)

    kept, counts, drops = df.process_records(
        records=recs,
        min_level=df.DecisionLevel.VP_PLUS,
        fetch_vcard=True,
        vcard_budget=5,
        timeout_s=2.5,
        max_vcard_bytes=65536,
        site_allow=["example.com"],
    )

    assert head_calls["n"] == 1
    assert len(kept) == 1
    out = kept[0]
    assert out["decision_level"] == df.DecisionLevel.C_SUITE.value
    assert out["role_title"] == "Managing Director"


def test_vcard_budget_limits_requests(monkeypatch):
    # Two records, budget = 1 -> only first should trigger requests
    recs = [
        {"person_name": "A", "role_title": "Unknown", "vcard": "https://example.com/a.vcf"},
        {"person_name": "B", "role_title": "Unknown", "vcard": "https://example.com/b.vcf"},
    ]

    head_calls = {"n": 0}

    def mock_head(url, timeout_s):
        head_calls["n"] += 1
        return 200, {"content-length": "16"}

    def mock_get(url, timeout_s, max_bytes):
        return 200, b"TITLE: VP\n"

    monkeypatch.setattr(df, "_http_head", mock_head)
    monkeypatch.setattr(df, "_http_get", mock_get)

    kept, counts, drops = df.process_records(
        records=recs,
        min_level=df.DecisionLevel.VP_PLUS,
        fetch_vcard=True,
        vcard_budget=1,  # budget for only one card
        timeout_s=2.5,
        max_vcard_bytes=65536,
        site_allow=["example.com"],
    )

    # Only one HEAD (and one GET) should have occurred
    assert head_calls["n"] == 1

    # First should be upgraded to at least VP_PLUS and kept; second remains UNKNOWN and dropped by threshold
    assert len(kept) == 1
    levels = [rec.get("decision_level") for rec in kept]
    assert df.DecisionLevel.VP_PLUS.value in levels or df.DecisionLevel.C_SUITE.value in levels
