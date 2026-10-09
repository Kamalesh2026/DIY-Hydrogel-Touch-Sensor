import csv
import io
import math
import queue
import threading
import unittest
from resistance_logger import App, Capture, parse_sample


def row(r='20.00', led='ON'):
    return parse_sample(f'A0: 112.5 | Supply ADC: 675.0 | Estimated R: {r} ohms | LED command: {led}')

class LoggerTests(unittest.TestCase):
    def setUp(self):
        self.stream = io.StringIO()
        self.capture = Capture(self.stream, 'TEST', 100.0)

    def test_exact_user_format(self):
        sample = row()
        self.assertEqual((sample.resistance, sample.a0, sample.supply, sample.led), (20, 112.5, 675, 1))

    def test_baseline_and_change_and_saved_columns(self):
        self.assertIsNone(self.capture.add(row(), 99.0, 'before'))
        first = self.capture.add(row(), 100.1, 'first')
        second = self.capture.add(row('25.00'), 100.2, 'second')
        self.assertEqual(first[1:4], (20, 0, 0))
        self.assertEqual(second[1:4], (25, 5, 25))
        data = list(csv.DictReader((x for x in self.stream.getvalue().splitlines()
                                  if not x.startswith('#')), delimiter='\t'))
        self.assertEqual(len(data), 2)
        self.assertEqual(float(data[1]['delta_R_percent']), 25)
        self.assertEqual(float(data[1]['elapsed_s']), 0.2)
        self.assertIn('Estimated R: 25.00', data[1]['raw_serial_line'])
        self.assertNotIn('arduino_ms', data[1])

    def test_both_errors_are_logged_as_gaps(self):
        for message, status in [('Open / very high resistance', 'OPEN_OR_HIGH_R'),
                                ('Check input wiring', 'CHECK_WIRING')]:
            sample = parse_sample(f'A0: 675.0 | Supply ADC: 675.0 | {message} | LED command: OFF')
            self.assertEqual(sample.status, status)
            p = self.capture.add(sample, 101, 'fault')
            self.assertTrue(math.isnan(p[1]))
            self.assertIsNone(self.capture.baseline)
        self.assertEqual(self.capture.rows, 2)

    def test_startup_reset_establishes_new_baseline(self):
        self.capture.add(row(), 101, 'a')
        self.capture.board_reset()
        p = self.capture.add(row('30.00', 'OFF'), 102, 'b')
        self.assertEqual(self.capture.segment, 1)
        self.assertEqual(self.capture.baseline, 30)
        self.assertEqual(p[2], 0)

    def test_zero_baseline_percentage_unavailable(self):
        p = self.capture.add(row('0.00', 'OFF'), 101, 'zero')
        self.assertTrue(math.isnan(p[3]))
        self.assertEqual(p[2], 0)

    def test_led_uses_reported_command_even_at_rounded_boundary(self):
        self.assertEqual(row('12.00', 'ON').led, 1)
        self.assertEqual(row('30.00', 'OFF').led, 0)

    def test_bad_input_is_rejected(self):
        for text in ('hello', '1,2,3', 'A0: 112 | Supply ADC: 675 | Estimated R: nan ohms | LED command: ON',
                     'A0: 2000 | Supply ADC: 675 | Estimated R: 20 ohms | LED command: ON'):
            with self.assertRaises(ValueError):
                parse_sample(text)

    def test_fragmented_serial_lines_and_startup(self):
        stop = threading.Event()
        events = queue.Queue()
        content = ('LED ON only for 10 < estimated R < 30 ohms.\r\n' + row().raw + '\r\n').encode()
        class FakeSerial:
            in_waiting = 0
            def __init__(self): self.data = content; self.closed = False
            def read(self, size):
                if not self.data:
                    stop.set(); return b''
                out, self.data = self.data[:7], self.data[7:]
                return out
            def close(self): self.closed = True
        device = FakeSerial()
        holder = type('Holder', (), {'demo': False})()
        App.reader(holder, device, events, stop)
        self.assertTrue(device.closed)
        self.assertEqual(events.get_nowait()[0], 'header')
        event = events.get_nowait()
        self.assertEqual(parse_sample(event[3]).resistance, 20)

if __name__ == '__main__':
    unittest.main()
