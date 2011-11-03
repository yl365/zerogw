import json

from .service import BaseService

import logging
log = logging.getLogger(__name__)


class Service(BaseService):
    _method_prefix = 'chat.'

    def configure(self, loop):
        super().configure(loop)
        self._redis = loop.get('redis')
        self._output = loop.get('output')

    def join_by_name(self, usr, room):
        id = self._redis.execute(b'HGET', b'rooms', room)
        if id is None:
            id = self._create_room(room, usr)
        else:
            id = int(id)
        self._join(usr, id)

    def join_by_ids(self, usr, ids):
        for i in ids:
            self._join(usr, ids)

    def _join(self, usr, id):
        username, mood, rname, rtopic = self._redis.bulk((
            (b'GET', 'user:{0}:name'.format(usr.uid)),
            (b'GET', 'user:{0}:mood'.format(usr.uid)),
            (b'GET', 'room:{0}:name'.format(id)),
            (b'GET', 'room:{0}:topic'.format(id)),
            ))
        if not username:
            log.warning("Wrong user trying to join room")
            return
        if not rname:
            log.warning("Wrong room id is being joined")
            return
        username = username.decode('utf-8')
        rname = rname.decode('utf-8')
        rchannel = 'room:{0}'.format(id)
        self._output.subscribe(usr, rchannel)
        room_history = 'room:{0}:history'.format(id)
        _, ul, _, _, _, hist = self._redis.bulk((
            (b"SADD", 'room:{0}:users'.format(id), str(usr.uid)),
            (b"SORT", 'room:{0}:users'.format(id), b'BY', b'nosort',
                b'GET', b'#', b'GET', b'user:*:name', b'GET', b'user:*:mood'),
            (b"SADD", 'user:{0}:rooms'.format(usr.uid), str(id)),
            (b"RPUSH", room_history, json.dumps(
                {"kind": "join", "author": username, "uid": usr.uid})),
            (b"LTRIM", room_history, b'-100', b'-1'),
            (b"LRANGE", room_history, b'0', b'-1'),
            ))
        uit = iter(ul)
        self._output.send(usr, ['chat.room', {
            'ident': id,
            'name': rname,
            'topic': rtopic.decode('utf-8'),
            'users': [{'ident': int(uid), 'name': name.decode('utf-8'),
                       'mood': mood.decode('utf-8')}
                      for uid, name, mood in zip(uit, uit, uit)],
            'history': [json.loads(m.decode('utf-8')) for m in hist],
            }])
        self._output.publish(rchannel, ['chat.joined', id, {
            'ident': usr.uid,
            'name': username,
            'mood': mood.decode('utf-8'),
            }])

    def _create_room(self, room, usr):
        rid = int(self._redis.execute(b'INCR', b'next:room_id'))
        self._redis.bulk((
            (b'MSET',
                'room:{0}:name'.format(rid), room,
                'room:{0}:topic'.format(rid), 'Discussing '+room,
                ),
            (b'SADD', 'room:{0}:moderators'.format(rid), str(usr.uid)),
            (b'HSET', b'rooms', room, str(rid)),
            ))
        return rid

    def message(self, usr, room, txt):
        username, ismem = self._redis.bulk((
            (b'GET', 'user:{0}:name'.format(usr.uid)),
            (b'SISMEMBER', 'user:{0}:rooms'.format(usr.uid), str(room)),
            ))
        if not ismem:
            log.warning("Trying to write in non-subscribed room")
            return
        username = username.decode('utf-8')
        room_history = 'room:{0}:history'.format(room)
        self._redis.bulk((
            (b"RPUSH", room_history, json.dumps(
                {"text": txt, "author": username, "uid": usr.uid})),
            (b"LTRIM", room_history, b'-100', b'-1'),
            ))
        self._output.publish('room:{0}'.format(room), ['chat.message', room, {
            'author': username,
            'uid': usr.uid,
            'text': txt,
            }])

