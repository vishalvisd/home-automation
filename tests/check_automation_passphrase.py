"""
Check of the passphrase that guards the automation scripts.

Run on the development machine:

    uv run python tests/check_automation_passphrase.py

It starts a small web server on this machine with only the automation
addresses, the real passphrase service and the real script service,
all working in a temporary folder. Nothing on the Pi is touched and no
script is run.

The checks: before a passphrase is set every script address is refused;
the first visitor sets it and a second attempt is refused; afterwards
the scripts answer only to the right passphrase; the file holds no
passphrase in plain text and is private; deleting the file (the way out
when the passphrase is forgotten) brings back "not set" at once.

To look at the Automations tab against this stand-in on the Mac:

    uv run python tests/check_automation_passphrase.py --serve 8011
"""

import json
import logging
import shutil
import stat
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI

from home_automation.api.routes import automations
from home_automation.config.application import AUTOMATION_TEMPLATE_DIRECTORY
from home_automation.services import passphrase_service as module
from home_automation.services.automation_passphrase_service import (
    AutomationPassphraseService,
)
from home_automation.services.automation_script_service import (
    AutomationScriptService,
)


logging.getLogger("home_automation").setLevel(logging.CRITICAL)

failures = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global failures

    if condition:
        print(f"ok    {name}")
    else:
        failures += 1
        print(f"FAIL  {name}  {detail}")


def build_app(folder: Path) -> tuple[FastAPI, Path]:
    passphrase_file = folder / "automation_passphrase.json"

    app = FastAPI()
    app.state.automation_script_service = AutomationScriptService(
        AUTOMATION_TEMPLATE_DIRECTORY,
        folder / "automations",
    )
    app.state.automation_passphrase_service = AutomationPassphraseService(
        passphrase_file
    )
    app.include_router(automations.router)

    return app, passphrase_file


def start(app: FastAPI, port: int) -> uvicorn.Server:
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    threading.Thread(target=server.run, daemon=True).start()

    while not server.started:
        time.sleep(0.05)

    return server


def call(
    port: int,
    method: str,
    path: str,
    passphrase: str | None = None,
    body: dict | None = None,
) -> tuple[int, dict | list | None]:
    headers = {}

    if passphrase is not None:
        headers["X-Automations-Passphrase"] = quote(passphrase, safe="")

    data = None

    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read() or b"null")
        except ValueError:
            return error.code, None


def run_checks() -> None:
    # The real wait after a wrong passphrase is one second; the checks
    # give several wrong ones.
    module.WRONG_PASSPHRASE_DELAY_SECONDS = 0.05

    folder = Path(tempfile.mkdtemp(prefix="passphrase_check_"))
    port = 8012

    try:
        app, passphrase_file = build_app(folder)
        server = start(app, port)

        good = "tulsi ke patte 42"
        base = "/api/automations"

        # --- nothing set yet -------------------------------------------
        code, body = call(port, "GET", f"{base}/passphrase")
        check("not set at first", code == 200 and body == {"set": False})

        code, _ = call(port, "GET", base)
        check("script list refused before one is set", code == 403, str(code))

        code, _ = call(port, "GET", base, passphrase="anything")
        check("...also with some passphrase given", code == 403, str(code))

        code, _ = call(port, "POST", f"{base}/passphrase", body={"passphrase": "abc"})
        check("a passphrase under 4 characters is refused", code == 422, str(code))

        # --- first visitor sets it -------------------------------------
        code, body = call(port, "POST", f"{base}/passphrase", body={"passphrase": good})
        check("first visitor sets it", code == 200 and body == {"set": True}, str(code))

        code, _ = call(port, "POST", f"{base}/passphrase", body={"passphrase": "another one"})
        check("setting it a second time is refused", code == 409, str(code))

        code, body = call(port, "GET", f"{base}/passphrase")
        check("now reported as set", body == {"set": True})

        # --- the file ---------------------------------------------------
        text = passphrase_file.read_text(encoding="utf-8")
        check("the file does not hold the passphrase", good not in text)
        mode = stat.S_IMODE(passphrase_file.stat().st_mode)
        check("the file is private (0600)", mode == 0o600, oct(mode))

        # --- every script address -------------------------------------
        code, scripts = call(port, "GET", base, passphrase=good)
        check(
            "script list with the right passphrase",
            code == 200 and isinstance(scripts, list) and len(scripts) > 0,
            str(code),
        )
        key = scripts[0]["key"] if scripts else "none"

        guarded = [
            ("GET", base, None),
            ("GET", f"{base}/{key}", None),
            ("PUT", f"{base}/{key}", {"source": "print('x')"}),
            ("POST", f"{base}/{key}/restore", None),
            ("POST", f"{base}/{key}/run", None),
            ("POST", f"{base}/passphrase/check", None),
        ]

        for method, path, payload in guarded:
            code, _ = call(port, method, path, body=payload)
            check(f"no passphrase: {method} {path}", code == 401, str(code))

            code, _ = call(port, method, path, passphrase="wrong one", body=payload)
            check(f"wrong passphrase: {method} {path}", code == 401, str(code))

        code, body = call(port, "GET", f"{base}/{key}", passphrase=good)
        check("one script with the right passphrase", code == 200, str(code))
        untouched = body["source"] if isinstance(body, dict) else None

        code, _ = call(port, "POST", f"{base}/passphrase/check", passphrase=good)
        check("the check address accepts the right one", code == 200, str(code))

        code, _ = call(port, "POST", f"{base}/passphrase/check", passphrase=good + " ")
        check("a near miss is refused", code == 401, str(code))

        # The refused PUT above must not have changed the script.
        code, body = call(port, "GET", f"{base}/{key}", passphrase=good)
        check(
            "a refused save changed nothing",
            isinstance(body, dict) and body["source"] == untouched,
        )

        # --- other characters -----------------------------------------
        # (reset first: delete the file, as the owner would on the Pi)
        passphrase_file.unlink()

        code, body = call(port, "GET", f"{base}/passphrase")
        check("file deleted: not set again, no restart", body == {"set": False})

        code, _ = call(port, "GET", base, passphrase=good)
        check("the old passphrase no longer opens anything", code == 403, str(code))

        hindi = "मेरा घर 2026 %&+"
        code, _ = call(port, "POST", f"{base}/passphrase", body={"passphrase": hindi})
        check("a new one can be set, with any characters", code == 200, str(code))

        code, _ = call(port, "GET", base, passphrase=hindi)
        check("and it opens the scripts", code == 200, str(code))

        code, _ = call(port, "GET", base, passphrase=good)
        check("the old one stays refused", code == 401, str(code))

        # --- a damaged file is "not set", never "open" -----------------
        passphrase_file.write_text("{not json", encoding="utf-8")
        code, _ = call(port, "GET", base, passphrase=hindi)
        check("a damaged file opens nothing", code == 403, str(code))

        server.should_exit = True
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def serve(port: int) -> None:
    folder = Path(tempfile.mkdtemp(prefix="passphrase_demo_"))
    app, passphrase_file = build_app(folder)

    print(f"Stand-in backend on http://127.0.0.1:{port}")
    print(f"Passphrase file: {passphrase_file}")

    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    if "--serve" in sys.argv:
        serve(int(sys.argv[sys.argv.index("--serve") + 1]))
        sys.exit(0)

    run_checks()

    if failures:
        print(f"\n{failures} check(s) failed")
        sys.exit(1)

    print("\nall checks passed")
