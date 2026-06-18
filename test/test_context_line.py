import re

import yas.renderer as renderer
from yas.constants import CLR_ALERT, CLR_WARN, GLYPH_HOURGLASS
from yas.renderer import _ctx_fill_ratio, _ctx_used_tokens
from yas.session import ContextWindow
from yas.render.text import _visible_width

Renderer = renderer.Renderer

_ANSI = re.compile(r'\x1b\[[^m]*m')


def _strip(s: str) -> str:
    return _ANSI.sub('', s)


def test_context_line_under_soft_limit() -> None:
    r = Renderer()
    ctx = ContextWindow(
        total_input_tokens=10_000,
        total_output_tokens=5_000,
        context_window_size=200_000,
    )
    available = 76
    out = r.context_line(ctx, available)
    assert _visible_width(out) <= available
    assert CLR_ALERT not in out


def test_context_line_over_soft_limit() -> None:
    r = Renderer()
    ctx = ContextWindow(
        total_input_tokens=200_000,
        total_output_tokens=0,
        context_window_size=200_000,
    )
    available = 76
    out = r.context_line(ctx, available)
    assert CLR_ALERT in out
    assert _visible_width(out) <= available


def test_context_line_fields_right_justified_and_aligned() -> None:
    # Token count, the context-window `(N%)`, and the soft-limit `N%` sit in
    # fixed-width right-justified fields (6 / 5 / 4) so their columns hold a
    # stable right edge across magnitudes — small values pad left, the widest
    # values sit flush. This keeps the `context`/`fill`/`dumb` labels anchored.
    # Covers both the normal branch (small) and the fill_ratio>=1.0 branch (large).
    r = Renderer()
    small = ContextWindow(total_input_tokens=30_000, context_window_size=1_000_000)
    large = ContextWindow(total_input_tokens=194_000, context_window_size=200_000)

    def fields(ctx: ContextWindow, soft_limit: int) -> tuple[str, str, str]:
        plain = _strip(r.context_line(ctx, available=76, soft_limit=soft_limit))
        h = plain.index(GLYPH_HOURGLASS)
        return plain[h + 2:h + 8], plain[h + 9:h + 14], plain[h + 15:h + 19]

    s_tok, s_lim, s_soft = fields(small, 150_000)   # normal branch (20%)
    l_tok, l_lim, l_soft = fields(large, 194_000)   # over-limit branch (100%)

    assert (s_tok, s_lim, s_soft) == (' 30.0K', ' (3%)', ' 20%')
    assert (l_tok, l_lim, l_soft) == ('194.0K', '(97%)', '100%')


def test_context_line_compact_respects_available() -> None:
    r = Renderer()
    ctx = ContextWindow(
        total_input_tokens=10_000,
        total_output_tokens=5_000,
    )
    available = 30
    out = r.context_line_compact(ctx, available)
    assert _visible_width(out) <= available


# ---------------------------------------------------------------------------
# _ctx_fill_ratio unit tests (tasks 4.1–4.5)
# ---------------------------------------------------------------------------

def test_fill_ratio_host_supplied_used_percentage() -> None:
    # Task 4.1: host-supplied used_percentage=42.7 → fill 0.427, label 43%
    ctx = ContextWindow(
        used_percentage=42.7,
        total_input_tokens=10_000,
        total_output_tokens=99_000,
        context_window_size=200_000,
    )
    fill, pct = _ctx_fill_ratio(ctx, soft_limit=200_000)
    assert abs(fill - 0.427) < 1e-9
    assert abs(pct - 42.7) < 1e-9


def test_fill_ratio_host_supplied_renders_correct_label() -> None:
    # Task 4.1: the rendered line must display "43%" (rounded from 42.7)
    r = Renderer()
    ctx = ContextWindow(
        used_percentage=42.7,
        total_input_tokens=10_000,
        total_output_tokens=99_000,
        context_window_size=200_000,
    )
    out = r.context_line(ctx, available=76, soft_limit=200_000)
    assert '43%' in _strip(out)


def test_used_tokens_prefers_host_value() -> None:
    # The effective token count is host used_percentage rescaled to the window,
    # not the raw total_input_tokens field.
    ctx = ContextWindow(
        used_percentage=8.0,
        total_input_tokens=428,
        context_window_size=200_000,
    )
    assert _ctx_used_tokens(ctx) == 16_000


def test_used_tokens_falls_back_to_input() -> None:
    ctx = ContextWindow(used_percentage=None, total_input_tokens=12_345, context_window_size=200_000)
    assert _ctx_used_tokens(ctx) == 12_345


def test_used_tokens_negative_host_clamped() -> None:
    ctx = ContextWindow(used_percentage=-5.0, total_input_tokens=428, context_window_size=200_000)
    assert _ctx_used_tokens(ctx) == 0


def test_label_and_fill_share_one_source() -> None:
    # Reconciliation guard: the displayed token figure is derived from the same
    # used_percentage that drives the fill, so they cannot disagree. Host says 8%
    # of a 200k window (16.0K) → label shows "16.0K" and "(8%)" window-headroom.
    r = Renderer()
    ctx = ContextWindow(
        used_percentage=8.0,
        total_input_tokens=428,
        context_window_size=200_000,
    )
    out = _strip(r.context_line(ctx, available=120, soft_limit=150_000))
    assert '16.0K' in out
    assert '(8%)' in out
    # 16K / 150K soft limit ≈ 11%
    assert '11%' in out


def test_fill_ratio_fallback_input_only() -> None:
    # Task 4.2: used_percentage=None, input=80k, window=200k → fill 0.40, label 40%
    ctx = ContextWindow(
        used_percentage=None,
        total_input_tokens=80_000,
        total_output_tokens=5_000,
        context_window_size=200_000,
    )
    fill, pct = _ctx_fill_ratio(ctx, soft_limit=200_000)
    assert abs(fill - 0.40) < 1e-9
    assert abs(pct - 40.0) < 1e-9


def test_fill_ratio_fallback_renders_correct_label() -> None:
    # Task 4.2: the rendered line must display "40%"
    r = Renderer()
    ctx = ContextWindow(
        used_percentage=None,
        total_input_tokens=80_000,
        total_output_tokens=5_000,
        context_window_size=200_000,
    )
    out = r.context_line(ctx, available=76)
    assert '40%' in _strip(out)


def test_fill_ratio_output_tokens_excluded() -> None:
    # Task 4.3: used_percentage=None, input=60k, output=40k, window=200k
    #           → fill 0.30 (input-only), not 0.50 (input+output)
    ctx = ContextWindow(
        used_percentage=None,
        total_input_tokens=60_000,
        total_output_tokens=40_000,
        context_window_size=200_000,
    )
    fill, pct = _ctx_fill_ratio(ctx, soft_limit=200_000)
    assert abs(fill - 0.30) < 1e-9
    assert abs(pct - 30.0) < 1e-9


def test_fill_ratio_negative_used_percentage_clamped() -> None:
    # Task 4.4: used_percentage=-2.0 → fill 0.0, no exception
    ctx = ContextWindow(
        used_percentage=-2.0,
        total_input_tokens=10_000,
        context_window_size=200_000,
    )
    fill, pct = _ctx_fill_ratio(ctx, soft_limit=200_000)
    assert fill == 0.0
    assert pct == 0.0


def test_fill_ratio_zero_context_window_no_exception() -> None:
    # Task 4.5: used_percentage=None, context_window_size=0 → no ZeroDivisionError.
    # The fill is now soft-limit-relative, so a zero window still yields a
    # meaningful input-only ratio (80k / 200k = 0.40) rather than collapsing to 0.
    ctx = ContextWindow(
        used_percentage=None,
        total_input_tokens=80_000,
        context_window_size=0,
    )
    fill, pct = _ctx_fill_ratio(ctx, soft_limit=200_000)
    assert abs(fill - 0.40) < 1e-9


def test_fill_ratio_relative_to_soft_limit() -> None:
    # The bar fills against soft_limit, not the model window: host says 75% of a
    # 200k window (150k tokens), and with a 150k soft limit that is a full bar.
    ctx = ContextWindow(
        used_percentage=75.0,
        total_input_tokens=10_000,
        total_output_tokens=99_000,
        context_window_size=200_000,
    )
    fill, pct = _ctx_fill_ratio(ctx, soft_limit=150_000)
    assert abs(fill - 1.0) < 1e-9
    assert abs(pct - 100.0) < 1e-9


def test_fill_ratio_fallback_relative_to_soft_limit() -> None:
    # Fallback path (no host value) also scales by soft_limit: 75k input against
    # a 150k soft limit → 50%, regardless of the 200k window.
    ctx = ContextWindow(
        used_percentage=None,
        total_input_tokens=75_000,
        total_output_tokens=40_000,
        context_window_size=200_000,
    )
    fill, pct = _ctx_fill_ratio(ctx, soft_limit=150_000)
    assert abs(fill - 0.50) < 1e-9
    assert abs(pct - 50.0) < 1e-9


def test_fill_ratio_zero_soft_limit_no_exception() -> None:
    ctx = ContextWindow(used_percentage=42.7, total_input_tokens=10_000, context_window_size=200_000)
    fill, pct = _ctx_fill_ratio(ctx, soft_limit=0)
    assert fill == 0.0
    assert pct == 0.0
    assert pct == 0.0


# ---------------------------------------------------------------------------
# exceeds_200k badge tests (tasks 6.1–6.4)
# ---------------------------------------------------------------------------

def test_context_line_badge_present_when_exceeds_200k() -> None:
    # Task 6.1: exceeds_200k_tokens=True → '!200K' appears in output
    r = Renderer()
    ctx = ContextWindow(
        total_input_tokens=250_000,
        total_output_tokens=0,
        context_window_size=1_000_000,
    )
    out = r.context_line(ctx, available=76, exceeds_200k=True)
    assert '!200K' in _strip(out)


def test_context_line_badge_absent_when_not_exceeds_200k() -> None:
    # Task 6.2: exceeds_200k_tokens=False → no '!200K' in output
    r = Renderer()
    ctx = ContextWindow(
        total_input_tokens=250_000,
        total_output_tokens=0,
        context_window_size=1_000_000,
    )
    out = r.context_line(ctx, available=76, exceeds_200k=False)
    assert '!200K' not in _strip(out)


def test_context_line_badge_reduces_bar_width() -> None:
    # Task 6.3: exceeds_200k=True, available=60 → bar fills at most 54 columns.
    # We measure by comparing the bar width with badge vs without badge.
    r = Renderer()
    ctx = ContextWindow(
        total_input_tokens=30_000,
        total_output_tokens=0,
        context_window_size=200_000,
    )
    available = 60
    out_badge  = r.context_line(ctx, available=available, exceeds_200k=True)
    out_no_badge = r.context_line(ctx, available=available, exceeds_200k=False)
    # The badged version must be no wider than the un-badged version.
    # Both must fit within `available` visible columns.
    assert _visible_width(out_badge)    <= available
    assert _visible_width(out_no_badge) <= available
    # The bar in the badged version is shorter (badge_w=6 columns deducted).
    assert _visible_width(out_badge) <= _visible_width(out_no_badge)


def test_context_line_badge_colour_is_clr_warn() -> None:
    # Task 6.4: CLR_WARN (amber) appears immediately before '!200K'
    r = Renderer()
    ctx = ContextWindow(
        total_input_tokens=250_000,
        total_output_tokens=0,
        context_window_size=1_000_000,
    )
    out = r.context_line(ctx, available=76, exceeds_200k=True)
    # CLR_WARN escape must precede the badge text
    idx_warn  = out.find(CLR_WARN)
    idx_badge = out.find('!200K')
    assert idx_warn != -1, 'CLR_WARN not present in output'
    assert idx_badge != -1, '!200K not present in output'
    assert idx_warn < idx_badge, 'CLR_WARN must appear before !200K'


def test_context_line_compact_badge_present_when_exceeds_200k() -> None:
    # Compact variant: exceeds_200k=True → '!200K' appears
    r = Renderer()
    ctx = ContextWindow(
        total_input_tokens=250_000,
        total_output_tokens=0,
        context_window_size=1_000_000,
    )
    out = r.context_line_compact(ctx, available=40, exceeds_200k=True)
    assert '!200K' in _strip(out)


def test_context_line_compact_badge_absent_by_default() -> None:
    # Compact variant: default (no badge) → no '!200K'
    r = Renderer()
    ctx = ContextWindow(
        total_input_tokens=250_000,
        total_output_tokens=0,
        context_window_size=1_000_000,
    )
    out = r.context_line_compact(ctx, available=40)
    assert '!200K' not in _strip(out)
