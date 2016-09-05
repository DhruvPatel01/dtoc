from twisted.internet import reactor
import hashlib
import os
import random
from bitarray import bitarray
import string
import math
import logging
import sys
import time

import dtoc_bencode
import dtoc_exceptions
import aux
import Tracker
import PeerProtocol
import LNDP

MAX_CONNECTONS = 1
BAR_LENGTH = 30

class Torrent(object):
    def __init__(self, path, save_path="./", name=None, port = 6891, verbose=1):
        try:
            f = open(path, 'rb')
            file_data_binary = f.read()
            bdecoded = dtoc_bencode.bdecode(file_data_binary)
        except Exception:
            raise
        else:
            f.close()

        self.connections = set() #just outgoing
        self.current_protocols = set() #all instances of PeerProtocol
        self._client_factory = None

        self.peers = set()
        self.trackers = []
        self.verbose = verbose
        self.status = 'idle'
        self.port = port
        self.announce = bdecoded[b'announce'].decode('utf-8')
        self.announce_list = [l[0].decode('utf-8')
                              for l in bdecoded.get(b'announce-list',[])]

        self.save_path = save_path
        if not os.path.exists(save_path): os.makedirs(save_path)

        info = bdecoded[b'info']
        info_hash_temp = hashlib.sha1(dtoc_bencode.bencode(info))
        self.info_hash = info_hash_temp.digest()
        self.info_hash_str = info_hash_temp.hexdigest()
        if name is None:
            self.name = self.info_hash_str[:4] + '...' + self.info_hash_str[-4:]
        else:
            self.name = name
        self.peer_id = "-DT0001-" + ''.join(random.choice(string.digits) for i in range(12))
        self.peer_id = self.peer_id.encode('ascii')
        self.piece_length = info[b'piece length']
        self.key = int(random.random()*2**31)

        files = info.get(b'files', None)
        self.size = 0
        if files:
            self.file_mode = 'multi'
            self.base_dir = info[b'name'].decode('utf-8')
            temp = os.path.join(self.save_path, self.base_dir)
            if not os.path.exists(temp):
                os.makedirs(temp)
            self.files = []
            temp_offset = 0
            for file_ in files:
                self.size += file_.get(b'length')
                lst = [s.decode('utf-8') for s in file_[b'path']]
                temp = os.path.join(self.save_path, self.base_dir, *lst)
                self.files.append(aux.FileMetaData(temp,
                                                   int(file_[b'length']),
                                                   file_.get(b'md5sum', None),
                                                   temp_offset))
                temp_offset += int(file_[b'length'])
        else:
            self.file_mode = 'single'
            self.size += info.get(b'length')
            temp = os.path.join(self.save_path, info[b'name'].decode('utf-8'))
            self.files = [aux.FileMetaData(temp,
                                         info[b'length'],
                                         info.get(b'md5sum', None), 0)]
        self._open_files = []
        for f in self.files:
            if os.path.exists(f.path):
                self._open_files.append(open(f.path, 'rb+'))
            else:
                self._open_files.append(open(f.path, 'wb+'))

        temp = info[b'pieces']
        self.pieces = [temp[i*20:i*20+20] for i in range(len(temp)//20)]
        self.bitfield = bitarray(len(self.pieces))
        self.bitfield.setall(0)
        #priority queue highest <-...-> lowest <-> don't download
        self.queue = [set(), set(), set(), None, set()]
        self.queue[3] = set(i for i in range(len(self.pieces)))
        self.force_recheck()

    def start(self):
        if self.status == 'started': return
        if self.verbose > 15: print(self.name, "Staring...")
        self.started_at = time.time()
        self.downloaded_session = 0
        self.uploaded_session = 0
        self._client_factory = PeerProtocol.BTClientFactory(self)
        url = self.announce
        if not url.startswith('udp://'):
            raise(DTOCFailure("Non udp trackers not supported yet"))
        self.trackers.append(Tracker.UDPTracker(self, url, self.verbose))
        for url in self.announce_list:
            if url.startswith('udp://'):
                self.trackers.append(Tracker.UDPTracker(self, url, self.verbose))
        self.lndp = LNDP.LNDPProtocol(self)

    def peer_list_update(self, ips):
        if (self.verbose > 15): print("Peer list updated")
        self.peers.update(ips)
        self.state = 'started'
        self.connect_peers()

    def connect_peer(self, peer):
        reactor.connectTCP(peer.ip, peer.port, self._client_factory)

    def connect_peers(self):
        if self.progress() == 1.0: return
        if len(self.connections) > MAX_CONNECTONS: return
        lst = list(self.peers)
        random.shuffle(lst)
        for p in lst:
            if p in self.connections: continue
            self.connect_peer(p)
            if len(self.connections) > MAX_CONNECTONS: break

    def stop(self):
        logging.shutdown()
        print(self.name, "\nStopping...")
        for t in self.trackers: t.stop()
        for f in self._open_files: f.close()

    def index_to_file(self, index):
        """This method returns a file its index in files list
           and offset of start of i<sup>th</sup> piece
           in file.
           Note: some part of piece may belong to next file.
        """
        index *= self.piece_length
        for i,file_ in enumerate(self.files):
            if index < file_.length:
                return (i, file_, index)
            else:
                index -= file_.length
        raise ValueError("Too high index")

    def file_to_range(self, file_index):
        """returns (start_piece, start_offset, end_piece, end_offset)"""
        pass

    def offset_of_index_into_file(self, file_index, index):
        pass

    def force_recheck(self):
        if self.verbose >= 1: print(self.name, "Force rechecking.")
        self.downloaded = 0
        for i in range(len(self.pieces)):
            if self.read_piece(i) is not None and not self.bitfield[i]:
                self.downloaded += self.length_of_piece(i)

    def give_me_order(self, s):
        """this method returns piece number to download from s"""
        if self.status == 'seeding':
            return None
        for t in self.queue[:-1]:
            u = t & s
            while u:
                e, *_ = random.sample(u, 1)
                u.remove(e)
                t.remove(e)
                self.queue[-2].add(e)
                if not self.bitfield[e]: return e
        return None

    def read_piece(self, index):
        if not (0<= index < len(self.pieces)):
            return None
        f_index, file_, offset = self.index_to_file(index)
        piece = bytearray()
        l = self.piece_length
        for file_ in self._open_files[f_index:]:
            file_.seek(offset)
            data = file_.read(l)
            l -= len(data)
            piece.extend(data)
            if l == 0:
                break
            offset = 0
        if hashlib.sha1(piece).digest() == self.pieces[index]:
            if not self.bitfield[index]:
                self.downloaded += self.length_of_piece(index)
            self.bitfield[index] = True
            for q in self.queue:
                if index in q: q.remove(index)
        else:
            piece = None
        return piece

    def progress(self):
        return self.downloaded/self.size

    def progress_printer(self):
        prog  = self.progress()
        barlength = math.floor(prog*BAR_LENGTH)
        ctime = time.time()
        downloaded = 0
        for p in self.current_protocols:
            downloaded += p.downloaded
            p.downloaded = 0
        speed = (self.downloaded_session/1024) / (ctime - self.started_at)
        unit = 'KBps'
        if speed > 1000:
            speed /= 1024
            unit= 'MBps'
        s = '%s [%s%s] %6.2f%% %.2f %s' % (self.name, '#'*barlength, ' '*(BAR_LENGTH-barlength), prog*100, speed, unit)
        print('\b'*len(s), end='')
        print(s, end='')
        sys.stdout.flush()
        if prog < 1.0:
            reactor.callLater(2, self.progress_printer)

    def write_piece(self, index, piece):
        f_index, file_, offset = self.index_to_file(index)
        wrote = 0
        l = self.length_of_piece(index)
        if hashlib.sha1(piece).digest() != self.pieces[index]:
            logging.error("Hash didn't match")
            return False
        for i in range(f_index, len(self.files)):
            f = self._open_files[i]
            f.seek(offset)
            f_len = self.files[i].length - offset
            wrote += f.write(piece[wrote:wrote+f_len])
            offset = 0
        if not self.bitfield[index]:
            self.bitfield[index] = True
            self.downloaded += self.length_of_piece(index)
            self.downloaded_session += self.length_of_piece(index)
        for q in self.queue:
            if index in q: q.remove(index)
        return True

    def length_of_piece(self, index):
        """returns a lenth of particular piece in bytes"""
        if self.pieces[index] != self.pieces[-1]:
            return self.piece_length
        else:
            lop =  self.size % self.piece_length
            return self.piece_length if lop == 0 else lop
