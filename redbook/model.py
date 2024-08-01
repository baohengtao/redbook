import re
from datetime import datetime
from pathlib import Path
from typing import Iterator, Self

import pendulum
from peewee import Model
from photosinfo.model import GirlSearch
from playhouse.postgres_ext import (
    ArrayField, BooleanField,
    CharField,
    DateTimeTZField,
    ForeignKeyField,
    IntegerField, JSONField,
    PostgresqlExtDatabase,
    TextField
)
from playhouse.shortcuts import model_to_dict

from redbook import console
from redbook.helper import download_files
from redbook.redbook import get_note, get_user, get_user_notes

database = PostgresqlExtDatabase("redbook", host="localhost")


class BaseModel(Model):
    class Meta:
        database = database

    def __repr__(self):
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


class User(BaseModel):
    id = TextField(primary_key=True, unique=True)
    red_id = CharField(unique=True)
    username = CharField()
    nickname = CharField()
    age = CharField(null=True)
    description = TextField(null=True)
    homepage = TextField()
    following = BooleanField()
    location = CharField(null=True)
    ip_location = CharField(null=True)
    college = TextField(null=True)
    gender = IntegerField()
    follows = IntegerField()
    fans = IntegerField()
    interaction = IntegerField()
    profession = ArrayField(field_class=TextField, null=True)
    verified = BooleanField()
    collection_public = BooleanField()
    avatar = TextField()
    added_at = DateTimeTZField(null=True, default=pendulum.now)
    redirect = TextField(null=True)
    search_results = GirlSearch.get_search_results()['red']

    def __str__(slef):
        return super().__repr__()

    @classmethod
    async def from_id(cls, user_id: str, update=False) -> Self:
        if not (model := cls.get_or_none(id=user_id)) or update:
            for _ in range(3):
                user_dict = await get_user(user_id)
                if not model or user_dict['following'] == model.following:
                    break
            if not model:
                assert user_dict['following'] is True
            cls.upsert(user_dict)
        return cls.get_by_id(user_id)

    @classmethod
    def upsert(cls, user_dict: dict):
        user_id = user_dict['id']
        if not (model := cls.get_or_none(id=user_id)):
            if not (username := cls.search_results.get(user_id)):
                username = user_dict['nickname'].strip('-_ ')
            assert username
            user_dict['username'] = username
            return cls.insert(user_dict).execute()
        model_dict = model_to_dict(model)

        for k, v in user_dict.items():
            assert v or v == 0
            if k in ['fans', 'follows', 'interaction']:
                continue
            if v == model_dict[k]:
                continue
            console.log(f'+{k}: {v}', style='green bold on dark_green')
            if (ori := model_dict[k]) is not None:
                console.log(f'-{k}: {ori}', style='red bold on dark_red')
        return cls.update(user_dict).where(cls.id == user_id).execute()


class UserConfig(BaseModel):
    # user: "User" = DeferredForeignKey("User", unique=True, backref='config')
    user = ForeignKeyField(User, backref="config")
    red_id = CharField(unique=True)
    username = CharField()
    note_fetch = BooleanField(default=True)
    note_fetch_at = DateTimeTZField(null=True)
    note_next_fetch = DateTimeTZField(null=True)
    post_cycle = IntegerField(null=True)
    age = CharField(null=True)
    description = TextField(null=True)
    homepage = TextField()
    following = BooleanField()
    location = CharField(null=True)
    ip_location = CharField(null=True)
    college = TextField(null=True)
    post_at = DateTimeTZField(null=True)
    photos_num = IntegerField(null=True)
    folder = CharField(null=True)
    added_at = DateTimeTZField(null=True, default=pendulum.now)

    def __str__(slef):
        return super().__repr__()

    @classmethod
    async def from_id(cls, user_id: int) -> Self:
        user = await User.from_id(user_id, update=True)
        user_dict = model_to_dict(user)
        user_dict['user_id'] = user_dict.pop('id')
        to_insert = {k: v for k, v in user_dict.items()
                     if k in cls._meta.columns}
        if cls.get_or_none(user_id=user_id):
            cls.update(to_insert).where(cls.user_id == user_id).execute()
        else:
            cls.insert(to_insert).execute()
        return cls.get(user_id=user_id)

    async def page(self) -> Iterator[tuple[dict, str]]:
        async for note in get_user_notes(self.user_id):
            assert note.pop('avatar') == self.user.avatar
            assert note.pop('nick_name') == self.user.nickname
            assert note.pop('nickname') == self.user.nickname
            assert note.pop('user_id') == self.user_id

            note['liked_count'] = int(note['liked_count'])

            assert 'id' not in note
            note['id'] = note.pop('note_id')
            yield note

    def get_post_cycle(self) -> int:
        interval = pendulum.Duration(days=30)
        start, end = self.note_fetch_at-interval, self.note_fetch_at
        count = self.user.notes.where(Note.time.between(start, end)).count()
        cycle = interval / (count + 1)
        return cycle.in_hours()

    @classmethod
    def update_table(cls):
        from photosinfo.model import Girl
        for config in UserConfig:
            if girl := Girl.get_or_none(red_id=config.user_id):
                config.photos_num = girl.red_num
                config.folder = girl.folder
            else:
                config.photos_num = 0
            if config.note_fetch_at:
                config.post_cycle = config.get_post_cycle()
                config.note_next_fetch = (
                    config.note_fetch_at +
                    pendulum.Duration(hours=config.post_cycle))
            config.save()

    async def fetch_note(self, download_dir: Path):
        if not self.note_fetch:
            return
        if self.note_fetch_at:
            since = pendulum.instance(self.note_fetch_at)
        else:
            Artist.from_id(self.user_id)
            since = pendulum.from_timestamp(0)
        if self.note_fetch_at:
            estimated_post = since.diff().in_hours() / self.post_cycle
            estimated_post = f'estimated_new_posts:{estimated_post:.2f}'
            msg = f' (fetch_at:{since:%y-%m-%d} {estimated_post})'
        else:
            msg = ''
        console.rule(f"开始获取 {self.username} 的主页 {msg}")
        console.log(self.user)
        console.log(f"Media Saving: {download_dir}")

        now = pendulum.now()
        imgs = self._save_notes(since, download_dir)
        await download_files(imgs)
        console.log(f"{self.username} 📕 获取完毕\n")

        self.note_fetch_at = now
        self.post_at = self.user.notes.order_by(Note.time.desc()).first().time
        self.post_cycle = self.get_post_cycle()
        self.note_next_fetch = now.add(hours=self.post_cycle)
        self.save()

    async def _save_notes(
            self,
            since: pendulum.DateTime,
            download_dir: Path
    ) -> Iterator[dict]:
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
        note_time_order = []
        async for note_info in self.page():
            sticky = note_info.pop('sticky')
            if note := Note.get_or_none(id=note_info['id']):
                if note.time < since:
                    if sticky:
                        console.log("略过置顶笔记...")
                        continue
                    elif note.time > since.subtract(months=1):
                        continue
                    else:
                        console.log(
                            f"时间 {note.time:%y-%m-%d} 在 {since:%y-%m-%d}之前, "
                            "获取完毕")
                        break

            note = await Note.from_id(note_info['id'],
                                      xsec_token=note_info['xsec_token'])
            if note.time < since:
                console.log(
                    f'find note {note.id} before {since:%y-%m-%d} '
                    'but not fetched!', style='error')
            display_title = re.sub(
                r'\s|\n', '', note.title or note.desc or '')
            display_topic = ''.join(note.topics or [])
            t = re.sub(r'\s|\n', '', note_info.pop('display_title'))

            if t not in display_topic + display_title + display_topic:
                console.log(f"note_info['display_title] {t} not in "
                            f"{[note.title, note.desc]}", style='error')
            for k, v in note_info.items():
                if getattr(note, k) != v:
                    assert k in ['liked_count', 'xsec_token']
            if not sticky:
                note_time_order.append(note.time)

            medias = list(note.medias(download_dir))
            console.log(note)
            console.log(
                f"Downloading {len(medias)} files to {download_dir}..")
            console.print()
            for media in medias:
                yield media
        if note_time_order:
            console.log(f'{len(note_time_order)} notes fetched')
            assert sorted(note_time_order, reverse=True) == note_time_order


class Note(BaseModel):
    id = TextField(primary_key=True, unique=True)
    user = ForeignKeyField(User, backref="notes")
    username = CharField()
    following = BooleanField()
    title = TextField(null=True)
    desc = TextField(null=True)
    time = DateTimeTZField()
    last_update_time = DateTimeTZField()
    ip_location = CharField(null=True)
    at_user = JSONField(null=True)
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
    added_at = DateTimeTZField(null=True)
    updated_at = DateTimeTZField(null=True)
    xsec_token = TextField(null=True)

    @classmethod
    async def from_id(cls, note_id, update=None, xsec_token=None) -> Self:
        note_id = note_id.removeprefix("https://www.xiaohongshu.com/explore/")
        if not update and (note := cls.get_or_none(id=note_id)):
            date = note.updated_at or note.added_at
            if update is False or (pendulum.now() - date).in_hours() < 24:
                return note
        if note:
            xsec_token = note.xsec_token
        note_dict = await get_note(note_id, xsec_token)
        note_dict = {k: v for k, v in note_dict.items() if v != []}
        user: User = User.get_by_id(note_dict['user_id'])
        assert note_dict.pop('avatar') == user.avatar
        assert note_dict.pop('nickname') == user.nickname
        assert note_dict['following'] == user.following
        note_dict['username'] = user.username
        cls.upsert(note_dict)
        return cls.get_by_id(note_id)

    @classmethod
    def upsert(cls, note_dict):
        note_id = note_dict['id']
        assert 'added_at' not in note_dict
        assert 'updated_at' not in note_dict
        if not (model := cls.get_or_none(id=note_id)):
            note_dict['added_at'] = pendulum.now()
            return cls.insert(note_dict).execute()
        else:
            note_dict['updated_at'] = pendulum.now()
        model_dict = model_to_dict(model, recurse=False)
        model_dict['user_id'] = model_dict.pop('user')

        for key, value in note_dict.items():
            assert value or value == 0
            if (ori := model_dict[key]) == value:
                continue
            if key == 'pics':
                continue
            if key in ['pic_ids', 'video', 'video_md5']:
                assert note_dict['last_update_time'] > model.last_update_time
            console.log(f'+{key}: {value}', style='green bold on dark_green')
            if ori is not None:
                console.log(f'-{key}: {ori}', style='red bold on dark_red')
        return cls.update(note_dict).where(cls.id == note_id).execute()

    def medias(self, filepath: Path = None) -> Iterator[dict]:
        prefix = f'{self.last_update_time:%y-%m-%d}_{self.username}_{self.id}'
        for sn, pic_id in enumerate(self.pic_ids, start=1):
            url = (f'http://sns-img-hw.xhscdn.com/{pic_id}?imageView2/2/w/1000000000'
                   '/format/jpg')
            yield {
                'url': url.split('?')[0],
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

    def __str__(self):
        model = model_to_dict(self, recurse=False)
        model.pop('pics')
        model.pop('pic_ids')
        return "\n".join(f'{k}: {v}' for k, v in model.items())

    def __repr__(slef):
        return super().__repr__()


class Artist(BaseModel):
    user = ForeignKeyField(User, unique=True, backref='artist')
    red_id = CharField(unique=True)
    username = CharField(index=True)
    age = CharField(null=True)
    photos_num = IntegerField(default=0)
    description = TextField(null=True)
    homepage = CharField(null=True)
    following = BooleanField()
    location = CharField(null=True)
    ip_location = CharField(null=True)
    college = TextField(null=True)
    gender = IntegerField()
    follows = IntegerField()
    fans = IntegerField()
    interaction = IntegerField()
    added_at = DateTimeTZField(null=True, default=pendulum.now)

    _cache: dict[int, Self] = {}

    class Meta:
        table_name = "artist"

    def __str__(slef):
        return super().__repr__()

    @classmethod
    def from_id(cls, user_id: int) -> Self:
        if user_id in cls._cache:
            return cls._cache[user_id]
        user = User.get_by_id(user_id)
        user_dict = model_to_dict(user)
        user_dict['user_id'] = user_dict.pop('id')
        user_dict = {k: v for k, v in user_dict.items()
                     if k in cls._meta.columns}
        if cls.get_or_none(user_id=user_id):
            cls.update(user_dict).where(cls.user_id == user_id).execute()
        else:
            cls.insert(user_dict).execute()
        artist = cls.get(user_id=user_id)
        cls._cache[user_id] = artist
        return artist

    @property
    def xmp_info(self):
        xmp = {
            "Artist": self.username,
            "ImageCreatorID": self.homepage,
            "ImageSupplierID": self.user_id,
            "ImageSupplierName": "RedBook",
        }

        return {"XMP:" + k: v for k, v in xmp.items()}


database.create_tables(
    [User, UserConfig, Note, Artist])
