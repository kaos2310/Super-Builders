#!/usr/bin/env python3
import importlib.util,subprocess,unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('fetch',Path(__file__).with_name('fetch-pinned-git.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
PIN='5369359dbd10f6dd8cbdd59d1df7b788b29b168c'
class Tests(unittest.TestCase):
    def test_transient_failure_recovers_with_exact_pin(self):
        with patch.object(m.subprocess,'run',side_effect=[subprocess.CompletedProcess([],128),subprocess.CompletedProcess([],0)]) as run,patch.object(m.subprocess,'check_output',return_value=PIN+'\n'),patch.object(m.time,'sleep') as sleep:
            m.fetch(Path('/isolated'),PIN)
            self.assertEqual(run.call_count,2);sleep.assert_called_once_with(10)
            for call in run.call_args_list:self.assertEqual(call.args[0][-1],PIN)
    def test_exhaustion_fails_closed(self):
        with patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],128)) as run,patch.object(m.subprocess,'check_output') as read,patch.object(m.time,'sleep'):
            with self.assertRaises(RuntimeError):m.fetch(Path('/isolated'),PIN)
            self.assertEqual(run.call_count,4);read.assert_not_called()
    def test_timeout_is_retried(self):
        with patch.object(m.subprocess,'run',side_effect=[subprocess.TimeoutExpired([],90),subprocess.CompletedProcess([],0)]),patch.object(m.subprocess,'check_output',return_value=PIN),patch.object(m.time,'sleep'):
            m.fetch(Path('/isolated'),PIN)
    def test_wrong_commit_is_rejected(self):
        with patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0)),patch.object(m.subprocess,'check_output',return_value='0'*40):
            with self.assertRaises(RuntimeError):m.fetch(Path('/isolated'),PIN)
    def test_floating_ref_is_rejected(self):
        with patch.object(m.subprocess,'run') as run:
            with self.assertRaises(RuntimeError):m.fetch(Path('/isolated'),'main')
            run.assert_not_called()
if __name__=='__main__':unittest.main()
