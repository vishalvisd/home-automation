"""
Check of the "Restart router" button (RouterRestartService.power_cycle).

Run on the development machine:

    uv run python tests/check_router_button.py

No relay is touched: a stand-in relay writes down what it is told. The
check is that the router's power always comes back by itself, that a
second press while one is running is refused, and that a backend
shutdown or a failing relay never leaves the relay on.
"""

import logging
import time
from types import SimpleNamespace

from home_automation.services import router_restart_service as module
from home_automation.services.router_restart_service import (
    ROUTER_RELAY_KEY,
    RouterRestartService,
)


class FakeRelays:
    def __init__(self, fail_on: bool = False) -> None:
        self.calls: list[tuple[str, str, float]] = []
        self.fail_on = fail_on

    def turn_on(self, key: str) -> None:
        self.calls.append(("on", key, time.monotonic()))

        if self.fail_on:
            raise RuntimeError("relay did not answer")

    def turn_off(self, key: str) -> None:
        self.calls.append(("off", key, time.monotonic()))

    def commands(self) -> list[str]:
        return [command for command, _, _ in self.calls]


def build(off_seconds: float, fail_on: bool = False):
    settings = SimpleNamespace(
        router_restart_enabled=True,
        router_restart_off_seconds=off_seconds,
        router_restart_wait_seconds=0,
    )
    relays = FakeRelays(fail_on=fail_on)
    service = RouterRestartService(
        SimpleNamespace(get=lambda: settings),
        relays,
    )

    return service, relays


def wait_until_free(service: RouterRestartService, seconds: float) -> bool:
    """True once no restart is running any more."""

    deadline = time.monotonic() + seconds

    while time.monotonic() < deadline:
        if service._run_lock.acquire(blocking=False):
            service._run_lock.release()
            return True

        time.sleep(0.02)

    return False


def check(name: str, ok: bool) -> bool:
    print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    return ok


def main() -> None:
    # The real wait before the power is cut is 2 seconds; shorten it.
    module.BUTTON_DELAY_SECONDS = 0.2
    results = []

    # 1. A press: power off, then back on by itself after the set time.
    service, relays = build(off_seconds=0.6)
    started = service.power_cycle()

    results.append(check(
        "a press is accepted and says how long the power is off",
        started == {"delay_seconds": 0.2, "off_seconds": 0.6},
    ))
    results.append(check(
        "nothing is switched before the short delay has passed",
        relays.commands() == [],
    ))

    # 2. A second press while the first is running is refused.
    results.append(check(
        "a second press while it is running is refused",
        service.power_cycle() is None,
    ))

    results.append(check(
        "it finishes by itself",
        wait_until_free(service, 3),
    ))
    results.append(check(
        "the relay was switched on once and off once, in that order",
        relays.commands() == ["on", "off"]
        and all(key == ROUTER_RELAY_KEY for _, key, _ in relays.calls),
    ))

    off_for = relays.calls[1][2] - relays.calls[0][2] if len(relays.calls) == 2 else 0
    results.append(check(
        f"the power was off for the set time (0.6 s, measured {off_for:.2f} s)",
        0.5 <= off_for <= 1.0,
    ))

    # 3. Afterwards another press works again.
    relays.calls.clear()
    results.append(check(
        "a later press is accepted again",
        service.power_cycle() is not None and wait_until_free(service, 3)
        and relays.commands() == ["on", "off"],
    ))

    # 4. A backend shutdown in the middle gives the power back at once.
    service, relays = build(off_seconds=30)
    service.power_cycle()
    time.sleep(0.5)
    began = time.monotonic()
    service.abort()

    results.append(check(
        "a backend shutdown ends it at once",
        wait_until_free(service, 2) and time.monotonic() - began < 2,
    ))
    results.append(check(
        "and the relay is released, not left on",
        relays.commands() == ["on", "off"],
    ))

    # 5. A shutdown before the power was cut switches nothing.
    service, relays = build(off_seconds=30)
    service.power_cycle()
    service.abort()

    results.append(check(
        "a shutdown during the short delay never cuts the power",
        wait_until_free(service, 2) and relays.commands() == [],
    ))

    # 6. A relay that fails when switched on is still released. The
    #    service writes the error to the log; keep it off the screen.
    logging.disable(logging.CRITICAL)
    service, relays = build(off_seconds=0.3, fail_on=True)
    service.power_cycle()

    results.append(check(
        "a relay error still ends with the relay released",
        wait_until_free(service, 3) and relays.commands() == ["on", "off"],
    ))
    results.append(check(
        "and the next press is not blocked by the failed one",
        service.power_cycle() is not None and wait_until_free(service, 3),
    ))

    if not all(results):
        raise SystemExit("some checks failed")

    print("all router button checks passed")


if __name__ == "__main__":
    main()
