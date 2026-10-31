# Nanoleaf Lightstrip controller

Custom controller and live visualiser for the Nanoleaf PC Screen Mirror Lightstrip (NL82K2, USB `37FA:8202`).
See `CHANGES.md` for what was fixed and added compared with the single-file original.

## Install
```
pip install hidapi pillow        # hidapi: hardware. pillow: glow preview + Screen mirror
pip install mss                  # optional: faster screen capture
```
Install **hidapi**, not the unrelated package called `hid`. Quit the Nanoleaf Desktop app first.
On Linux you may also need `python3-tk` and a udev rule for the device.

## Run
```
python run.py                        # GUI + real strip
python run.py --sim                  # GUI only, no hardware
python run.py --headless --effect "Screen mirror"
python run.py --probe                # USB diagnostics + colour test sweep
python run.py --list-effects
python run.py --help
```
Also works as `python -m nanoleaf_strip`.

### Setting up the layout
In the window, pick the start corner and direction so the ringed LED in the preview matches LED 0 on your monitor.
Use **Shift by** if the strip starts a few LEDs off the corner. Screen mirror uses the same layout.

### Safety options (remembered)
| Option | Effect |
|---|---|
| `--on-exit off\|leave` | blank and power down on quit (default `off`) |
| `--max-brightness N` | hard ceiling on hardware brightness |
| `--power-limit 0.5` | cap total LED draw at half of full white |
| `--button-action none` | stop the strip's button from cycling effects |

Settings live in `%APPDATA%\nanoleaf-strip\config.json` (Windows), `~/Library/Application Support/nanoleaf-strip/` (macOS)
or `~/.config/nanoleaf-strip/` (Linux). Use `--no-save` to ignore them.

## Layout of the code
```
run.py                      launcher
nanoleaf_strip/
  cli.py  runtime.py        argument parsing; wires everything together
  engine.py                 animation clock thread (effects -> frames)
  worker.py                 I/O thread: reconnect, retry, dead-man switch, power limiter
  settings.py  layout.py    live settings + persistence; strip geometry
  frame.py                  colour helpers, frame sanitising, crossfade
  procs.py  instance.py     Nanoleaf Desktop detection; single-instance lock
  diagnostics.py            --probe
  devices/                  base interface, USB HID (usb.py), simulator, HID descriptor parser
  effects/                  base, classic, extras, screen (add yours to effects/__init__.py)
  gui/                      theme, widgets, render (Pillow), preview (Tk canvas), app (window)
tests/                      python -m unittest discover -s tests -t .
```

## Adding an effect
```python
class Pulse(Effect):
    name = "Pulse"
    uses_color = True
    def render(self, ctx):            # ctx.n zones, ctx.phase clock, ctx.dt, ctx.color, ctx.layout
        return [scale(ctx.color, 0.5 + 0.5 * math.sin(ctx.phase * 3))] * ctx.n
```
Append it to `ALL_EFFECTS` in `effects/__init__.py`.

## Tests
```
python -m unittest discover -s tests -t .
xvfb-run python -m unittest discover -s tests -t .     # also runs the real-window smoke test
```
