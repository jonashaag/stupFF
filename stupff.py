from __future__ import division
import os
import thread
import subprocess
import time
from itertools import chain
from utils import *

__all__ = (
    'Options', 'AudioOptions', 'VideoOptions',
    'FFmpegVideo', 'ConversionProcess'
)

# TODO: Event-driven/inheritance-"signal-methods"

class SPECIAL:
    pass

class Options(dict):
    """
    Dict-like interface abstracting FFmpeg command line flags.

    Example::

        >>> AudioOptions(codec='vp8', bitrate=150000).commandline
        ['-acodec', 'vp8', '-ab', '150000']
    """
    @cached_property
    def commandline(self):
        cmd = []
        for option, value in self.iteritems():
            ffmpeg_arg = self.OPTIONS[option]
            if ffmpeg_arg is SPECIAL:
                continue
            cmd.append('-'+ffmpeg_arg)
            cmd.append(str(value))
        return cmd

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
        aspect_ratio='aspect',
        bitrate_tolerance='bt',
        minimum_bitrate='minrate',
        maximum_bitarte='maxrate',
        codec='vcodec',
        same_quality='sameq',
        max_width=SPECIAL,
        max_height=SPECIAL
    )

    def select_good_size(self, video):
        max_height = self.get('max_height')
        max_width  = self.get('max_width')
        assert not (max_height is None and max_width is None)
        # chose width and height intelligently so that the maximum values
        # (given in ``max_width`` and ``max_height``)
        # are respected and the aspect ratio is preserved.
        aspect_ratio = video.width / video.height

        # calculate the ratio of the video and would-be heights and widths
        # and go on with the highest of the both.
        if max_height and video.height >= max_height:
            heights_ratio = video.height / max_height
        else:
            heights_ratio = -1
        if max_width and video.width >= max_width:
            widths_ratio = video.width / max_width
        else:
            widths_ratio = -1
        if heights_ratio == widths_ratio == -1:
            # do nothing. no maximums given that would matter in any way
            w, h = video.width, video.height
        else:
            if heights_ratio > widths_ratio:
                h, w = max_height, video.width / heights_ratio
            else:
                w, h = max_width, video.height / widths_ratio

        # ensure we did preserve the original aspect ratio:
        assert round(w / h, 2) == round(aspect_ratio, 2), (w/h, '!=', aspect_ratio)
        self['size'] = '%dx%d' % tuple(map(round, (w, h)))

DEFAULT_AUDIO_OPTIONS = AudioOptions()
DEFAULT_VIDEO_OPTIONS = VideoOptions()

class FFmpegVideo(object):
    def __init__(self, filename, exists=True):
        self.filename = filename
        if exists:
            self._get_ffmpeg_metadata()

    def _get_ffmpeg_metadata(self):
        assert self.exists()
        proc = subprocess.Popen(
            ['ffprobe', self.filename],
            stderr=subprocess.PIPE
        )
        proc.wait()
        returncode = proc.returncode
        if returncode:
            if not raise_ffmpeg_error(returncode, self):
                from . import FFmpegError
                raise FFmpegError("FFprobe returned with unknown code %d" % returncode)
        stderr = proc.stderr.read()
        self.fps = extract_fps(stderr)
        self.duration = extract_duration(stderr)
        self.width, self.height = extract_width_and_height(stderr)
        self.bitrate = extract_bitrate(stderr)

    def exists(self):
        return os.path.exists(self.filename)

    @cached_property
    def total_number_of_frames(self):
        assert self.fps != None
        assert self.duration != None
        return self.fps * self.duration

class ConversionProcess(subprocess.Popen):
    """
    Represents a call to FFmpeg (inheriting behaviour from ``subprocess.Popen``).

    Adds some comfort features like watching the conversion progress and
    calculating the estimated remaining time the task will run.
    """
    #: Conversion progress on a scale from 0 to 100.
    progress = 0
    #: The last frame FFmpeg reported it would work on.
    current_frame = 0

    def __init__(self, original_file, result_file,
                 audio_options=None, video_options=None):
        self.original_video = FFmpegVideo(original_file)
        self.result_video   = FFmpegVideo(result_file, exists=False)

        self.audio_options = audio_options or DEFAULT_AUDIO_OPTIONS
        self.video_options = video_options or DEFAULT_VIDEO_OPTIONS
        self.video_options.select_good_size(self.original_video)

        if not self.original_video.exists():
            raise OSError("Original file '%s' does not exist" % original_video.filename)
        if self.result_video.exists():
            raise OSError("Result file '%s' exists" % self.result_video.filename)

        self.start_time = time.time()
        subprocess.Popen.__init__(self, self.commandline, stderr=subprocess.PIPE)
        self._read_progress_thread()

    @cached_property
    def commandline(self):
        """ Full command line used to call FFmpeg. """
        return tuple(chain(
            ['ffmpeg', '-v', '10', '-i', self.original_video.filename],
            self.audio_options.commandline,
            self.video_options.commandline,
            [self.result_video.filename]
        ))

    @threadify(daemon=True)
    def _read_progress_thread(self):
        buf = StringIO()
        while not self.finished() and self.progress < 100:
            buf.truncate(0)
            c = self.stderr.read(1)
            while c != '\r':
                buf.write(c)
                c = self.stderr.read(1)
            current_frame = extract_frame(buf.getvalue())
            if current_frame is not None:
                self.current_frame = current_frame
                self.progress = nice_percent(
                    current_frame,
                    self.original_video.total_number_of_frames
                )

    @property
    def was_successful(self):
        assert self.finished()
        return self.returncode == 0

    def finished(self):
        """ ``True`` if this process has ended and a ``returncode`` is set. """
        return self.poll() is not None

    def seconds_left(self):
        """
        Estimated remaining time this conversion will take (approximated :)
        """
        seconds_spent = time.time() - self.start_time
        converted_frames_per_second = self.current_frame / seconds_spent
        frames_left = self.original_video.total_number_of_frames - self.current_frame
        try:
            return int(frames_left // converted_frames_per_second)
        except ZeroDivisionError:
            return None

    def wait_for_progress(self, check_interval=3):
        while True:
            if not self.finished():
                old_curframe = self.current_frame
                time.sleep(check_interval)
                if self.current_frame == old_curframe:
                    # nothing changed
                    continue
            return (self.progress, self.seconds_left())

if __name__ == '__main__':
    proc = ConversionProcess(
        'sintel_trailer-480p.ogv',
        'sintel.mp3',
        AudioOptions(codec='libmp3lame', bitrate=320 * 1000),
        VideoOptions(codec='mpeg4', max_width=200)
    )
    while not proc.finished():
        print '\rProgress: %s%% (%s seconds left)' % (proc.progress, proc.seconds_left())
        time.sleep(0.3)
    print 'process ended with code', proc.returncode
