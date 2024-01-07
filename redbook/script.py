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
def user_loop(frequency: float = 2,
              download_dir: Path = default_path,
              update_note: bool = Option(
                  False, "--update-note", "-u", help="Update note of user")
              ):

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
        elif configs := query.where(UserConfig.note_next_fetch < pendulum.now()):
            console.log(
                f' {len(configs)} users satisfy fetching conditions, '
                'Fetching 5 users whose note_fetch_at is earliest.')
            configs = configs[:5]
        else:
            configs = query[:2]
            console.log(
                'no user satisfy fetching conditions, '
                'fetching 2 users whose note_fetch_at is earliest.')
        for i, config in enumerate(configs):
            if start_time.diff().in_minutes() > WORKING_TIME:
                break
            console.log(f'fetching {i+1}/{len(configs)}: {config.username}')
            config = UserConfig.from_id(user_id=config.user_id)
            is_new = config.note_fetch_at is None
            config.fetch_note(download_dir, update_note=update_note)
            if is_new:
                logsaver.save_log(save_manually=True)
                print_command()

        for search_query, remark in get_user_search_query():
            if start_time.diff().in_minutes() > WORKING_TIME:
                break
            Query.search(search_query, remark)
            console.log('waiting for 120 seconds to fetching next user')
            time.sleep(120)

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
                        logsaver.save_log(save_manually=True)
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
    UserConfig.update_table()
    user = UserConfig.select().order_by(UserConfig.id.desc()).first()
    console.log(f'total {UserConfig.select().count()} users in database')
    console.log(f'the latest added user is {user.username}({user.user_id})')

    while user_id := Prompt.ask('请输入用户名:smile:').strip():
        if uc := UserConfig.get_or_none(username=user_id):
            user_id = uc.user_id
        user_id = normalize_user_id(user_id)
        if uc := UserConfig.get_or_none(user_id=user_id):
            console.log(f'用户{uc.username}已在列表中')
        uc = UserConfig.from_id(user_id)
        console.log(uc)
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
        console.log()


@app.command()
def write_meta(download_dir: Path = default_path):
    from imgmeta.script import rename, write_meta
    for folder in ['User', 'New']:
        ori = download_dir / folder
        if ori.exists():
            write_meta(ori)
            rename(ori, new_dir=True, root=ori.parent / (ori.stem + 'Pro'))


def get_user_search_query():

    from sinaspider.model import UserConfig as SinaConfig
    sina_users = (SinaConfig.select()
                  .where(SinaConfig.weibo_fetch)
                  .where(SinaConfig.weibo_fetch_at.is_null(False))
                  .where(SinaConfig.photos_num > 0)
                  .order_by(SinaConfig.id.desc())
                  )
    for u in sina_users:
        query = u.nickname
        remark = u.username
        if re.search(r'[\u4e00-\u9fff·]', query):
            continue
        if Query.get_or_none(query=query):
            continue
        yield query, remark
