from __future__ import division
from future_builtins import map
import re
import threading
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

class _missing:
    pass

__all__ = (
    'parse_duration', 'parse_fps', 'parse_frame',
    'cached_property', 'StringIO', 'nice_percent',
    'threadify'
)

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
    return int(a*100 // b)

def parse_duration(ffmpeg_stderr, regex=re.compile('Duration:\s*([\d:]+)')):
    """
    Returns the duration extracted from FFmpeg's stderr output in seconds::

        >>> parse_duration("...blah...Duration:\t 02:17:22...blah...")
        8242
    """
    duration = regex.search(ffmpeg_stderr)
    if duration is None:
        return None
    duration = duration.group(1)
    hours, minutes, seconds = map(int, duration.split(':'))
    return hours*3600 + minutes*60 + seconds

def parse_fps(ffmpeg_stderr, regex=re.compile('(\d+) fps')):
    """
    Returns the fps extracted from FFmpeg's stderr output::

        >>> parse_fps("...blah...42 fps...blah...")
        42
    """
    fps = regex.search(ffmpeg_stderr)
    if fps is None:
        return None
    return int(fps.group(1))

def parse_frame(ffmpeg_stderr, regex=re.compile('frame=\s*(\d+)')):
    """
    Returns the number of frames extracted from FFmpeg's stderr output::

        >>> parse_frame("...blah...frame=\t 42...blah...")
        42
    """
    frame = regex.search(ffmpeg_stderr)
    if frame is None:
        return None
    return int(frame.group(1))

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
