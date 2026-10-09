"""USB Arduino resistance logger. Run locally: python resistance_logger.py.
Use --demo for explicitly simulated data. Requires pyserial and matplotlib.
"""
import argparse
import csv
from collections import deque
from dataclasses import dataclass
from datetime import datetime
import math
from pathlib import Path
import queue
import re
import threading
import time

# Reads the exact human-readable Serial.print format in the user's sketch.
STARTUP_PREFIX = 'LED ON only for '
COLUMNS = ['pc_timestamp', 'elapsed_s', 'segment', 'resistance_ohm',
           'baseline_ohm', 'delta_R_ohm', 'delta_R_percent',
           'a0_adc', 'supply_adc', 'led', 'status', 'raw_serial_line']
NUMBER = r'(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)'
LINE_RE = re.compile(
    rf'^A0:\s*(?P<a0>{NUMBER})\s*\|\s*Supply ADC:\s*(?P<supply>{NUMBER})'
    rf'\s*\|\s*(?P<result>.*?)\s*\|\s*LED command:\s*(?P<led>ON|OFF)\s*$')
RESISTANCE_RE = re.compile(rf'^Estimated R:\s*(?P<r>{NUMBER})\s+ohms$')

@dataclass
class Sample:
    resistance: float
    a0: float
    supply: float
    led: int
    status: str
    raw: str


def parse_sample(line):
    raw = line.strip()
    match = LINE_RE.fullmatch(raw)
    if not match:
        raise ValueError('Expected A0 / Supply ADC / Estimated R / LED command text')
    a0, supply = float(match['a0']), float(match['supply'])
    if not all(math.isfinite(v) and 0 <= v <= 1023 for v in (a0, supply)):
        raise ValueError('Invalid ADC reading')
    result = match['result'].strip()
    resistance_match = RESISTANCE_RE.fullmatch(result)
    if resistance_match:
        resistance = float(resistance_match['r'])
        if not math.isfinite(resistance):
            raise ValueError('Invalid resistance')
        status = 'OK'
    elif result == 'Open / very high resistance':
        resistance, status = math.nan, 'OPEN_OR_HIGH_R'
    elif result == 'Check input wiring':
        resistance, status = math.nan, 'CHECK_WIRING'
    else:
        raise ValueError('Unrecognised sensor result')
    # Trust the command reported by Arduino. Do not recompute it from rounded R.
    return Sample(resistance, a0, supply, int(match['led'] == 'ON'), status, raw)


def fmt(value):
    return f'{value:.6f}' if math.isfinite(value) else 'nan'


class Capture:
    """Time is monotonic PC receive time; this Arduino sketch sends no timestamp."""
    def __init__(self, stream, source, started_at):
        self.stream = stream
        self.started_at = started_at
        self.baseline = None
        self.rows = 0
        self.segment = 0
        stream.write('# Resistance logger; source=' + source + '\n')
        stream.write('# elapsed_s = PC monotonic receive time since Start logging\n')
        stream.write('# R0 = first valid reading of capture; new baseline after board reset\n')
        stream.write('# delta_R = R - R0; percent = 100*(R-R0)/R0; nan = unavailable\n')
        stream.write('# Measured resistance includes contacts; graph keeps latest 6000 readings\n')
        self.writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
        self.writer.writerow(COLUMNS)
        stream.flush()

    def board_reset(self):
        self.segment += 1
        self.baseline = None

    def add(self, sample, received_at, timestamp):
        # Ignore samples received before Start logging, even if still queued.
        if received_at < self.started_at:
            return None
        valid = sample.status == 'OK'
        resistance = sample.resistance if valid else math.nan
        if valid and self.baseline is None:
            self.baseline = resistance
        baseline = self.baseline if self.baseline is not None else math.nan
        delta = resistance - baseline
        percent = 100 * delta / baseline if baseline > 0 else math.nan
        elapsed = received_at - self.started_at
        self.writer.writerow([timestamp, fmt(elapsed), self.segment,
                              fmt(resistance), fmt(baseline), fmt(delta), fmt(percent),
                              fmt(sample.a0), fmt(sample.supply),
                              sample.led, sample.status, sample.raw])
        self.stream.flush()  # Every row, including faulty/open readings.
        self.rows += 1
        return elapsed, resistance, delta, percent


class App:
    def __init__(self, root, demo=False):
        import tkinter as tk
        from tkinter import ttk
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
        self.root = root
        self.demo = demo
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = None
        self.connected = False
        self.capture = None
        self.stream = None
        self.path = None
        self.malformed = 0
        self.history = deque(maxlen=6000)
        self.dirty = False
        self.last_plot = 0.0
        root.title('Resistance logger v2 (Arduino text) | ' + ('SIMULATED DEMO' if demo else 'Arduino Uno'))
        root.geometry('1080x760')
        root.minsize(800, 620)
        bar = ttk.Frame(root, padding=10)
        bar.pack(fill='x')
        ttk.Label(bar, text='Serial port:').pack(side='left')
        self.port = tk.StringVar()
        self.ports = ttk.Combobox(bar, textvariable=self.port, width=16)
        self.ports.pack(side='left', padx=5)
        self.refresh_btn = ttk.Button(bar, text='Refresh', command=self.refresh)
        self.refresh_btn.pack(side='left')
        self.connect_btn = ttk.Button(bar, text='Connect', command=self.connect)
        self.connect_btn.pack(side='left', padx=5)
        self.disconnect_btn = ttk.Button(bar, text='Disconnect', command=self.disconnect, state='disabled')
        self.disconnect_btn.pack(side='left')
        ttk.Label(bar, text='9600 baud').pack(side='left', padx=10)
        actions = ttk.Frame(root, padding=(10, 0, 10, 8))
        actions.pack(fill='x')
        self.start_btn = ttk.Button(actions, text='Start logging (.txt)', command=self.start, state='disabled')
        self.start_btn.pack(side='left')
        self.stop_btn = ttk.Button(actions, text='Stop logging', command=self.stop, state='disabled')
        self.stop_btn.pack(side='left', padx=5)
        ttk.Button(actions, text='Save graph (.png)', command=self.save_graph).pack(side='left')
        self.auto_scale = tk.BooleanVar(value=True)
        ttk.Checkbutton(actions, text='Auto-scale graph', variable=self.auto_scale).pack(side='left', padx=12)
        self.reading = tk.StringVar(value='Waiting for Arduino data…')
        ttk.Label(root, textvariable=self.reading, padding=10, font=('Segoe UI', 12)).pack(fill='x')
        self.info = tk.StringVar(value='Close Arduino Serial Monitor and Serial Plotter before connecting.')
        ttk.Label(root, textvariable=self.info, padding=(10, 0), wraplength=1000).pack(fill='x')
        self.file_info = tk.StringVar(value='Not logging. Baseline will be the first valid reading after Start.')
        ttk.Label(root, textvariable=self.file_info, padding=10, wraplength=1000).pack(fill='x')
        self.fig = Figure(figsize=(10, 5), dpi=100, constrained_layout=True)
        self.axes = self.fig.subplots(2, 1, sharex=True)
        self.axes[0].set_ylabel('Resistance R (Ω)')
        self.axes[1].set_ylabel('Change ΔR (Ω)')
        self.axes[1].set_xlabel('Elapsed time since Start logging (s)')
        self.lines = [self.axes[0].plot([], [], color='#1565c0', linewidth=1.4)[0],
                      self.axes[1].plot([], [], color='#bc4a00', linewidth=1.4)[0]]
        for ax in self.axes:
            ax.grid(True, alpha=0.25)
        self.canvas = FigureCanvasTkAgg(self.fig, master=root)
        self.canvas.get_tk_widget().pack(fill='both', expand=True)
        NavigationToolbar2Tk(self.canvas, root)
        self.refresh()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(50, self.poll)

    def refresh(self):
        if self.demo:
            ports = ['DEMO']
        else:
            from serial.tools import list_ports
            ports = [p.device for p in list_ports.comports()]
        self.ports['values'] = ports
        if ports and self.port.get() not in ports:
            self.port.set(ports[0])

    def connect(self):
        from tkinter import messagebox
        if self.connected:
            return
        port = self.port.get().strip()
        if not port:
            messagebox.showinfo('Select port', 'Connect the Uno, click Refresh, and select its COM port.')
            return
        try:
            if self.demo:
                device = None
            else:
                import serial
                device = serial.Serial(port, 9600, timeout=0.2)
        except Exception as exc:
            messagebox.showerror('Cannot open port', f'{exc}\n\nClose Serial Monitor, Serial Plotter, and other programs using this port.')
            return
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.connected = True
        self.malformed = 0
        self.connect_btn.config(state='disabled')
        self.ports.config(state='disabled')
        self.refresh_btn.config(state='disabled')
        self.disconnect_btn.config(state='normal')
        self.info.set('Connected; waiting for Arduino text readings. Opening USB may reset the Uno.')
        self.thread = threading.Thread(target=self.reader, args=(device, self.events, self.stop_event), daemon=True)
        self.thread.start()

    def reader(self, device, events, stop):
        start = time.monotonic()
        buffer = b''
        try:
            if self.demo:
                events.put(('header', time.monotonic(), None, None))
            while not stop.is_set():
                if self.demo:
                    elapsed = time.monotonic() - start
                    r = 21 + 12 * math.sin(elapsed / 3)
                    a0 = 675 * r / (100 + r)
                    led = 'ON' if 12 < r < 30 else 'OFF'
                    line = (f'A0: {a0:.1f} | Supply ADC: 675.0 | Estimated R: {r:.2f}'
                            f' ohms | LED command: {led}')
                    events.put(('line', time.monotonic(), datetime.now().astimezone().isoformat(timespec='milliseconds'), line))
                    stop.wait(0.1)
                    continue
                chunk = device.read(device.in_waiting or 1)
                if not chunk:
                    continue
                buffer += chunk
                while b'\n' in buffer:
                    raw, buffer = buffer.split(b'\n', 1)
                    line = raw.decode('ascii', errors='replace').strip()
                    if line.startswith(STARTUP_PREFIX) and line.endswith("ohms."):
                        events.put(('header', time.monotonic(), None, None))
                    elif line:
                        events.put(('line', time.monotonic(), datetime.now().astimezone().isoformat(timespec='milliseconds'), line))
                if len(buffer) > 8192:
                    raise ValueError('No line ending received. Check sketch and baud rate.')
        except Exception as exc:
            if not stop.is_set():
                events.put(('error', time.monotonic(), None, str(exc)))
        finally:
            if device is not None:
                device.close()

    def start(self):
        from tkinter import filedialog, messagebox
        if not self.connected or self.capture:
            return
        prefix = 'DEMO_' if self.demo else ''
        filename = filedialog.asksaveasfilename(defaultextension='.txt', filetypes=[('Text data', '*.txt')],
                    initialfile=prefix + datetime.now().strftime('resistance_%Y%m%d_%H%M%S.txt'))
        if not filename:
            return
        stream = None
        try:
            stream = open(filename, 'w', encoding='utf-8', newline='')
            capture = Capture(stream, 'SIMULATED_DEMO' if self.demo else self.port.get(), time.monotonic())
        except OSError as exc:
            if stream:
                stream.close()
            messagebox.showerror('Cannot save file', str(exc))
            return
        self.stream, self.capture, self.path = stream, capture, Path(filename)
        self.history.clear()
        self.dirty = True
        self.start_btn.config(state='disabled')
        self.stop_btn.config(state='normal')
        self.file_info.set(f'Logging to {self.path}; waiting for first valid baseline.')

    def stop(self):
        from tkinter import messagebox
        rows = self.capture.rows if self.capture else 0
        if self.stream:
            try:
                self.stream.close()
            except OSError as exc:
                messagebox.showerror('File close error', str(exc))
        self.stream = self.capture = None
        self.stop_btn.config(state='disabled')
        self.start_btn.config(state='normal' if self.connected else 'disabled')
        if self.path:
            self.file_info.set(f'Logging stopped ({rows} rows): {self.path}')

    def disconnect(self):
        self.connected = False
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1.0)
        self.stop()
        self.connect_btn.config(state='normal')
        self.disconnect_btn.config(state='disabled')
        self.ports.config(state='normal')
        self.refresh_btn.config(state='normal')
        self.info.set('Disconnected. The Uno can still run its LED program while USB-powered.')

    def poll(self):
        from tkinter import messagebox
        for _ in range(500):
            try:
                kind, received, timestamp, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if not self.connected:
                continue
            if kind == 'error':
                self.disconnect()
                self.info.set('Serial connection lost: ' + payload)
                break
            if kind == 'header':
                if self.capture and received >= self.capture.started_at:
                    self.capture.board_reset()
                    self.history.append((received - self.capture.started_at, math.nan, math.nan))
                    self.dirty = True
                continue
            try:
                sample = parse_sample(payload)
            except (ValueError, csv.Error):
                self.malformed += 1
                self.info.set(f'Skipped {self.malformed} non-data lines; use your pasted Arduino sketch at 9600 baud.')
                continue
            self.start_btn.config(state='disabled' if self.capture else 'normal')
            self.reading.set(f'R: {sample.resistance:.2f} Ω   |   LED: {"ON" if sample.led else "OFF"}'
                             f'   |   {sample.status}')
            self.info.set(f'Connected to {self.port.get()} | Skipped malformed lines: {self.malformed}'
                          + (' | SIMULATED DATA' if self.demo else ''))
            if self.capture:
                try:
                    point = self.capture.add(sample, received, timestamp)
                except OSError as exc:
                    self.stop()
                    messagebox.showerror('Logging stopped: write error', str(exc))
                    continue
                if point:
                    t, r, delta, percent = point
                    self.history.append((t, r, delta))
                    self.dirty = True
                    baseline = self.capture.baseline
                    base_text = 'waiting' if baseline is None else f'{baseline:.2f} Ω'
                    self.file_info.set(f'{self.path} | {self.capture.rows} rows | R0: {base_text}'
                                       f' | ΔR: {delta:.2f} Ω | ΔR/R0: {percent:.2f}%')
        if self.dirty and time.monotonic() - self.last_plot >= 0.25:
            data = list(self.history)
            xs = [p[0] for p in data]
            for index, line in enumerate(self.lines):
                line.set_data(xs, [p[index+1] for p in data])
                if self.auto_scale.get():
                    self.axes[index].relim()
                    self.axes[index].autoscale_view()
            self.canvas.draw_idle()
            self.last_plot = time.monotonic()
            self.dirty = False
        self.root.after(50, self.poll)

    def save_graph(self):
        from tkinter import filedialog, messagebox
        filename = filedialog.asksaveasfilename(defaultextension='.png', filetypes=[('PNG graph', '*.png')])
        if filename:
            try:
                self.fig.savefig(filename, dpi=200)
            except OSError as exc:
                messagebox.showerror('Cannot save graph', str(exc))

    def close(self):
        self.disconnect()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--demo', action='store_true', help='Use clearly labelled synthetic data without Arduino')
    args = parser.parse_args()
    try:
        import tkinter as tk
        import serial
        import matplotlib
    except ImportError as exc:
        raise SystemExit(f'{exc}\nInstall packages: py -m pip install -r requirements.txt\nUse desktop Python with Tkinter.')
    root = tk.Tk()
    App(root, args.demo)
    root.mainloop()


if __name__ == '__main__':
    main()
