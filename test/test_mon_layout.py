from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent))

from claude.mon.discovery import ActiveSession
from claude.mon.layout import (
    aggregate_day_cost,
    aggregate_rate_limits,
    clip_to_height,
    format_empty_body,
    format_footer,
    format_header,
    format_narrow_body,
)
from helper import strip_ansi


def _vw(s: str) -> int:
    '''Visible width of the first line of s (strip ANSI, count chars).'''
    return len(strip_ansi(s.split('\n')[0]))


def _make_session(
    session_id: str = 'abc',
    payload: dict | None = None,
    payload_mtime: float = 1.0,
) -> ActiveSession:
    return ActiveSession(
        session_id=session_id,
        jsonl_path=Path('/tmp/fake.jsonl'),
        jsonl_mtime=1.0,
        payload=payload or {},
        payload_mtime=payload_mtime,
    )


class TestFormatHeader:
    def test_contains_session_count_and_costs(self):
        # setup
        width = 80

        # run
        result = format_header(
            n_sessions=2,
            five_h_pct=42,
            seven_d_pct=75,
            day_cost_usd=1.23,
            width=width,
        )

        # expected
        plain = strip_ansi(result)

        # assert
        assert '2 sessions' in plain
        assert '42%' in plain
        assert '75%' in plain
        assert '$1.23' in plain

    def test_visible_width_equals_width_parameter(self):
        # setup
        width = 80

        # run
        result = format_header(
            n_sessions=2,
            five_h_pct=42,
            seven_d_pct=75,
            day_cost_usd=1.23,
            width=width,
        )

        # expected
        expected = width

        # assert
        assert _vw(result) == expected

    def test_none_percentages_show_placeholder(self):
        # setup
        width = 80

        # run
        result = format_header(
            n_sessions=1,
            five_h_pct=None,
            seven_d_pct=None,
            day_cost_usd=0.0,
            width=width,
        )

        # expected
        plain = strip_ansi(result)

        # assert
        assert plain.count('–') == 2

    def test_zero_sessions_shows_all_placeholders(self):
        # setup
        width = 80

        # run
        result = format_header(
            n_sessions=0,
            five_h_pct=None,
            seven_d_pct=None,
            day_cost_usd=0.0,
            width=width,
        )

        # expected
        plain = strip_ansi(result)

        # assert
        assert '0 sessions' in plain
        assert '5h:' in plain
        assert '7d:' in plain
        assert 'day: $0.00' in plain
        assert plain.count('–') == 2


class TestFormatFooter:
    def test_no_hidden_when_hidden_count_zero(self):
        # setup
        width = 80

        # run
        result = format_footer(
            refresh_age_seconds=5,
            n_sessions=3,
            hidden_count=0,
            width=width,
        )

        # expected
        plain = strip_ansi(result)

        # assert
        assert 'hidden' not in plain

    def test_shows_hidden_count_when_positive(self):
        # setup
        width = 80

        # run
        result = format_footer(
            refresh_age_seconds=5,
            n_sessions=5,
            hidden_count=2,
            width=width,
        )

        # expected
        plain = strip_ansi(result)

        # assert
        assert '+2 hidden' in plain

    def test_visible_width_equals_width_parameter(self):
        # setup
        width = 80

        # run
        result = format_footer(
            refresh_age_seconds=10,
            n_sessions=2,
            hidden_count=1,
            width=width,
        )

        # expected
        expected = width

        # assert
        assert _vw(result) == expected


class TestFormatEmptyBody:
    def test_returns_exactly_height_lines(self):
        # setup
        width, height = 60, 7

        # run
        result = format_empty_body(width=width, height=height)

        # expected
        expected = height

        # assert
        assert len(result.split('\n')) == expected

    def test_contains_no_active_sessions_message(self):
        # setup
        width, height = 60, 5

        # run
        result = format_empty_body(width=width, height=height)

        # expected
        expected = '(no active sessions)'

        # assert
        assert expected in result

    def test_each_line_has_correct_visible_width(self):
        # setup
        width, height = 60, 5

        # run
        result = format_empty_body(width=width, height=height)
        lines = result.split('\n')

        # expected
        expected = [width] * height

        # assert
        assert [len(strip_ansi(ln)) for ln in lines] == expected


class TestFormatNarrowBody:
    def test_contains_terminal_too_narrow_message(self):
        # setup
        # width must exceed the 21-char message to avoid clipping
        width, height = 40, 5

        # run
        result = format_narrow_body(width=width, height=height)

        # assert
        assert '(terminal too narrow)' in result

    def test_returns_exactly_height_lines(self):
        # setup
        width, height = 40, 5

        # run
        result = format_narrow_body(width=width, height=height)

        # expected
        expected = height

        # assert
        assert len(result.split('\n')) == expected


class TestClipToHeight:
    def test_all_boxes_fit(self):
        # setup
        boxes = ['line1\nline2', 'line3', 'line4\nline5']
        available = 10

        # run
        visible, hidden_count = clip_to_height(boxes, available)

        # expected
        expected_visible = boxes
        expected_hidden = 0

        # assert
        assert visible == expected_visible
        assert hidden_count == expected_hidden

    def test_excess_boxes_are_hidden(self):
        # setup
        boxes = ['a\nb', 'c\nd', 'e\nf\ng']
        # box 0 = 2 lines, box 1 = 2 lines, box 2 = 3 lines; total = 7
        available = 4

        # run
        visible, hidden_count = clip_to_height(boxes, available)

        # expected
        expected_visible = ['a\nb', 'c\nd']
        expected_hidden = 1

        # assert
        assert visible == expected_visible
        assert hidden_count == expected_hidden

    def test_boxes_kept_in_order(self):
        # setup
        boxes = ['first', 'second', 'third', 'fourth']
        available = 3

        # run
        visible, hidden_count = clip_to_height(boxes, available)

        # expected
        expected_visible = ['first', 'second', 'third']
        expected_hidden = 1

        # assert
        assert visible == expected_visible
        assert hidden_count == expected_hidden

    def test_first_box_too_large_hides_all(self):
        # setup
        boxes = ['a\nb\nc\nd\ne']
        available = 3

        # run
        visible, hidden_count = clip_to_height(boxes, available)

        # expected
        expected_visible = []
        expected_hidden = 1

        # assert
        assert visible == expected_visible
        assert hidden_count == expected_hidden


class TestAggregateRateLimits:
    def test_empty_list_returns_none_none(self):
        # setup
        sessions = []

        # run
        result = aggregate_rate_limits(sessions)

        # expected
        expected = (None, None)

        # assert
        assert result == expected

    def test_returns_from_session_with_highest_payload_mtime(self):
        # setup
        old = _make_session(
            session_id='old',
            payload={'rate_limits': {
                'five_hour': {'used_percentage': 10},
                'seven_day': {'used_percentage': 20},
            }},
            payload_mtime=1.0,
        )
        new = _make_session(
            session_id='new',
            payload={'rate_limits': {
                'five_hour': {'used_percentage': 55},
                'seven_day': {'used_percentage': 77},
            }},
            payload_mtime=2.0,
        )
        sessions = [old, new]

        # run
        result = aggregate_rate_limits(sessions)

        # expected
        expected = (55, 77)

        # assert
        assert result == expected

    def test_missing_rate_limits_returns_none_none(self):
        # setup
        sessions = [_make_session(payload={})]

        # run
        result = aggregate_rate_limits(sessions)

        # expected
        expected = (None, None)

        # assert
        assert result == expected


class TestAggregateDayCost:
    def test_sums_total_cost_across_sessions(self):
        # setup
        sessions = [
            _make_session(payload={'cost': {'total_cost_usd': 1.50}}),
            _make_session(payload={'cost': {'total_cost_usd': 0.75}}),
        ]

        # run
        result = aggregate_day_cost(sessions)

        # expected
        expected = 2.25

        # assert
        assert abs(result - expected) < 1e-9

    def test_missing_cost_field_treated_as_zero(self):
        # setup
        sessions = [
            _make_session(payload={'cost': {'total_cost_usd': 1.00}}),
            _make_session(payload={}),
        ]

        # run
        result = aggregate_day_cost(sessions)

        # expected
        expected = 1.00

        # assert
        assert abs(result - expected) < 1e-9

    def test_empty_sessions_returns_zero(self):
        # setup
        sessions = []

        # run
        result = aggregate_day_cost(sessions)

        # expected
        expected = 0.0

        # assert
        assert result == expected
