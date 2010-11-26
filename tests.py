import unittest
import stupff

try:
    import json
except ImportError:
    import simplejson as json

TESTFILES = json.load(open('test_files.json'))

class UtilsTestcase(unittest.TestCase):
    def test_nice_percent(self):
        for inp, outp in (
            [(2, 4), 50],
            [(0.339, 1), 33],
            [(1000, 3), 100]
        ):
            self.assertEqual(stupff.nice_percent(*inp), outp)

    def test_autosize(self):
        for digits in (1, 2, 3):
            for size, max_size, outp in (
                [(400, 300), (400, 300), (400, 300)],
                [(360, 150), (40, 999),  (40, 16.666)],
                [(800, 200), (400, 300), (400, 100)],
                [(10, 1000), (1000, 10), (0.1, 10)],
                [(100, 100), (20, 5000), (20, 20)]
            ):
                class video:
                    width, height = size
                w, h = stupff.autosize(video, *max_size)
                outp = [round(x, digits) for x in outp]
                w_h = [round(x, digits) for x in outp]
                self.assertEqual(w_h, outp)

    def test_files(self):
        for file in TESTFILES['images']:
            ffile = stupff.FFmpegFile(file)
            for required in ['width', 'height']:
                self.assertNotEqual(ffile.meta[required], None)

        for file in TESTFILES['videos']:
            if file.endswith('webm'): continue
            ffile = stupff.FFmpegFile(file)
            for key in 'width height framerate bitrate framecount duration'.split():
                self.assertNotEqual(ffile.meta[key], '')
                self.assertNotEqual(ffile.meta[key], None, "%s %s is None" % (file, key))
                self.assertIsInstance(ffile.meta[key], int)

if __name__ == '__main__':
    unittest.main()
