import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable

import execjs
import requests
from exiftool import ExifToolHelper

from redbook import console


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


def download_files(imgs: Iterable[dict]):
    # TODO: gracefully handle exception and keyboardinterrupt
    with ThreadPoolExecutor(max_workers=7) as pool:
        futures = [pool.submit(download_single_file, **img) for img in imgs]
    for future in futures:
        future.result()


def download_single_file(
        url: str,
        filepath: Path,
        filename: str,
        xmp_info: dict = None
):
    filepath.mkdir(parents=True, exist_ok=True)
    img = filepath / filename
    if img.exists():
        console.log(f'{img} already exists..skipping...', style='info')
        return
    else:
        console.log(f'downloading {img}...', style="dim")
    while True:
        try:
            r = requests.get(url)
        except ConnectionError as e:
            period = 60
            console.log(
                f"{e}: Sleepping {period} seconds and "
                f"retry [link={url}]{url}[/link]...", style='error')
            time.sleep(period)
            continue

        if r.status_code == 404:
            console.log(
                f"{url}, {xmp_info}, {r.status_code}", style="error")
            return
        elif r.status_code != 200:
            console.log(f"{url}, {r.status_code}", style="error")
            time.sleep(15)
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
    with ExifToolHelper() as et:
        ext = et.get_tags(img, 'File:FileTypeExtension')[
            0]['File:FileTypeExtension'].lower()
        if (suffix := f'.{ext}') != img.suffix:
            new_img = img.with_suffix(suffix)
            console.log(
                f'{img}: suffix is not right, moving to {new_img}...',
                style='error')
            img = img.rename(new_img)
        et.set_tags(img, tags, params=params)
