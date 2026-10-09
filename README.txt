RESISTANCE LOGGER v2 -- FOR YOUR EXISTING ARDUINO TEXT OUTPUT

USE YOUR PASTED ARDUINO CODE. NO CIRCUIT OR SKETCH CHANGE IS REQUIRED.
This package reads lines exactly like:
A0: 112.5 | Supply ADC: 675.0 | Estimated R: 20.00 ohms | LED command: ON
It also recognises "Open / very high resistance" and "Check input wiring".
The previous CSV firmware is not required and is not included in this package.

YOUR CURRENT LED RULE
LOWER_LIMIT_OHMS = 12.0 and UPPER_LIMIT_OHMS = 30.0.
Therefore LED ON only for 12 < estimated resistance < 30 ohms.
Exactly 12 or 30 is OFF. This sketch has NO 30-second hold.
Your comments/startup message and diagram still say 10 ohms. Those labels
are outdated; the numeric constants and comparison control the LED.
Python displays Arduino's reported LED command without recalculating it
from rounded resistance. An ON command does not confirm physical light.

WINDOWS: FIRST SETUP
1. Extract this ZIP into a NEW folder to avoid mixing with the previous app.
2. If needed, install desktop Python 3.11 or newer from
   https://www.python.org/downloads/ . Include pip, Python launcher and
   Tcl/Tk (normally included). This runs on the USB-connected PC, not Kaggle.
3. Keep your pasted sketch on the Arduino. If not uploaded, open Arduino
   IDE, paste it into a sketch, select Arduino Uno and the correct COM port,
   then upload. Note that COM port (for example COM3).
4. You may verify the human-readable lines in Serial Monitor at 9600 baud.
   Then CLOSE Serial Monitor AND Serial Plotter before running Python.
5. Open the extracted Resistance_Logger folder. Click File Explorer's address
   bar, type powershell, and press Enter. Run:
      py -m pip install -r requirements.txt
      py resistance_logger.py
   If 'py' is unavailable but Python is installed, use 'python' instead in
   BOTH commands. On later runs double-click START_WINDOWS.bat, or rerun
   the second command. Dependencies only need installing once per environment.

RECORD AN EXPERIMENT
6. Select the Uno COM port; click Refresh if needed, then Connect.
   The title should say "Resistance logger v2 (Arduino text)".
   Opening the port often resets the Uno. Wait for a resistance reading.
7. Keep your sensor at rest. Click Start logging (.txt) and choose a path.
   The first VALID sample after saving defines baseline R0. Start pressing
   or stretching only after R0 appears in the window.
8. The upper graph plots R versus elapsed time. The lower plots Delta R.
   Delta R = R - R0; percent change = 100*(R-R0)/R0.
   Positive change means increased resistance; negative means decreased.
   The displayed LED status comes from Arduino, not a physical light sensor.
9. Click Stop logging when finished. The text file is already saved at your
   chosen location. Click Save graph (.png) to export the displayed graph.
10. Start logging again to make a new file with a new baseline. Disconnect
    Python before opening Serial Monitor or uploading another sketch.

TEXT FILE FORMAT
UTF-8 .txt with TAB-separated columns. In Excel/Origin choose TAB delimiter.
Skip the first five comment lines beginning '#'; line six is the header.
Columns:
pc_timestamp, elapsed_s, segment, resistance_ohm, baseline_ohm,
delta_R_ohm, delta_R_percent, a0_adc, supply_adc, led, status, raw_serial_line.
All received, recognised measurement lines are saved, even when R is outside
12-30 ohms and LED is off. The app does not filter by the LED condition.
Each row is flushed to disk immediately. Open/fault rows are recorded with
nan for unavailable resistance, and appear as gaps in the plots, not zeros.
If R0 is zero, relative percent is undefined (nan), but Delta R still works.
Malformed lines are skipped and counted visibly in the window.

TIMING / BASELINE
Your sketch sends no timestamp. elapsed_s is the PC's monotonic RECEIVE time
since Start logging; it is not an exact Arduino acquisition timestamp.
The actual row interval includes averaging, Serial prints and delay(100).
The app records every received line without assuming an exact 10 Hz rate.
If the startup message is received during logging, segment increments and
the next valid reading sets a new baseline. This is how a board reset is
identified. Without that startup message a reset cannot be detected reliably.
The first valid sample is a single-sample baseline, not an averaged calibration.

GRAPH / LONG RUNS
The graph keeps the latest 6000 rows to limit memory use. The text file keeps
ALL logged rows. Save graph exports only the displayed range.
Disable Auto-scale before using toolbar zoom/pan. After stopping, zoom and
save as desired. Re-enable Auto-scale for a new run.

CIRCUIT (your diagram, BUILD_OPTION=1)
3.3V -> 100 ohm reference -> A0 junction -> sample -> GND
A1 -> 3.3V before the reference resistor (NOT AREF)
D8 -> 100 ohm -> 100 ohm -> LED anode; LED cathode -> common GND
Python reads the resistance printed by Arduino; it does not re-estimate R
from rounded ADC readings. The same resistor tolerance, ADC and contact
errors still apply. Extra saved decimal places do not increase accuracy.
The program does not send control commands or change the LED thresholds.

TROUBLESHOOTING
Access denied / cannot open COM: close Serial Monitor/Plotter, other Arduino
IDE instances, and other serial apps; select the current port after reconnect.
No port: check USB data cable, power and Windows Device Manager > Ports.
Many skipped lines: use your pasted text-output sketch, not the old CSV one.
No plot: click Start logging and choose the output .txt file.
OPEN_OR_HIGH_R: check sample continuity, A0 connection and common ground.
CHECK_WIRING: inspect A0/A1 and supply wiring.
Serial disconnection stops logging; already flushed rows remain in the file.
Disk write errors stop logging and display an error.

DEMO WITHOUT ARDUINO
  py resistance_logger.py --demo
Click Connect, then Start logging. Title and file metadata explicitly label
synthetic data; these values are not experimental measurements.

VALIDATION
Eight automated checks cover exact text parsing, error lines, baseline and
change calculations, reset handling, zero baseline, reported LED state,
malformed lines, and fragmented serial delivery. Desktop GUI/physical Uno
operation still needs checking on your Windows PC.
Optional tests (standard Python library only): py -m unittest test_logger -v

IMPLEMENTATION REFERENCES
https://pyserial.readthedocs.io/en/latest/shortintro.html
https://matplotlib.org/stable/gallery/user_interfaces/embedding_in_tk_sgskip.html

Code was developed using AI to supplement manually designed and fabricate the electrical circuit.
