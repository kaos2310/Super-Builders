from pathlib import Path
import contextlib
import io
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ci.network import source_get
from center_core import CenterError


class SourceNetworkTests(unittest.TestCase):
    def call(self,responses):
        get=Mock(side_effect=responses);sleep=Mock()
        with contextlib.redirect_stdout(io.StringIO()):
            result=source_get('https://gitlab.com/api/v4/projects/simonpunk%2Fsusfs4ksu/repository/commits/gki-android14-6.1',requester=get,sleep=sleep,now=lambda:0)
        return result,get,sleep

    def test_rate_limit_waits_then_uses_fresh_success(self):
        success={'status':200,'headers':{},'data':{'id':'exact-pin'}}
        result,get,sleep=self.call([{'status':429,'headers':{'retry-after':'7'}},success])
        self.assertEqual(result,success);sleep.assert_called_once_with(7)
        self.assertEqual(get.call_count,2)
        self.assertTrue(all(c.kwargs=={'allow_http_errors':True} for c in get.call_args_list))

    def test_retry_after_date_is_honored(self):
        result,get,sleep=self.call([{'status':503,'headers':{'retry-after':'Thu, 01 Jan 1970 00:00:12 GMT'}},{'status':200}])
        sleep.assert_called_once_with(12)

    def test_permanent_errors_are_not_retried(self):
        for status in (401,403,404,422):
            get=Mock(return_value={'status':status});sleep=Mock()
            with self.subTest(status=status),self.assertRaisesRegex(CenterError,str(status)):
                source_get('https://gitlab.com/',requester=get,sleep=sleep)
            self.assertEqual(get.call_count,1);sleep.assert_not_called()

    def test_retries_are_bounded_and_never_ignore_long_server_wait(self):
        get=Mock(return_value={'status':429,'headers':{}});sleep=Mock()
        with contextlib.redirect_stdout(io.StringIO()),self.assertRaisesRegex(CenterError,'429'):
            source_get('https://gitlab.com/',requester=get,sleep=sleep)
        self.assertEqual(get.call_count,4)
        self.assertEqual([c.args[0] for c in sleep.call_args_list],[5,10,20])
        get=Mock(return_value={'status':429,'headers':{'retry-after':'120'}});sleep=Mock()
        with self.assertRaisesRegex(CenterError,'Wartezeit'):
            source_get('https://gitlab.com/',requester=get,sleep=sleep)
        self.assertEqual(get.call_count,1);sleep.assert_not_called()


if __name__=='__main__':unittest.main()
