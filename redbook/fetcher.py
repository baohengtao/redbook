import asyncio
import json
import logging
import pickle
import random
import time
from pathlib import Path

from DrissionPage import ChromiumOptions, ChromiumPage
from httpx import HTTPError, HTTPStatusError, Response

from redbook import console
from redbook.client.client import GetXS
from redbook.helper import client

httpx_logger = logging.getLogger("httpx")
httpx_logger.disabled = True


class Fetcher:
    def __init__(self) -> None:
        self.cookies = self.load_cookie()
        self.xs_getter = GetXS(self.cookies)
        self._visit_count = 0
        self.visits = 0
        self._last_fetch = time.time()

    async def login(self):
        while True:
            r = await self.get('https://edith.xiaohongshu.com',
                               api='/api/sns/web/v2/user/me')
            js = r.json()
            if js.pop('success'):
                return js["data"]["nickname"]
            else:
                console.log(js)
            Path(__file__).with_name('cookie.pkl').unlink(missing_ok=True)
            raise ValueError('not logined')

    def load_cookie(self):
        cookie_file = Path(__file__).with_name('cookie.pkl')
        if cookie_file.exists():
            cookies = pickle.loads(cookie_file.read_bytes())
        else:
            co = ChromiumOptions().use_system_user_path()
            browser = ChromiumPage(co)
            browser.get('https://www.xiaohongshu.com/')
            input('press enter after login...')
            cookies = browser.get_cookies()
            browser.quit()
            cookie_file = Path(__file__).with_name('cookie.pkl')
            cookie_file.write_bytes(pickle.dumps(cookies))
        return cookies

    async def request(self, method, url, **kwargs) -> Response:
        for try_time in range(1, 100):
            try:
                await self._pause()
                r = await client.request(method, url, **kwargs)
                r.raise_for_status()
            except asyncio.CancelledError:
                console.log(f'{method} {url}  was cancelled.', style='error')
                raise
            except HTTPError as e:
                if isinstance(e, HTTPStatusError) and r.status_code == 461:
                    raise
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

    async def get(self, url, api='') -> Response:
        url += api
        headers = await self._get_xs(api)
        return await self.request('Get', url, headers=headers)

    async def post(self, url, api, data: dict) -> Response:
        headers = await self._get_xs(api, data)
        data = json.dumps(data, separators=(',', ':'))
        url += api
        return await self.request('Post', url, headers=headers, data=data)

    async def _get_xs(self, api, data=''):
        return await self.xs_getter.get_header(api, data)

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
        sleep_time *= random.uniform(0.9, 1.1) * 5
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
