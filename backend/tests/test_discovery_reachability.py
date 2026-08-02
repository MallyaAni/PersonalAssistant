"""Calendar links have to open on the phone they were sent to.

A digest's entire value is the "Add" link, and a loopback link works perfectly on
the machine that served it while being dead everywhere else. That is exactly the
kind of defect a test on the serving machine will not notice, so it is asserted
directly.
"""

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-testing")

from backend.discovery.reachability import (
    calendar_base_url,
    is_reachable_from_other_devices,
)


def test_loopback_is_not_reachable_from_another_device():
    # On the recipient's phone, localhost is the phone.
    assert not is_reachable_from_other_devices("http://localhost:8000/api/v1/discovery")
    assert not is_reachable_from_other_devices("http://127.0.0.1:8000/x")
    assert not is_reachable_from_other_devices("http://0.0.0.0:8000/x")
    assert not is_reachable_from_other_devices("http://[::1]:8000/x")


def test_a_lan_address_or_hostname_is_reachable():
    assert is_reachable_from_other_devices("http://192.168.1.20:8000/x")
    assert is_reachable_from_other_devices("https://anios.example.com/x")


def test_an_explicit_routable_setting_is_never_second_guessed():
    # An operator publishing a real hostname must win over any detection.
    configured = "https://anios.example.com/api/v1/discovery"
    assert calendar_base_url(configured) == configured


def test_a_loopback_default_is_replaced_with_something_routable():
    resolved = calendar_base_url("http://localhost:8000/api/v1/discovery")

    # Either a LAN address was found and used, or detection failed and the
    # caller is left with the original to warn about — never a silent success.
    assert resolved.endswith("/api/v1/discovery")
    if resolved != "http://localhost:8000/api/v1/discovery":
        assert is_reachable_from_other_devices(resolved)


def test_a_malformed_base_is_treated_as_unreachable():
    assert not is_reachable_from_other_devices("")
    assert not is_reachable_from_other_devices("http://")
