import struct
from twisted.internet.protocol import Protocol, Factory, ClientFactory
from twisted.internet import reactor
import bitarray
from enum import Enum
import logging

REQUEST_PIECE_SIZE = 0X4000

class BTProtocolStates(Enum):
    handshake_sent = 1
    connected = 2

class BTClientFactory(ClientFactory):
    def __init__(self, torrent):
        self.torrent = torrent

    def buildProtocol(self, addr):
        p = BTProtocol(self.torrent)
        p.addr = addr
        p.type = 0 #outgoing
        return p

    def clientConnectionFailed(self, connector, reason):
        # if self.torrent.verbose > 10: print(self.torrent.name, "Lost Failed")
        d = connector.getDestination()
        addr = (d.host, d.port)
        if addr in self.torrent.peers:
            self.torrent.peers.remove(addr)

    def clientConnectionLost(self, connector, reason):
        if self.torrent.verbose > 10: print(self.torrent.name, "Lost connection", reason)


class BTProtocolFactory(Factory):
    def __init__(self, torrent):
        self.torrent = torrent

    def buildProtocol(self, addr):
        p = BTProtocol(self.torrent)
        p.addr = addr
        p.type = 1 #incoming
        return p

class BTProtocol(Protocol):
    def __init__(self, torrent):
        self._torrent = torrent
        self._buffer_piece = b''
        self._buffer_block = b''
        self._buffer_msg = b''
        self._current_index = None #cached block
        self._current_request = None
        self._currently_downloading_block = None #the block we are currently downloading
        self.am_choking = True
        self.am_ineterested = False
        self.peer_choking = True
        self.peer_interested = False
        self.peer_bitfield = set()
        self.state = None
        self.type = None #incoming:0 or outgoing:1 set by factory

    def connectionMade(self):
        self._send_handshake()
        self._torrent.current_protocols.add(self)
        logging.info("Connection made with %s"%self.addr)

    def connectionLost(self, reason):
        self._torrent.current_protocols.remove(self)
        logging.warn("Connection lost with %s"%self.addr)

    def dataReceived(self, data):
        self._buffer_msg += data
        while True:
            if self.state == BTProtocolStates.connected:
                if len(self._buffer_msg) < 4:
                    break
                l, *_ = struct.unpack_from('>I', self._buffer_msg)
                if len(self._buffer_msg) < 4+l: break
                msg = self._buffer_msg[4:4+l]
                self._buffer_msg = self._buffer_msg[4+l:]
                self._call_msg_handler(msg)
            elif self.state == BTProtocolStates.handshake_sent:
                if len(self._buffer_msg) < 68:
                    break
                if not self._buffer_msg.startswith(b'\x13BitTorrent protocol'):
                    self.transport.loseConnection()
                    break
                msg = self._buffer_msg[:68]
                self._buffer_msg = self._buffer_msg[68:]
                self._handle_handshake(msg)

    def do_download(self, index=None):
        if self.peer_choking == True: return
        if index is None or index < 0 or index >= len(self._torrent.pieces):
            index = self._torrent.give_me_order(self.peer_bitfield)
        if index is None:
            return
        target_piece_size = self._torrent.length_of_piece(index)
        offset = 0
        length = min(REQUEST_PIECE_SIZE, target_piece_size)
        self._currently_downloading_block = index
        self._send_request(index, offset, length)

    def _send_handshake(self):
        reserved = bytearray(b'\x00'*8)
        # reserved[5] |= 0x10
        self.transport.write(b'\x13BitTorrent protocol')
        self.transport.write(reserved)
        self.transport.write(self._torrent.info_hash)
        self.transport.write(self._torrent.peer_id)
        self.state = BTProtocolStates.handshake_sent

    def _handle_handshake(self, packet):
        """Assume packet is valid"""
        if packet[28:48] != self._torrent.info_hash:
            self.transport.loseConnection()
            return
        # if packet[25] & 0x10:
        #     self._send_ltep_handshake()
        self.peer_id = packet[48:68] #self.peer_id is his peer id, self._torrent.peer_id is ours
        if self.peer_id == self._torrent.peer_id:
            self.transport.loseConnection()
            return
        self.state = BTProtocolStates.connected
        self._send_bitfield()
        self._send_intereseted()

    id_to_method = {
        -1: '_handle_keep_alive',
        0 : '_handle_choke',
        1 : '_handle_unchoke',
        2 : '_handle_interested',
        3 : '_handle_not_ineteresetd',
        4 : '_handle_have',
        5 : '_handle_bitfield',
        6 : '_handle_request',
        7 : '_handle_piece',
        8 : '_handle_cancle',
        20: '_handle_ltep'
    }

    def _call_msg_handler(self, msg):
        msg_id = struct.unpack_from('>B', msg)[0] if msg else -1
        payload = msg[1:] if msg else None
        getattr(self, self.id_to_method[msg_id])(payload)

    def _send_keep_alive(self):
        self.transport.write(b'\x00\x00\x00\x00')

    def _send_choke(self):
        self.transport.write(b'\x00\x00\x00\x01\x00')

    def _send_unchoke(self):
        self.transport.write(b'\x00\x00\x00\x01\x01')

    def _send_intereseted(self):
        self.transport.write(b'\x00\x00\x00\x01\x02')

    def _send_not_interested(self):
        self.transport.write(b'\x00\x00\x00\x01\x03')

    def _send_have(self, index):
        self.transport.write(b'\x00\x00\x00\x05\x04')
        self.transport.write(struct.pack('>I', index))

    def _send_bitfield(self):
        bytes_ = self._torrent.bitfield.tobytes()
        self.transport.write(struct.pack('>I', len(bytes_)+1))
        self.transport.write(b'\x05')
        self.transport.write(bytes_)

    def _send_request(self, index, begin, length=REQUEST_PIECE_SIZE):
        self.transport.write(b'\x00\x00\x00\x0D\x06')
        self.transport.write(struct.pack('>III', index, begin, length))
        self._current_request = (index, begin, length)

    def _handle_keep_alive(self, payload=None):
        pass

    def _handle_choke(self, payload=None):
        self.peer_choking = True

    def _handle_unchoke(self, payload=None):
        self.peer_choking = False
        self.do_download()

    def _handle_interested(self, payload=None):
        self.peer_interested = True

    def _handle_not_ineteresetd(self, payload=None):
        self.peer_interested = False

    def _handle_have(self, payload):
        b = struct.unpack('>I', payload)
        self.peer_bitfield.add(b[0])

    def _handle_bitfield(self, payload):
        ba = bitarray.bitarray(endian="big")
        ba.frombytes(payload)
        self.peer_bitfield = set(i for i, e in enumerate(ba) if e)
        self.do_download()

    def _handle_request(self, payload):
        index, begin, length = struct.unpack('>III', payload)
        if (
                self.am_choking or
                length > REQUEST_PIECE_SIZE or
                length <= 0 or
                begin >= self._torrent.piece_length
        ):
            return
        if self._current_index != index:
            self._current_piece = self._torrent.read_piece(index)
            self._current_index = index
        self.transport.write(self._current_piece[begin:begin+length])

    def _handle_piece(self, payload):
        index, begin = struct.unpack_from('>II', payload)
        if self._current_request != (index, begin, len(payload)-8):
            self._send_request(*self._current_request)

        target_piece_size = self._torrent.length_of_piece(self._currently_downloading_block)
        self._buffer_piece += payload[8:]
        if len(self._buffer_piece) != target_piece_size:
            nr = self._currently_downloading_block
            offset = len(self._buffer_piece)
            length = min(REQUEST_PIECE_SIZE, target_piece_size - offset)
            self._send_request(nr, offset, length)
        elif self._torrent.write_piece(self._currently_downloading_block, self._buffer_piece):
            logging.info("Successfully downloaded picece no %d"%index)
            self._buffer_piece = b''
            for protocol in self._torrent.current_protocols:
                protocol._send_have(index)
            self.do_download()
        else:
            self._buffer_piece = b''
            print("Block download failed")
            #TODO: RESTART DOWNLOADING THIS BLOCK AGAIN

    def _handle_ltep(self, payload=None):
        if payload[0] == 0:
            self._handle_ltep_handshake(payload[1:])
        if payload[0] == 1:
            self.lndp.handle(payload)

    def _send_ltep_handshake(self):
        #msg = {'m':{'dt_lndp': 1}}
        msg = b'd1:md7:dt_lndpi1eee'
        self._send_ltep(0, msg)

    def _send_ltep(self, msg_protocol, payload):
        msg_id = self.peer_ltep.get(msg_protocol, -1)
        if msg_id == -1:
            raise("No support for ltep")
        self.transport.write(struct.pack('>I', len(payload)+2))
        self.transport.write(0x14)
        self.transport.write(msg_id)
        self.transport.write(payload)

    def _handle_ltep_handshake(self, msg):
        msg = dtoc_bencode.bdecode(msg)
        self.peer_ltep = {k:int(v) for k,v in msg[b'm']}
        print(self.peer_ltep)
        input()

    def _handle_invalid(self, payload=None):
        if (self.torrent.verbose > 10):
            print(self.torrent.name, "Invalid packet. Losing conneciton")
        self.transport.loseConnection()
