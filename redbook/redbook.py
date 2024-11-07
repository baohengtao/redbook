import itertools
import re
import time
from copy import deepcopy
from typing import Iterator

import pendulum
from camel_converter import dict_to_snake
from furl import furl

from redbook import console
from redbook.fetcher import fetcher
from redbook.helper import convert_js_dict_to_py, normalize_count


async def get_user(user_id: str, parse: bool = True) -> dict:
    while True:
        url = f"https://www.xiaohongshu.com/user/profile/{user_id}"
        r = await fetcher.get(url)
        try:
            info = re.findall(
                r'<script>window.__INITIAL_STATE__=(.*?)</script>', r.text)[0]
        except Exception:
            console.log(f'find failed: {r.text}', style='error')
            raise
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

    user['collection_public'] = user.pop('tabPublic')['collection']

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


async def get_user_notes(user_id: str) -> Iterator[dict]:
    cursor = ''
    for page in itertools.count(start=1):
        console.log(f'fetching page {page}...')
        api = ("/api/sns/web/v1/user_posted?num=30&image_formats=jpg,webp,avif"
               f"&cursor={cursor}&user_id={user_id}")
        url = 'https://edith.xiaohongshu.com'
        js = (await fetcher.get(url=url, api=api)).json()
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


async def get_note_from_web(note_id, params: str = '', parse=True):
    note_id = note_id.removeprefix("https://www.xiaohongshu.com/explore/")
    r = await fetcher.get(f'https://www.xiaohongshu.com/explore/{note_id}{params}')
    info = re.findall(
        r'<script>window.__INITIAL_STATE__=(.*?)</script>', r.text)[0]
    note = convert_js_dict_to_py(info)['note']['noteDetailMap']
    k, v = note.popitem()
    assert not note
    note = v.pop('note')
    note = dict_to_snake(note)
    note['url'] = f'https://www.xiaohongshu.com/explore/{note_id}'
    try:
        return parse_note(note) if parse else note
    except AssertionError:
        console.log(note['url'], style='error')
        raise


async def get_note_short_url(note_id: str) -> dict:
    data = {
        "original_url": f"https://www.xiaohongshu.com/discovery/item/{note_id}"
    }
    r = await fetcher.post(
        'https://edith.xiaohongshu.com', '/api/sns/web/short_url', data=data)
    short_url: str = r.json()['data']['short_url']
    assert short_url.startswith('xhslink.com')
    return f'https://{short_url}'


async def get_note(note_id, xsec_token=None, parse=True):
    if note_id.startswith('https://www.xiaohongshu.com/explore/'):
        url = furl(note_id)
        note_id = url.path.segments[-1]
        xsec_token = url.args.get('xsec_token')
    assert xsec_token
    note_data = {'source_note_id': note_id,
                 'image_formats': ['jpg', 'webp', 'avif'],
                 'extra': {'need_body_topic': 1},
                 'xsec_token': xsec_token
                 }
    for _ in range(3):
        r = await fetcher.post('https://edith.xiaohongshu.com',
                               '/api/sns/web/v1/feed', note_data)
        js = r.json()
        data = js.pop('data')
        if js == {'code': 0, 'success': True, 'msg': '成功'}:
            break
        console.log(f'fetch failed: {js}, retrying...', style='error')
    else:
        raise ValueError(js)
    items = data.pop('items')
    assert len(items) == 1
    item = items[0]
    note = item.pop('note_card')
    assert 'url' not in note
    assert 'xsec_token' not in note
    note['url'] = f'https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec_token}'
    note['xsec_token'] = xsec_token
    assert item == {'id': note_id, 'model_type': 'note'}
    try:
        return parse_note(note) if parse else note
    except AssertionError:
        console.log(note['url'], style='error')
        raise


def parse_video_url(url):
    url = furl(url)
    if url.query:
        assert url.host == 'sns-video-qc.xhscdn.com'
        url.query = None
    url.host = 'sns-video-bd.xhscdn.com'
    return str(url)


def parse_note(note):
    note = deepcopy(note)
    for key in ['user',  'share_info', 'interact_info']:
        value = note.pop(key)
        assert note | value == value | note
        note |= value
    note.pop('illegal_info', None)

    for k in note:
        if 'count' in k:
            note[k] = normalize_count(note[k])

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

    pics, pic_ids = [], []
    for image in note.pop('image_list'):
        image = {k: v for k, v in image.items() if (v is False or v) and k not in [
            'height', 'width']}
        info_list = image.pop('info_list')
        assert all(len(i) == 2 for i in info_list)
        info_list = {i['image_scene']: i['url'] for i in info_list}
        assert (pic := image.pop('url_default')) == info_list.pop('WB_DFT')
        assert (pic_pre := image.pop('url_pre')) == info_list.pop('WB_PRV')
        assert not info_list
        pic_id = pic.split('/')[-1].split('!')[0]
        pic_id_pre = pic_pre.split('/')[-1].split('!')[0]
        assert pic_id == pic_id_pre
        pic = f'http://sns-img-hw.xhscdn.com/{pic_id}?imageView2/2/w/100000/format/jpg'
        if image.pop('live_photo') is True:
            stream = {k: v for k, v in image.pop('stream').items() if v}
            assert len(stream) == 1
            video_url = stream.pop('h264')[0]['master_url']
            pic += ' ' + parse_video_url(video_url)
        assert not image
        pic_ids.append(pic_id)
        pics.append(pic)
    assert 'pics' not in note
    note['pics'] = pics
    note['pic_ids'] = pic_ids

    if 'video' in note:
        stream = note.pop('video').pop('media').pop('stream')
        stream = {k: v for k, v in stream.items() if v}
        x = stream.pop('h264', None)
        h264 = stream.pop('h265', None) or x
        assert not stream
        assert len(h264) == 1
        note['video'] = parse_video_url(h264[0]['master_url'])

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
