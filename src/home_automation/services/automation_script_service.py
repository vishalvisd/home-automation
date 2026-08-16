import subprocess
import sys

from pathlib import Path
from threading import Lock, Thread

from home_automation.config.automations import (
    AUTOMATIONS,
    AutomationDefinition,
)


class UnknownAutomationError(ValueError):
    pass


class AutomationAlreadyRunningError(RuntimeError):
    pass


class AutomationScriptService:
    """
    Maintain editable runtime copies of automation scripts.

    Repository templates are factory defaults.
    runtime/automations contains the scripts actually executed.
    """

    def __init__(
        self,
        template_directory: Path,
        runtime_directory: Path,
    ) -> None:
        self._template_directory = template_directory
        self._runtime_directory = runtime_directory

        self._lock = Lock()
        self._running: set[str] = set()
        self._results: dict[str, dict] = {}

        self._runtime_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._create_missing_runtime_scripts()

    def list(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "key": definition.key,
                    "name": definition.name,
                    "description": definition.description,
                    "running": definition.key in self._running,
                }
                for definition in AUTOMATIONS.values()
            ]

    def get(self, key: str) -> dict:
        definition = self._get_definition(key)

        path = self._runtime_path(definition)

        with self._lock:
            result = self._results.get(
                key,
                {
                    "exit_code": None,
                    "output": None,
                },
            )

            running = key in self._running

        return {
            "key": definition.key,
            "name": definition.name,
            "description": definition.description,
            "source": path.read_text(
                encoding="utf-8"
            ),
            "running": running,
            "last_exit_code": result["exit_code"],
            "last_output": result["output"],
        }

    def save(self, key: str, source: str) -> dict:
        definition = self._get_definition(key)
        path = self._runtime_path(definition)

        temporary_file = path.with_suffix(".tmp")

        temporary_file.write_text(
            source,
            encoding="utf-8",
        )

        temporary_file.replace(path)

        return self.get(key)

    def restore(self, key: str) -> dict:
        definition = self._get_definition(key)

        template_path = self._template_path(definition)
        runtime_path = self._runtime_path(definition)

        runtime_path.write_text(
            template_path.read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )

        return self.get(key)

    def run(self, key: str) -> dict:
        definition = self._get_definition(key)

        with self._lock:
            if key in self._running:
                raise AutomationAlreadyRunningError(
                    f"{definition.name} is already running."
                )

            self._running.add(key)

        thread = Thread(
            target=self._execute,
            args=(definition,),
            name=f"automation-{key}",
            daemon=True,
        )

        thread.start()

        return self.get(key)

    def _execute(
        self,
        definition: AutomationDefinition,
    ) -> None:
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(
                        self._runtime_path(
                            definition
                        )
                    ),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            output = (
                result.stdout
                + result.stderr
            ).strip()

            with self._lock:
                self._results[definition.key] = {
                    "exit_code": result.returncode,
                    "output": output,
                }

        except Exception as error:
            with self._lock:
                self._results[definition.key] = {
                    "exit_code": -1,
                    "output": str(error),
                }

        finally:
            with self._lock:
                self._running.discard(
                    definition.key
                )

    def _create_missing_runtime_scripts(self) -> None:
        for definition in AUTOMATIONS.values():
            runtime_path = self._runtime_path(
                definition
            )

            if runtime_path.exists():
                continue

            template_path = self._template_path(
                definition
            )

            runtime_path.write_text(
                template_path.read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
            )

    @staticmethod
    def _get_definition(
        key: str,
    ) -> AutomationDefinition:
        try:
            return AUTOMATIONS[key]
        except KeyError as error:
            raise UnknownAutomationError(
                f"Unknown automation: {key}"
            ) from error

    def _template_path(
        self,
        definition: AutomationDefinition,
    ) -> Path:
        return (
            self._template_directory
            / definition.filename
        )

    def _runtime_path(
        self,
        definition: AutomationDefinition,
    ) -> Path:
        return (
            self._runtime_directory
            / definition.filename
        )