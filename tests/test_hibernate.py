from __future__ import annotations

import pytest

from presence_guard import session


def test_preflight_reports_swap_smaller_than_ram(monkeypatch):
    monkeypatch.setattr(session, "_mem_total_bytes", lambda: 64 * 2**30)
    monkeypatch.setattr(session, "_swap_total_bytes", lambda: 8 * 2**30)
    monkeypatch.setattr("builtins.open", lambda *a, **k: _FakeFile("freeze mem disk\n"))
    monkeypatch.setattr(session, "_read_resume", lambda: "0:0")

    problems = session.hibernate_preflight()

    assert any("swap is 8.0 GiB but RAM is 64.0 GiB" in p for p in problems)


def test_preflight_reports_missing_resume_device(monkeypatch):
    monkeypatch.setattr(session, "_mem_total_bytes", lambda: 8 * 2**30)
    monkeypatch.setattr(session, "_swap_total_bytes", lambda: 64 * 2**30)
    monkeypatch.setattr("builtins.open", lambda *a, **k: _FakeFile("freeze mem disk\n"))
    monkeypatch.setattr(session, "_read_resume", lambda: "0:0")

    problems = session.hibernate_preflight()

    assert any("resume device" in p for p in problems)


def test_preflight_reports_kernel_without_disk_state(monkeypatch):
    monkeypatch.setattr(session, "_mem_total_bytes", lambda: 8 * 2**30)
    monkeypatch.setattr(session, "_swap_total_bytes", lambda: 64 * 2**30)
    monkeypatch.setattr("builtins.open", lambda *a, **k: _FakeFile("freeze mem\n"))
    monkeypatch.setattr(session, "_read_resume", lambda: "/dev/mapper/swap")

    problems = session.hibernate_preflight()

    assert any("'disk'" in p for p in problems)


def test_preflight_clean_when_everything_is_configured(monkeypatch):
    monkeypatch.setattr(session, "_mem_total_bytes", lambda: 8 * 2**30)
    monkeypatch.setattr(session, "_swap_total_bytes", lambda: 64 * 2**30)
    monkeypatch.setattr("builtins.open", lambda *a, **k: _FakeFile("freeze mem disk\n"))
    monkeypatch.setattr(session, "_read_resume", lambda: "/dev/mapper/ubuntu--vg-swap")

    assert session.hibernate_preflight() == []


def test_hibernate_refuses_without_touching_the_system(monkeypatch):
    monkeypatch.setattr(session, "hibernate_preflight", lambda: ["swap too small"])

    def boom(*_a, **_k):
        raise AssertionError("must not run a command when preflight fails")

    monkeypatch.setattr(session, "_run", boom)

    with pytest.raises(session.SessionError, match="not usable"):
        session.hibernate()


class _FakeFile:
    def __init__(self, text):
        self._lines = text.splitlines(keepends=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._lines)

    def read(self):
        return "".join(self._lines)
