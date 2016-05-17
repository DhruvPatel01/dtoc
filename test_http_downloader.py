from twisted.internet import reactor
import logging

import Torrent
import HTTPDownloader


url = b'http://localhost/~dhruv/file/Harry%20Potter%20and%20the%20Deathly%20Hallows%20-%20Part%201%202010%201080p%20BluRay%20x264%20AAC%20-%20Ozlem/Harry%20Potter%20and%20the%20Deathly%20Hallows%20-%20Part%201%202010%201080p%20bluRay%20x264%20AAC%20-%20Ozlem.mp4'

url2 = b'http://localhost/~dhruv/file/Harry%20Potter%20and%20the%20Deathly%20Hallows%20-%20Part%201%202010%201080p%20BluRay%20x264%20AAC%20-%20Ozlem/Subs.rar'

url3 = b'http://localhost/~dhruv/file/Harry%20Potter%20and%20the%20Deathly%20Hallows%20-%20Part%201%202010%201080p%20BluRay%20x264%20AAC%20-%20Ozlem/Ozlem.png'

logging.basicConfig(level=logging.DEBUG)

def run():
    t = Torrent.Torrent('test/test.torrent', '/tmp')
    #t.progress_printer()
    h = HTTPDownloader.HTTPDownloader(t, 1, url2)
    reactor.addSystemEventTrigger('before', 'shutdown', t.stop)
    
reactor.callLater(1, run)
reactor.run()
