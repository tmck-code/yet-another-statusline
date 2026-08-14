"""Tests for replay play command."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'ops'))
from replay import (
    _compute_frame_duration,
    _resolve_width,
    _format_hud,
)


class TestFrameDurationComputation:
    """Tests for gap scheduling with speed and cap."""

    def test_gap_divided_by_speed(self):
        """Gap is divided by speed."""
        duration = _compute_frame_duration(gap=20.0, speed=10.0, gap_cap=2.0)
        assert duration == 2.0  # min(20/10, 2) = min(2, 2) = 2

    def test_gap_capped_at_max(self):
        """Gap capped at gap_cap."""
        duration = _compute_frame_duration(gap=40.0, speed=10.0, gap_cap=2.0)
        assert duration == 2.0  # min(40/10, 2) = min(4, 2) = 2

    def test_small_gap_not_capped(self):
        """Small gap not affected by cap."""
        duration = _compute_frame_duration(gap=10.0, speed=10.0, gap_cap=2.0)
        assert duration == 1.0  # min(10/10, 2) = min(1, 2) = 1

    def test_speed_one_no_scaling(self):
        """Speed 1 gives unscaled gap (capped)."""
        duration = _compute_frame_duration(gap=4.0, speed=1.0, gap_cap=2.0)
        assert duration == 2.0  # min(4/1, 2) = min(4, 2) = 2

    def test_fractional_speed(self):
        """Fractional speed works."""
        duration = _compute_frame_duration(gap=1.0, speed=0.5, gap_cap=10.0)
        assert duration == 2.0  # min(1/0.5, 10) = min(2, 10) = 2


class TestWidthResolution:
    """Tests for width resolution and clamping."""

    def test_recorded_width_no_clamp(self):
        """Recorded width used when terminal is wider."""
        width, should_warn = _resolve_width(
            recorded_width=80,
            terminal_width=120,
            mode='recorded',
        )
        assert width == 80
        assert should_warn is False

    def test_recorded_width_with_clamp(self):
        """Recorded width clamped to narrower terminal."""
        width, should_warn = _resolve_width(
            recorded_width=120,
            terminal_width=80,
            mode='recorded',
        )
        assert width == 80
        assert should_warn is True

    def test_current_mode_uses_terminal(self):
        """Current mode uses terminal width."""
        width, should_warn = _resolve_width(
            recorded_width=80,
            terminal_width=120,
            mode='current',
        )
        assert width == 120
        assert should_warn is False

    def test_fixed_width_no_clamp(self):
        """Fixed width ignores both recorded and terminal."""
        width, should_warn = _resolve_width(
            recorded_width=80,
            terminal_width=120,
            mode='100',
        )
        assert width == 100
        assert should_warn is False

    def test_invalid_mode_defaults_to_recorded(self):
        """Invalid mode defaults to recorded width."""
        width, should_warn = _resolve_width(
            recorded_width=80,
            terminal_width=120,
            mode='invalid',
        )
        assert width == 80
        assert should_warn is False


class TestHUDFormatting:
    """Tests for HUD string formatting."""

    def test_hud_format_basic(self):
        """HUD shows time, speed, paused, progress."""
        hud = _format_hud(
            elapsed_secs=90.0,
            total_secs=600.0,
            speed=10.0,
            paused=False,
            progress=0.15,
            width=80,
        )
        assert '00:01:30' in hud  # elapsed
        assert '00:10:00' in hud  # total
        assert '10' in hud  # speed
        assert '[' in hud  # progress bar

    def test_hud_paused_indicator(self):
        """HUD shows [paused] when paused."""
        hud = _format_hud(
            elapsed_secs=90.0,
            total_secs=600.0,
            speed=10.0,
            paused=True,
            progress=0.15,
            width=80,
        )
        assert '[paused]' in hud

    def test_hud_no_paused_when_playing(self):
        """HUD omits [paused] when playing."""
        hud = _format_hud(
            elapsed_secs=90.0,
            total_secs=600.0,
            speed=10.0,
            paused=False,
            progress=0.15,
            width=80,
        )
        assert '[paused]' not in hud

    def test_hud_zero_time(self):
        """HUD handles zero times."""
        hud = _format_hud(
            elapsed_secs=0.0,
            total_secs=0.0,
            speed=1.0,
            paused=False,
            progress=0.0,
            width=80,
        )
        assert '00:00:00' in hud

    def test_hud_respects_width(self):
        """HUD truncates if too long for width."""
        hud = _format_hud(
            elapsed_secs=90.0,
            total_secs=600.0,
            speed=10.0,
            paused=True,
            progress=0.5,
            width=20,
        )
        assert len(hud) <= 20

    def test_hud_progress_bar_full(self):
        """Progress bar fills at 100%."""
        hud = _format_hud(
            elapsed_secs=600.0,
            total_secs=600.0,
            speed=1.0,
            paused=False,
            progress=1.0,
            width=80,
        )
        assert '[==========]' in hud or '=' * 10 in hud

    def test_hud_progress_bar_empty(self):
        """Progress bar empty at 0%."""
        hud = _format_hud(
            elapsed_secs=0.0,
            total_secs=600.0,
            speed=1.0,
            paused=False,
            progress=0.0,
            width=80,
        )
        assert '[          ]' in hud or '[ ]' in hud or '[]' in hud
