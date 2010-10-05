from __future__ import division
import os
import time
from subprocess import Popen, PIPE

from mediainfo import get_metadata as get_file_metadata

from commandline import AudioOptions, VideoOptions
from utils import *

class FFmpegError(Exception):
    pass

class InvalidInputError(FFmpegError):
    pass

class FFmpegSubprocess(Popen):
    def __init__(self, *args, **kwargs):
        self._procname = args[0][0]
        # hackaround to avoid Python bug #1731717
        with MonkeyPatch(subprocess, '_cleanup', lambda: None):
            Popen.__init__(self, *args, **kwargs)

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
    def __init__(self, filename, exists=True):
        self.filename = filename
        if exists:
            self.get_metadata()

    def get_metadata(self):
        info = get_file_metadata(
            self.filename,
            General={'VideoCount' : bool},
            Video={'FrameRate' : lambda x:int(float(x)),
                   'Width' : int, 'Height' : int,
                   'Duration' : int, 'BitRate' : float}
        )
        if not info['General']['VideoCount']:
            raise InvalidInputError(self.filename)
        info = info['Video']
        self.width = info['Width']
        self.height = info['Height']
        self.duration = info['Duration']/1000
        self.bitrate = info['BitRate']/1000
        self.fps = info['FrameRate']
        self.total_number_of_frames = self.duration * self.fps

class Job(object):
    process = None
    progress = None
    commandline = None
    current_frame = None
    extra_ffmpeg_args = []

    def __init__(self, original_file, result_file,
                       audio_options, video_options):
        self.original_file = original_file
        self.result_file = result_file
        self.audio_options = audio_options
        self.video_options = video_options

    def get_commandline(self):
        return (
            ['ffmpeg', '-v', '10'] +
            self.extra_ffmpeg_args +
            ['-i', self.original_file.filename] +
            list(self.audio_options.as_commandline()) +
            list(self.video_options.as_commandline()) +
            [self.result_file.filename]
        )

    def run(self):
        self.commandline = self.get_commandline()
        self.start_time = time.time()
        self.process = process = FFmpegSubprocess(self.commandline, stderr=PIPE)
        process.wait()
        if not process.successful():
            process.raise_error()

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
            average_speed = self.current_frame / seconds_spent
            frames_left = self.original_file.total_number_of_frames - self.current_frame
            self.__sr_cache = int(frames_left // average_speed)
        return self.__sr_cache


def job_create(original_file, result_file, audio_options=None,
               video_options=None, auto_size=True):
    job = Job(
        FFmpegFile(original_file),
        FFmpegFile(result_file, exists=False),
        audio_options or AudioOptions(),
        video_options or VideoOptions()
    )

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

def generate_thumbnail(original_file, thumbnail_file, seek=None, **vkwargs):
    seeks = [lambda n:n/3, lambda n:n/2, 1]
    if seek is not None:
        seeks.insert(0, seek)

    video_options = VideoOptions(codec='mjpeg', frames=1, **vkwargs)
    job = job_create(original_file, thumbnail_file,
                     video_options=video_options)
    for seek in seeks:
        if callable(seek):
            seek = seek(job.original_file.duration)
        job.extra_ffmpeg_args = ['-ss', str(seek)]
        job.run()
        if os.path.exists(thumbnail_file):
            # alright, we're done
            break
        else:
            # FFmpeg exited with code 0 but failed to generate thumbnails.
            # This can happen for some formats and has something to do with
            # keyframes I don't understand at all.  Try a different seek.
            continue
    return job


@threadify(daemon=True)
def _track_progress(job, progress_cb):
    while job.process is None:
        # wait until the job has been started (a matter of milliseconds, but
        # there's a chance this code is executed before `Job.__init__` is done)
        time.sleep(0.01)
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
                job.current_frame = current_frame
                if not job.process.finished():
                    # IMPORTANT: It is possible that the job has
                    # finished while we did the above calculations, so
                    # re-check the state before invoking `progress_cb`.
                    progress_cb(job)
