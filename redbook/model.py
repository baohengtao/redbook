from datetime import datetime
from pathlib import Path
from typing import Iterator, Self

import pendulum
from peewee import Model
from playhouse.postgres_ext import (
    ArrayField,
    BigIntegerField,
    BooleanField,
    DateTimeTZField,
    ForeignKeyField,
    IntegerField,
    PostgresqlExtDatabase,
    TextField
)
from playhouse.shortcuts import model_to_dict

from redbook import console
from redbook.page import get_note, get_user_info

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


class User(BaseModel):
    id = TextField(primary_key=True, unique=True)
    red_id = BigIntegerField(unique=True)
    username = TextField()
    nickname = TextField()
    age = TextField()
    description = TextField()
    homepage = TextField()
    fstatus = TextField()
    location = TextField()
    ip_location = TextField()
    college = TextField(null=True)
    gender = IntegerField()
    follows = IntegerField()
    fans = IntegerField()
    interaction = IntegerField()
    profession = TextField(null=True)
    avatar = TextField()

    @classmethod
    def from_id(cls, user_id, update=False) -> Self:
        if update or not cls.get_or_none(id=user_id):
            user_dict = get_user_info(user_id)
            cls.upsert(user_dict)
        return cls.get_by_id(user_id)

    @classmethod
    def upsert(cls, user_dict):
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
    username = TextField()
    followed = BooleanField()
    title = TextField()
    desc = TextField()
    time = DateTimeTZField()
    last_update_time = DateTimeTZField()
    ip_location = TextField()
    at_user = ArrayField(field_class=TextField, null=True)
    topics = ArrayField(field_class=TextField, null=True)
    url = TextField()
    comment_count = IntegerField()
    share_count = IntegerField()
    liked = BooleanField()
    liked_count = IntegerField()
    collected = BooleanField()
    collected_count = IntegerField()
    type = TextField()
    pic_ids = ArrayField(field_class=TextField)
    pics = ArrayField(field_class=TextField)

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
            assert key != 'pic_ids'
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

    def gen_meta(self, sn: str | int = '', url: str = "") -> dict:
        if (pic_num := len(self.pics)) == 1:
            assert not sn or int(sn) == 1
            sn = ""
        elif sn and pic_num > 9:
            sn = f"{int(sn):02d}"
        title = (f'{self.title.strip()}\n{self.desc.strip()} '
                 f'发布于 {self.ip_location}')
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


class UserConfig(BaseModel):
    pass


database.create_tables(
    [User, Note])
