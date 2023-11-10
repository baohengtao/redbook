from pathlib import Path

from rich.prompt import Confirm, Prompt
from typer import Option, Typer

from redbook import console
from redbook.helper import default_path, logsaver, normalize_user_id
from redbook.model import UserConfig

app = Typer()


@app.command(help="Loop through users in database and fetch weibos")
@logsaver
def user_loop(download_dir: Path = default_path,
              max_user: int = 1,
              new_user: bool = Option(False, "--new-user", "-n"),
              ):
    if new_user:
        users = (UserConfig.select()
                 .where(UserConfig.note_fetch)
                 .where(UserConfig.note_fetch_at.is_null()))

    else:
        users = (UserConfig.select()
                 .where(UserConfig.note_fetch)
                 .where(UserConfig.note_fetch_at.is_null(False))
                 .order_by(UserConfig.note_fetch_at)
                 )
    users = users[:max_user]
    console.log(f'{len(users)} will be fetched...')
    for i, user in enumerate(users, start=1):
        config = UserConfig.from_id(user_id=user.user_id)
        config.fetch_note(download_dir)
        console.log(f'user {i}/{len(users)} completed!')


@app.command(help='Add user to database of users whom we want to fetch from')
@logsaver
def user(download_dir: Path = default_path):
    """Add user to database of users whom we want to fetch from"""
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
