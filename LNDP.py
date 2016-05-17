from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor
import os

from aux import MsgCache

MULTICAST_IP = "239.5.10.15"
MULTICAST_PORT = 8691

class LNDPFinder(DatagramProtocol):
    def __init__(self, lndp):
        self._lndp = lndp
        self._torrent = lndp.torrent
        self.state = 'starting'

    def startProtocol(self):
        self.transport.joinGroup(MULTICAST_IP)
        self._tid = os.urandom(4)
        self.re_ask()

    def datagramReceived(self, data, addr):
        if not data.startswith(b'DTOC-LNDP'): return
        if self.state == 'starting':
            if data[9:13] != self._tid or data[13] != 1: return
            self._tid = b'abcd'
            port = struct.unpack_from('>H', data, 14)
            print("HE is downloading same file", addr, port)
            self._lndp.found_peer(addr, port)
        elif self.state == 'listening':
            if data[14] == 0 and data[15:] == self._torrent.info_hash:
                self.transport.write(b'DTOC-LNDP'+data[9:13]+'\x01'+
                                     struct.pack('>H', self._torrent.port))
        else:
            print("Wrong protocol update")

    def re_ask(self, cnt=0):
        if cnt > 3:
            self.state = 'listening'
            print("IN listening mode")
        else:
            print("Sending UDP")
            self.transport.write(b'DTOC-LNDP'+self._tid+b'\x00'+self._torrent.info_hash, (MULTICAST_IP, MULTICAST_PORT))
            reactor.callLater(3, self.re_ask, cnt+1)

    def pause(self):
        pass

    def resume(self):
        pass

class LNDPProtocol:
    def __init__(self, torrent):
        self.torrent = torrent
        self.lndp_finder = LNDPFinder(self)
        self.id = 0
        self.swarm_size = 1
        self.peers = []
        self.msgcache = MsgCache()
        reactor.listenMulticast(MULTICAST_PORT, self.lndp_finder, listenMultiple=True)

    def handle_msg(self, msg, peer_protocol):
        incoming = peer.protocol.type == 1 #1 is for incoming
        msg_id = msg[0]
        if msg_id == 0: #handshake
            if incoming: self._send_handshake()
            else:
                pass
        elif msg_id == 1: #update
            self._handle_update(self, msg)

    def _handle_update(self, msg):
        if len(msg) != 6: return
        msg_uid = msg[1:5]
        if msg_uid in self.msgcache.set: return #already seen
        self.swarm_size = msg[5]
        for p in self.peers: p._send_ltep("dt_lndp", msg)
