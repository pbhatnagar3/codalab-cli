'''
Provides basic formatting utilities.
'''

import datetime
import sys

def contents_str(input_string):
    '''
    input_string: raw string (may be None)
    Return 'MISSING' if input_string is None.
    '''
    return input_string if input_string is not None else 'MISSING'

def size_str(size):
    '''
    size: number of bytes
    Return a human-readable string.
    '''
    if size == None: return None
    for unit in ('', 'K', 'M', 'G'):
        if size < 100 and size != int(size):
            return '%.1f%s' % (size, unit)
        if size < 1024:
            return '%d%s' % (size, unit)
        size /= 1024.0

def date_str(ts):
    return datetime.datetime.fromtimestamp(ts).isoformat().replace('T', ' ')

def duration_str(s):
    '''
    s: number of seconds
    Return a human-readable string.
    Example: 100 => "1m40s", 10000 => "2h46m"
    '''
    if s == None: return None
    m = int(s / 60)
    if m == 0: return "%.1fs" % s
    s -= m * 60

    h = int(m / 60)
    if h == 0: return "%dm%ds" % (m, s)
    m -= h * 60

    d = int(h / 24)
    if d == 0: return "%dh%dm" % (h, m)
    h -= d * 24

    y = int(d / 365)
    if y == 0: return "%dd%dh" % (d, h)
    d -= y * 365

    return "%dy%dd" % (y, d)

def parse_size(s):
    '''
    s: <number><k|m|g>
    Returns the number of bytes.
    '''
    if s[-1].isdigit():
        return float(s)
    n, unit = float(s[0:-1]), s[-1].lower()
    if unit == 'k':
        return n * 1024
    if unit == 'm':
        return n * 1024 * 1024
    if unit == 'g':
        return n * 1024 * 1024 * 1024
    # If error, ignore unit
    print >>sys.stderr, 'Warning: invalid unit in ', s
    raise n

def parse_duration(s):
    '''
    s: <number><s|m|h|d|y>
    Returns the number of seconds
    '''
    if s[-1].isdigit():
        return float(s)
    n, unit = float(s[0:-1]), s[-1].lower()
    if unit == 's':
        return n
    if unit == 'm':
        return n * 60
    if unit == 'h':
        return n * 60 * 60
    if unit == 'd':
        return n * 60 * 60 * 24
    if unit == 'y':
        return n * 60 * 60 * 24 * 365
    # If error, ignore unit
    print >>sys.stderr, 'Warning: invalid unit in ', s
    raise n
