from utils import cached_property

class SPECIAL:
    pass

class Options(dict):
    """
    Dict-like interface abstracting FFmpeg command line flags.

    Example::

        >>> opt = AudioOptions(codec='vp8', bitrate=150000)
        >>> opt.bitrate
        150000
        >>> opt.as_commandline
        ['-acodec', 'vp8', '-ab', '150000']
    """
    __getattr__ = dict.__getitem__

    @cached_property
    def as_commandline(self):
        if not self:
            return
        for option, value in self.iteritems():
            ffmpeg_arg = self.OPTIONS[option]
            if ffmpeg_arg is SPECIAL:
                continue
            yield '-' + ffmpeg_arg
            yield str(value)

class AudioOptions(Options):
    OPTIONS = dict(
        sample_rate='ar',
        bitrate='ab',
        quality='aq',
        channels='ac',
        codec='acodec'
    )

class VideoOptions(Options):
    OPTIONS = dict(
        bitrate='b',
        frame_rate='r',
        size='s',
        codec='vcodec',
        max_width=SPECIAL,
        max_height=SPECIAL
    )
