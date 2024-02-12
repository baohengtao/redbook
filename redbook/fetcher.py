import http.cookies
import json
import os
import random
import time
from pathlib import Path

import execjs
import requests
from dotenv import load_dotenv

from redbook import console

NODE_PATH = Path(__file__).resolve().parent.parent
NODE_PATH /= 'node_modules'
os.environ['NODE_PATH'] = str(NODE_PATH)


def _get_session():
    env_file = Path(__file__).with_name('.env')
    load_dotenv(env_file)
    if not (cookie := os.getenv('COOKIE')):
        raise ValueError(f'no cookie found in {env_file}')
    cookie_dict = http.cookies.SimpleCookie(cookie)
    cookies = {k: v.value for k, v in cookie_dict.items()}
    sess = requests.Session()
    sess.cookies = requests.utils.cookiejar_from_dict(cookies)
    sess.headers = {
        "authority": "edith.xiaohongshu.com",
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://www.xiaohongshu.com",
        "referer": "https://www.xiaohongshu.com/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36 Edg/115.0.1901.188",
        # "x-s": "",
        # "x-t": ""
    }
    return sess


class Fetcher:
    def __init__(self) -> None:
        self.sess = _get_session()
        self._visit_count = 0
        self.visits = 0
        self._last_fetch = time.time()

    def get(self, url, api='') -> requests.Response:
        self._pause()
        if api:
            headers = self.sess.headers | self._get_xs(api)
            url += api
        else:
            headers = None
        while True:
            try:
                r = self.sess.get(url, headers=headers)
                r.raise_for_status()
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.HTTPError,
                    requests.exceptions.ProxyError) as e:
                period = 60
                console.log(
                    f"{e}: Sleepping {period} seconds and "
                    f"retry [link={url}]{url}[/link]...", style='error')
                time.sleep(period)
            else:
                assert r.status_code != 503
                return r

    def post(self, url, api, data: dict):
        self._pause()
        data = json.dumps(data, separators=(',', ':'))
        headers = self.sess.headers | self._get_xs(api, data)
        url += api
        while True:
            r = self.sess.post(url, headers=headers, data=data)
            try:
                r.raise_for_status()
            except requests.exceptions.HTTPError as e:
                period = 60
                console.log(
                    f"{e}: Sleeping {period} seconds and "
                    f"retry [link={url}]{url}[/link]...", style='error')
                time.sleep(period)
            else:
                assert r.status_code != 503
                return r

    def _get_xs(self, api, data=''):
        a1 = self.sess.cookies.get('a1')
        jsfile = Path(__file__).with_name('info.js')
        js = execjs.compile(open(jsfile, 'r', encoding='utf-8').read())
        ret = js.call('get_xs', api, data, a1)
        return {k.lower(): str(v) for k, v in ret.items()}

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
