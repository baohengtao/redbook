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

    assert 'followed' not in user
    if (fstatus := user.pop('fstatus')) == 'follows':
        user['followed'] = True
    else:
        assert fstatus == 'none'
        user['followed'] = False

    tab_public = user.pop('tabPublic')
    collection_public = tab_public.pop('collection')
    assert not tab_public
    user['collection_public'] = collection_public

    user = {k: v for k, v in user.items() if v not in [None, [], '']}

    keys = ['id', 'red_id', 'nickname', 'age', 'description', 'homepage',
            'followed', 'location', 'ip_location', 'college']
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

    tag_list = []
    for t in note.pop('tag_list'):
        if t not in tag_list:
            tag_list.append(t)
    tags = {t['name']: t['type'] for t in tag_list}
    assert len(tags) == len(tag_list)
    tag_types = {'topic', 'topic_page', 'location_page', 'vendor',
                 'buyable_goods', 'goods', 'brand_page', 'brand',
                 'interact_pk', 'interact_vote', 'moment', 'custom'}
    if extra_types := (set(tags.values()) - tag_types):
        extra = {k: v for k, v in tags.items() if v in extra_types}
        console.log(
            f'{note["url"]} find extra tag types {extra}', style='error')
    assert 'topics' not in note
    note['topics'] = [k for k, v in tags.items() if v in (
        'topic', 'topic_page', 'custom')]

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
            note[k] = note[k].strip()
    note = {k: v for k, v in note.items() if v not in [None, [], '', {}]}

    keys = ['id', 'user_id', 'nickname',   'followed', 'title',
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


def search_user(query: str) -> Iterator[dict]:
    end_js = {
        'msg': '方案执行结果为NULL',
        'data': {'has_more': False,
                 'result': {'code': 3002,
                            'message': '方案执行结果为NULL',
                            'success': True},
                 'users': []},
        'code': 3002,
        'success': True}
    post_data = {
        "search_user_request": {
            "page_size": 15,
            "biz_type": "web_search_user",
            "request_id": "1670737538-1700066036681",
            "search_id": "2cggv3l10n0gzxfuj5rl7",
            "keyword":  query
        }
    }
    for page in itertools.count(start=1):
        console.log(f'fetching page {page}')
        post_data['search_user_request']['page'] = page
        url = "https://edith.xiaohongshu.com"
        api = '/api/sns/web/v1/search/usersearch'
        js = fetcher.post(url, api, post_data).json()
        if js == end_js:
            if page == 1:
                yield {'red_id': 'failed',
                       'red_official_verified': False,
                       'is_self': False,
                       'vshow': 0,
                       'followed': False,
                       'red_official_verify_type': 0,
                       'show_red_official_verify_icon': False,
                       'fans': 0,
                       'note_count': 0,
                       'nickname': query,
                       'avatar': 'failed',
                       'homepage': 'failed',
                       'query': query,
                       'query_url': f'https://www.xiaohongshu.com/search_result?keyword={query}',
                       'user_id': 'failed'}

            return
        data = js.pop('data')
        assert js == {'code': 1000, 'success': True, 'msg': '成功'}
        assert data.pop('result') == {'code': 1000,
                                      'success': True, 'message': '成功'}
        assert data.pop('has_more') in [False, True]
        users = data.pop('users')
        assert not data
        for user in users:
            assert 'nickname' not in user
            user['nickname'] = user.pop('name')
            assert 'avatar' not in user
            user['avatar'] = user.pop('image').split('?')[0]
            assert 'homepage' not in user
            user['homepage'] = ('https://www.xiaohongshu.com'
                                f'/user/profile/{user["id"]}')
            assert 'query' not in user
            user['query'] = query
            assert 'query_url' not in user
            user['query_url'] = ('https://www.xiaohongshu.com/'
                                 f'search_result?keyword={query}')

            try:
                fans = user['fans']
            except KeyError:
                user['fans'] = 0
            else:
                if fans.endswith('万'):
                    fans = float(fans.removesuffix('万')) * 10000
                user['fans'] = int(fans)
                assert user['fans'] > 0

            assert user['red_id'] == user.pop(
                'sub_title').removeprefix('小红书号：')
            assert user['id'] == user.pop(
                'link').removeprefix('xhsdiscover://1/user/user.')

            assert 'user_id' not in user
            user['user_id'] = user.pop('id')

            yield user
