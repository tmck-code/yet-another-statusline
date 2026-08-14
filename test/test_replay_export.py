"""Tests for replay export command."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / 'ops'))
from replay import (
    _check_export_preflight,
    _validate_export_extension,
)


class TestExportPreflight:
    """Tests for export command preflight checks."""

    def test_preflight_success_when_binaries_present(self):
        """Preflight succeeds when both ffmpeg and magick are available."""
        with patch('shutil.which') as mock_which:
            mock_which.side_effect = lambda x: '/usr/bin/' + x
            assert _check_export_preflight() is True

    def test_preflight_fails_when_ffmpeg_missing(self):
        """Preflight fails when ffmpeg is missing."""
        def mock_which(name):
            if name == 'ffmpeg':
                return None
            return '/usr/bin/' + name
        with patch('shutil.which', side_effect=mock_which):
            assert _check_export_preflight() is False

    def test_preflight_fails_when_magick_missing(self):
        """Preflight fails when magick is missing."""
        def mock_which(name):
            if name == 'magick':
                return None
            return '/usr/bin/' + name
        with patch('shutil.which', side_effect=mock_which):
            assert _check_export_preflight() is False

    def test_preflight_fails_when_both_missing(self):
        """Preflight fails when both binaries are missing."""
        with patch('shutil.which', return_value=None):
            assert _check_export_preflight() is False


class TestExportExtensionValidation:
    """Tests for output extension validation."""

    def test_mp4_extension_valid(self):
        """MP4 extension is valid."""
        assert _validate_export_extension('output.mp4') is True

    def test_gif_extension_valid(self):
        """GIF extension is valid."""
        assert _validate_export_extension('output.gif') is True

    def test_webm_extension_invalid(self):
        """WebM extension is rejected."""
        assert _validate_export_extension('output.webm') is False

    def test_avi_extension_invalid(self):
        """AVI extension is rejected."""
        assert _validate_export_extension('output.avi') is False

    def test_uppercase_extension_valid(self):
        """Uppercase extensions are handled."""
        assert _validate_export_extension('output.MP4') is True
        assert _validate_export_extension('output.GIF') is True

    def test_mixed_case_extension_valid(self):
        """Mixed-case extensions are handled."""
        assert _validate_export_extension('output.Mp4') is True
