import re
import select
import sys
import time
from pathlib import Path

import pendulum
from rich.prompt import Confirm, Prompt
from typer import Option, Typer

from redbook import console
from redbook.fetcher import fetcher
from redbook.helper import (
    default_path,
    logsaver_decorator,
    normalize_user_id,
    print_command, save_log
)
from redbook.model import Query, UserConfig

app = Typer()


class LogSaver:
    def __init__(self, command: str, download_dir: Path):
        self.command = command
        self.download_dir = download_dir
        self.save_log_at = pendulum.now()
        self.total_fetch_count = 0
        self.SAVE_LOG_INTERVAL = 12  # hours
        self.SAVE_LOG_FOR_COUNT = 100

    def save_log(self, fetch_count=0):
        self.total_fetch_count += fetch_count
        log_hours = self.save_log_at.diff().in_hours()
        console.log(
            f'total fetch count: {self.total_fetch_count}, '
            f'threshold: {self.SAVE_LOG_FOR_COUNT}')
        console.log(
            f'log hours: {log_hours}, threshold: {self.SAVE_LOG_INTERVAL}h')
        if (log_hours > self.SAVE_LOG_INTERVAL or
                self.total_fetch_count > self.SAVE_LOG_FOR_COUNT):
            console.log('Threshold reached, saving log automatically...')
        elif fetch_count == 0:
            console.log('Saving log manually...')
        else:
            return
        save_log(self.command, self.download_dir)
        self.save_log_at = pendulum.now()
        self.total_fetch_count = 0


@app.command(help="Loop through users in database and fetch weibos")
@logsaver_decorator
def user_loop(frequency: float = 2,
              download_dir: Path = default_path,
              update_note: bool = Option(
                  False, "--update-note", "-u", help="Update note of user")
              ):
    query = (UserConfig.select()
             .where(UserConfig.note_fetch_at <
                    pendulum.now().subtract(hours=12))
             .order_by(UserConfig.note_fetch_at.asc(nulls='first'),
                       UserConfig.id.asc()))
    WORKING_TIME = 10
    logsaver = LogSaver('user_loop', download_dir)
    while True:
        print_command()
        update_user_config()
        start_time = pendulum.now()
        start_count = fetcher.visits
        for user in query.where(UserConfig.note_fetch)[:2]:
            config = UserConfig.from_id(user_id=user.user_id)
            config.fetch_note(download_dir, update_note=update_note)
            if (work_time := start_time.diff().in_minutes()) > WORKING_TIME:
                console.log(
                    f'have been working for {work_time}m '
                    f'which is more than {WORKING_TIME}m, taking a break')
                break
            console.log('waiting for 60 seconds to fetching next user')
            time.sleep(60)

        for query in get_user_search_query():
            if (work_time := start_time.diff().in_minutes()) > WORKING_TIME:
                console.log(
                    f'have been working for {work_time}m '
                    f'which is more than {WORKING_TIME}m, taking a break')
                break
            Query.search(query)
            console.log('waiting for 60 seconds to fetching next user')
            time.sleep(60)

        logsaver.save_log(fetcher.visits-start_count)
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
            if select.select([sys.stdin], [], [], 600)[0]:
                match (input().lower()):
                    case "s":
                        console.log(
                            "S pressed. continuing immediately.")
                        break
                    case "q":
                        console.log("Q pressed. exiting.")
                        return
                    case "l":
                        logsaver.save_log()
                    case _:
                        console.log(
                            "Press S to fetching immediately,\n"
                            "L to save log,\n"
                            "Q to exit,\n"
                        )


@app.command(help='Add user to database of users whom we want to fetch from')
@logsaver_decorator
def user(download_dir: Path = default_path):
    """Add user to database of users whom we want to fetch from"""
    update_user_config()
    while user_id := Prompt.ask('请输入用户名:smile:').strip():
        if uc := UserConfig.get_or_none(username=user_id):
            user_id = uc.user_id
        user_id = normalize_user_id(user_id)
        if uc := UserConfig.get_or_none(user_id=user_id):
            console.log(f'用户{uc.username}已在列表中')
        uc = UserConfig.from_id(user_id)
        console.log(uc, '\n')
        uc.note_fetch = Confirm.ask(f"是否获取{uc.username}的主页？", default=True)
        uc.save()
        console.log(f'用户{uc.username}更新完成')
        if uc.note_fetch and not uc.followed:
            console.log(f'用户{uc.username}未关注，记得关注🌸', style='notice')
        elif not uc.note_fetch and uc.followed:
            console.log(f'用户{uc.username}已关注，记得取关🔥', style='notice')
        if not uc.note_fetch and Confirm.ask('是否删除该用户？', default=False):
            uc.delete_instance()
            console.log('用户已删除')
        elif uc.note_fetch and Confirm.ask('是否现在抓取', default=False):
            uc.fetch_note(download_dir)


def update_user_config():
    """
    Update photos num for user_config
    """
    from redbook.model import Artist, UserConfig
    for uc in UserConfig:
        if artist := Artist.get_or_none(user=uc.user):
            uc.photos_num = artist.photos_num
            uc.folder = artist.folder
            uc.save()


def get_user_search_query():

    from sinaspider.model import UserConfig as SinaConfig
    sina_users = (SinaConfig.select()
                  .where(SinaConfig.weibo_fetch)
                  .where(SinaConfig.weibo_fetch_at.is_null(False))
                  .where(SinaConfig.photos_num > 0)
                  .order_by(SinaConfig.id.desc())
                  )
    for u in sina_users:
        query = u.screen_name
        if re.search(r'[\u4e00-\u9fff]', query):
            continue
        if Query.get_or_none(query=query):
            continue
        yield query
