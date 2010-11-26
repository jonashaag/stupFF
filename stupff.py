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
        Popen.__init__(self, *args, **kwargs)

    def wait(self):
        raise SystemError("Use safe_wait(). wait() sucks. (see bug #1731717)")

    def safe_wait(self):
        # mimics the bahaviour of `.wait()`, but hopefully with a lot smaller
        # chance to hit Python bug #1731717 (which crashes calls to `waitpid`,
        # and thus to `.wait()`, `.poll()`, ... randomly)
        while not self.finished():
            time.sleep(0.1)

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
            self.__dict__.update(self.get_metadata())

    def get_metadata(self):
        cull_empty = lambda d: dict((k, v) for k, v in d.items() if v not in ('', None))
        want = set('framerate duration width height bitrate framecount'.split())

        # First, try MediaInfo, as it gives better results for many files.
        try:
            meta = cull_empty(self._get_mediainfo_metadata())
            missing = want.difference(meta.keys())
        except InvalidInputError:
            meta = dict()
            missing = want

        if missing:
            # MediaInfo didn't provide all the information we want.
            # Try FFprobe.
            try:
                meta.update(cull_empty(self._get_ffprobe_metadata()))
            except InvalidInputError:
                pass

            still_missing = want.difference(meta.keys())
            for key in still_missing:
                meta[key] = None

        if meta['framecount'] is None and \
           meta['duration'] is not None and \
           meta['framerate'] is not None:
            # manually calculate the number of frames
            meta['framecount'] = meta['duration'] * meta['framerate']

        return meta

    def _get_mediainfo_metadata(self):
        floatint = lambda x: int(float(x))
        query = {
            'General' : {'VideoCount' : bool},
            'Video' : {
                'FrameRate' : floatint,
                'Width' : int, 'Height' : int,
                'Duration' : int, 'BitRate' : floatint,
                'FrameCount' : int
            }
        }
        info = get_file_metadata(self.filename, **query)
        if not info['General']['VideoCount']:
            raise InvalidInputError(self.filename)

        info = info['Video']
        meta = dict((key.lower(), info[key]) for key in query['Video'].keys())
        if meta.get('bitrate') is not None:
            meta['bitrate'] //= 1000
        if meta.get('duration') is not None:
            meta['duration'] //= 1000
        return meta

    def _get_ffprobe_metadata(self):
        proc = FFmpegSubprocess(['ffprobe', self.filename], stderr=PIPE)
        proc.safe_wait()
        if not proc.successful():
            proc.raise_error()
        stderr = proc.stderr.read()
        width, height = extract_width_and_height(stderr)
        return {
            'framerate' : extract_fps(stderr),
            'duration' : extract_duration(stderr),
            'bitrate' : extract_bitrate(stderr, unavailable=None),
            'width' : width,
            'height' : height
        }


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
        process.safe_wait()
        if not process.successful():
            process.raise_error()

    def calculate_remaining_seconds(self):
        """
        Remaining time until this conversion is done (approximated :-)
        """
        seconds_spent = int(time.time() - self.start_time)
        if not seconds_spent:
            return -1
        average_speed = self.current_frame / seconds_spent
        frames_left = self.original_file.framecount - self.current_frame
        return int(frames_left // average_speed)


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
    if job.original_file.framecount:
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
    else:
        # If we can't calculate the number of frames in this video, we can't
        # calculate any progress. Just run the job.
        job.run()
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
            if not job.original_file.duration:
                continue # we have no duration information
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
    framecount = job.original_file.framecount
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
                job.progress = nice_percent(current_frame, framecount)
                job.current_frame = current_frame
                if not job.process.finished():
                    # IMPORTANT: It is possible that the job has
                    # finished while we did the above calculations, so
                    # re-check the state before invoking `progress_cb`.
                    progress_cb(job)
