import argparse
import logging
from twisted.internet import reactor
from twisted.internet.protocol import Factory
import json
import tempfile
import sys

import PeerProtocol
import Torrent
from HTTPDownloader import HTTPDownloader
import dtoc_bencode

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('torrent', help="Path to .torrent file.")
    parser.add_argument('save_to', default='./', nargs='?',
                        help="Where to save torrent? defaults to current directory")
    parser.add_argument('--name', help="User's name for this torrent.", default=None)
    parser.add_argument('--verbose', help="How much of output to display?",
                        default=1, type=int)
    parser.add_argument('--progress', help="Show only progress bar. Verbose will not have any effect",
                        action="store_true")
    parser.add_argument('--port', help="Port to listen BitTorrent", type=int, default=6891)
    parser.add_argument('--http', help="file containing json list of urls",
                        type=argparse.FileType('r', encoding="utf-8"))
    parser.add_argument('--list_files', help="Only list the files. do not download",
                        action="store_true")
    args = parser.parse_args()

    logging.basicConfig(filename="/tmp/dtoc_log", filemode="w", level=logging.DEBUG)

    if args.progress: args.verbose = -10000
    torrent = Torrent.Torrent(args.torrent, args.save_to, args.name,
                              args.port, args.verbose)

    if args.list_files:
        for f in torrent._open_files:
            f.close()
        for f in torrent.files:
            print(f.path)
        sys.exit(0)

    if args.progress:
        reactor.callLater(2, torrent.progress_printer)
    if args.http:
        json_list = json.load(args.http)
        if len(json_list) != len(torrent.files):
            raise ValueError("Invalid JSON file for --http")
        httpdownloaders = set()
        for i, file_ in enumerate(torrent.files):
            if json_list[i]:
                url = json_list[i][0].encode('utf-8')
                httpdownloaders.add(HTTPDownloader(torrent, i, url))


    factory = PeerProtocol.BTProtocolFactory(torrent)
    reactor.listenTCP(args.port, factory)
    reactor.callLater(1, torrent.start)
    reactor.addSystemEventTrigger('before', 'shutdown', torrent.stop)
    reactor.run()
