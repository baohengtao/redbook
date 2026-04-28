import re
from pathlib import Path
from typing import AsyncGenerator, Iterator, Self

import pendulum
from photosinfo.model import GirlSearch
from playhouse.shortcuts import model_to_dict, update_model_from_dict
from rich.prompt import Confirm
from toolkit.model import (
    ArrayField, BaseModel,
    BooleanField,
    DateTimeTZField,
    ForeignKeyField,
    IntegerField, JSONField,
    TextField, get_database
)

from redbook import console
from redbook.exception import UserNotFoundError
from redbook.helper import (
    SAVE_PATH, download_files,
    download_single_file,
    normalize_count
)
from redbook.redbook import (
    get_note, get_user,
    get_user_notes,
    parse_note, shorten_url
)

database = get_database('redbook')
BaseModel.bind(database)


class User(BaseModel):
    id = TextField(primary_key=True, unique=True)
    red_id = TextField(unique=True)
    username = TextField()
    nickname = TextField()
    age = TextField(null=True)
    description = TextField(null=True)
    homepage = TextField()
    short_url = TextField()
    following = BooleanField()
    location = TextField(null=True)
    ip_location = TextField(null=True)
    college = TextField(null=True)
    gender = IntegerField()
    follows = IntegerField()
    fans = IntegerField()
    interaction = IntegerField()
    profession = ArrayField(field_class=TextField, null=True)
    verified = BooleanField()
    verified_type = IntegerField(null=True)
    collection_public = BooleanField()
    avatar = TextField()
    avatar_saved = BooleanField(default=False)
    added_at = DateTimeTZField(null=True, default=pendulum.now)
    redirect = TextField(null=True)
    account_deleted = BooleanField(default=False)
    search_results = GirlSearch.get_search_results()['red']

    def __str__(self):
        return super().__repr__()

    @classmethod
    async def from_id(cls, user_id: str, update=False) -> Self:
        if not (model := cls.get_or_none(id=user_id)) or update:
            for _ in range(3):
                try:
                    user_dict = await get_user(user_id)
                except UserNotFoundError as e:
                    console.log(e, style='error')
                    if not model:
                        raise
                    model.account_deleted = True
                    model.save()
                    return model
                if not model or user_dict['following'] == model.following:
                    break
            else:
                console.log(model)
                if not Confirm.ask('following status changed?'):
                    raise ValueError('following status changed!')
            await cls.upsert(user_dict)
        model = cls.get_by_id(user_id)
        await model.save_avatar()
        return model

    @classmethod
    async def upsert(cls, user_dict: dict):
        user_id = user_dict['id']
        if not (model := cls.get_or_none(id=user_id)):
            if not (username := cls.search_results.get(user_id)):
                username = user_dict['nickname'].strip('-_ ')
            assert username
            user_dict['username'] = username
            return cls.insert(user_dict).execute()
        model_dict = model_to_dict(model)
        if not (model and model.short_url):
            user_dict['short_url'] = await shorten_url(user_dict['homepage'])

        for k, v in user_dict.copy().items():
            assert v or v == 0
            if k in ['fans', 'follows', 'interaction']:
                continue
            if v == model_dict[k]:
                continue
            if k == 'avatar':
                console.log('avatar changed!', style='error')
                assert model.avatar_saved is True
                user_dict['avatar_saved'] = False
            console.log(f'+{k}: {v}', style='green bold on dark_green')
            if (ori := model_dict[k]) is not None:
                console.log(f'-{k}: {ori}', style='red bold on dark_red')
        return cls.update(user_dict).where(cls.id == user_id).execute()

    async def save_avatar(self):
        if self.avatar_saved:
            return
        assert self.short_url
        aid = Path(self.avatar.split('?')[0].split('/')[-1])
        aid = aid.with_suffix(aid.suffix or '.jpg')
        filename = Path(f'{self.username}_{aid}')
        xmp_info = {
            "ImageSupplierID": self.id,
            "ImageSupplierName": "RedBook",
            "ImageCreatorName": self.username,
            "BlogURL": self.short_url,
            "BlogTitle": f'{self.username}的小红书头像',
            "DateCreated": pendulum.now(),
            "URLUrl": self.avatar
        }
        xmp_info["DateCreated"] = xmp_info["DateCreated"].strftime(
            "%Y:%m:%d %H:%M:%S.%f").strip('0').strip('.')
        xmp_info = {'XMP:'+k: v for k, v in xmp_info.items()}
        console.log(f"save {self.username}'s avatar")
        await download_single_file(
            url=self.avatar,
            filepath=SAVE_PATH/'Avatar',
            filename=filename,
            xmp_info=xmp_info)
        self.avatar_saved = True
        self.save()

    @classmethod
    async def save_all_avatars(cls):
        for u in User.select().where(~User.avatar_saved):
            u: User
            await u.save_avatar()


class UserConfig(BaseModel):
    user = ForeignKeyField(User, backref="config")
    red_id = TextField(unique=True)
    username = TextField()
    note_fetch = BooleanField(default=True)
    note_fetch_at = DateTimeTZField(null=True)
    note_refetch_at = DateTimeTZField(null=True)
    note_next_fetch = DateTimeTZField(null=True)
    is_caching = BooleanField(default=True)
    post_cycle = IntegerField(null=True)
    age = TextField(null=True)
    description = TextField(null=True)
    homepage = TextField()
    following = BooleanField()
    location = TextField(null=True)
    ip_location = TextField(null=True)
    college = TextField(null=True)
    post_at = DateTimeTZField(null=True)
    photos_num = IntegerField(null=True)
    folder = TextField(null=True)
    added_at = DateTimeTZField(null=True, default=pendulum.now)
    notes_count = IntegerField(default=0)

    def __str__(self):
        return super().__repr__()

    @classmethod
    async def from_id(cls, user_id: int) -> Self:
        user = await User.from_id(user_id, update=True)
        user_dict = model_to_dict(user)
        user_dict['user_id'] = user_dict.pop('id')
        to_insert = {k: v for k, v in user_dict.items()
                     if k in cls._meta.columns}
        if config := cls.get_or_none(user_id=user_id):
            cls.update(to_insert).where(cls.user_id == user_id).execute()
        else:
            cls.insert(to_insert).execute()
        if user.account_deleted:
            console.log(config)
            if not Confirm.ask('seems account deleted, disable fetch?'):
                raise ValueError('账号已注销')
            config.note_fetch = False
            config.save()

        return cls.get(user_id=user_id)

    async def page(self) -> AsyncGenerator[dict]:
        async for note in get_user_notes(self.user_id):
            assert note.pop('avatar') == self.user.avatar.split(
                '?')[0].replace('sns-avatar-bak', 'sns-avatar-qc')
            assert note.pop('nick_name') == self.user.nickname
            assert note.pop('nickname') == self.user.nickname
            assert note.pop('user_id') == self.user_id

            note['liked_count'] = normalize_count(note['liked_count'])

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
                    pendulum.Duration(hours=2*config.post_cycle))
            config.save()

    async def fetch_note(self, download_dir: Path):
        refetch = (self.notes_count < 50 or not self.note_refetch_at or
                   self.note_refetch_at.diff().in_days() > self.notes_count/10)
        if not self.note_fetch:
            return
        if since := self.note_fetch_at:
            estimated_post = since.diff().in_hours() / self.post_cycle
            estimated_post = f'estimated_new_posts:{estimated_post:.2f}'
            msg = f' (fetch_at:{since:%y-%m-%d} {estimated_post})'
        else:
            msg = '(New User)'
            assert refetch is True
        console.rule(f"开始获取 {self.username} 的主页 {msg}")
        console.log(self.user)
        console.log(f"Media Saving: {download_dir}")

        now = pendulum.now()
        imgs = self._save_notes(download_dir, refetch=refetch)
        await download_files(imgs)
        console.log(f"{self.username} 📕 获取完毕\n")

        self.note_fetch_at = now
        if notes := self.user.notes.order_by(Note.time.desc()):
            self.post_at = notes.first().time
        self.post_cycle = self.get_post_cycle()
        self.note_next_fetch = now.add(hours=2*self.post_cycle)
        if refetch:
            self.note_refetch_at = now
        self.notes_count = self.user.notes.count()
        self.save()

    async def _save_notes(
            self,
            download_root: Path,
            refetch=False,
    ) -> AsyncGenerator[list[dict]]:
        """
        Save note to database and return media info
        :return: generator of medias to downloads
        """

        since = self.note_fetch_at or pendulum.from_timestamp(0)
        user_root = 'User' if (
            self.note_fetch_at and self.photos_num) else 'NewInit'
        if user_root == 'NewInit' and self.note_fetch_at:
            if not (download_root / user_root / self.username).exists():
                user_root = 'New'
        download_dir = download_root / user_root / self.username
        if user_root == 'User':
            revisit_dir = download_root / 'Revisit' / self.username
        else:
            revisit_dir = download_dir
        if self.is_caching:
            console.log(f'caching notes from {since:%Y-%m-%d}\n')
        else:
            console.log(f'fetch notes from {since:%Y-%m-%d}\n')
        note_time_order, note_ids = [], []
        async for note_info in self.page():
            update_xsec_token(note_info['id'], note_info['xsec_token'])
            sticky = note_info.pop('sticky')
            cached = Cache.get_or_none(id=note_info['id'])
            if note := Note.get_or_none(id=note_info['id']):
                if note.time < since and (cached or not self.is_caching):
                    if sticky:
                        console.log("略过置顶笔记...")
                        continue
                    if refetch or note.time > since.subtract(months=1):
                        continue
                    console.log(
                        f"时间 {note.time:%y-%m-%d} 在 {since:%y-%m-%d}之前, "
                        "获取完毕")
                    break

            has_fetched = note
            note = await Note.from_id(
                note_info['id'],
                xsec_token=note_info['xsec_token'],
                update=not cached)
            if note.time < since and not has_fetched:
                console.log(
                    f'find note {note.id} before {since:%y-%m-%d} '
                    'but not fetched!', style='error')
                save_path = revisit_dir
            else:
                save_path = download_dir
            display_title = re.sub(
                r'\s|\n', '', note.title or note.desc or '')
            display_topic = ''.join(note.topics or [])
            t = re.sub(r'\s|\n', '', note_info.pop('display_title'))

            if t not in display_topic + display_title + display_topic:
                console.log(f"note_info['display_title'] {t} not in "
                            f"{[note.title, note.desc]}", style='error')
            for k, v in note_info.items():
                if getattr(note, k) != v:
                    assert k in ['liked_count', 'xsec_token', 'liked']
            if not sticky:
                note_time_order.append(note.time)
            note_ids.append(note.id)

            medias = list(note.medias(save_path))
            console.log(note.url, style=f"link {note.url}")
            console.log(note, '\n')
            if self.is_caching:
                continue
            console.log(
                f"Downloading {len(medias)} files to {save_path}..")
            console.print()
            for media in medias:
                yield media
        if note_time_order:
            console.log(f'{len(note_time_order)} notes fetched')
            assert sorted(note_time_order, reverse=True) == note_time_order
        if self.is_caching:
            return
        query = self.user.notes.where(
            Note.id.not_in(note_ids)).where(Note.time > since)
        for note in query:
            console.log(f'find invisible note {note.id}', style='notice')
            medias = list(note.medias(download_dir))
            console.log(note)
            console.log(
                f"Downloading {len(medias)} files to {download_dir}..")
            console.print()
            for media in medias:
                yield media


def update_xsec_token(note_id, xsec_token):
    url = f'https://xiaohongshu.com/explore/{note_id}?xsec_token={xsec_token}&xsec_source=pc_user'
    if cache := Cache.get_or_none(id=note_id):
        cache.xsec_token = xsec_token
        cache.note_info |= {'url': url, 'xsec_token': xsec_token}
        cache.save()
    if note := Note.get_or_none(id=note_id):
        note.xsec_token = xsec_token
        note.url = url
        note.save()


class Cache(BaseModel):
    id = TextField(primary_key=True, unique=True)
    xsec_token = TextField()
    note_info = JSONField()
    added_at = DateTimeTZField()
    updated_at = DateTimeTZField(null=True)

    @classmethod
    def upsert(cls, note_info: dict) -> Self:
        d = {'id': (id := note_info['note_id']),
             'xsec_token': note_info['xsec_token'],
             'note_info': note_info}
        if cache := cls.get_or_none(id=id):
            d['updated_at'] = pendulum.now()
            update_model_from_dict(cache, d)
            cache.save()
        else:
            d['added_at'] = pendulum.now()
            cls.insert(d).execute()
        return cls.get_by_id(id)

    def parse(self) -> dict:
        return parse_note(self.note_info)


class Note(BaseModel):
    id = TextField(primary_key=True, unique=True)
    user = ForeignKeyField(User, backref="notes")
    username = TextField()
    following = BooleanField()
    title = TextField(null=True)
    desc = TextField(null=True)
    time = DateTimeTZField()
    last_update_time = DateTimeTZField()
    ip_location = TextField(null=True)
    at_user = JSONField(null=True)
    topics = ArrayField(field_class=TextField, null=True)
    url = TextField()
    comment_count = IntegerField(default=0)
    share_count = IntegerField(default=0)
    liked = BooleanField()
    liked_count = IntegerField(default=0)
    collected = BooleanField()
    collected_count = IntegerField(default=0)
    type = TextField()
    pic_ids = ArrayField(field_class=TextField)
    pics = ArrayField(field_class=TextField)
    video = TextField(null=True)
    audio = JSONField(null=True)
    added_at = DateTimeTZField(null=True)
    updated_at = DateTimeTZField(null=True)
    xsec_token = TextField(null=True)

    @classmethod
    async def from_id(cls, note_id, update: bool = False, xsec_token: str = '') -> Self:
        note = cls.get_or_none(id=note_id)
        cache = Cache.get_or_none(id=note_id)
        if update or not (note or cache):
            note_info = await get_note(note_id, xsec_token or note.xsec_token)
            cache = Cache.upsert(note_info)
        elif cache:
            note_info = cache.note_info
        else:
            return note
        note_dict = parse_note(note_info)
        note_dict = {k: v for k, v in note_dict.items() if v != []}
        user: User = User.get_by_id(note_dict['user_id'])
        assert note_dict.pop('nickname') == user.nickname
        assert note_dict['following'] == user.following
        note_dict['username'] = user.username
        assert 'added_at' not in note_dict
        assert 'updated_at' not in note_dict
        note_dict['updated_at'] = cache.updated_at or cache.added_at
        await cls.upsert(note_dict)
        return cls.get_by_id(note_id)

    @classmethod
    async def upsert(cls, note_dict):
        note_id = note_dict['id']
        if not (model := cls.get_or_none(id=note_id)):
            note_dict['added_at'] = note_dict.pop('updated_at')
            try:
                return cls.insert(note_dict).execute()
            except Exception:
                url = note_dict['url']
                console.log(url, style=f'link {url}')
                console.log(
                    f'{url} insert to database failed', style='error')
                raise
        model_dict = model_to_dict(model, recurse=False)
        model_dict['user_id'] = model_dict.pop('user')

        for key, value in note_dict.items():
            assert value or value == 0
            if (ori := model_dict[key]) == value:
                continue
            if key in ['xsec_token', 'url', 'updated_at',
                       'following', 'liked_count', 'share_count',
                       'comment_count', 'collected_count']:
                continue
            if key in ['pic_ids', 'pics', 'video', 'video_md5']:
                assert note_dict['last_update_time'] >= model.last_update_time, (
                    note_dict['last_update_time'], model.last_update_time)
            if key in ['pics', 'pic_ids']:
                assert set(v.split()[0].split('/')[-1]
                           for v in value) == set(v.split()[0].split('/')[-1] for v in ori)

            console.log(f'+{key}: {value}', style='green bold on dark_green')
            if ori is not None:
                console.log(f'-{key}: {ori}', style='red bold on dark_red')
        return cls.update(note_dict).where(cls.id == note_id).execute()

    def medias(self, filepath: Path = None) -> Iterator[list[dict]]:
        prefix = f'{self.last_update_time:%y-%m-%d}_{self.username}_{self.id}'
        if self.video:
            if len(self.pics) == 1:
                yield [{
                    'url': self.video,
                    'filename': f'{prefix}.mp4',
                    'filepath': filepath,
                    'xmp_info': self.gen_meta(url=self.video),
                }]
                return
            assert len(self.pics) > 1  # video is a set of imgs
        for sn, url in enumerate(self.pics, start=1):
            if ' ' not in url:
                url += ' '
            url, live = url.split(' ')
            live_tag = '_live' if live else ''
            suffix = '.heic' if live else '.webp'
            meta = [{
                'url': url.split('?')[0] if not live else url,
                'filename': f'{prefix}_{sn}{live_tag}_img{suffix}',
                'filepath': filepath,
                'xmp_info': self.gen_meta(sn=sn, url=url),
            }]
            if live:
                meta.append({
                    'url': live,
                    'filename': f'{prefix}{live_tag}_{sn}.mov',
                    'filepath': filepath,
                    'xmp_info': self.gen_meta(sn=sn, url=live),
                })
            yield meta

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

    def __repr__(self):
        return BaseModel.__repr__(self)


class Artist(BaseModel):
    user = ForeignKeyField(User, unique=True, backref='artist')
    red_id = TextField(unique=True)
    username = TextField(index=True)
    age = TextField(null=True)
    photos_num = IntegerField(default=0)
    description = TextField(null=True)
    homepage = TextField(null=True)
    following = BooleanField()
    location = TextField(null=True)
    ip_location = TextField(null=True)
    college = TextField(null=True)
    gender = IntegerField()
    follows = IntegerField()
    fans = IntegerField()
    interaction = IntegerField()
    added_at = DateTimeTZField(null=True, default=pendulum.now)

    _cache: dict[int, Self] = {}

    class Meta:
        table_name = "artist"

    def __str__(self):
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
    [User, UserConfig, Note, Artist, Cache])
