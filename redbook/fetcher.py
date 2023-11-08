import http.cookies
import os
from pathlib import Path

import execjs
import requests
from dotenv import load_dotenv


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

    def get(self, url, api='') -> requests.Response:
        if not api:
            return self.sess.get(url)
        headers = self.sess.headers | self._get_xs(api)
        return self.sess.get(url+api, headers=headers)

    def post(self, url, api, data):
        headers = self.sess.headers | self._get_xs(api, data)
        return self.sess.post(url+api, headers=headers, data=data)

    def _get_xs(self, api, data=''):
        a1 = self.sess.cookies.get('a1')
        jsfile = Path(__file__).with_name('info.js')
        js = execjs.compile(open(jsfile, 'r', encoding='utf-8').read())
        ret = js.call('get_xs', api, data, a1)
        return {k.lower(): str(v) for k, v in ret.items()}


fetcher = Fetcher()
