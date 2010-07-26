from __future__ import division
import os
import thread
import subprocess
import time
from itertools import chain
from utils import *

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
            cmd.append('-'+self.OPTIONS[option])
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
        same_quality='sameq'
    )
DEFAULT_AUDIO_OPTIONS = AudioOptions()
DEFAULT_VIDEO_OPTIONS = VideoOptions()


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
    #: Total number of frames of the video (``None`` if the input and/or result
    #: file is/are audio-only.)
    number_of_frames = None

    def __init__(self, original_file, result_file,
                 audio_options=None, video_options=None):
        self.original_file = original_file
        self.result_file = result_file
        self.audio_options = audio_options or DEFAULT_AUDIO_OPTIONS
        self.video_options = video_options or DEFAULT_VIDEO_OPTIONS
        self.start_time = time.time()

        if not os.path.exists(original_file):
            raise OSError("Original file '%s' does not exist" % original_file)
        if os.path.exists(result_file):
            raise OSError("Result file '%s' exists" % result_file)

        subprocess.Popen.__init__(self, self.commandline, stderr=subprocess.PIPE)
        self.number_of_frames = self._get_number_of_frames()
        self._read_progress_thread()

    @cached_property
    def commandline(self):
        """ Full command line used to call FFmpeg. """
        return tuple(chain(
            ['ffmpeg', '-v', '10', '-i', self.original_file],
            self.audio_options.commandline,
            self.video_options.commandline,
            [self.result_file]
        ))

    def _get_number_of_frames(self):
        buf = StringIO()
        line = self.stderr.readline()
        while 'Press [q]' not in line:
            if self.returncode is not None:
                # program has exited
                return None
            buf.write(line)
            line = self.stderr.readline()
        buf = buf.getvalue()
        fps = parse_fps(buf)
        duration = parse_duration(buf)
        return fps * duration

    @threadify(daemon=True)
    def _read_progress_thread(self):
        buf = StringIO()
        while self.progress < 100:
            buf.truncate(0)
            c = self.stderr.read(1)
            while c != '\r':
                buf.write(c)
                c = self.stderr.read(1)
            current_frame = parse_frame(buf.getvalue())
            if current_frame is not None:
                self.current_frame = current_frame
                self.progress = nice_percent(current_frame, self.number_of_frames)

    @property
    def seconds_left(self):
        """
        Estimated remaining time this conversion will take (approximated :)
        """
        seconds_spent = time.time() - self.start_time
        converted_frames_per_second = self.current_frame / seconds_spent
        frames_left = self.number_of_frames - self.current_frame
        try:
            return int(frames_left // converted_frames_per_second)
        except ZeroDivisionError:
            return None

if __name__ == '__main__':
    proc = ConversionProcess(
        'sintel_trailer-480p.ogv',
        'sintel.mp3',
        AudioOptions(codec='libmp3lame', bitrate=320 * 1000),
        VideoOptions(codec='mpeg4')
    )
    while True:
        proc.poll()
        if proc.returncode is not None:
            print 'process ended with code', proc.returncode
            break
        print '\rProgress: %s%% (%s seconds left)' % (proc.progress, proc.seconds_left)
        time.sleep(0.3)
