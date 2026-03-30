import asyncio
import json
import logging
import pickle
import random
import time
from http.cookies import SimpleCookie
from pathlib import Path

import httpx
from httpx import HTTPError, HTTPStatusError, Response

from redbook import console
from redbook.client_v2.xhs_util import generate_headers, splice_str

httpx_logger = logging.getLogger("httpx")
httpx_logger.disabled = True

BASE_URL = 'https://edith.xiaohongshu.com'


def load_cookie() -> dict:
    cookie_file = Path(__file__).with_name('cookie.pkl')
    if cookie_file.exists():
        cookies = pickle.loads(cookie_file.read_bytes())
    else:
        cookie_text = input('input cookie text...')
        cookies = SimpleCookie()
        cookies.load(cookie_text)
        cookie_file.write_bytes(pickle.dumps(cookies))
    cookies = {k: v.value for k, v in cookies.items()}
    return cookies


class Fetcher:
    def __init__(self) -> None:
        self.cookies = load_cookie()
        self.client = httpx.AsyncClient(cookies=self.cookies)
        self._visit_count = 0
        self.visits = 0
        self._last_fetch = time.time()

    async def login(self):
        while True:
            r = await self.get('/api/sns/web/v2/user/me')
            js = r.json()
            if js.pop('success'):
                return js["data"]["nickname"]
            else:
                console.log(js)
            Path(__file__).with_name('cookie.pkl').unlink(missing_ok=True)
            raise ValueError('not logined')

    async def request(self, method, url, **kwargs) -> Response:
        for try_time in range(1, 20):
            try:
                await self._pause()
                r = await self.client.request(method, url, **kwargs)
                r.raise_for_status()
            except asyncio.CancelledError:
                console.log(f'{method} {url}  was cancelled.', style='error')
                raise
            except HTTPError as e:
                if isinstance(e, HTTPStatusError):
                    if r.status_code in [461, 302]:
                        console.log(r.text)
                        input(f'{r.status_code} ERROR, verification needed...')
                        continue
                    elif r.status_code == 406:
                        raise ValueError(f'Failed to fetch: {r.text}')
                period = 30 * ((try_time % 10) or 30)
                console.log(
                    f"{e!r}: failed on {try_time}th trys, sleeping {period} "
                    f"seconds and retry [link={url}]{url}[/link]...",
                    style='info')
                await asyncio.sleep(period)
            else:
                return r
        else:
            raise ConnectionError('request failed')

    async def get(self, api, params: dict = None) -> Response:
        splice_api = splice_str(api, params)
        headers, _ = self.get_headers(splice_api, method='GET')
        return await self.request('GET', BASE_URL+splice_api, headers=headers)

    async def post(self, api, data: dict) -> Response:
        headers, data = self.get_headers(api, data=data, method='POST')
        return await self.request('POST', BASE_URL+api, headers=headers, data=data)

    def get_headers(self, api: str, data: dict = None, method: str = 'POST'):
        headers, data = generate_headers(self.cookies['a1'], api, data, method)
        return headers, data

    async def _pause(self):
        self.visits += 1
        if self._visit_count == 0:
            self._visit_count = 1
            self._last_fetch = time.time()
            return

        if self._visit_count % 64 == 0:
            sleep_time = 64
        elif self._visit_count % 16 == 0:
            sleep_time = 16
        elif self._visit_count % 4 == 0:
            sleep_time = 4
        else:
            sleep_time = 2
        sleep_time *= random.uniform(0.9, 1.1) * 2
        self._last_fetch += sleep_time
        if (wait_time := (self._last_fetch-time.time())) > 0:
            console.log(
                f'sleep {wait_time:.1f} seconds...'
                f'(count: {self._visit_count})',
                style='info')
        elif wait_time < -3600:
            self._visit_count = 0
            console.log(
                f'reset visit count to {self._visit_count} since have '
                f'no activity for {wait_time:.1f} seconds, '
                'which means  more than 1 hour passed')
        else:
            console.log(
                f'no sleeping since more than {sleep_time:.1f} seconds passed'
                f'(count: {self._visit_count})')
        while time.time() < self._last_fetch:
            try:
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                console.log('Cancelled on sleep', style='error')
                raise KeyboardInterrupt
        self._last_fetch = time.time()
        self._visit_count += 1


fetcher = Fetcher()
