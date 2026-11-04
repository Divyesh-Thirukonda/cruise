"""Local SDK/harness checks only; no Modal cloud calls or deployment."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec("modal"), "optional Modal SDK is not installed")
class ModalVerifierTests(unittest.TestCase):
    def setUp(self):
        from integrations import modal_verify
        self.integration = modal_verify

    def test_local_function_runs_real_verifier_and_cannot_authorize_activation(self):
        from tests.test_game_runtime import fixture
        result = self.integration.verify_package.local(fixture())
        self.assertTrue(result["report"]["passed"], result)
        self.assertFalse(result["activation_authorized"])
        self.assertEqual(len(result["report"]["metrics"]["package_sha256"]), 64)
        broken = fixture("function init(){while(true){}}")
        result = self.integration.verify_package.local(broken)
        self.assertFalse(result["report"]["passed"])
        self.assertFalse(result["activation_authorized"])

    def test_invalid_package_never_uploads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "package.json"
            path.write_text(json.dumps({"kind": "shell"}))
            with patch.object(self.integration.verify_package, "remote") as remote:
                with self.assertRaises(ValueError):
                    self.integration.main(str(path))
                remote.assert_not_called()

    def test_remote_failure_is_not_reported_as_success(self):
        from tests.test_game_runtime import fixture
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "package.json"
            path.write_text(json.dumps(fixture()))
            with patch.object(self.integration.verify_package, "remote",
                              return_value={"report": {"passed": False}}), patch("builtins.print"):
                with self.assertRaises(SystemExit) as caught:
                    self.integration.main(str(path))
                self.assertEqual(caught.exception.code, 1)
