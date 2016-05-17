from twisted.web.client import Agent, readBody
from twisted.internet import reactor
from twisted.python import log
from urllib import parse
import io


import dtoc_bencode
from dtoc_exceptions import DTOCFailure

def  get_peers(agent, url, torrent, event=None, numwant=50,trackerid=None):
    def _handle_response(resp):
        d = readBody(resp)
        d.addCallback(dtoc_bencode.bdecode)
        return d

    def _handle_error(failure):
        print(failure)
        return failure

    qs = {'info_hash': torrent.info_hash,
          'peer_id': torrent.peer_id,
          'port': torrent.port,
          'uploaded': torrent.uploaded,
          'downloaded': torrent.downloaded,
          'left': torrent.left,
          'compact': 1,
          'numwant': numwant}
    if event: qs['event'] = event
    if trackerid: qs['trackerid'] = trackerid
    q = parse.urlencode(qs, safe='~')
    url = '?'.join((url, q)).encode('utf-8')
    # print(url)
    d = agent.request(b'GET', url)
    d.addCallbacks(_handle_response, _handle_error)
    return d

class HttpTracker(object):
    def __init__(self, torrent, url):
        self._torrent = torrent
        self.url = url
        self.state = 'init'
        self._tracker_id = None
        self._agent = Agent(reactor)

    def start(self):
        if self.state == 'started':
            return

    def force_reannounce(self):
        self._announce()

    def _response_received(data):
        if b'failure reason' in data:
            self.state = 'error'
            self.error = data[b'failure reason'].decode('utf-8')
            return
        self._interval = data[b'interval']
        self._min_interval = data[b'min interval']

        if b'tracker id' in data:
            self._tracker_id = data[b'tracker id']

        self.complete = data.get(b'complete')
        self.incomplete = data.get(b'incomplete')


    def _error_occured(data):
        self.state = 'error'
        self.error = "HTTP announce failed"
        reactor.callLater(120, self._announce)

    def _announce(self):
        d = get_peers(self._agent, self.url, self._torrent, trackerid = self._tracker_id)
        d.addCallbacks(_response_received, _error_occured)


if __name__ == '__main__':
    a = Agent(reactor)
    def ppr(data):
        print("PPR")
        print(data)

    def dothings():
        t = Stub_Torrent()
        d = get_peers(a, 'http://tracker.glotorrents.com:6969/announce',t, 'started')
        d.addCallbacks(ppr, log.err)
    reactor.callLater(1, dothings)
    reactor.run()
