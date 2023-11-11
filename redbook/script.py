import select
import sys
import time
from pathlib import Path

import pendulum
from rich.prompt import Confirm, Prompt
from typer import Typer

from redbook import console
from redbook.helper import default_path, logsaver, normalize_user_id
from redbook.model import UserConfig

app = Typer()


@app.command(help="Loop through users in database and fetch weibos")
@logsaver
def user_loop(download_dir: Path = default_path,
              frequency: float = 3
              ):
    fetching_time = pendulum.now()
    while True:
        update_user_config()
        while pendulum.now() < fetching_time:
            # sleeping for  600 seconds while listing for enter key
            if select.select([sys.stdin], [], [], 600)[0]:
                match (input()):
                    case "":
                        console.log(
                            "Enter key pressed. continuing immediately.")
                        break
                    case "q":
                        console.log("q pressed. exiting.")
                        return
                    case _:
                        console.log(
                            "Press enter to fetching immediately,\n"
                            "Q to exit,\n"
                        )
                        continue
        start_time = time.time()
        for user in (UserConfig.select()
                     .where(UserConfig.note_fetch)
                     .order_by(
                         UserConfig.note_fetch_at.asc(nulls='first'),
                         UserConfig.id.asc()
        )):
            config = UserConfig.from_id(user_id=user.user_id)
            config.fetch_note(download_dir)
            if time.time() > start_time + 600:
                break
        fetching_time = pendulum.now().add(hours=frequency)
        console.log(f'waiting for next fetching at {fetching_time:%H:%M:%S}')


@app.command(help='Add user to database of users whom we want to fetch from')
@logsaver
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
