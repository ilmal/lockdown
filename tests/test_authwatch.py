from __future__ import annotations

import pytest

from presence_guard import authwatch


def test_classify_gdm_password_failure():
    line = (
        "pam_unix(gdm-password:auth): authentication failure; logname=nils uid=0 "
        "euid=0 tty=/dev/tty1 ruser= rhost=  user=nils"
    )

    assert authwatch.classify(line) == ("failure", "nils")


def test_classify_sudo_wrong_password():
    line = "pam_unix(sudo:auth): auth could not identify password for [nils]"

    assert authwatch.classify(line) == ("failure", "nils")


def test_classify_ignores_unwatched_service():
    line = (
        "pam_unix(sssd:auth): authentication failure; logname=nils uid=0 "
        "euid=0 tty=/dev/tty1 ruser= rhost=  user=nils"
    )

    assert authwatch.classify(line) is None


def test_classify_ignores_non_auth_lines():
    line = "pam_unix(cron:session): session closed for user nils"

    assert authwatch.classify(line) is None


def test_cron_session_never_resets_the_counter():
    # cron opens a session for nils every 15 minutes. If that counted as a
    # success it would zero the failure count before the threshold is reached.
    line = "pam_unix(cron:session): session opened for user nils(uid=1000) by nils(uid=0)"

    assert authwatch.classify(line) is None


def test_gdm_session_open_counts_as_success_for_the_password_user():
    line = "pam_unix(gdm-password:session): session opened for user nils(uid=1000) by nils(uid=0)"

    assert authwatch.classify(line) == ("success", "nils")


def test_sudo_success_attributes_to_the_password_user():
    line = "pam_unix(sudo:session): session opened for user root(uid=0) by nils(uid=1000)"

    assert authwatch.classify(line) == ("success", "nils")


def test_three_failures_inside_the_window_trigger():
    tracker = authwatch.Tracker(threshold=3, window_seconds=600)

    assert [tracker.record_failure("nils", t) for t in (0.0, 10.0, 20.0)] == [1, 2, 3]


def test_failures_outside_the_window_do_not_accumulate():
    tracker = authwatch.Tracker(threshold=3, window_seconds=600)

    assert tracker.record_failure("nils", 0.0) == 1
    assert tracker.record_failure("nils", 601.0) == 1


def test_success_clears_the_counter():
    tracker = authwatch.Tracker(threshold=3, window_seconds=600)
    tracker.record_failure("nils", 0.0)
    tracker.record_failure("nils", 1.0)

    tracker.record_success("nils")

    assert tracker.record_failure("nils", 2.0) == 1


def test_users_are_counted_separately():
    tracker = authwatch.Tracker(threshold=3, window_seconds=600)
    tracker.record_failure("nils", 0.0)
    tracker.record_failure("nils", 0.0)

    assert tracker.record_failure("someoneelse", 0.0) == 1
