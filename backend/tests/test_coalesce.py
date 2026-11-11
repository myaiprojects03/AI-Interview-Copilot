from app.api.realtime import coalesce_deltas


def test_answer_pieces_are_merged_in_order():
    events = [
        {"type": "suggestion_start", "id": 1},
        {"type": "suggestion_delta", "id": 1, "text": "I led "},
        {"type": "suggestion_delta", "id": 1, "text": "the payments "},
        {"type": "speech", "channel": "interviewer", "active": True},
        {"type": "suggestion_delta", "id": 1, "text": "team."},
        {"type": "suggestion_delta", "id": 2, "text": "New"},
        {"type": "suggestion_end", "id": 1},
    ]
    assert coalesce_deltas(events) == [
        {"type": "suggestion_start", "id": 1},
        {"type": "suggestion_delta", "id": 1, "text": "I led the payments "},
        {"type": "speech", "channel": "interviewer", "active": True},
        {"type": "suggestion_delta", "id": 1, "text": "team."},
        {"type": "suggestion_delta", "id": 2, "text": "New"},
        {"type": "suggestion_end", "id": 1},
    ]
