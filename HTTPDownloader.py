import struct
from twisted.internet.protocol import Protocol, Factory, ClientFactory
from twisted.web.client import Agent, HTTPConnectionPool
from twisted.internet.defer import Deferred
from twisted.web.http_headers import Headers
from twisted.internet import reactor
import logging
import bitarray
from pprint import pformat
import math
from enum import Enum


agent = Agent(reactor, pool=HTTPConnectionPool(reactor))

class HTTPDataDownloader(Protocol):
    def __init__(self, p, finished):
        self.p = p
        self.finished = finished
        self.buffer = b''
        self.expected = p.currently_downloading[1]

    def dataReceived(self, data):
        self.buffer += data
        self.expected -= len(data)
        if self.expected <= 0:
            cd = self.p.currently_downloading
            if cd[0] == self.p.first:
                f = self.p.torrent._open_files[self.p.findex]
                f.seek(0)
                f.write(self.buffer)
                self.finished.callback(True)
            elif cd[0] == self.p.last:
                f = self.p.torrent._open_files[self.p.findex]
                f.seek(cd[2])
                f.write(self.buffer)
                self.finished.callback(True)
            else:
                if self.p.torrent.write_piece(cd[0], self.buffer):
                    self.finished.callback(True)
                else:
                    print("Failed")
                    print(cd)
class HTTPDownloader:
    def __init__(self, torrent, findex, url):
        self.torrent = torrent
        self.findex = findex
        self.url = url
        self.finfo = torrent.files[findex]
        self.session_downloaded = 0
        self.first = self.finfo.start // torrent.piece_length #first piece
        self.last = (self.finfo.start + self.finfo.length - 1)//torrent.piece_length #end piece
        to_download = None
        first_piece_data = (self.first+1)*torrent.piece_length - self.finfo.start
        if not torrent.bitfield[self.first]:
            to_download = self.first
            if self.first == self.last: expected = self.finfo.length
            else: expected = first_piece_data
            offset = 0
        else:
            offset = first_piece_data
            for i in range(self.first+1, self.last+1):
                if not torrent.bitfield[i]:
                    to_download = i
                    expected = torrent.length_of_piece(i)
                    break
                offset += torrent.length_of_piece(i)
        if to_download is None:
            logging.info("Already complete file. %s", self.finfo)
            return

        self.currently_downloading = (to_download, expected, offset)
        self._do_download()

    def _resp_received(self, response):
        logging.debug('Response version: %s', response.version)
        logging.debug('Response code: %s', response.code)
        logging.debug('Response phrase: %s', response.phrase)
        logging.debug('Response headers:')
        logging.debug(pformat(list(response.headers.getAllRawHeaders())))
        f = Deferred()
        response.deliverBody(HTTPDataDownloader(self, f))
        f.addCallback(self._downloader_caller)
        f.addErrback(logging.error)

    def _downloader_caller(self, data):
        cd = self.currently_downloading
        to_download = None
        self.session_downloaded += cd[1]
        offset = cd[2] + cd[1]
        for i in range(cd[0]+1, self.last+1):
            if not self.torrent.bitfield[i]:
                to_download = i
                expected = self.torrent.length_of_piece(i)
                break
            offset += self.torrent.length_of_piece(i)
        if to_download is None:
            logging.debug("Downloaded in session %d", self.session_downloaded)
            return
        if to_download == self.last:
            expected = self.finfo.length - offset
        else:
            expected = self.torrent.length_of_piece(to_download)
        self.currently_downloading = (to_download, expected, offset)
        reactor.callLater(1, self._do_download)

    def _do_download(self):
        cd = self.currently_downloading
        h = Headers({b'range': [b'bytes=%d-%d'%(cd[2], cd[2]+cd[1]-1)]})
        d = agent.request(b'GET', self.url, h, None)
        logging.info("Requested for %s", h)
        d.addCallback(self._resp_received)
        d.addErrback(logging.error)
