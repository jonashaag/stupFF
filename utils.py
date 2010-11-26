from __future__ import division
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

__all__ = (
    'extract_duration', 'extract_fps', 'extract_frame',
    'extract_width_and_height', 'extract_bitrate',
    'StringIO', 'nice_percent', 'threadify', 'autosize'
)

def nice_percent(a, b):
    return min(100, int(a*100 // b))

def autosize(video, max_width, max_height, digits=None):
    """
    Returns a tuple (width, height) chosen intelligently so that the
    maximum values (given in ``max_width`` and ``max_height``)
    are respected and the aspect ratio is preserved.

    :param video: The ``FFmpegVideo`` that has the original
                  ``width`` and ``height`` properties to do the calculation with.
    :param int digits: Number of digits the resulting `width` and `height` shall
                       be rounded to (or ``-1`` if no rounding shall be done)
    """
    # The following code could be expressed in about two lines, but I think
    # readability is much more important than performance/elegance here.

    aspect_ratio = video.width / video.height

    # calculate the ratio of the video and would-be heights and widths
    # and go on with the highest of the both.
    if max_height and video.height >= max_height:
        heights_ratio = video.height / max_height
    else:
        heights_ratio = None
    if max_width and video.width >= max_width:
        widths_ratio = video.width / max_width
    else:
        widths_ratio = None

    if heights_ratio is widths_ratio is None:
        # do nothing. no maximums given that would matter in any way
        return video.width, video.height

    if heights_ratio > widths_ratio:
        h, w = max_height, video.width / heights_ratio
    else:
        w, h = max_width, video.height / widths_ratio
    if digits > 0:
        w, h = round(w, digits), round(h, digits)
    return w, h

def threadify(daemon=False):
    """
    Decorator to "threadify" a function, so that ::

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
    from threading import Thread

    def wrapper(func):
        def decorator(*args, **kwargs):
            thread = Thread(target=func, args=args, kwargs=kwargs)
            if daemon:
                thread.daemon = True
            thread.start()
            return thread

        decorator.__name__ = '%r [threadified]' % func
        return decorator

    return wrapper

def simple_extractor(regex, fallback=None):
    from re import compile
    from functools import wraps
    regex = compile(regex)
    def wrapper(func):
        @wraps(func)
        def decorator(ffmpeg_stderr, **kwargs):
            match = regex.search(ffmpeg_stderr)
            if match is None:
                return fallback
            return func(match, **kwargs)
        return decorator
    return wrapper

@simple_extractor('bitrate: (\d+|N\/A)')
def extract_bitrate(match, unavailable=-1):
    """
        >>> extract_bitrate("...blah...bitrate: 4242...blah...")
        4242
    """
    match = match.group(1)
    if match == 'N/A':
        return unavailable
    return int(match)

@simple_extractor(',\s+(\d+)x(\d+)', fallback=(None, None))
def extract_width_and_height(match):
    """
        >>> extract_width_and_height("...blah...,  42x32,...blah...")
        (42, 32)
    """
    return int(match.group(1)), int(match.group(2))

@simple_extractor('Duration:\s*([\d:]+)(\.\d+)?')
def extract_duration(match):
    """
    Returns the duration extracted from FFmpeg's stderr output in seconds::

        >>> extract_duration("...blah...Duration:\t 02:17:22...blah...")
        8242
        >>> extract_duration("...blah...Duration:\t\\n 02:17:22.4...blah")
        8242
        >>> extract_duration("...blah...Duration:\t\\n 02:17:22.5...blah")
        8243
    """
    duration = match.group(1)
    milliseconds = match.group(2)
    hours, minutes, seconds = map(int, duration.split(':'))
    if milliseconds:
        seconds = int(round(seconds + float(milliseconds), 0))
    return hours*3600 + minutes*60 + seconds

@simple_extractor('(\d+) fps')
def extract_fps(match):
    """
        >>> extract_fps("...blah...42 fps...blah...")
        42
    """
    return int(match.group(1))

@simple_extractor('frame=\s*(\d+)')
def extract_frame(match):
    """
        >>> extract_frame("...blah...frame=\t 42...blah...")
        42
    """
    return int(match.group(1))

if __name__ == '__main__':
    import doctest
    doctest.testmod()
