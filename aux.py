from collections import namedtuple, UserDict, deque

IpPortPair = namedtuple('IpPortPair', 'ip port')
FileMetaData = namedtuple('FileMetaData', 'path length md5 start')

class MsgCache:
    def __init__(self, max=50):
        self._set = dict()
        self._list = deque(maxlen=max)

    def append(self, msg):
        if len(self._set) == self.maxlen and self._list[0] in self._set:
            self._set.remove(self._list[0])
        self._list.append(msg)
        self._set.add(msg)
