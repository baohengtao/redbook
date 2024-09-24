import asyncio
import itertools
import select
import sys
import time
from functools import wraps
from pathlib import Path

import pendulum
from rich.prompt import Confirm, Prompt
from typer import Typer

from redbook import console
from redbook.fetcher import fetcher
from redbook.helper import (
    default_path,
    logsaver_decorator,
    normalize_user_id,
    print_command, save_log
)
from redbook.model import User, UserConfig

app = Typer()


def run_async(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        async def coro_wrapper():
            return await func(*args, **kwargs)

        return asyncio.run(coro_wrapper())

    return wrapper


class LogSaver:
    def __init__(self, command: str, download_dir: Path):
        self.command = command
        self.download_dir = download_dir
        self.save_log_at = pendulum.now()
        self.save_visits_at = fetcher.visits
        self.SAVE_LOG_INTERVAL = 12  # hours
        self.SAVE_LOG_FOR_COUNT = 100

    def save_log(self, save_manually=False):
        fetch_count = fetcher.visits - self.save_visits_at
        log_hours = self.save_log_at.diff().in_hours()
        console.log(
            f'total fetch count: {fetch_count}, '
            f'threshold: {self.SAVE_LOG_FOR_COUNT}')
        console.log(
            f'log hours: {log_hours}, threshold: {self.SAVE_LOG_INTERVAL}h')
        if (log_hours > self.SAVE_LOG_INTERVAL or
                fetch_count > self.SAVE_LOG_FOR_COUNT):
            console.log('Threshold reached, saving log automatically...')
        elif save_manually:
            console.log('Saving log manually...')
        else:
            return
        save_log(self.command, self.download_dir)
        self.save_log_at = pendulum.now()
        self.save_visits_at = fetcher.visits


@app.command()
@logsaver_decorator
@run_async
async def user_loop(frequency: float = 2,
                    download_dir: Path = default_path,
                    ):
    console.log(f'current logined as: {await fetcher.login()}')

    WORKING_TIME = 20
    logsaver = LogSaver('user_loop', download_dir)
    while True:
        print_command()
        UserConfig.update_table()
        post_count = ((time.time()-UserConfig.note_fetch_at.to_timestamp())
                      / UserConfig.post_cycle).desc()

        start_time = pendulum.now()
        query = (UserConfig.select()
                 .where(UserConfig.note_fetch)
                 .order_by(post_count, UserConfig.id)
                 )
        if configs := query.where(UserConfig.note_fetch_at.is_null(True)):
            console.log(
                f'total {configs.count()} new users found, fetching...')
            limit = len(configs)
        elif ((configs := query.where(
                UserConfig.note_next_fetch < pendulum.now()))
                and (len(configs) >= 5)):
            console.log(
                f' {len(configs)} users satisfy fetching conditions, '
                'Fetching 10 users whose estimated new notes is most')
            limit = 10
        else:
            configs = query.order_by(UserConfig.note_fetch_at)
            if configs[0].note_fetch_at < pendulum.now().subtract(days=15):
                limit = 5
            else:
                limit = 2
            console.log(
                'no user satisfy fetching conditions, '
                f'fetching {limit} users whose note_fetch_at is earliest.')
        for i, config in enumerate(configs[:limit]):
            if start_time.diff().in_minutes() > WORKING_TIME:
                break
            console.log(
                f'fetching {i+1}/{limit}: {config.username} '
                f'(total: {len(configs)})')
            config = await UserConfig.from_id(user_id=config.user_id)
            is_new = config.note_fetch_at is None
            await config.fetch_note(download_dir)
            if is_new:
                logsaver.save_log(save_manually=True)
                print_command()

        console.log(
            f'have been working for {start_time.diff().in_minutes()}m '
            f'which is more than {WORKING_TIME}m, taking a break')
        logsaver.save_log()
        next_start_time = pendulum.now().add(hours=frequency)
        console.rule(f'waiting for next fetching at {next_start_time:%H:%M:%S}',
                     style='magenta on dark_magenta')
        console.log(
            "Press S to fetching immediately,\n"
            "L to save log,\n"
            "Q to exit,\n",
            style='info'
        )
        while pendulum.now() < next_start_time:
            # sleeping for  600 seconds while listing for enter key
            if select.select([sys.stdin], [], [], 60)[0]:
                match (input().lower()):
                    case "s":
                        console.log(
                            "S pressed. continuing immediately.")
                        break
                    case "q":
                        console.log("Q pressed. exiting.")
                        return
                    case "l":
                        logsaver.save_log(save_manually=True)
                    case _:
                        console.log(
                            "Press S to fetching immediately,\n"
                            "L to save log,\n"
                            "Q to exit,\n"
                        )


@app.command(help='Add user to database of users whom we want to fetch from')
@logsaver_decorator
@run_async
async def user(download_dir: Path = default_path):
    """Add user to database of users whom we want to fetch from"""
    UserConfig.update_table()
    query = UserConfig.select().where(
        UserConfig.following).order_by(UserConfig.id.desc())
    user = query[0].user
    console.log(f'total {query.count()} users in database')
    console.log(
        f'the latest added user is {user.username} ({user.id, user.nickname})')

    while user_id := Prompt.ask('请输入用户名:smile:').strip():
        if uc := UserConfig.get_or_none(username=user_id):
            user_id = uc.user_id
        user_id = normalize_user_id(user_id)
        if uc := UserConfig.get_or_none(user_id=user_id):
            console.log(f'用户{uc.username}已在列表中')
        uc = await UserConfig.from_id(user_id)
        console.log(uc)
        uc.note_fetch = Confirm.ask(f"是否获取{uc.username}的主页？", default=True)
        uc.save()
        console.log(f'用户{uc.username}更新完成')
        if uc.note_fetch and not uc.following:
            console.log(f'用户{uc.username}未关注，记得关注🌸', style='notice')
        elif not uc.note_fetch and uc.following:
            console.log(f'用户{uc.username}已关注，记得取关🔥', style='notice')
        if not uc.note_fetch and Confirm.ask('是否删除该用户？', default=False):
            uc.delete_instance()
            console.log('用户已删除')
        elif uc.note_fetch and Confirm.ask('是否现在抓取', default=False):
            await uc.fetch_note(download_dir)
        console.log()


@app.command()
def write_meta(download_dir: Path = default_path):
    from imgmeta.script import rename, write_meta
    for folder in ['User', 'New']:
        ori = download_dir / folder
        if ori.exists():
            write_meta(ori)
            rename(ori, new_dir=True, root=ori.parent / (ori.stem + 'Pro'))


@app.command()
def clean_database():
    for u in User:
        if (u.artist and u.artist[0].photos_num) or u.config:
            continue
        console.log(u, '\n')
        for n in itertools.chain(u.config, u.artist):
            console.log(n, '\n')
        if Confirm.ask(f'是否删除{u.username}({u.id})？', default=False):
            for n in itertools.chain(u.notes, u.config, u.artist):
                n.delete_instance()
            u.delete_instance()
            console.log(f'用户{u.username}已删除')
