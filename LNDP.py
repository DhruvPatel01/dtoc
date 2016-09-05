from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor
import os
import struct
import math

from aux import MsgCache
import PeerProtocol

MULTICAST_IP = "239.5.10.15"
MULTICAST_PORT = 8691
MC_ADDR = (MULTICAST_IP, MULTICAST_PORT)

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
            self._timer.cancel()
            self.state = 'listening'
            self._lndp.found_peer(addr, port)
        elif self.state == 'listening':
            if data[13] == 0 and data[14:] == self._torrent.info_hash:
                self.transport.write(b'DTOC-LNDP'+data[9:13]+b'\x01'+
                                     struct.pack('>H', self._torrent.port), MC_ADDR)
        else:
            print("Wrong protocol update")

    def re_ask(self, cnt=0):
        if self.state == 'listening': return
        elif cnt > 1:
            self.state = 'listening'
            print("\nIN listening mode")
        else:
            self.transport.write(b'DTOC-LNDP'+self._tid+b'\x00'+self._torrent.info_hash, (MULTICAST_IP, MULTICAST_PORT))
            self._timer = reactor.callLater(3, self.re_ask, cnt+1)

    def _change_state(self, ignored):
        self.state = 'stopped'

    def stop(self):
        d = self.transport.stopListening()
        d.addCallback(self._change_state)

class LNDPProtocol:
    def __init__(self, torrent):
        self.torrent = torrent
        self.id = 0
        self.swarm_size = 1
        self.peers = [None, None] # [0] left, [1] right
        self.msgcache = MsgCache()
        self.client_factory = PeerProtocol.BTClientFactory(torrent, True)
        self.lndp_finder = LNDPFinder(self)
        reactor.listenMulticast(MULTICAST_PORT, self.lndp_finder, listenMultiple=True)

    def handle(self, msg, peer_protocol):
        """Handle a lndp message. to be called by PeerProtocol"""
        msg_id = msg[0]
        if msg_id == 0:
            self._handle_handshake(msg, peer_protocol)
        elif msg_id == 1: #update
            print(msg, len(msg))
            self._handle_update(msg)

    def send_handshake(self, peer_protocol):
        """
        handshake should be done if connection is
        incoming and peer has said he supports
        dt_lndp inside ltep.
        """
        msg = struct.pack('>BI', 0, self.swarm_size)
        self.swarm_size += 1
        peer_protocol.send_ltep('dt_lndp', msg)
        self.peers[1] = peer_protocol
        self.lndp_finder.stop()
        updt_msg = struct.pack('>B4sI', 1, os.urandom(4), self.swarm_size)
        self._handle_update(updt_msg)

    def _handle_handshake(self, msg, peer_protocol):
        msg_id, size = struct.unpack('>BI', msg)
        self.id = size
        self.swarm_size = size + 1
        self.peers[0] = peer_protocol
        self._update_queues()

    def _handle_update(self, msg):
        msg_uid = msg[1:5]
        if msg_uid in self.msgcache.set: return #already seen
        self.swarm_size, *_ = struct.unpack_from('>I', msg, 5)
        if self.peers[0]: self.peers[0].send_ltep("dt_lndp", msg)
        self._update_queues()

    def found_peer(self, addr, port):
        reactor.connectTCP(addr[0], port[0], self.client_factory)

    def _update_queues(self):
        self.torrent.queue[1].update(self.torrent.queue[0])
        self.torrent.queue[0] = set()
        ub = math.ceil((len(self.torrent.pieces) - self.id)/self.swarm_size)
        for i in range(ub):
            piece_no = self.swarm_size*i + self.id
            self.torrent.queue[0].add(piece_no)
            for q in self.torrent.queue[1:-1]:
                if piece_no in q: q.remove(piece_no)
