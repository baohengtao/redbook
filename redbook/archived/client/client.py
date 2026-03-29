import json
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Optional, Tuple

import requests
from playwright.async_api import (
    Browser, BrowserContext,
    Cookie, Page,
    async_playwright
)

from redbook import console
from redbook.client.playwright_sign import sign_with_playwright


class GetXS:
    def __init__(self, cookies) -> None:
        self.cookies = cookies
        self.client = None

    async def init_client(self):
        if not self.client:
            self.client = await get_client(self.cookies)
        return self.client

    async def get_header_v2(self, url: str, data: str | dict, method: str):
        await self.init_client()
        xs = await self.client._pre_headers_v2(url, data, method)
        return self.client.headers | xs

    async def aclose(self):
        await self.client.browser.close()
        self.client = None


async def get_client(cookies=None):
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch()
    browser_context = await browser.new_context(
        viewport={"width": 1920, "height": 1080})
    await browser_context.add_init_script(
        path=Path(__file__).parent/'stealth.min.js')
    context_page = await browser_context.new_page()
    await context_page.goto('https://www.xiaohongshu.com')
    xhs_client = XiaoHongShuClient(
        await browser_context.cookies(),
        playwright_page=context_page,
        browser_context=browser_context,
        browser=browser,
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
                 browser: Browser,
                 browser_context: BrowserContext):
        cookie_str, cookie_dict = convert_cookies(cookies)
        self.headers = {
            "Cookie": cookie_str,
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9",
            "cache-control": "no-cache",
            "content-type": "application/json;charset=UTF-8",
            "origin": "https://www.xiaohongshu.com",
            "pragma": "no-cache",
            "priority": "u=1, i",
            "referer": "https://www.xiaohongshu.com/",
            "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36", }
        self.playwright_page = playwright_page
        self.cookie_dict = cookie_dict
        self.browser_context = browser_context
        self.browser = browser

    async def _pre_headers_v2(self, url: str, data: str | dict, method: str) -> dict:
        signs = await sign_with_playwright(
            uri=url,
            data=data,
            method=method,
            a1=self.cookie_dict.get("a1", ""),
            page=self.playwright_page,
        )
        return {
            "X-S": signs["x-s"],
            "X-T": signs["x-t"],
            "x-S-Common": signs["x-s-common"],
            "X-B3-Traceid": signs["x-b3-traceid"]
        }

    async def login(self, cookies: SimpleCookie):
        for key, morsel in cookies.items():
            if key != "web_session":  # only set web_session cookie attr
                continue
            await self.browser_context.add_cookies([{
                'name': key,
                'value': morsel.value,
                'domain': ".xiaohongshu.com",
                'path': "/"
            }])
        cookie_str, cookie_dict = convert_cookies(
            await self.browser_context.cookies())
        self.headers['Cookie'] = cookie_str
        self.cookie_dict = cookie_dict
