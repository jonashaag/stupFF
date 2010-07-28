class FFmpegError(Exception):
    pass

class FFmpegUnknownFileFormat(FFmpegError):
    pass

from stupff import *
