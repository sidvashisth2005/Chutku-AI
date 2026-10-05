from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chutku.app import create_runtime
from chutku.plans import build_plan, run_plan
from chutku.tools.registry import Tool


class ReviewedPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.runtime = create_runtime(Path(self.temp.name))
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.runtime.close)

    def test_dependencies_exact_content_and_final_state(self):
        plan = build_plan(['create folder demo', 'write two  spaces then stop to demo/note.txt',
                           'read demo/note.txt', 'list files in demo'], self.runtime)
        self.assertFalse((self.runtime.granted_root / 'demo').exists())
        result = run_plan(plan, self.runtime)
        self.assertEqual(result['state'], 'COMPLETED', result)
        self.assertEqual(len(result['steps']), 4)
        self.assertEqual((self.runtime.granted_root / 'demo/note.txt').read_text(), 'two  spaces then stop')

    def test_late_invalid_step_has_no_effects(self):
        for last in ['delete everything', 'write secret to ../escape.txt', 'read missing.txt']:
            with self.assertRaises(ValueError):
                build_plan(['create folder untouched', last], self.runtime)
            self.assertFalse((self.runtime.granted_root / 'untouched').exists())

    def test_changed_file_invalidates_before_any_step(self):
        target = self.runtime.granted_root / 'note.txt'
        target.write_text('before')
        plan = build_plan(['create folder untouched', 'write replacement to note.txt'], self.runtime)
        target.write_text('external edit')
        self.assertEqual(run_plan(plan, self.runtime)['state'], 'FAILED')
        self.assertEqual(target.read_text(), 'external edit')
        self.assertFalse((self.runtime.granted_root / 'untouched').exists())

    def test_tampered_tool_call_fails_closed(self):
        plan = deepcopy(build_plan(['what time is it'], self.runtime))
        plan['steps'][0]['tool'] = 'apps.open'
        self.assertEqual(run_plan(plan, self.runtime)['state'], 'FAILED')

    def test_changed_tool_manifest_invalidates_reviewed_plan(self):
        plan = build_plan(['what time is it'], self.runtime)
        original = self.runtime.registry.get('system.get_time')
        self.runtime.registry._tools['system.get_time'] = Tool(
            original.name, 'Changed after review', original.base_risk, original.execute,
            original.validate_arguments, argument_schema=original.argument_schema)
        self.assertEqual(run_plan(plan, self.runtime)['state'], 'FAILED')

    def test_pause_prevents_execution(self):
        plan = build_plan(['write blocked to note.txt'], self.runtime)
        self.runtime.action_control.pause()
        self.assertEqual(run_plan(plan, self.runtime)['state'], 'FAILED')
        self.assertFalse((self.runtime.granted_root / 'note.txt').exists())

    def test_external_change_between_steps_stops_remaining_work(self):
        plan = build_plan(['write intended to note.txt', 'create folder untouched'], self.runtime)
        original = self.runtime.run
        def changed(*args, **kwargs):
            result = original(*args, **kwargs)
            (self.runtime.granted_root / 'note.txt').write_text('external edit')
            return result
        with patch.object(self.runtime, 'run', side_effect=changed):
            result = run_plan(plan, self.runtime)
        self.assertEqual(result['state'], 'FAILED')
        self.assertEqual(len(result['steps']), 1)
        self.assertFalse((self.runtime.granted_root / 'untouched').exists())
        self.assertEqual((self.runtime.granted_root / 'note.txt').read_text(), 'external edit')

    def test_repeated_writes_verify_last_intended_value(self):
        plan = build_plan(['write first to note.txt', 'write last to note.txt'], self.runtime)
        result = run_plan(plan, self.runtime)
        self.assertEqual(result['state'], 'COMPLETED', result)
        self.assertEqual((self.runtime.granted_root / 'note.txt').read_text(), 'last')

    def test_bounded_input(self):
        for commands in (None, [], ['time'] * 7, [None], [' '], ['x'] * 70001):
            with self.assertRaises(ValueError):
                build_plan(commands, self.runtime)
