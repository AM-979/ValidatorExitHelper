#!/usr/bin/env python3
"""Safely submit Lighthouse voluntary exits for local validators.

The script reads enabled local-keystore validators from Lighthouse's
``validator_definitions.yml``, validates all inputs before making changes,
requires an explicit irreversible-operation confirmation, and records an
append-only JSON Lines audit log.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

import yaml

DEFAULT_VALIDATOR_DEFINITIONS = (
    "~/.lighthouse/custom/validators/validator_definitions.yml"
)
DEFAULT_TESTNET_DIR = "~/node/config"
DEFAULT_LIGHTHOUSE = "lighthouse"
DEFAULT_BEACON_NODE = "https://metrabyte-cl.jibchain.net/"
DEFAULT_EXPLORER_BASE = "https://dora.jibchain.net/validator/"
DEFAULT_LOG_FILE = "exited_validators_log.jsonl"

PUBLIC_KEY_PATTERN = re.compile(r"^0x[0-9a-fA-F]{96}$")


class ValidatorExitError(Exception):
    """Raised for configuration or validation errors that prevent safe execution."""


@dataclass(frozen=True)
class Validator:
    """Validated local validator definition used to construct an exit command."""

    public_key: str
    keystore_path: Path
    password_path: Optional[Path]
    inline_password: Optional[str]


def expand_path(value: str, base_dir: Optional[Path] = None) -> Path:
    """Expand environment variables and ``~``, resolving relative paths safely."""

    expanded = Path(os.path.expandvars(os.path.expanduser(value)))
    if not expanded.is_absolute() and base_dir is not None:
        expanded = base_dir / expanded
    return expanded.resolve()


def load_validators(file_path: Path) -> Tuple[List[Validator], List[str]]:
    """Load and validate enabled local-keystore validators from Lighthouse YAML."""

    if not file_path.is_file():
        raise ValidatorExitError(
            "Validator definitions file does not exist or is not a file: "
            f"{file_path}"
        )

    try:
        with file_path.open("r", encoding="utf-8") as handle:
            raw_data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ValidatorExitError(
            f"Unable to parse validator definitions YAML: {exc}"
        ) from exc
    except OSError as exc:
        raise ValidatorExitError(
            f"Unable to read validator definitions file: {exc}"
        ) from exc

    if raw_data is None:
        raise ValidatorExitError("Validator definitions file is empty.")
    if not isinstance(raw_data, list):
        raise ValidatorExitError(
            "Validator definitions YAML must contain a top-level list."
        )

    validators: List[Validator] = []
    warnings: List[str] = []
    public_keys = set()
    base_dir = file_path.parent

    for index, entry in enumerate(raw_data, start=1):
        location = f"entry {index}"
        if not isinstance(entry, dict):
            raise ValidatorExitError(f"{location} must be a YAML mapping.")
        if entry.get("enabled") is not True:
            continue

        validator_type = entry.get("type", "local_keystore")
        if validator_type != "local_keystore":
            warnings.append(
                f"Skipping {location}: enabled validator type '{validator_type}' "
                "does not expose a local keystore."
            )
            continue

        public_key = entry.get("voting_public_key")
        if not isinstance(public_key, str) or not PUBLIC_KEY_PATTERN.fullmatch(
            public_key
        ):
            raise ValidatorExitError(
                f"{location} has an invalid voting_public_key; expected 0x plus "
                "96 hexadecimal characters."
            )
        public_key = public_key.lower()
        if public_key in public_keys:
            raise ValidatorExitError(
                f"Duplicate voting_public_key in enabled validators: {public_key}"
            )

        raw_keystore_path = entry.get("voting_keystore_path")
        if not isinstance(raw_keystore_path, str) or not raw_keystore_path.strip():
            raise ValidatorExitError(
                f"{location} is missing voting_keystore_path."
            )
        keystore_path = expand_path(raw_keystore_path, base_dir)
        if not keystore_path.is_file():
            raise ValidatorExitError(
                f"Keystore for {public_key} does not exist or is not a file: "
                f"{keystore_path}"
            )

        password_path: Optional[Path] = None
        raw_password_path = entry.get("voting_keystore_password_path")
        if raw_password_path is not None:
            if not isinstance(raw_password_path, str) or not raw_password_path.strip():
                raise ValidatorExitError(
                    f"{location} has an invalid voting_keystore_password_path."
                )
            password_path = expand_path(raw_password_path, base_dir)
            if not password_path.is_file():
                raise ValidatorExitError(
                    f"Password file for {public_key} does not exist or is not a file: "
                    f"{password_path}"
                )

        inline_password = entry.get("voting_keystore_password")
        if inline_password is not None and not isinstance(inline_password, str):
            raise ValidatorExitError(
                f"{location} has a non-string voting_keystore_password."
            )
        if password_path is not None and inline_password is not None:
            warnings.append(
                f"{public_key}: both password path and inline password are present; "
                "the password path will be used."
            )
            inline_password = None
        elif inline_password is not None:
            warnings.append(
                f"{public_key}: inline keystore password detected. It will be copied "
                "to a temporary mode-0600 file for Lighthouse and deleted immediately."
            )

        validators.append(
            Validator(
                public_key=public_key,
                keystore_path=keystore_path,
                password_path=password_path,
                inline_password=inline_password,
            )
        )
        public_keys.add(public_key)

    if not validators:
        raise ValidatorExitError(
            "No enabled local-keystore validators were found after validation."
        )

    return validators, warnings


def resolve_lighthouse(executable: str) -> Path:
    """Resolve and validate the Lighthouse executable without invoking a shell."""

    expanded = os.path.expandvars(os.path.expanduser(executable))
    if os.sep in expanded:
        candidate = Path(expanded).resolve()
    else:
        located = shutil.which(expanded)
        if located is None:
            raise ValidatorExitError(
                f"Lighthouse executable was not found in PATH: {executable}"
            )
        candidate = Path(located).resolve()

    if not candidate.is_file():
        raise ValidatorExitError(
            f"Lighthouse executable does not exist or is not a file: {candidate}"
        )
    if not os.access(str(candidate), os.X_OK):
        raise ValidatorExitError(
            f"Lighthouse executable is not executable: {candidate}"
        )
    return candidate


def validate_testnet_dir(testnet_dir: Path) -> None:
    """Verify that the custom network directory is present and non-empty."""

    if not testnet_dir.is_dir():
        raise ValidatorExitError(
            f"Testnet directory does not exist or is not a directory: {testnet_dir}"
        )
    try:
        if not any(testnet_dir.iterdir()):
            raise ValidatorExitError(f"Testnet directory is empty: {testnet_dir}")
    except OSError as exc:
        raise ValidatorExitError(f"Unable to inspect testnet directory: {exc}") from exc


def parse_exit_count(value: str, available: int) -> int:
    """Parse ``all`` or a positive validator count within the available range."""

    normalized = value.strip().lower()
    if normalized == "all":
        return available
    if not normalized.isdigit():
        raise ValidatorExitError("Exit count must be a positive integer or 'all'.")

    count = int(normalized)
    if count < 1:
        raise ValidatorExitError("Exit count must be at least 1.")
    if count > available:
        raise ValidatorExitError(
            f"Requested {count} validators, but only {available} are available."
        )
    return count


def build_exit_command(
    lighthouse: Path,
    testnet_dir: Path,
    beacon_node: str,
    validator: Validator,
    password_file: Optional[Path],
) -> List[str]:
    """Build a shell-free Lighthouse command after the script's strong confirmation."""

    command = [
        str(lighthouse),
        "--testnet-dir",
        str(testnet_dir),
        "account",
        "validator",
        "exit",
        "--keystore",
        str(validator.keystore_path),
        "--beacon-node",
        beacon_node,
        "--no-confirmation",
    ]
    if password_file is not None:
        command.extend(["--password-file", str(password_file)])
    return command


@contextmanager
def lighthouse_password_file(validator: Validator) -> Iterator[Optional[Path]]:
    """Yield a password file without exposing password contents in process arguments."""

    if validator.password_path is not None:
        yield validator.password_path
        return
    if validator.inline_password is None:
        yield None
        return

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=".validator-exit-password-", text=True
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(file_descriptor, 0o600)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(validator.inline_password)
            handle.write("\n")
        yield temporary_path
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def append_audit_log(log_file: Path, record: Dict[str, object]) -> None:
    """Append one mode-0600 JSON record without truncating prior audit history."""

    log_file.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    file_descriptor = os.open(str(log_file), flags, 0o600)
    try:
        os.fchmod(file_descriptor, 0o600)
        payload = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        os.write(file_descriptor, payload.encode("utf-8"))
    finally:
        os.close(file_descriptor)


def make_audit_record(
    validator: Validator,
    status: str,
    beacon_node: str,
    explorer_base: str,
    message: str = "",
) -> Dict[str, object]:
    """Create an audit record that contains no password material."""

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "public_key": validator.public_key,
        "status": status,
        "beacon_node": beacon_node,
        "keystore_path": str(validator.keystore_path),
        "explorer_url": f"{explorer_base.rstrip('/')}/{validator.public_key}",
        "message": message,
    }


def print_selection(validators: Sequence[Validator], explorer_base: str) -> None:
    """Display exact validators before the irreversible confirmation prompt."""

    print("\nValidators selected for voluntary exit:")
    for position, validator in enumerate(validators, start=1):
        print(f"  {position}. {validator.public_key}")
        print(f"     Keystore: {validator.keystore_path}")
        print(
            "     Explorer: "
            f"{explorer_base.rstrip('/')}/{validator.public_key}"
        )


def confirm_irreversible_action(count: int) -> bool:
    """Require an exact phrase instead of a weak yes/no confirmation."""

    noun = "VALIDATOR" if count == 1 else "VALIDATORS"
    phrase = f"EXIT {count} {noun}"
    print("\nWARNING: A voluntary exit is irreversible.")
    response = input(f"Type '{phrase}' to continue: ").strip()
    return response == phrase


def submit_validator_exit(
    lighthouse: Path,
    testnet_dir: Path,
    beacon_node: str,
    validator: Validator,
    dry_run: bool,
) -> Tuple[str, str]:
    """Submit one exit and return an audit status and human-readable message."""

    with lighthouse_password_file(validator) as password_file:
        command = build_exit_command(
            lighthouse=lighthouse,
            testnet_dir=testnet_dir,
            beacon_node=beacon_node,
            validator=validator,
            password_file=password_file,
        )
        if dry_run:
            return "dry-run", shlex.join(command)

        try:
            # shell=False is intentional. Lighthouse inherits the terminal only when
            # it needs to prompt for a password that was not supplied by the YAML.
            subprocess.run(command, check=True)
        except subprocess.CalledProcessError as exc:
            return "failed", f"Lighthouse exited with status {exc.returncode}."
        except OSError as exc:
            return "failed", f"Unable to execute Lighthouse: {exc}"

    # Lighthouse is intentionally run without --no-wait. A zero exit status is
    # recorded only after it observes the validator entering an exiting/exited state.
    return "confirmed", "Lighthouse confirmed the voluntary exit state."


def create_argument_parser() -> argparse.ArgumentParser:
    """Create the command-line interface."""

    parser = argparse.ArgumentParser(
        description=(
            "Safely exit enabled local-keystore validators using Lighthouse. "
            "Defaults target Jibchain but every path and endpoint is configurable."
        )
    )
    parser.add_argument(
        "--validator-definitions",
        default=os.environ.get(
            "VALIDATOR_DEFINITIONS_PATH", DEFAULT_VALIDATOR_DEFINITIONS
        ),
        help="Path to Lighthouse validator_definitions.yml.",
    )
    parser.add_argument(
        "--testnet-dir",
        default=os.environ.get("TESTNET_DIR", DEFAULT_TESTNET_DIR),
        help="Path to the Lighthouse custom-network configuration directory.",
    )
    parser.add_argument(
        "--lighthouse",
        default=os.environ.get("LIGHTHOUSE_PATH", DEFAULT_LIGHTHOUSE),
        help="Lighthouse executable name or absolute path.",
    )
    parser.add_argument(
        "--beacon-node",
        default=os.environ.get("BEACON_NODE", DEFAULT_BEACON_NODE),
        help="Beacon Node HTTP API endpoint used to publish and verify exits.",
    )
    parser.add_argument(
        "--explorer-base",
        default=os.environ.get("EXPLORER_BASE", DEFAULT_EXPLORER_BASE),
        help="Base validator explorer URL used in console output and logs.",
    )
    parser.add_argument(
        "--log-file",
        default=os.environ.get("EXIT_LOG_FILE", DEFAULT_LOG_FILE),
        help="Append-only JSON Lines audit log path.",
    )
    parser.add_argument(
        "--count",
        help="Number of validators to exit, or 'all'. Prompts when omitted.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and display commands without submitting any exit.",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop after the first Lighthouse failure instead of continuing.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds to wait between validator exit commands (default: 1).",
    )
    return parser


def run(argv: Optional[Sequence[str]] = None) -> int:
    """Run the CLI and return a process exit code."""

    arguments = create_argument_parser().parse_args(argv)
    if arguments.delay < 0:
        raise ValidatorExitError("--delay cannot be negative.")
    if not arguments.beacon_node.startswith(("http://", "https://")):
        raise ValidatorExitError("--beacon-node must start with http:// or https://.")

    validator_definitions = expand_path(arguments.validator_definitions)
    testnet_dir = expand_path(arguments.testnet_dir)
    log_file = expand_path(arguments.log_file)
    lighthouse = resolve_lighthouse(arguments.lighthouse)
    validate_testnet_dir(testnet_dir)

    validators, warnings = load_validators(validator_definitions)
    for warning in warnings:
        print(f"Warning: {warning}", file=sys.stderr)

    print(f"Validated enabled local validators: {len(validators)}")
    raw_count = arguments.count
    if raw_count is None:
        raw_count = input("Enter the number of validators to exit or 'all': ")
    exit_count = parse_exit_count(raw_count, len(validators))
    selected = validators[:exit_count]
    print_selection(selected, arguments.explorer_base)

    if arguments.dry_run:
        print("\nDry-run mode: no voluntary exits will be submitted.")
    elif not confirm_irreversible_action(exit_count):
        print("Confirmation did not match. Operation canceled.")
        return 2

    confirmed = 0
    failed = 0
    dry_runs = 0

    for position, validator in enumerate(selected, start=1):
        print(
            f"\n[{position}/{exit_count}] Processing validator "
            f"{validator.public_key}"
        )
        try:
            status, message = submit_validator_exit(
                lighthouse=lighthouse,
                testnet_dir=testnet_dir,
                beacon_node=arguments.beacon_node,
                validator=validator,
                dry_run=arguments.dry_run,
            )
        except KeyboardInterrupt:
            append_audit_log(
                log_file,
                make_audit_record(
                    validator,
                    "interrupted",
                    arguments.beacon_node,
                    arguments.explorer_base,
                    "Interrupted by user.",
                ),
            )
            raise

        append_audit_log(
            log_file,
            make_audit_record(
                validator,
                status,
                arguments.beacon_node,
                arguments.explorer_base,
                message,
            ),
        )

        if status == "confirmed":
            confirmed += 1
            print(f"Confirmed: {validator.public_key}")
        elif status == "dry-run":
            dry_runs += 1
            print(f"Dry run command: {message}")
        else:
            failed += 1
            print(f"Failed: {validator.public_key}: {message}", file=sys.stderr)
            if arguments.stop_on_error:
                break

        if position < exit_count and not arguments.dry_run and arguments.delay:
            time.sleep(arguments.delay)

    print("\nExit process summary")
    print(f"  Confirmed exits: {confirmed}")
    print(f"  Failed exits:    {failed}")
    print(f"  Dry-run entries: {dry_runs}")
    print(f"  Audit log:       {log_file}")
    print(
        "Keep each validator client online until its exit epoch. Withdrawal timing "
        "depends on the chain's exit queue, withdrawability delay, credentials, and "
        "withdrawal sweep; it must not be assumed to be 1-2 days."
    )

    return 1 if failed else 0


def main() -> None:
    """Console entry point with concise safe error handling."""

    try:
        raise SystemExit(run())
    except ValidatorExitError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2)
    except KeyboardInterrupt:
        print("\nInterrupted. Check the audit log and explorer before retrying.", file=sys.stderr)
        raise SystemExit(130)


if __name__ == "__main__":
    main()
