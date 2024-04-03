import itertools
import re
import time
from typing import Iterator

import pendulum

from redbook import console
from redbook.fetcher import fetcher
from redbook.helper import convert_js_dict_to_py


def get_user(user_id: str, parse: bool = True) -> dict:
    while True:
        url = f"https://www.xiaohongshu.com/user/profile/{user_id}"
        r = fetcher.get(url)
        assert (c := r.status_code) != 503
        info = re.findall(
            r'<script>window.__INITIAL_STATE__=(.*?)</script>', r.text)[0]
        info = convert_js_dict_to_py(info)
        user_info = info['user']['userPageData']

        assert user_info.pop('result') == {
            'success': True, 'code': 0, 'message': 'success'}

        assert 'id' not in user_info
        user_info['id'] = user_id

        assert 'homepage' not in user_info
        user_info['homepage'] = url
        try:
            return _parse_user(user_info) if parse else user_info
        except ValueError as e:
            assert parse
            console.log(e, style='error')
            console.log('parsing failed, retrying after 60 seconds')
            time.sleep(60)


def _parse_user(user_info: dict) -> dict:
    #
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
    tags_lst = [(t['tagType'], t.get('name')) for t in tags_lst]
    tags = {t: n for t, n in tags_lst if t != 'profession'}
    if 'info' in tags:
        tags['age'] = tags.pop('info')
    profession = [n for t, n in tags_lst if t == 'profession']
    assert len(tags_lst) == len(tags) + len(profession)
    tags['profession'] = profession

    assert user | tags == tags | user
    user |= tags

    assert user | user_info == user_info | user
    user |= user_info

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

    for key in ['follows', 'fans', 'interaction']:
        user[key] = int(user[key])

    assert 'following' not in user
    if (fstatus := user.pop('fstatus')) in ['follows', 'both']:
        user['following'] = True
    else:
        assert fstatus == 'none'
        user['following'] = False

    tab_public = user.pop('tabPublic')
    collection_public = tab_public.pop('collection')
    assert not tab_public
    user['collection_public'] = collection_public

    assert 'verified' not in user
    if verifyInfo := user.pop('verifyInfo', None):
        assert verifyInfo == {'redOfficialVerifyType': 1}
        user['verified'] = True
    else:
        user['verified'] = False

    assert user.pop('blockType') == 'DEFAULT'

    user = {k: v for k, v in user.items() if v not in [None, [], '']}

    keys = ['id', 'red_id', 'nickname', 'age', 'description', 'homepage',
            'following', 'location', 'ip_location', 'college']
    user1 = {k: user[k] for k in keys if k in user}
    user2 = {k: user[k] for k in user if k not in keys}
    user_sorted = user1 | user2
    assert user_sorted == user

    return user_sorted


def get_user_notes(user_id: str) -> Iterator[dict]:
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
            console.log(
                f"seems reached end at page {page} for {url+api} "
                "since not has_more",
                style='warning')
            break
        assert cursor


def get_note(note_id, parse=True):
    note_id = note_id.removeprefix("https://www.xiaohongshu.com/explore/")
    note_data = {'source_note_id': note_id,
                 'image_scenes': ['CRD_PRV_WEBP', 'CRD_WM_WEBP']}
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
    try:
        return _parse_note(note) if parse else note
    except AssertionError:
        console.log(note['url'], style='error')
        raise


def _parse_note(note: dict) -> dict:
    for key in ['user',  'share_info', 'interact_info']:
        value = note.pop(key)
        assert note | value == value | note
        note |= value
    note.pop('illegal_info', None)

    for k in note:
        if 'count' in k:
            note[k] = int(note[k])

    assert note.pop('un_share') is False
    assert 'id' not in note
    note['id'] = note.pop('note_id')
    assert 'following' not in note
    note['following'] = note.pop('followed')
    if (relation := note.pop('relation')) in ['follows', 'both']:
        assert note['following'] is True
    else:
        assert relation == 'none'
        assert note['following'] is False
    # relation = 'follows' if note['following'] else 'none'
    # assert relation == note.pop('relation')

    for k in ['time', 'last_update_time']:
        note[k] = pendulum.from_timestamp(note[k]/1000, tz='local')

    tags = {(tag['name'], tag['type']) for tag in note.pop('tag_list')}
    tag_types = {'topic', 'topic_page', 'location_page', 'vendor',
                 'buyable_goods', 'goods', 'brand_page', 'brand',
                 'interact_pk', 'interact_vote', 'moment', 'custom'}

    if extra_types := ({t for _, t in tags} - tag_types):
        extra = {(n, t) for n, t in tags if t in extra_types}
        console.log(
            f'{note["url"]} find extra tag types {extra}', style='error')
    assert 'topics' not in note
    note['topics'] = sorted({n for n, t in tags if t in (
        'topic', 'topic_page', 'custom', 'location_page')})

    assert 'at_user' not in note
    at_user_list = []
    for a in note.pop('at_user_list'):
        if a not in at_user_list:
            at_user_list.append(a)
    at_user = {user['nickname']: user['user_id'] for user in at_user_list}
    assert len(at_user) == len(at_user_list)
    note['at_user'] = at_user

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

    if 'video' in note:
        stream = note.pop('video').pop('media').pop('stream')
        # video = media.pop('video')
        # note['video_md5'] = video['md5']
        stream = {k: v for k, v in stream.items() if v}
        key, h264 = stream.popitem()
        assert key in ['h264', 'h265']
        assert not stream
        assert len(h264) == 1
        h264 = h264[0]
        note['video'] = h264['master_url']

    for k in note:
        if isinstance(note[k], str):
            note[k] = note[k].replace('\x0b', ' ').strip()
    note = {k: v for k, v in note.items() if v not in [None, [], '', {}]}

    keys = ['id', 'user_id', 'nickname',   'following', 'title',
            'desc', 'time', 'last_update_time',
            'ip_location', 'at_user', 'topics', 'url',
            'comment_count', 'share_count', 'liked', 'liked_count',
            'collected', 'collected_count', 'type', 'pic_ids', 'pics',
            'video', 'video_md5'
            ]
    note1 = {k: note[k] for k in keys if k in note}
    note2 = {k: note[k] for k in note if k not in keys}
    note_sorted = note1 | note2
    assert note_sorted == note
    return note_sorted
