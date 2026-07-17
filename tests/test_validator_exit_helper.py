import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

import ValidatorExitHelper as helper


PUBLIC_KEY = "0x" + ("a" * 96)
SECOND_PUBLIC_KEY = "0x" + ("b" * 96)


class ValidatorExitHelperTests(unittest.TestCase):
    def create_validator_tree(self, directory: Path):
        keys = directory / "keys"
        secrets = directory / "secrets"
        keys.mkdir()
        secrets.mkdir()
        keystore = keys / "voting-keystore.json"
        password = secrets / "password.txt"
        keystore.write_text("{}", encoding="utf-8")
        password.write_text("secret\n", encoding="utf-8")
        return keystore, password

    def test_load_validators_validates_and_resolves_relative_paths(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            keystore, password = self.create_validator_tree(root)
            definitions = root / "validator_definitions.yml"
            definitions.write_text(
                yaml.safe_dump(
                    [
                        {
                            "enabled": True,
                            "voting_public_key": PUBLIC_KEY.upper().replace("0X", "0x"),
                            "type": "local_keystore",
                            "voting_keystore_path": "keys/voting-keystore.json",
                            "voting_keystore_password_path": "secrets/password.txt",
                        },
                        {
                            "enabled": False,
                            "voting_public_key": SECOND_PUBLIC_KEY,
                            "type": "local_keystore",
                            "voting_keystore_path": "missing.json",
                        },
                    ]
                ),
                encoding="utf-8",
            )

            validators, warnings = helper.load_validators(definitions)

            self.assertEqual(len(validators), 1)
            self.assertEqual(validators[0].public_key, PUBLIC_KEY)
            self.assertEqual(validators[0].keystore_path, keystore.resolve())
            self.assertEqual(validators[0].password_path, password.resolve())
            self.assertEqual(warnings, [])

    def test_load_validators_skips_enabled_web3signer(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            keystore, _ = self.create_validator_tree(root)
            definitions = root / "validator_definitions.yml"
            definitions.write_text(
                yaml.safe_dump(
                    [
                        {
                            "enabled": True,
                            "voting_public_key": SECOND_PUBLIC_KEY,
                            "type": "web3signer",
                            "url": "http://127.0.0.1:9000",
                        },
                        {
                            "enabled": True,
                            "voting_public_key": PUBLIC_KEY,
                            "type": "local_keystore",
                            "voting_keystore_path": str(keystore),
                        },
                    ]
                ),
                encoding="utf-8",
            )

            validators, warnings = helper.load_validators(definitions)

            self.assertEqual([validator.public_key for validator in validators], [PUBLIC_KEY])
            self.assertEqual(len(warnings), 1)
            self.assertIn("web3signer", warnings[0])

    def test_load_validators_rejects_empty_yaml(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            definitions = Path(temporary_directory) / "validator_definitions.yml"
            definitions.write_text("", encoding="utf-8")

            with self.assertRaisesRegex(helper.ValidatorExitError, "empty"):
                helper.load_validators(definitions)

    def test_parse_exit_count_rejects_zero_and_out_of_range(self):
        with self.assertRaisesRegex(helper.ValidatorExitError, "at least 1"):
            helper.parse_exit_count("0", 2)
        with self.assertRaisesRegex(helper.ValidatorExitError, "only 2"):
            helper.parse_exit_count("3", 2)
        self.assertEqual(helper.parse_exit_count("all", 2), 2)
        self.assertEqual(helper.parse_exit_count("1", 2), 1)

    def test_build_command_contains_no_shell_pipeline_or_sudo(self):
        validator = helper.Validator(
            public_key=PUBLIC_KEY,
            keystore_path=Path("/tmp/keystore.json"),
            password_path=Path("/tmp/password.txt"),
            inline_password=None,
        )

        command = helper.build_exit_command(
            lighthouse=Path("/usr/local/bin/lighthouse"),
            testnet_dir=Path("/home/user/node/config"),
            beacon_node="https://example.invalid/",
            validator=validator,
            password_file=validator.password_path,
        )

        self.assertEqual(command[0], "/usr/local/bin/lighthouse")
        self.assertNotIn("echo", command)
        self.assertNotIn("sudo", command)
        self.assertNotIn("|", command)
        self.assertIn("--no-confirmation", command)
        self.assertIn("--password-file", command)

    def test_submit_exit_calls_subprocess_without_shell_true(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            keystore = root / "keystore.json"
            password = root / "password.txt"
            keystore.write_text("{}", encoding="utf-8")
            password.write_text("secret\n", encoding="utf-8")
            validator = helper.Validator(
                public_key=PUBLIC_KEY,
                keystore_path=keystore,
                password_path=password,
                inline_password=None,
            )

            with mock.patch.object(helper.subprocess, "run") as run_mock:
                status, message = helper.submit_validator_exit(
                    lighthouse=Path("/usr/local/bin/lighthouse"),
                    testnet_dir=root,
                    beacon_node="https://example.invalid/",
                    validator=validator,
                    dry_run=False,
                )

            self.assertEqual(status, "confirmed")
            self.assertIn("confirmed", message.lower())
            run_mock.assert_called_once()
            _, keyword_arguments = run_mock.call_args
            self.assertEqual(keyword_arguments, {"check": True})

    def test_submit_exit_reports_nonzero_lighthouse_status(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            keystore = root / "keystore.json"
            keystore.write_text("{}", encoding="utf-8")
            validator = helper.Validator(
                public_key=PUBLIC_KEY,
                keystore_path=keystore,
                password_path=None,
                inline_password=None,
            )

            with mock.patch.object(
                helper.subprocess,
                "run",
                side_effect=subprocess.CalledProcessError(7, ["lighthouse"]),
            ):
                status, message = helper.submit_validator_exit(
                    lighthouse=Path("/usr/local/bin/lighthouse"),
                    testnet_dir=root,
                    beacon_node="https://example.invalid/",
                    validator=validator,
                    dry_run=False,
                )

            self.assertEqual(status, "failed")
            self.assertIn("7", message)

    def test_inline_password_uses_temporary_mode_0600_file_and_removes_it(self):
        validator = helper.Validator(
            public_key=PUBLIC_KEY,
            keystore_path=Path("/tmp/keystore.json"),
            password_path=None,
            inline_password="top-secret",
        )

        with helper.lighthouse_password_file(validator) as password_file:
            self.assertIsNotNone(password_file)
            assert password_file is not None
            self.assertTrue(password_file.exists())
            self.assertEqual(password_file.read_text(encoding="utf-8"), "top-secret\n")
            permissions = stat.S_IMODE(password_file.stat().st_mode)
            self.assertEqual(permissions, 0o600)
            temporary_path = password_file

        self.assertFalse(temporary_path.exists())

    def test_dry_run_does_not_call_subprocess(self):
        validator = helper.Validator(
            public_key=PUBLIC_KEY,
            keystore_path=Path("/tmp/keystore.json"),
            password_path=None,
            inline_password=None,
        )

        with mock.patch.object(helper.subprocess, "run") as run_mock:
            status, command = helper.submit_validator_exit(
                lighthouse=Path("/usr/local/bin/lighthouse"),
                testnet_dir=Path("/tmp/config"),
                beacon_node="https://example.invalid/",
                validator=validator,
                dry_run=True,
            )

        self.assertEqual(status, "dry-run")
        self.assertIn("lighthouse", command)
        run_mock.assert_not_called()

    def test_audit_log_appends_and_forces_private_permissions(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            log_file = Path(temporary_directory) / "audit.jsonl"
            helper.append_audit_log(log_file, {"status": "dry-run", "number": 1})
            helper.append_audit_log(log_file, {"status": "confirmed", "number": 2})

            records = [
                json.loads(line)
                for line in log_file.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["number"], 1)
            self.assertEqual(records[1]["number"], 2)
            self.assertEqual(stat.S_IMODE(log_file.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
