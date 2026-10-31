# Analysis of the original script, and what changed

## What the original did well
- The USB framing logic is careful: it reads the HID report descriptor, and on Windows works out the real report size by probing writes. That logic is kept as is.
- It already had a sensible worker/GUI split and a simulation mode.

## Problems found

**Bugs**
1. The speed slider had no effect on Fire, because the effect received an unscaled `dt`.
2. Fire's colour ramp used `>` where the heat-colour algorithm needs bit tests, so each colour band started one step late.
3. A frame was marked "sent" before the write happened, so a failed write silently dropped it.
4. Reconnecting had no backoff, so a missing strip was polled and re-enumerated constantly.
5. Frame length was never checked against the strip, so a frame of the wrong size went straight to the device.
6. Status fields were written by the worker thread and read by the GUI with no synchronisation.
7. One `except ImportError` around the whole GUI could hide real errors, and the worker was already streaming before the tkinter check ran.
8. Dragging the brightness slider re-sent the power command as well as brightness on every step.
9. Installing the wrong package (`pip install hid`) gave a confusing failure instead of a clear message.
10. Physical-button events were parsed, then thrown away.
11. The "Nanoleaf Desktop is running" check started a new thread and subprocess every 5 s, and matched on a bare substring.
12. No DPI awareness on Windows, so the window was bitmap-scaled and blurry.
13. The animation clock lived in the Tk main loop. A modal dialog (the colour picker) or any GUI stall could freeze the strip.
14. On exit the strip stayed lit on its last frame.

**Design limits**
- No settings persistence, no headless mode, no way to run without tkinter.
- The window was fixed-size, and the preview's fake glow only worked against one flat background colour.
- "Screen mirror" strip, but no screen mirroring.

## What was added

**Failsafes**
- The animation engine is its own thread, so GUI stalls and dialogs can't freeze the strip.
- An effect that raises an exception shows black and reports the error; the loop keeps going.
- Dead-man switch: if no frames arrive for 4 s, the strip is blanked instead of freezing on a colour.
- Reconnect with exponential backoff (0.5 s up to 5 s, with jitter), and any unexpected I/O error is treated like a dropped link.
- Frames are retried after a failed write, and resampled/clamped to the strip's length.
- Optional hard brightness ceiling (`--max-brightness`) and power limiter (`--power-limit`).
- Strip is blanked and powered down on quit (`--on-exit leave` restores the old behaviour); handles Ctrl+C, SIGTERM and window close.
- One-copy-at-a-time lock, so two instances can't fight over the strip.
- Settings are written atomically; a corrupt settings file is set aside as `.bad` rather than crashing startup.
- Clear error if the wrong `hid` package is installed.

**Features**
- Screen mirror effect (samples the monitor edges, with smoothing and saturation boost).
- New effects: Aurora, Scanner, Twinkle, Gradient (two colours).
- Crossfade when switching effects.
- Layout control: start corner, direction and shift, shared by the preview and the screen mirror so they agree.
- The strip's physical button cycles effects (`--button-action none` disables).
- Settings remembered between runs; `--headless`, `--effect`, `--color`, `--list-effects`.
- Device model, firmware and zone count shown in the window.
- Keyboard: Ctrl+Left / Ctrl+Right change effect, Ctrl+P toggles power.

**Modernised look**
- Resizable window with a gradient and vignette backdrop.
- Preview renders real additive glow (bloom) with anti-aliased LEDs, plus a ring on LED 0.
- Custom pill switch, swatch buttons and labelled sliders; native-font selection; DPI awareness.
- Falls back to a plain dot preview if Pillow is missing.

## Not verified
- No real strip was available. The USB layer is tested against a fake HID device that speaks the TLV protocol (multi-chunk frames, button events, failures), which covers the non-Windows path. The Windows write-size probing is unchanged from the original and has not been exercised.
- The meaning of the button event payload isn't documented, so any event counts as a press (debounced).
- Screen mirror is tested with injected frames, not a live capture.
