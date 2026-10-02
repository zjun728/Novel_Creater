"""Author decisions are separate from immutable quality reports."""

def effective_findings(report, decisions=None):
    from backend.domain.review_disputes import retained_ids
    ignored = set((decisions or {}).get("ignoredFindingIds", []))
    findings = (report or {}).get("findings", [])
    eligible = {item["id"] for item in findings if item.get("severity") == "optional"}
    if not ignored <= eligible:
        raise ValueError("invalid ignored quality findings")
    retained = retained_ids(report, decisions)
    return [item for item in findings if item["id"] not in ignored | retained]


def has_required_findings(report, decisions=None):
    return any(item.get("severity") == "required" for item in effective_findings(report, decisions))


def validate_package_decisions(data, report):
    """Reject malformed or cross-report decisions before package publication."""
    ignored = data.get("ignoredFindingIds")
    report_hash = data.get("reportHash")
    if (not isinstance(report_hash, str) or len(report_hash) != 64
        or any(char not in "0123456789abcdef" for char in report_hash)
        or type(data.get("revision")) is not int or data["revision"] < 1
        or type(data.get("updatedAt")) is not int or data["updatedAt"] < 0
        or not isinstance(ignored, (list, tuple))
        or any(not isinstance(item, str) or not item for item in ignored)
        or len(set(ignored)) != len(ignored)
        or report.get("status") != "completed"):
        raise ValueError("invalid review decisions")
    effective_findings(report, data)
