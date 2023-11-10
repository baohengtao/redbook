from datetime import datetime
from pathlib import Path
from typing import Iterator, Self

import pendulum
from peewee import Model
from playhouse.postgres_ext import (
    ArrayField,
    BigIntegerField,
    BooleanField, CharField,
    DateTimeTZField,
    DeferredForeignKey,
    ForeignKeyField,
    IntegerField,
    PostgresqlExtDatabase,
    TextField
)
from playhouse.shortcuts import model_to_dict

from redbook import console
from redbook.helper import download_files
from redbook.page import get_note, get_user_info, get_user_notes

database = PostgresqlExtDatabase("redbook", host="localhost")


class BaseModel(Model):
    class Meta:
        database = database

    def __str__(self):
        model = model_to_dict(self, recurse=False)
        for k, v in model.items():
            if isinstance(v, datetime):
                model[k] = v.strftime("%Y-%m-%d %H:%M:%S")

        return "\n".join(f'{k}: {v}'.replace('\n', '  ') for k, v
                         in model.items() if v is not None)

    @classmethod
    def get_or_none(cls, *query, **filters) -> Self | None:
        return super().get_or_none(*query, **filters)

    @classmethod
    def get(cls, *query, **filters) -> Self:
        return super().get(*query, **filters)


class UserConfig(BaseModel):
    user: "User" = DeferredForeignKey("User", unique=True, backref='config')
    red_id = CharField(unique=True)
    username = CharField()
    age = CharField(null=True)
    description = TextField()
    homepage = TextField()
    fstatus = CharField()
    location = CharField(null=True)
    ip_location = CharField()
    college = TextField(null=True)
    note_fetch = BooleanField(default=False)
    note_fetch_at = DateTimeTZField(null=True)
    post_at = DateTimeTZField(null=True)
    photos_num = IntegerField(null=True)
    folder = CharField(null=True)

    @classmethod
    def from_id(cls, user_id: int) -> Self:
        user = User.from_id(user_id, update=True)
        user_dict = model_to_dict(user)
        user_dict['user_id'] = user_dict.pop('id')
        to_insert = {k: v for k, v in user_dict.items()
                     if k in cls._meta.columns}
        if cls.get_or_none(user_id=user_id):
            cls.update(to_insert).where(cls.user_id == user_id).execute()
        else:
            cls.insert(to_insert).execute()
        return cls.get(user_id=user_id)

    def page(self) -> Iterator[dict]:
        for note in get_user_notes(self.user_id):
            assert note.pop('avatar') == self.user.avatar
            assert note.pop('nick_name') == self.user.nickname
            assert note.pop('nickname') == self.user.nickname
            assert note.pop('user_id') == self.user_id

            assert 'title' not in note
            note['title'] = note.pop('display_title').strip()
            note['liked_count'] = int(note['liked_count'])

            assert 'id' not in note
            note['id'] = note.pop('note_id')
            yield note

    def fetch_note(self, download_dir: Path):
        if not self.note_fetch:
            return
        if self.note_fetch_at:
            since = pendulum.instance(self.note_fetch_at)
        else:
            since = pendulum.from_timestamp(0)
        msg = f"fetch_at:{since:%y-%m-%d} liked_fetch:"
        console.rule(f"开始获取 {self.username} 的主页 ({msg})")
        console.log(self.user)
        console.log(f"Media Saving: {download_dir}")

        now = pendulum.now()
        imgs = self._save_notes(since, download_dir)
        download_files(imgs)
        console.log(f"{self.username} 📒 获取完毕\n")

        self.note_fetch_at = now
        self.save()

    def _save_notes(
            self,
            since: pendulum.DateTime,
            download_dir: Path) -> Iterator[dict]:
        """
        Save weibo to database and return media info
        :return: generator of medias to downloads
        """

        if since < pendulum.now().subtract(years=1):
            user_root = 'New'
        elif not self.photos_num:
            console.log(
                f'seems {self.username} not processed, using New folder',
                style='green on dark_green')
            user_root = 'New'
        else:
            user_root = 'User'
        download_dir = download_dir / user_root / self.username

        console.log(f'fetch notes from {since:%Y-%m-%d}\n')
        for note_info in self.page():
            sticky = note_info.pop('sticky')
            if note := Note.get_or_none(id=note_info['id']):
                if note.time < since:
                    if sticky:
                        console.log("略过置顶笔记...")
                        continue
                    else:
                        console.log(
                            f"时间 {note.time:%y-%m-%d} 在 {since:%y-%m-%d}之前, "
                            "获取完毕")
                        return

            note = Note.from_id(note_info['id'], update=True)
            assert note.time > since
            assert note_info.pop('title') in [note.title, note.desc]
            for k, v in note_info.items():
                assert getattr(note, k) == v

            medias = list(note.medias(download_dir))
            console.log(note)
            console.log(
                f"Downloading {len(medias)} files to {download_dir}..")
            console.print()
            yield from medias


class User(BaseModel):
    id = TextField(primary_key=True, unique=True)
    red_id = CharField(unique=True)
    username = CharField()
    nickname = CharField()
    age = CharField(null=True)
    description = TextField()
    homepage = TextField()
    fstatus = CharField()
    location = CharField(null=True)
    ip_location = CharField()
    college = TextField(null=True)
    gender = IntegerField()
    follows = IntegerField()
    fans = IntegerField()
    interaction = IntegerField()
    profession = TextField(null=True)
    avatar = TextField()

    @classmethod
    def from_id(cls, user_id: str, update=False) -> Self:
        if update or not cls.get_or_none(id=user_id):
            user_dict = get_user_info(user_id)
            cls.upsert(user_dict)
        return cls.get_by_id(user_id)

    @classmethod
    def upsert(cls, user_dict: dict):
        user_id = user_dict['id']
        if not (model := cls.get_or_none(id=user_id)):
            user_dict['username'] = user_dict['nickname']
            return cls.insert(user_dict).execute()
        model_dict = model_to_dict(model)

        for k, v in user_dict.items():
            assert v or v == 0
            if v == model_dict[k]:
                continue
            console.log(f'+{k}: {v}', style='green bold on dark_green')
            if (ori := model_dict[k]) is not None:
                console.log(f'-{k}: {ori}', style='red bold on dark_red')
        return cls.update(user_dict).where(cls.id == user_id).execute()


class Note(BaseModel):
    id = TextField(primary_key=True, unique=True)
    user = ForeignKeyField(User, backref="notes")
    username = CharField()
    followed = BooleanField()
    title = TextField(null=True)
    desc = TextField(null=True)
    time = DateTimeTZField()
    last_update_time = DateTimeTZField()
    ip_location = CharField(null=True)
    at_user = ArrayField(field_class=TextField, null=True)
    topics = ArrayField(field_class=TextField, null=True)
    url = TextField()
    comment_count = IntegerField()
    share_count = IntegerField()
    liked = BooleanField()
    liked_count = IntegerField()
    collected = BooleanField()
    collected_count = IntegerField()
    type = CharField()
    pic_ids = ArrayField(field_class=TextField)
    pics = ArrayField(field_class=TextField)
    video = TextField(null=True)
    video_md5 = TextField(null=True)

    @classmethod
    def from_id(cls, note_id, update=False) -> Self:
        if update or not cls.get_or_none(id=note_id):
            note_dict = get_note(note_id)
            note_dict = {k: v for k, v in note_dict.items() if v != []}
            user: User = User.get_by_id(note_dict['user_id'])
            assert note_dict.pop('avatar') == user.avatar
            assert note_dict.pop('nickname') == user.nickname
            note_dict['username'] = user.username
            cls.upsert(note_dict)
        return cls.get_by_id(note_id)

    @classmethod
    def upsert(cls, note_dict):
        note_id = note_dict['id']
        if not (model := cls.get_or_none(id=note_id)):
            return cls.insert(note_dict).execute()
        model_dict = model_to_dict(model, recurse=False)
        model_dict['user_id'] = model_dict.pop('user')

        for key, value in note_dict.items():
            assert value or value == 0
            if (ori := model_dict[key]) == value:
                continue
            if key == 'pics':
                continue
            assert key not in ['pic_ids', 'video', 'video_md5']
            console.log(f'+{key}: {value}', style='green bold on dark_green')
            if ori is not None:
                console.log(f'-{key}: {ori}', style='red bold on dark_red')
        return cls.update(note_dict).where(cls.id == note_id).execute()

    def medias(self, filepath: Path = None) -> Iterator[dict]:
        prefix = f'{self.time:%y-%m-%d}_{self.username}_{self.id}'
        for sn, url in enumerate(self.pics, start=1):
            yield {
                'url': url,
                'filename': f'{prefix}_{sn}.webp',
                'filepath': filepath,
                'xmp_info': self.gen_meta(sn=sn, url=url),
            }
        if self.video:
            yield {
                'url': self.video,
                'filename': f'{prefix}.mp4',
                'filepath': filepath,
                'xmp_info': self.gen_meta(url=self.video),
            }

    def gen_meta(self, sn: str | int = '', url: str = "") -> dict:
        if (pic_num := len(self.pics)) == 1:
            assert not sn or int(sn) == 1
            sn = ""
        elif sn and pic_num > 9:
            sn = f"{int(sn):02d}"
        title = f"{self.title or ''}\n{self.desc or ''}".strip()
        if self.ip_location:
            title += f' 发布于{self.ip_location}'.strip()
        xmp_info = {
            "ImageUniqueID": self.id,
            "ImageSupplierID": self.user_id,
            "ImageSupplierName": "RedBook",
            "ImageCreatorName": self.username,
            "BlogTitle": title.strip(),
            "BlogURL": self.url,
            "DateCreated": (self.time +
                            pendulum.Duration(microseconds=int(sn or 0))),
            "SeriesNumber": sn,
            "URLUrl": url
        }

        xmp_info["DateCreated"] = xmp_info["DateCreated"].strftime(
            "%Y:%m:%d %H:%M:%S.%f").strip('0').strip('.')
        res = {"XMP:" + k: v for k, v in xmp_info.items() if v}
        return res


database.create_tables(
    [User, UserConfig, Note])
