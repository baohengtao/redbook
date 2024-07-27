import json
from pathlib import Path
from typing import Optional, Tuple

import requests
from playwright.async_api import BrowserContext, Cookie, Page, async_playwright

from redbook import console
from redbook.client.help import sign


class GetXS:
    def __init__(self, cookies) -> None:
        self.cookies = cookies
        self.client = None

    async def init_client(self):
        if not self.client:
            self.client = await get_client(self.cookies)
        return self.client

    async def get_header(self, api, data=''):
        await self.init_client()
        xs = (await self.client._pre_headers(api, data)) if api else {}
        return self.client.headers | xs


async def get_client(cookies=None):
    playwright = await async_playwright().start()
    chromium = playwright.chromium
    user_data_dir = Path(__file__).parent / "browser_data"
    browser_context = await chromium.launch_persistent_context(
        user_data_dir=user_data_dir,
        viewport={"width": 1920, "height": 1080},
    )
    await browser_context.add_init_script(
        path=Path(__file__).parent/'stealth.min.js')
    context_page = await browser_context.new_page()
    await context_page.goto('https://www.xiaohongshu.com')
    xhs_client = XiaoHongShuClient(
        await browser_context.cookies(),
        playwright_page=context_page,
        browser_context=browser_context,
    )
    if cookies:
        console.log('login...')
        await xhs_client.login(cookies)
    return xhs_client


def convert_cookies(cookies: Optional[list[Cookie]]) -> Tuple[str, dict]:
    if not cookies:
        return "", {}
    cookies_str = ";".join(
        [f"{cookie.get('name')}={cookie.get('value')}" for cookie in cookies])
    cookie_dict = dict()
    for cookie in cookies:
        cookie_dict[cookie.get('name')] = cookie.get('value')
    return cookies_str, cookie_dict


class XiaoHongShuClient:
    def __init__(self,
                 cookies,
                 playwright_page: Page,
                 browser_context: BrowserContext):
        cookie_str, cookie_dict = convert_cookies(cookies)
        self.headers = {
            "User-Agent":  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.5112.79 Safari/537.36",
            "Cookie": cookie_str,
            "Origin": "https://www.xiaohongshu.com",
            "Referer": "https://www.xiaohongshu.com",
            "Content-Type": "application/json;charset=UTF-8"
        }
        self.playwright_page = playwright_page
        self.cookie_dict = cookie_dict
        self.browser_context = browser_context

    async def _pre_headers(self, api: str, data=None) -> dict:
        encrypt_params = await self.playwright_page.evaluate(
            "([url, data]) => window._webmsxyw(url,data)", [api, data])
        local_storage = await self.playwright_page.evaluate(
            "()=>window.localStorage")
        signs = sign(
            a1=self.cookie_dict.get("a1", ""),
            b1=local_storage.get("b1", ""),
            x_s=encrypt_params.get("X-s", ""),
            x_t=str(encrypt_params.get("X-t", ""))
        )
        return {
            "X-S": signs["x-s"],
            "X-T": signs["x-t"],
            "x-S-Common": signs["x-s-common"],
            "X-B3-Traceid": signs["x-b3-traceid"]
        }

    async def get(self, url: str, api=''):
        xs = (await self._pre_headers(api)) if api else {}
        return requests.get(url=f"{url}{api}", headers=self.headers | xs)

    async def post(self, url: str, api: str, data: dict):
        headers = await self._pre_headers(api, data)
        json_str = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
        return requests.post(
            url=f"{url}{api}", data=json_str, headers=headers)

    async def login(self, cookies):
        for cookie in cookies:
            key, value = cookie.get('name'), cookie.get('value')
            if key != "web_session":  # only set web_session cookie attr
                continue
            await self.browser_context.add_cookies([{
                'name': key,
                'value': value,
                'domain': ".xiaohongshu.com",
                'path': "/"
            }])
        cookie_str, cookie_dict = convert_cookies(
            await self.browser_context.cookies())
        self.headers['Cookie'] = cookie_str
        self.cookie_dict = cookie_dict
