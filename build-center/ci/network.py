"""Bounded retries for read-only immutable source resolution in CI."""
from datetime import timezone
from email.utils import parsedate_to_datetime
import time

from center_core import CenterError, request


def source_get(url,token='',*,requester=None,sleep=None,now=None):
    requester=requester or request;sleep=sleep or time.sleep;now=now or time.time
    waited=0
    for attempt in range(4):
        result=requester(url,token,allow_http_errors=True)
        status=result['status']
        if 200<=status<300:return result
        if status not in (429,502,503,504) or attempt==3:
            raise CenterError(f'Quellenabfrage fehlgeschlagen (HTTP {status}).')
        delay=5*(2**attempt)
        retry=result.get('headers',{}).get('retry-after','')
        if retry:
            try:delay=max(1,float(retry))
            except (ValueError,TypeError):
                try:
                    date=parsedate_to_datetime(retry)
                    if date.tzinfo is None:date=date.replace(tzinfo=timezone.utc)
                    delay=max(1,date.timestamp()-now())
                except (ValueError,TypeError,OverflowError):pass
        if delay>60 or waited+delay>120:
            raise CenterError(f'Quellserver verlangt längere Wartezeit (HTTP {status}); CI-Wiederholungsgrenze erreicht.')
        print(f'Quellserver HTTP {status}; lesende Anfrage in {delay:g} Sekunden erneut ({attempt+1}/3).',flush=True)
        sleep(delay);waited+=delay

