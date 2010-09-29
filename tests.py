import unittest
import stupff

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

if __name__ == '__main__':
    unittest.main()
