# coding: utf-8
import PeerProtocol
import Torrent
th = Torrent.Torrent('test.torrent')
p1 = PeerProtocol.BTProtocol(th)
p1.state = PeerProtocol.BTProtocolStates.connected
