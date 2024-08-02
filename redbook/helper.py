import asyncio
import json
import sys
from pathlib import Path
from typing import AsyncIterable

import execjs
import httpx
import pendulum
from exiftool import ExifToolHelper

from redbook import console

if not (d := Path('/Volumes/Art')).exists():
    d = Path.home()/'Pictures'
default_path = d / 'RedBook'
semaphore = asyncio.Semaphore(1e7)
client = httpx.AsyncClient()
et = ExifToolHelper()


def normalize_user_id(user_id: str) -> str:
    import re
    user_id = user_id.strip()
    user_id = user_id.split('?')[0]
    user_id = user_id.removeprefix('https://www.xiaohongshu.com/user/profile/')
    assert re.match(r'^[0-9a-z]{24}$', user_id)
    return user_id


def convert_js_dict_to_py(js_dict: str) -> dict:
    """
    convert a JavaScript dictionary to a Python dictionary
    """
    js_code = f"var dict = {js_dict}; JSON.stringify(dict);"
    ctx = execjs.compile("""
        function convertJsToPy(jsCode) {
            var dict = eval(jsCode);
            return dict;
        }
    """)
    try:
        py_dict = json.loads(ctx.call("convertJsToPy", js_code))
        return py_dict
    except Exception as e:
        print("Error converting JavaScript dictionary to Python:", str(e))
        raise


async def download_files(imgs: AsyncIterable[dict]):
    tasks = [asyncio.create_task(download_single_file(**img)) async for img in imgs]
    await asyncio.gather(*tasks)


async def download_single_file(
        url: str,
        filepath: Path,
        filename: str,
        xmp_info: dict = None
):
    filepath.mkdir(parents=True, exist_ok=True)
    img = filepath / filename
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36 Edg/115.0.1901.188", }
    if img.suffix == '.webp':
        suffixs = ['.webp', '.jpg', '.heic']
    else:
        assert img.suffix == '.mp4'
        suffixs = ['.mp4']
    for suffix in suffixs:
        if (i := img.with_suffix(suffix)).exists():
            console.log(f'{i} already exists..skipping...', style='info')
            return

    console.log(f'downloading {img}...', style="dim")
    while True:
        try:
            async with semaphore:
                r = await client.get(url, headers=headers)
        except httpx.HTTPError as e:
            period = 60
            console.log(
                f"{e}: Sleepping {period} seconds and "
                f"retry [link={url}]{url}[/link]...", style='error')
            await asyncio.sleep(period)
            continue
        except asyncio.CancelledError:
            console.log(f'{url} was cancelled.', style='info')
            raise KeyboardInterrupt

        if r.status_code == 404:
            console.log(
                f"{url}, {xmp_info}, {r.status_code}", style="error")
            return
        elif r.status_code != 200:
            console.log(f"{url}, {r.status_code}", style="error")
            await asyncio.sleep(15)
            console.log(f'retrying download for {url}...')
            continue

        if int(r.headers['Content-Length']) != len(r.content):
            console.log(f"expected length: {r.headers['Content-Length']}, "
                        f"actual length: {len(r.content)} for {img}",
                        style="error")
            console.log(f'retrying download for {img}')
            continue

        img.write_bytes(r.content)

        if xmp_info:
            write_xmp(img, xmp_info)
        break


def write_xmp(img: Path, tags: dict):
    for k, v in tags.copy().items():
        if isinstance(v, str):
            tags[k] = v.replace('\n', '&#x0a;')
    params = ['-overwrite_original', '-ignoreMinorErrors', '-escapeHTML']
    ext = et.get_tags(img, 'File:FileTypeExtension')[
        0]['File:FileTypeExtension'].lower()
    if (suffix := f'.{ext}') != img.suffix:
        new_img = img.with_suffix(suffix)
        console.log(
            f'{img}: suffix is not right, moving to {new_img}...',
            style='error')
        img = img.rename(new_img)
    et.set_tags(img, tags, params=params)


def logsaver_decorator(func):
    from functools import wraps
    from inspect import signature

    """Decorator to save console log to html file"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            with console.capture():
                console.print_exception(show_locals=True)
            raise
        finally:
            callargs = signature(func).bind(*args, **kwargs).arguments
            download_dir: Path = callargs.get('download_dir', default_path)
            save_log(func.__name__, download_dir)
    return wrapper


def print_command():
    argv = sys.argv
    argv[0] = Path(argv[0]).name
    console.log(
        f" run command  @ {pendulum.now().format('YYYY-MM-DD HH:mm:ss')}")
    console.log(' '.join(argv))


def save_log(func_name, download_dir):
    from rich.terminal_theme import MONOKAI
    download_dir.mkdir(parents=True, exist_ok=True)
    time_format = pendulum.now().format('YY-MM-DD_HHmmss')
    log_file = f"{func_name}_{time_format}.html"
    console.log(f'Saving log to {download_dir / log_file}')
    console.save_html(download_dir / log_file, theme=MONOKAI)
