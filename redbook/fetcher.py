import json
import pickle
import random
import time
from pathlib import Path

import requests
from DrissionPage import ChromiumOptions, ChromiumPage

from redbook import console
from redbook.client.client import GetXS


def _get_session():
    sess = requests.Session()
    sess.headers = {
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://www.xiaohongshu.com",
        "referer": "https://www.xiaohongshu.com/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36 Edg/115.0.1901.188",
    }
    return sess


class Fetcher:
    def __init__(self) -> None:
        self.sess = _get_session()
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
        cookie_str = ';'.join(
            f"{cookie['name']}={cookie['value']}" for cookie in cookies)
        self.sess.headers['Cookie'] = cookie_str
        return cookies

    async def get(self, url, api='') -> requests.Response:
        console.log(f'Getting {url}, {api}')
        self._pause()
        url += api
        headers = await self._get_xs(api) if api else None
        while True:
            try:
                r = self.sess.get(url, headers=headers)
                r.raise_for_status()
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.HTTPError,
                    requests.exceptions.ProxyError) as e:
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

    async def post(self, url, api, data: dict):
        console.log(f'Posting {url}, {api}, {data}')
        self._pause()
        data = json.dumps(data, separators=(',', ':'))
        headers = await self._get_xs(api, data)
        url += api
        while True:
            try:
                r = self.sess.post(url, headers=headers, data=data)
                r.raise_for_status()
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.HTTPError,
                    requests.exceptions.ProxyError) as e:
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

    def _pause(self):
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
        sleep_time *= random.uniform(0.5, 1.5) * 4
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
            time.sleep(0.1)
        self._last_fetch = time.time()
        self._visit_count += 1


fetcher = Fetcher()
