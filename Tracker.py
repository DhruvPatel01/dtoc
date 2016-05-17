import struct
import os
import enum
import socket
from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor, defer
from twisted.python import log

from aux import IpPortPair
from dtoc_exceptions import DTOCFailure


def _parse_connect_packet(data):
    if len(data) != 16: #we have an error
        raise DTOCFailure('invalid input packet')
    return struct.unpack('>i4s8s', data)

def _parse_announce_packet(data):
    if len(data) < 20:
        raise DTOCFailure('invalid input packet')

    unpacked = struct.unpack_from('>i4siii', data)

    no_of_ip_port = (len(data)-20)//6
    raw_ips = struct.unpack_from(">" + "4sH"*no_of_ip_port, data, 20)
    ip_ports = set(IpPortPair(socket.inet_ntoa(raw_ips[2*i]), raw_ips[2*i+1])
                            for i in range(no_of_ip_port))
    return (*unpacked, ip_ports)

def _parse_error_packet(data):
    if len(data) < 8:
        raise DTOCFailure('invalid input packet')
    return struct.unpack('>i4s%ds' % (len(data)-8), data)

def _parse_scrap_packet(data):
    pass

_pack_fmt = [
    struct.Struct(">8si4s"),
    struct.Struct(">8si4s20s20sqqqiIIiHH")
]

def _pack_connect_data(args):
    return _pack_fmt[0].pack(args['connection_id'], 0, args['transaction_id'])

def _pack_announce_data(args):
    return _pack_fmt[1].pack(args["connection_id"], 1,
                             args["transaction_id"],
                             args["info_hash"], args["peer_id"],
                             args["downloaded"], args["left"],
                             args["uploaded"], args["event"],
                             args.get("ip", 0), args["key"],
                             args.get("num_want", -1), args["port"],
                             args.get("extensions", 0))

def _pack_scrap_data(args):
    return struct.pack(">qii"+"20b"*len(args['info_hashes']),
                        args['connection_id'], 2, args['transaction_id'],
                        *args['info_hashes'])

def _pack_data(kwargs):
    return [_pack_connect_data,
            _pack_announce_data,
            _pack_scrap_data][kwargs['action']](kwargs)

def _parse_packet(data):
    if len(data) < 8:
        raise DTOCFailure('invalid input packet')
    action = data[3] #last byte of first int32_t
    return [_parse_connect_packet,
            _parse_announce_packet,
            _parse_scrap_packet,
            _parse_error_packet][action](data)


class TimeOutException(Exception):
    pass

class Messenger(DatagramProtocol):
    def __init__(self, host, port):
        self._address = (host, port)
        self._transaction_id = None
        self._pkt = None
        self._defer = None

    def datagramReceived(self, data, address):
        pkt = _parse_packet(data)
        action = pkt[0]
        if pkt[1] != self._transaction_id: return
        self._transaction_id = None
        self._pkt = None
        if self._timer is not None:
            self._timer.cancel()
        if self._defer is not None:
            d = self._defer
            self._defer = None
            d.callback(pkt)

    def send_packet(self, **kwargs):
        if self._defer is not None:
            self._defer.errback(Exception("Previous call failed due to new call"))
        self._transaction_id = os.urandom(4)
        kwargs['transaction_id'] = self._transaction_id
        self._pkt = _pack_data(kwargs)
        self._defer = defer.Deferred()
        self._resend(n = 0)
        return self._defer

    def _resend(self, n = 0):
        if self._pkt is None: return
        if self._defer is None: return
        if n == 4:
            d = self._defer
            self._defer = None
            self._transaction_id = None
            d.errback(TimeOutException())
        else:
            self.transport.write(self._pkt, self._address)
            self._timer = reactor.callLater(15, self._resend, n+1)


class UDPTracker:
    def __init__(self, torrent, url, verbose=None):
        self._torrent = torrent
        self._verbose = verbose
        self.status = "Connecting..."
        self._connection_id = None
        self._msngr = None
        self.seeders = -1 #negative means not connected yet
        self.leechers = -1
        if not url.startswith('udp://'):
            raise ValueError("URL should be udp")
        else:
            u, p = url.split('/')[2].split(':')
            if self._verbose > 10: print("Trying to resolve ip for %s"%u)
            self._url  = url
            self._port = int(p)
            reactor.resolve(u).addCallbacks(self._ip_resolved, self._ip_failed)

    def _ip_resolved(self, ip):
        self._ip = ip
        if (self._verbose > 10): print("IP resolved for %s" % self._url)
        self._msngr = Messenger(self._ip, self._port)
        p = reactor.listenUDP(0, self._msngr)
        self._start()

    def _ip_failed(self, err):
        if (self._verbose > 10): print("IP resolved failed %s" % self._url)
        self.status = "IP resolve failed"

    def _got_connection_id(self, pkt):
        if pkt[0] != 0: return
        self._connection_id = pkt[2]
        reactor.callLater(180, self._do_expire_connection_id)
        return pkt[2]

    def _do_expire_connection_id(self):
        self._connection_id = None

    def _timeout_handler(self, err):
        if self._verbose > 10: print("Server Not Responding: %s"% self._url)
        self.status = "Server not responding"

    def _get_connection_id(self):
        d = self._msngr.send_packet(
                connection_id= b"\x00\x00\x04\x17'\x10\x19\x80",
                action= 0
        )
        d.addCallbacks(self._got_connection_id, self._timeout_handler)
        return d

    def _send_event(self, funct, event = 0):
        if not self._msngr: return
        if self.status == 'Server not responding':
            return
        if self._connection_id is None:
            d = self._get_connection_id()
            d.addCallbacks(funct, self._timeout_handler)
            return
        d = self._msngr.send_packet(
            connection_id=self._connection_id, action=1, event=event,
            info_hash=self._torrent.info_hash,
            peer_id=self._torrent.peer_id,
            downloaded=self._torrent.downloaded_session,
            left=self._torrent.size - self._torrent.downloaded,
            uploaded=self._torrent.uploaded_session,
            key=self._torrent.key, port=self._torrent.port
        )
        d.addCallbacks(self._handle_response, log.err)

    def _start(self, *args):
        if self._verbose > 10: print("Sending start packet :%s"%self._url)
        self._send_event(self._start, 2)

    def _reannounce(self, *args):
        if self._verbose > 10: print("Sending reannounce packet :%s"%self._url)
        self._send_event(self._reannounce, 0)

    def stop(self, *args):
        if self._verbose > 10: print("Sending Stop packet :%s"%self._url)
        self._send_event(self.stop, 3)

    def complete(self, *args):
        self._send_event(self._complete, 1)

    def _handle_response(self, pkt):
        if pkt[0] == 3:
            self.status = pkt[2].decode('utf-8')
        elif pkt[0] == 1:
            self.leechers = pkt[3]
            self.seeders = pkt[4]
            if pkt[5]: self._torrent.peer_list_update(pkt[5])
            reactor.callLater(int(pkt[2]), self._reannounce)
