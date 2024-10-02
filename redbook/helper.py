import asyncio
import json
import mimetypes
import sys
from pathlib import Path
from typing import AsyncIterable

import execjs
import httpx
import magic
import pendulum
from exiftool import ExifToolHelper
from humanize import naturalsize
from makelive import is_live_photo_pair, live_id, make_live_photo
from makelive.makelive import (
    add_asset_id_to_image_file,
    add_asset_id_to_quicktime_file
)

from redbook import console

if not (d := Path('/Volumes/Art')).exists():
    d = Path.home()/'Pictures'
default_path = d / 'RedBook'
semaphore = asyncio.Semaphore(10)
client = httpx.AsyncClient()
et = ExifToolHelper()
mime_detector = magic.Magic(mime=True)


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


async def download_files(imgs: AsyncIterable[list[dict]]):
    tasks = [asyncio.create_task(download_file_pair(img)) async for img in imgs]
    await asyncio.gather(*tasks)


async def download_file_pair(medias: list[dict]):
    if len(medias) == 1:
        await download_single_file(**medias[0])
        return
    img_info, mov_info = medias
    img_xmp = img_info.pop('xmp_info')
    mov_xmp = mov_info.pop('xmp_info')
    try:
        img_path = await download_single_file(**img_info)
        mov_path = await download_single_file(**mov_info)
    except Exception:
        if (img_path := img_info['filepath']/img_info['filename']).exists():
            img_path.unlink()
        if (mov_path := mov_info['filepath']/mov_info['filename']).exists():
            mov_path.unlink()
        raise
    img_size = naturalsize(img_path.stat().st_size)
    mov_size = naturalsize(mov_path.stat().st_size)
    if not is_live_photo_pair(img_path, mov_path):
        assert not (live_id(img_path) and live_id(mov_path))
        if assert_id := live_id(img_path):
            add_asset_id_to_quicktime_file(mov_path, assert_id)
        elif assert_id := live_id(mov_path):
            add_asset_id_to_image_file(img_path, assert_id)
        else:
            make_live_photo(img_path, mov_path)
    if (x := naturalsize(img_path.stat().st_size)) != img_size:
        console.log(f'{img_path.name} size changed from {img_size} to {x}')
    if (x := naturalsize(mov_path.stat().st_size)) != mov_size:
        console.log(f'{mov_path.name} size changed from {mov_size} to {x}')
    assert is_live_photo_pair(img_path, mov_path)
    write_xmp(img_path, img_xmp)
    write_xmp(mov_path, mov_xmp)


async def download_single_file(
        url: str,
        filepath: Path,
        filename: str,
        xmp_info: dict = None
) -> Path:
    filepath.mkdir(parents=True, exist_ok=True)
    img = filepath / filename
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36 Edg/115.0.1901.188", }
    if img.suffix not in (suffixs := ['.webp', '.jpg', '.heic', '.png']):
        suffixs = ['.mp4', '.mov']
        assert img.suffix in suffixs
    for suffix in suffixs:
        if (i := img.with_suffix(suffix)).exists():
            console.log(f'{i} already exists..skipping...', style='info')
            return i

    while True:
        try:
            async with semaphore:
                r = await client.get(url, headers=headers)
        except httpx.HTTPError as e:
            period = 60
            console.log(
                f"{e!r}: sleep {period} seconds and "
                f"retry [link={url}]{url}[/link]...", style='error')
            await asyncio.sleep(period)
            continue
        except asyncio.CancelledError:
            console.log(f'{url} was cancelled.', style='info')
            raise

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

        mime = mime_detector.from_buffer(r.content)
        suffix = mimetypes.guess_extension(mime)
        assert suffix in suffixs
        if mime.startswith('image/'):
            img = img.with_suffix(suffix)

        img.write_bytes(r.content)

        if xmp_info:
            write_xmp(img, xmp_info)
        console.log(f'🎉 {img} successfully downloaded...', style="dim")
        return img


def write_xmp(img: Path, tags: dict):
    for k, v in tags.copy().items():
        if isinstance(v, str):
            tags[k] = v.replace('\n', '&#x0a;')
    params = ['-overwrite_original', '-ignoreMinorErrors', '-escapeHTML']
    ext = et.get_tags(img, 'File:FileTypeExtension')[
        0]['File:FileTypeExtension'].lower()
    if (suffix := f'.{ext}') != img.suffix:
        raise ValueError(f'{img} suffix is not right, should be {suffix}')
        new_img = img.with_suffix(suffix)
        console.log(
            f'{img}: suffix is not right, moving to {new_img}...',
            style='info')
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


def normalize_count(amount):
    if amount and isinstance(amount, str):
        num, mul = amount[:-1], amount[-1]
        match mul:
            case '亿':
                amount = float(num) * (10 ** 8)
            case '万':
                amount = float(num) * (10 ** 4)
            case _:
                if amount.isnumeric():
                    amount = int(amount)

    return amount
