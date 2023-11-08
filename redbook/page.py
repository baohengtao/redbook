import itertools
import re

import pendulum

from redbook import console
from redbook.fetcher import fetcher
from redbook.helper import convert_js_dict_to_py


def get_user_info(user_id):
    url = f"https://www.xiaohongshu.com/user/profile/{user_id}"
    r = fetcher.get(url)
    info = re.findall(
        r'<script>window.__INITIAL_STATE__=(.*?)</script>', r.text)[0]
    info = convert_js_dict_to_py(info)
    user_info = info['user']['userPageData']
    assert user_info.pop('result') == {
        'success': True, 'code': 0, 'message': 'success'}
    assert user_info.pop('tabPublic') == {'collection': False}
    user = _parse_user(user_info)
    assert 'id' not in user
    user['id'] = user_id
    user['homepage'] = url
    for key in ['red_id', 'follows', 'fans', 'interaction']:
        user[key] = int(user[key])
    keys = ['id', 'red_id', 'nickname', 'age', 'description', 'homepage',
            'fstatus', 'location', 'ip_location', 'college']
    user1 = {k: user[k] for k in keys if k in user}
    user2 = {k: user[k] for k in user if k not in keys}
    user_sorted = user1 | user2
    assert user_sorted == user
    return user_sorted


def _parse_user(user_info):
    user = user_info.pop('basicInfo')
    extra_info = user_info.pop('extraInfo')
    assert user | extra_info == extra_info | user
    user |= extra_info

    interactions_lst = user_info.pop('interactions')
    interactions = {i['type']: i['count'] for i in interactions_lst}
    assert len(interactions_lst) == len(interactions) == 3
    assert user | interactions == interactions | user
    user |= interactions

    tags_lst = user_info.pop('tags')
    tags = {t['tagType']: t['name'] for t in tags_lst}
    tags['age'] = tags.pop('info')
    assert len(tags) == len(tags_lst)
    assert user | tags == tags | user
    user |= tags
    assert not user_info

    avatar = user.pop('imageb').split('?')[0]
    assert avatar == user.pop('images').split('?')[0]
    assert avatar not in user
    user['avatar'] = avatar

    assert 'red_id' not in user
    user['red_id'] = user.pop('redId')

    assert 'ip_location' not in user
    user['ip_location'] = user.pop('ipLocation')

    assert 'description' not in user
    user['description'] = user.pop('desc')

    return user


def get_user_notes(user_id):
    cursor = ''
    for page in itertools.count(start=1):
        console.log(f'fetching page {page}...')
        api = ("/api/sns/web/v1/user_posted?num=30&image_scenes="
               f"&cursor={cursor}&user_id={user_id}")
        url = 'https://edith.xiaohongshu.com'
        js = fetcher.get(url=url, api=api).json()
        data = js.pop('data')
        assert js == {'success': True, 'msg': '成功', 'code': 0}

        cursor, has_more = data.pop('cursor'), data.pop('has_more')
        for note in data.pop('notes'):
            note.pop('cover')
            for k in ['user', 'interact_info']:
                v = note.pop(k)
                assert note | v == v | note
                note |= v
            yield note
        assert not data
        if not has_more:
            break
        assert cursor


def get_note(note_id, parse=True):
    note_data = (f'{{"source_note_id":"{note_id}",'
                 '"image_scenes":["CRD_PRV_WEBP","CRD_WM_WEBP"]}')
    r = fetcher.post('https://edith.xiaohongshu.com',
                     '/api/sns/web/v1/feed', note_data)
    js = r.json()
    data = js.pop('data')
    assert js == {'code': 0, 'success': True, 'msg': '成功'}
    items = data.pop('items')
    assert len(items) == 1
    item = items[0]
    note = item.pop('note_card')
    note['url'] = f'https://www.xiaohongshu.com/explore/{note_id}'
    assert item == {'id': note_id, 'model_type': 'note'}
    return _parse_note(note) if parse else note


def _parse_note(note: dict) -> dict:
    for key in ['user',  'share_info', 'interact_info']:
        value = note.pop(key)
        assert note | value == value | note
        note |= value

    for k in note:
        if 'count' in k:
            note[k] = int(note[k])

    assert note.pop('un_share') is False
    assert 'id' not in note
    note['id'] = note.pop('note_id')
    relation = 'follows' if note['followed'] else 'none'
    assert relation == note.pop('relation')

    for k in ['time', 'last_update_time']:
        note[k] = pendulum.from_timestamp(note[k]/1000, tz='local')

    tag_list = note.pop('tag_list')
    tags = {t['name']: t['type'] for t in tag_list}
    assert len(tags) == len(tag_list)
    assert set(tags.values()) == {'topic'} or not tags
    assert 'topics' not in note
    note['topics'] = list(tags.keys())

    assert 'at_user' not in note
    note['at_user'] = note.pop('at_user_list')

    image_list = note.pop('image_list')
    pics = []
    for image in image_list:
        image = {k: v for k, v in image.items() if v and k not in [
            'height', 'width']}
        info_list = image.pop('info_list')
        assert not image
        image = {i['image_scene']: i['url'] for i in info_list}
        pics.append(image['CRD_WM_WEBP'])
    assert 'pics' not in note
    note['pics'] = pics
    note['pic_ids'] = [pic.split('/')[-1] for pic in pics]

    keys = ['id', 'user_id', 'nickname',   'followed', 'title',
            'desc', 'time', 'last_update_time',
            'ip_location', 'at_user', 'topics', 'url',
            'comment_count', 'share_count', 'liked', 'liked_count',
            'collected', 'collected_count',
            ]
    note1 = {k: note[k] for k in keys if k in note}
    note2 = {k: note[k] for k in note if k not in keys}
    note_sorted = note1 | note2
    assert note_sorted == note
    return note_sorted
