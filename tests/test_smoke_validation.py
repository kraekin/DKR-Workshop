"""Smoke failures survive optimization and still produce a failing run."""
from __future__ import annotations

import logging
from pathlib import Path
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest

from src.ui.smoke_checks import smoke_test

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('flags', [[], ['-O'], ['-OO']])
def test_optimized_smoke_checks_keep_validation_and_side_effects(flags: list[str]) -> None:
    script = textwrap.dedent('''
        from src.ui.smoke_checks import SmokeCheckError, _check

        performed = []
        _check(performed.append('saved') is None, 'side effect failed')
        if performed != ['saved']:
            raise RuntimeError('Smoke operation was skipped')
        try:
            _check(False, 'forced smoke failure')
        except SmokeCheckError as error:
            if str(error) != 'forced smoke failure':
                raise RuntimeError('Failure diagnostic was lost')
        else:
            raise RuntimeError('Smoke validation was skipped')
        print('validation and side effects active')
    ''')
    result = subprocess.run([sys.executable, *flags, '-c', script], cwd=ROOT,
                            capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == 'validation and side effects active'


def test_failed_smoke_check_reports_failure_screenshot_and_cleanup(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[tuple[str, object]] = []
    toggle = SimpleNamespace(setChecked=lambda value: None)
    window = SimpleNamespace(
        viewport=SimpleNamespace(frame_count=10, render_error=None, setFocus=lambda: None),
        object_inspector=SimpleNamespace(mouse_move=toggle),
        toolbar=SimpleNamespace(objects=toggle, sprites=toggle),
        animation_toolbar=SimpleNamespace(models=toggle),
        activateWindow=lambda: None,
        catalog=SimpleNamespace(levels=[object()]),
        # Deliberately disagree with the catalog to fail the first real check.
        level_panel=SimpleNamespace(tree=SimpleNamespace(topLevelItemCount=lambda: 0)),
        edit_session=object(),
        grab=lambda: SimpleNamespace(save=lambda path: calls.append(('screenshot', path))),
        close=lambda: calls.append(('closed', True)),
    )
    app = SimpleNamespace(processEvents=lambda: calls.append(('events', True)))
    screenshot = tmp_path / 'shots' / 'smoke.png'
    with caplog.at_level(logging.ERROR):
        result = smoke_test(app, window, screenshot)
    assert result == 1
    assert 'SmokeCheckError' in caplog.text
    assert 'tree.topLevelItemCount() == len(catalog.levels)' in caplog.text
    assert calls == [('screenshot', str(screenshot.with_name('smoke-failure.png'))),
                     ('closed', True), ('events', True)]
    assert window.edit_session is None
    assert screenshot.parent.is_dir()
