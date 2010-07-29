from __future__ import division
from future_builtins import map
from functools import wraps
import re
import threading
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

class _missing:
    pass

__all__ = (
    'extract_duration', 'extract_fps', 'extract_frame',
    'extract_width_and_height', 'extract_bitrate',
    'cached_property', 'StringIO', 'nice_percent',
    'threadify', 'raise_ffmpeg_error'
)


def raise_ffmpeg_error(returncode, video):
    if returncode == 234:
        from . import FFmpegUnknownFileFormat
        raise FFmpegUnknownFileFormat(video.filename)

def threadify(daemon=False):
    """
    Decorator to "threadify" a function, so ::

        class MyThread(threading.Thread):
            def run(self):
                func()
        MyThread().start()

    is equivalent to ::

        @threadify
        def func():
            ...
        func()

    """
    def wrapper(func):
        def decorator(*args, **kwargs):
            thread = threading.Thread(target=func, args=args,
                                      kwargs=kwargs)
            if daemon:
                thread.daemon = True
            thread.start()
        decorator.__name__ = '%r [threadified]' % func
        return decorator
    return wrapper

def nice_percent(a, b):
    return min(100, int(a*100 // b))

def uses_regex(regex, fallback=None):
    regex = re.compile(regex)
    def wrapper(func):
        @wraps(func)
        def decorator(ffmpeg_stderr):
            match = regex.search(ffmpeg_stderr)
            if match is None:
                return fallback
            return func(match)
        return decorator
    return wrapper

@uses_regex('bitrate: (\d+)')
def extract_bitrate(match):
    """
        >>> extract_bitrate("...blah...bitrate: 4242...blah...")
        4242
    """
    return int(match.group(1))

@uses_regex(',\s+(\d+)x(\d+)', fallback=(None, None))
def extract_width_and_height(match):
    """
        >>> extract_width_and_height("...blah...,  42x32,...blah...")
        (42, 32)
    """
    return int(match.group(1)), int(match.group(2))

@uses_regex('Duration:\s*([\d:]+)')
def extract_duration(match):
    """
    Returns the duration extracted from FFmpeg's stderr output in seconds::

        >>> extract_duration("...blah...Duration:\t 02:17:22...blah...")
        8242
    """
    duration = match.group(1)
    hours, minutes, seconds = map(int, duration.split(':'))
    return hours*3600 + minutes*60 + seconds

@uses_regex('(\d+) fps')
def extract_fps(match):
    """
    Returns the fps extracted from FFmpeg's stderr output::

        >>> extract_fps("...blah...42 fps...blah...")
        42
    """
    return int(match.group(1))

@uses_regex('frame=\s*(\d+)')
def extract_frame(match):
    """
    Returns the number of frames extracted from FFmpeg's stderr output::

        >>> extract_frame("...blah...frame=\t 42...blah...")
        42
    """
    return int(match.group(1))

class cached_property(object):
    """
    A property that is lazily calculated and then cached.
    Stolen from Armin Ronacher's Logbook (http:/github.com/mitsuhiko/logbook)
    """
    def __init__(self, func, name=None, doc=None):
        self.__name__ = name or func.__name__
        self.__module__ = func.__module__
        self.__doc__ = doc or func.__doc__
        self.func = func

    def __get__(self, obj, type=None):
        if obj is None:
            return self
        value = obj.__dict__.get(self.__name__, _missing)
        if value is _missing:
            value = self.func(obj)
            obj.__dict__[self.__name__] = value
        return value

if __name__ == '__main__':
    import doctest
    doctest.testmod()
