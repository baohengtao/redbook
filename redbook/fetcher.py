import asyncio
import json
import pickle
import random
import time
from pathlib import Path

from DrissionPage import ChromiumOptions, ChromiumPage
from httpx import HTTPError, Response

from redbook import console
from redbook.client.client import GetXS
from redbook.helper import client


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

    async def get(self, url, api='') -> Response:
        console.log(f'Getting {url}, {api}')
        await self._pause()
        url += api
        headers = await self._get_xs(api)
        while True:
            try:
                r = await client.get(url, headers=headers)
                r.raise_for_status()
            except asyncio.CancelledError:
                console.log(f'{url+api}  was cancelled.', style='error')
                raise KeyboardInterrupt
            except HTTPError as e:
                if r.status_code == 461:
                    raise
                period = 60
                console.log(
                    f"{e}: Sleeping {period} seconds and "
                    f"retry [link={url}]{url}[/link]...", style='error')
                time.sleep(period)
            else:
                assert r.status_code != 503
                return r

    async def post(self, url, api, data: dict) -> Response:
        await self._pause()
        headers = await self._get_xs(api, data)
        data = json.dumps(data, separators=(',', ':'))
        url += api
        while True:
            try:
                r = await client.post(url, headers=headers, data=data)
                r.raise_for_status()
            except asyncio.CancelledError:
                console.log(f'{url+api} was cancelled.', style='error')
                raise KeyboardInterrupt
            except HTTPError as e:
                period = 60
                console.log(
                    f"{e}: Sleeping {period} seconds and "
                    f"retry [link={url}]{url}[/link]...", style='error')
                time.sleep(period)
            else:
                assert r.status_code != 503
                return r

    async def _get_xs(self, api, data=''):
        return await self.xs_getter.get_header(api, data)

    async def _pause(self):
        self.visits += 1
        if self._visit_count == 0:
            self._visit_count = 1
            self._last_fetch = time.time()
            return

        if self._visit_count % 256 == 0:
            sleep_time = 256
        elif self._visit_count % 64 == 0:
            sleep_time = 64
        elif self._visit_count % 16 == 0:
            sleep_time = 16
        elif self._visit_count % 4 == 0:
            sleep_time = 4
        else:
            sleep_time = 1
        sleep_time *= random.uniform(0.5, 1.5) * 2
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
