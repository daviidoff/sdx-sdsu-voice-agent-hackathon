import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from test_discovery import demo_request

spec = importlib.util.spec_from_file_location("run_daytona", Path(__file__).resolve().parents[1] / "scripts/run_daytona.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class DaytonaTests(unittest.TestCase):
    def test_upload_run_read_cleanup(self):
        sandbox = Mock(id="sandbox1")
        sandbox.process.run.return_value = SimpleNamespace(exit_code=0)
        sandbox.fs.read_text.return_value = json.dumps({"status": "completed", "leads": []})
        client = Mock()
        client.v2.create.return_value = sandbox
        result = launcher.run_in_daytona(client, demo_request())
        self.assertEqual(result["execution"]["sandbox_id"], "sandbox1")
        client.v2.delete.assert_called_once_with(sandbox)
        self.assertEqual(client.v2.create.call_args.kwargs["env"], {})
        files = [c.args[0] for c in sandbox.fs.upload_file.call_args_list]
        self.assertTrue(all(f.endswith((".py", "facilities.json")) for f in files))
        self.assertTrue(any(f.endswith("facilities.json") for f in files))

    def test_timeout_deletes_sandbox(self):
        sandbox = Mock(id="sandbox1")
        sandbox.process.run.return_value = SimpleNamespace(exit_code=None)
        client = Mock()
        client.v2.create.return_value = sandbox
        with self.assertRaises(RuntimeError):
            launcher.run_in_daytona(client, demo_request())
        client.v2.delete.assert_called_once_with(sandbox)
        sandbox.fs.read_text.assert_not_called()

    def test_upload_error_deletes_sandbox(self):
        sandbox = Mock(id="sandbox1")
        sandbox.fs.upload_file.side_effect = RuntimeError("upload error")
        client = Mock()
        client.v2.create.return_value = sandbox
        with self.assertRaises(RuntimeError):
            launcher.run_in_daytona(client, demo_request())
        client.v2.delete.assert_called_once_with(sandbox)

    def test_osm_needs_no_search_credentials(self):
        from test_osm import request
        sandbox = Mock(id="sandbox1")
        sandbox.process.run.return_value = SimpleNamespace(exit_code=0)
        sandbox.fs.read_text.return_value = json.dumps({"status": "completed", "leads": []})
        client = Mock()
        client.v2.create.return_value = sandbox
        launcher.run_in_daytona(client, request(), provider="osm")
        self.assertEqual(client.v2.create.call_args.kwargs["env"], {})
        self.assertIn("--provider osm", sandbox.process.run.call_args.args[0])

    def test_invalid_osm_request_does_not_allocate_sandbox(self):
        client = Mock()
        with self.assertRaises(ValueError):
            launcher.run_in_daytona(client, demo_request(), provider="osm")
        client.v2.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
