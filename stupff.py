from __future__ import division
import os
import time
import subprocess
from itertools import chain

from commandline import AudioOptions, VideoOptions
from utils import *


class FFmpegError(Exception):
    pass

class FFmpegSubprocess(subprocess.Popen):
    def __init__(self, *args, **kwargs):
        self._procname = args[0][0]
        subprocess.Popen.__init__(self, *args, **kwargs)

    def successful(self):
        assert self.finished()
        return self.returncode == 0

    def finished(self):
        return self.poll() is not None

    def raise_error(self):
        assert not self.successful()
        raise FFmpegError(
            "%s exited with code '%d'" % \
            (self._procname, self.returncode)
        )

class FFmpegVideo(object):
    fps = \
    duration = \
    bitrate = \
    width = \
    height = None

    def __init__(self, filename):
        self.filename = filename

    def ffprobe(self):
        proc = FFmpegSubprocess(
            ['ffprobe', self.filename],
            stderr=subprocess.PIPE
        )
        proc.wait()
        if not proc.successful():
            proc.raise_error()
        stderr = proc.stderr.read()
        self.fps = extract_fps(stderr)
        self.duration = extract_duration(stderr)
        self.bitrate = extract_bitrate(stderr)
        self.width, self.height = extract_width_and_height(stderr)

    @cached_property
    def total_number_of_frames(self):
        assert self.fps != None
        assert self.duration != None
        return self.fps * self.duration


class Job(object):
    progress = 0
    _current_frame = 0

    def __init__(self, original_video, result_video,
                       audio_options, video_options):
        self.original_video = original_video
        self.result_video = result_video
        self.audio_options = audio_options
        self.video_options = video_options

    def start(self, subproc):
        self.start_time = time.time()
        self.process = subproc

    __sr_cache = None
    @property
    def seconds_remaining(self):
        """
        Remaining time until this conversion is done (approximated :-)
        """
        seconds_spent = int(time.time() - self.start_time)
        if not seconds_spent:
            return -1
        if seconds_spent != self.__sr_cache:
            average_speed = self._current_frame / seconds_spent
            frames_left = self.original_video.total_number_of_frames - self._current_frame
            self.__sr_cache = int(frames_left // average_speed)
        return self.__sr_cache


def convert_file(original_file, result_file, progress_callback, finished_callback,
                 audio_options=AudioOptions(), video_options=VideoOptions(),
                 auto_size=True, check_interval=0.5):
    """
    Docstring blahblah
    """
    if not os.path.exists(original_file):
        raise OSError("Original file '%s' does not exist" % original_file)
    if os.path.exists(result_file):
        raise OSError("Result file '%s' already exists" % result_file)

    job = Job(
        FFmpegVideo(original_file),
        FFmpegVideo(result_file),
        audio_options,
        video_options
    )
    job.original_video.ffprobe()

    if auto_size:
        width, height = autosize(
            job.original_video,
            video_options.get('max_width'),
            video_options.get('max_height')
        )
        video_options['size'] = '%dx%d' % (width, height)

    job.start(FFmpegSubprocess(
        tuple(chain(
            ['ffmpeg', '-v', '10', '-i', original_file],
            audio_options.as_commandline,
            video_options.as_commandline,
            [result_file],
        )),
        stderr=subprocess.PIPE
    ))
    _track_progress(job, progress_cb)

    while not job.process.finished():
        time.sleep(check_interval)
    if not job.process.successful():
        job.process.raise_error()

    finished_callback(job)


@threadify(daemon=True)
def _track_progress(job, progress_cb):
    stderr = job.process.stderr
    total_number_of_frames = job.original_video.total_number_of_frames
    buf = StringIO()
    while not job.process.finished() and job.progress < 100:
        buf.truncate(0)
        c = stderr.read(1)
        while c != '\r':
            if not c:
                break
            buf.write(c)
            c = stderr.read(1)
        else:
            current_frame = extract_frame(buf.getvalue())
            if current_frame is not None:
                job.progress = nice_percent(
                    current_frame,
                    total_number_of_frames
                )
                job._current_frame = current_frame
                progress_cb(job)

if __name__ == '__main__':
    def progress_cb(job):
        print "Progress: %d, %d seconds remaining" % (job.progress, job.seconds_remaining)

    def ready_cb(job):
        print "Job %r done" % job

    convert_file(
        'sintel_trailer-480p.ogv',
        'sintel.mp3',
        progress_cb,
        ready_cb,
        AudioOptions(codec='libmp3lame', bitrate=320 * 1000),
        VideoOptions(codec='mpeg4', max_width=200)
    )
