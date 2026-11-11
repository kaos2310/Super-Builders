import io
import json
from email.message import Message
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from center_core import CenterError, request


class HttpErrorTests(unittest.TestCase):
    def failure(self, body, code=422, headers=None):
        return urllib.error.HTTPError('https://api.github.com/repos/example/project/commits/missing',
                                      code, 'Unprocessable Entity', headers or Message(), io.BytesIO(body))

    def test_proxy_keeps_status_and_message_for_the_shared_app_diagnosis(self):
        with patch('center_core.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = self.failure(json.dumps({'message':'No commit found for SHA: missing'}).encode())
            result = request('https://api.github.com/repos/example/project/commits/missing', allow_http_errors=True)
        self.assertEqual(result['status'], 422)
        self.assertEqual(result['data'], {'message':'No commit found for SHA: missing'})

    def test_ci_and_download_callers_keep_the_existing_exception_contract(self):
        with patch('center_core.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = self.failure(b'{}')
            with self.assertRaises(CenterError):
                request('https://api.github.com/repos/example/project/commits/missing')

    def test_non_json_failure_does_not_expose_response_pages(self):
        with patch('center_core.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = self.failure(b'<html>upstream page</html>')
            result = request('https://api.github.com/repos/example/project/commits/missing', allow_http_errors=True)
        self.assertEqual(result['status'],422)
        self.assertEqual(result['data'],{'message':''})

    def test_proxy_preserves_rate_limit_metadata_without_forwarding_other_headers(self):
        headers = Message()
        headers['X-RateLimit-Reset']='1794427200'
        headers['Set-Cookie']='test-only-cookie'
        with patch('center_core.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = self.failure(b'{}',403,headers)
            result = request('https://api.github.com/repos/example/project/commits/missing', allow_http_errors=True)
        self.assertEqual(result['status'],403)
        self.assertEqual(result['headers'],{'x-ratelimit-reset':'1794427200'})


if __name__ == '__main__':
    unittest.main()
