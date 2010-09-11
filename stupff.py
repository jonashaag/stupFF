from __future__ import division
import os
import time
import subprocess
from itertools import chain

from commandline import AudioOptions, VideoOptions
from utils import *


class FFmpegError(Exception):
    def __init__(self, proc, returncode):
        Exception.__init__(self, "%s returned code %d" % (proc, returncode))

class InvalidInputError(FFmpegError):
    pass

class PythonBug(Exception):
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
        if self.returncode in [234]:
            raise InvalidInputError(self._procname, self.returncode)
        else:
            raise FFmpegError(self._procname, self.returncode)

class FFmpegFile(object):
    fps = \
    duration = \
    bitrate = \
    width = \
    height = None

    def __init__(self, filename):
        self.filename = filename

    def ffprobe(self):
        self.ensure_exists()
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

    def ensure_exists(self):
        if not os.path.exists(self.filename):
            raise OSError("File %r does not exist" % self.filename)

    @cached_property
    def total_number_of_frames(self):
        assert self.fps != None
        assert self.duration != None
        return self.fps * self.duration


class Job(object):
    progress = 0
    _current_frame = 0
    extra_ffmpeg_args = ()

    def __init__(self, original_file, result_file,
                       audio_options, video_options):
        self.original_file = original_file
        self.result_file = result_file
        self.audio_options = audio_options
        self.video_options = video_options

    def run(self, check_interval=0.3):
        self.start_time = time.time()
        self.process = FFmpegSubprocess(
            tuple(chain(
                ['ffmpeg', '-v', '10'],
                self.extra_ffmpeg_args,
                ['-i', self.original_file.filename],
                self.audio_options.as_commandline,
                self.video_options.as_commandline,
                [self.result_file.filename],
            )),
            stderr=subprocess.PIPE
        )
        try:
            self.process.wait()
        except OSError as oserr:
            if oserr.errno == 10:
                raise PythonBug('See #1731717')
        if not self.process.successful():
            self.process.raise_error()

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
            frames_left = self.original_file.total_number_of_frames - self._current_frame
            self.__sr_cache = int(frames_left // average_speed)
        return self.__sr_cache


def job_create(original_file, result_file,
               audio_options=None, video_options=None,
               auto_size=True, check_interval=0.5):
    job = Job(
        FFmpegFile(original_file),
        FFmpegFile(result_file),
        audio_options or AudioOptions(),
        video_options or VideoOptions()
    )
    job.original_file.ffprobe()

    if os.path.exists(result_file):
        raise OSError("Result file '%s' already exists" % result_file)

    if auto_size:
        width, height = autosize(
            job.original_file,
            job.video_options.get('max_width'),
            job.video_options.get('max_height')
        )
        job.video_options['size'] = '%dx%d' % (width, height)

    return job

def convert_file(original_file, result_file, on_progress, *args, **kwargs):
    job = job_create(original_file, result_file, *args, **kwargs)
    thread = _track_progress(job, on_progress)
    job.run()
    # IMPORTANT: We `join` the thread to ensure it has ended when this
    # function returns to avoid weird behaviour. If we don't `join` the
    # thread, `on_progress` might be called *after* this function returned,
    # just because of the "randomness" threaded functions are scheduled with.
    # Users might expect that `on_progress` can't be called after the
    # conversion finished (which *would be* weird, indeed), so make sure
    # things don't mess up.
    thread.join()
    return job

def generate_thumbnail(original_file, thumbnail_file,
                       seek='HALF', **vkwargs):
    video_options = VideoOptions(codec='mjpeg', frames=1, **vkwargs)
    job = job_create(original_file, thumbnail_file,
                     video_options=video_options)
    seek = {
        'HALF' : job.original_file.duration / 2
    }.get(seek, seek)
    job.extra_ffmpeg_args = ['-ss', str(seek)]
    job.run()


@threadify(daemon=True)
def _track_progress(job, progress_cb):
    while not hasattr(job, 'process'):
        # wait until the job has been started
        time.sleep(0.1)
    stderr = job.process.stderr
    total_number_of_frames = job.original_file.total_number_of_frames
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
                if not job.process.finished():
                    # IMPORTANT: It is possible that the job has
                    # finished while we did the above calculations, so
                    # re-check the state before invoking `progress_cb`.
                    progress_cb(job)

if __name__ == '__main__':
    def progress_cb(job):
        print "Progress: %d%%, %d seconds remaining" % (job.progress, job.seconds_remaining)

    convert_file(
        'test_data/sintel_trailer-480p.ogv',
        'sintel.mp3',
        progress_cb,
        AudioOptions(codec='libmp3lame', bitrate=320 * 1000),
        VideoOptions(codec='mpeg4', max_width=200)
    )
