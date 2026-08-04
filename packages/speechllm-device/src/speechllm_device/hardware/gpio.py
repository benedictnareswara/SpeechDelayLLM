"""
GPIO — DFPlayer BUSY line

The DFPlayer's BUSY pin (module pin 16) is LOW while audio is playing and HIGH
when idle. It is wired to PI0, physical pin 11 on the Orange Pi Zero 3's 26-pin
header.

This is the ground truth for "the device is currently speaking", and the
pipeline uses it to keep the microphone gated. Without it the speaker — inches
from the mic — gets transcribed as if it were the child, and the device talks
to itself in a loop.

GPIO numbering on the Allwinner BSP kernel is `bank_index * 32 + pin`, with
banks A=0 … I=8. PI0 is therefore 8*32 + 0 = 256.

Three backends, tried in order:
  1. libgpiod  — preferred, present as python3-libgpiod on Ubuntu Jammy
  2. sysfs     — /sys/class/gpio, deprecated but reliable on kernel 5.4 BSP
  3. mock      — laptop development; reports "never busy"
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

SYSFS_ROOT = Path("/sys/class/gpio")


class BusyPin(Protocol):
    """Reads the DFPlayer BUSY line."""

    def is_busy(self) -> bool:
        """True while audio is playing (pin LOW)."""
        ...

    def close(self) -> None: ...


class MockBusyPin:
    """Laptop stand-in. Always reports idle.

    Callers must not rely on this to time playback — the null sink and the
    orchestrator fall back to manifest durations when the pin is mocked.
    """

    available = False

    def is_busy(self) -> bool:
        return False

    def close(self) -> None:
        pass


class GpiodBusyPin:
    """libgpiod backend (v1 or v2 API)."""

    available = True

    def __init__(self, chip: str = "gpiochip0", line: int = 256):
        import gpiod

        self._gpiod = gpiod
        self._line_offset = line
        self._v2 = hasattr(gpiod, "request_lines")

        if self._v2:
            self._request = gpiod.request_lines(
                f"/dev/{chip}",
                consumer="speechllm-busy",
                config={line: gpiod.LineSettings(direction=gpiod.line.Direction.INPUT)},
            )
        else:
            self._chip = gpiod.Chip(chip)
            self._line = self._chip.get_line(line)
            self._line.request(consumer="speechllm-busy", type=gpiod.LINE_REQ_DIR_IN)

    def is_busy(self) -> bool:
        if self._v2:
            value = self._request.get_value(self._line_offset)
            return value == self._gpiod.line.Value.INACTIVE
        return self._line.get_value() == 0

    def close(self) -> None:
        if self._v2:
            self._request.release()
        else:
            self._line.release()
            self._chip.close()


class SysfsBusyPin:
    """Legacy /sys/class/gpio backend for the Allwinner BSP kernel."""

    available = True

    def __init__(self, line: int = 256):
        self._line = line
        self._path = SYSFS_ROOT / f"gpio{line}"
        self._exported_by_us = False

        if not self._path.exists():
            (SYSFS_ROOT / "export").write_text(str(line))
            self._exported_by_us = True
            # udev needs a moment to create and chown the attribute files.
            for _ in range(50):
                if (self._path / "value").exists():
                    break
                time.sleep(0.02)

        (self._path / "direction").write_text("in")
        self._value_file = self._path / "value"

    def is_busy(self) -> bool:
        # Re-open each read: sysfs GPIO value files do not refresh on a cached
        # file handle without an explicit seek.
        return self._value_file.read_text().strip() == "0"

    def close(self) -> None:
        if self._exported_by_us:
            try:
                (SYSFS_ROOT / "unexport").write_text(str(self._line))
            except OSError:
                pass


def open_busy_pin(chip: str = "gpiochip0", line: int = 256, *, force_mock: bool = False) -> BusyPin:
    """Open the BUSY pin using the best backend available on this machine."""
    if force_mock:
        logger.info("BUSY pin: mock backend (forced)")
        return MockBusyPin()

    try:
        pin = GpiodBusyPin(chip, line)
        logger.info("BUSY pin: libgpiod on %s line %d", chip, line)
        return pin
    except Exception as e:  # noqa: BLE001 - any failure means try the next backend
        logger.debug("libgpiod unavailable (%s), trying sysfs", e)

    try:
        pin = SysfsBusyPin(line)
        logger.info("BUSY pin: sysfs gpio%d", line)
        return pin
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "No GPIO backend available (%s). Falling back to mock: playback will be "
            "timed from manifest durations instead of the BUSY line.",
            e,
        )

    return MockBusyPin()
