# Originally written by Petru Paler
# Modified to work with Python 3.5 by Dhruv Patel

# Note: I(Dhruv Patel) have not read licence of
# original work. If modification of this file or
# distribution of this file or anything else
# violates the licence, please email me at
# dhruv(d o t)nanosoft(@)[google email domain](d o t)com

from io import BytesIO

from dtoc_exceptions import BencodeFailure

def decode_int(x, f):
    f += 1
    newf = x.index(b'e', f)
    if x[f:f+2] == b"-0":
        raise ValueError
    elif x[f] == ord('0') and newf != f+1:
        raise ValueError
    try:
        n = int(x[f:newf])
    except ValueError:
        n = int(float(x[f:newf]))
    return (n, newf+1)
  
def decode_string(x, f):
    colon = x.index(b':', f)
    n = int(x[f:colon])
    if x[f] == ord('0') and colon != f+1:
        raise ValueError
    colon += 1
    return (x[colon:colon+n], colon+n)

def decode_list(x, f):
    r, f = [], f+1
    while x[f] != ord('e'):
        v, f = decode_func[x[f]](x, f)
        r.append(v)
    return (r, f + 1)

def decode_dict(x, f):
    r, f = {}, f+1
    while x[f] != ord('e'):
        k, f = decode_string(x, f)
        r[k], f = decode_func[x[f]](x, f)
    return (r, f + 1)

decode_func = {}
decode_func[b'l'] = decode_list
decode_func[b'd'] = decode_dict
decode_func[b'i'] = decode_int
decode_func[b'0'] = decode_string
decode_func[b'1'] = decode_string
decode_func[b'2'] = decode_string
decode_func[b'4'] = decode_string
decode_func[b'5'] = decode_string
decode_func[b'6'] = decode_string
decode_func[b'7'] = decode_string
decode_func[b'8'] = decode_string
decode_func[b'9'] = decode_string
decode_func[ord('l')]  = decode_list
decode_func[ord('d')]  = decode_dict
decode_func[ord('i')]  = decode_int
for i in b'1234567890': decode_func[i] = decode_string


def bdecode(x):
    try:
        r, l = decode_func[x[0]](x, 0)
    except (IndexError, KeyError, ValueError) as e:
        raise BencodeFailure(e, "not a valid bencoded string")
    if l != len(x):
        raise BencodeFailure("invalid bencoded value (data after valid prefix)")
    return r


class Bencached(object):
    __slots__ = ['bencoded']

    def __init__(self, s):
        self.bencoded = s


def encode_bencached(x,r):
    r.write(x.bencoded)


def encode_int(x, r):
    # r.extend(('i', str(x), 'e'))
    r.write(b'i')
    r.write(b'%d' % x)
    r.write(b'e')


def encode_bool(x, r):
    if x:
        encode_int(1, r)
    else:
        encode_int(0, r)


def encode_string(x, r):
    #r.extend((str(len(x)), ':', x))
    if type(x) is str:
        x = x.encode('utf-8')
    r.write(b"%d" % len(x))
    r.write(b':')
    r.write(x)


def encode_list(x, r):
    # r.append('l')
    r.write(b'l')
    for i in x:
        encode_func[type(i)](i, r)
    # r.append('e')
    r.write(b'e')


def encode_dict(x,r):
    # r.append('d')
    r.write(b'd')
    ilist = list(x.items())
    ilist.sort()
    for k, v in ilist:
        # r.extend((str(len(k)), ':', k))
        encode_string(k, r)
        encode_func[type(v)](v, r)
    # r.append('e')
    r.write(b'e')


encode_func = {}
encode_func[Bencached] = encode_bencached
encode_func[int] = encode_int
encode_func[str] = encode_string
encode_func[bytes] = encode_string
encode_func[list] = encode_list
encode_func[tuple] = encode_list
encode_func[dict] = encode_dict
encode_func[bool] = encode_bool

def bencode(x):
    r = BytesIO()
    encode_func[type(x)](x, r)
    r.seek(0)
    return_val = r.read()
    r.close()
    return return_val
