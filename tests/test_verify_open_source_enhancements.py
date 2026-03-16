from verify_open_source_enhancements import collect_statuses


def test_collect_statuses_returns_expected_tools():
    statuses = collect_statuses()
    tool_names = {status.tool for status in statuses}
    assert tool_names == {"Promptfoo", "MiroFish", "Impeccable", "OpenViking"}


def test_current_repo_enhancements_not_fully_complete():
    statuses = collect_statuses()
    status_by_tool = {status.tool: status for status in statuses}

    assert status_by_tool["Promptfoo"].ok is True
    assert status_by_tool["Impeccable"].ok is True

    # These are listed in open-source-enhancements.md but not fully wired yet.
    assert status_by_tool["MiroFish"].ok is False
    assert status_by_tool["OpenViking"].ok is False
