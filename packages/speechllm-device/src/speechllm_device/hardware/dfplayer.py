"""
DFPlayer Mini — UART Driver

Wire protocol is a fixed 10-byte frame at 9600 8N1:

    ┌──────┬──────┬──────┬─────┬─────┬────────┬────────┬───────┬───────┬──────┐
    │ 0x7E │ 0xFF │ 0x06 │ CMD │ ACK │ PARAM_H│ PARAM_L│ CHK_H │ CHK_L │ 0xEF │
    └──────┴──────┴──────┴─────┴─────┴────────┴────────┴───────┴───────┴──────┘

    0xFF = version, 0x06 = length of the checksummed region,
    checksum = -(0xFF + 0x06 + CMD + ACK + PARAM_H + PARAM_L) as int16.

Frame building is pure and lives apart from the serial transport, so the
protocol is unit-testable on a laptop with no hardware attached.

Playback is always addressed with CMD_PLAY_FOLDER_FILE (0x0F): folder in
PARAM_H, file in PARAM_L, resolved by *filename* on the card. The widely-copied
CMD 0x03 ("play the Nth file") resolves by FAT write order instead — re-copy a
card in a different order and every phrase shifts, which on this device means a
child hears the wrong response. Never use 0x03 here.

CLI smoke test (Milestone 3):

    python -m speechllm_device.hardware.dfplayer --folder 1 --track 7
    python -m speechllm_device.hardware.dfplayer --volume 20 --folder 2 --track 1
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Frame constants ──────────────────────────────────────────
START_BYTE = 0x7E
VERSION_BYTE = 0xFF
LENGTH_BYTE = 0x06
END_BYTE = 0xEF
FRAME_SIZE = 10

# ── Commands ─────────────────────────────────────────────────
CMD_NEXT = 0x01
CMD_PREV = 0x02
CMD_SET_VOLUME = 0x06
CMD_RESET = 0x0C
CMD_PLAYBACK = 0x0D
CMD_PAUSE = 0x0E
CMD_PLAY_FOLDER_FILE = 0x0F   # PARAM_H = folder 1-99, PARAM_L = file 1-255
CMD_STOP = 0x16
CMD_QUERY_STATUS = 0x42

# ── Module → host notifications ──────────────────────────────
NOTIFY_SD_INSERTED = 0x3A
NOTIFY_SD_REMOVED = 0x3B
NOTIFY_TRACK_FINISHED = 0x3D
NOTIFY_INIT_DONE = 0x3F
NOTIFY_ERROR = 0x40
NOTIFY_ACK = 0x41

ERROR_CODES = {
    0x01: "module busy",
    0x02: "device sleeping",
    0x03: "serial receive error",
    0x04: "checksum mismatch",
    0x05: "track number out of range",
    0x06: "track not found — check the file exists on the card",
    0x07: "insertion error",
    0x08: "SD card error",
    0x0A: "module sleeping",
}

VOLUME_MAX = 30
MAX_FOLDER = 99
MAX_FILE = 255

# The module needs time to mount the SD card after a reset. Under this it will
# answer commands with "track not found" for files that are actually present.
BOOT_DELAY_S = 2.0


class DFPlayerError(RuntimeError):
    """DFPlayer reported an error or failed to respond."""


# ── Pure protocol helpers (no I/O — unit tested on the laptop) ──


def checksum(cmd: int, ack: int, param_h: int, param_l: int) -> int:
    """Two's-complement checksum over the frame's payload region."""
    total = VERSION_BYTE + LENGTH_BYTE + cmd + ack + param_h + param_l
    return (-total) & 0xFFFF


def build_frame(cmd: int, param: int = 0, *, ack: bool = False) -> bytes:
    """Build a 10-byte command frame."""
    param_h = (param >> 8) & 0xFF
    param_l = param & 0xFF
    ack_byte = 0x01 if ack else 0x00
    chk = checksum(cmd, ack_byte, param_h, param_l)
    return bytes(
        [
            START_BYTE,
            VERSION_BYTE,
            LENGTH_BYTE,
            cmd,
            ack_byte,
            param_h,
            param_l,
            (chk >> 8) & 0xFF,
            chk & 0xFF,
            END_BYTE,
        ]
    )


def folder_file_param(folder: int, file: int) -> int:
    """Pack a folder/file pair into the 16-bit parameter of CMD 0x0F."""
    if not 1 <= folder <= MAX_FOLDER:
        raise ValueError(f"folder {folder} out of range 1-{MAX_FOLDER}")
    if not 1 <= file <= MAX_FILE:
        raise ValueError(f"file {file} out of range 1-{MAX_FILE}")
    return (folder << 8) | file


@dataclass(frozen=True)
class Frame:
    """A decoded frame received from the module."""

    cmd: int
    param: int

    @property
    def is_error(self) -> bool:
        return self.cmd == NOTIFY_ERROR

    @property
    def error_text(self) -> str:
        return ERROR_CODES.get(self.param, f"unknown error 0x{self.param:02X}")


def parse_frame(data: bytes) -> Frame | None:
    """Decode a 10-byte reply. Returns None if malformed.

    Checksum is verified but a mismatch is only logged, not fatal: some clone
    modules compute it incorrectly on notifications while still reporting the
    right command, and refusing those would make the device unusable.
    """
    if len(data) != FRAME_SIZE or data[0] != START_BYTE or data[-1] != END_BYTE:
        return None
    cmd = data[3]
    param = (data[5] << 8) | data[6]
    expected = checksum(cmd, data[4], data[5], data[6])
    actual = (data[7] << 8) | data[8]
    if expected != actual:
        logger.debug("DFPlayer checksum mismatch on 0x%02X (ignored)", cmd)
    return Frame(cmd=cmd, param=param)


# ── Serial transport ─────────────────────────────────────────


class DFPlayer:
    """Serial-attached DFPlayer Mini.

    Usage:
        with DFPlayer("/dev/ttyS5") as player:
            player.set_volume(22)
            player.play(folder=1, track=7)
    """

    def __init__(
        self,
        port: str,
        baud: int = 9600,
        *,
        timeout: float = 0.5,
        boot_delay_s: float = BOOT_DELAY_S,
    ):
        self._port_name = port
        self._baud = baud
        self._timeout = timeout
        self._boot_delay_s = boot_delay_s
        self._serial = None

    # ── Lifecycle ────────────────────────────────────────────

    def open(self) -> None:
        import serial  # imported lazily so the module can be unit tested without pyserial

        logger.info("Opening DFPlayer on %s @ %d baud", self._port_name, self._baud)
        self._serial = serial.Serial(
            self._port_name,
            self._baud,
            timeout=self._timeout,
            write_timeout=self._timeout,
        )
        self.reset()

    def close(self) -> None:
        if self._serial is not None:
            try:
                self.stop()
            except Exception:  # noqa: BLE001 - closing must never raise
                pass
            self._serial.close()
            self._serial = None

    def __enter__(self) -> DFPlayer:
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ── Commands ─────────────────────────────────────────────

    def _send(self, cmd: int, param: int = 0) -> None:
        if self._serial is None:
            raise DFPlayerError("DFPlayer port is not open — call open() first")
        frame = build_frame(cmd, param)
        logger.debug("DFPlayer → %s", frame.hex(" "))
        self._serial.reset_input_buffer()
        self._serial.write(frame)
        self._serial.flush()
        # The module drops commands sent back-to-back with no gap.
        time.sleep(0.05)
        self._drain_notifications()

    def _drain_notifications(self) -> None:
        """Read and log anything the module volunteered (errors, track-finished)."""
        if self._serial is None or self._serial.in_waiting < FRAME_SIZE:
            return
        while self._serial.in_waiting >= FRAME_SIZE:
            frame = parse_frame(self._serial.read(FRAME_SIZE))
            if frame is None:
                continue
            if frame.is_error:
                # Surfaced rather than raised: an error on one phrase should not
                # take down the whole session in front of a child.
                logger.error("DFPlayer error: %s", frame.error_text)
            elif frame.cmd == NOTIFY_TRACK_FINISHED:
                logger.debug("DFPlayer finished track %d", frame.param)
            elif frame.cmd == NOTIFY_SD_REMOVED:
                logger.error("DFPlayer SD card removed")

    def reset(self) -> None:
        """Reset the module and wait for the SD card to mount."""
        self._send(CMD_RESET)
        time.sleep(self._boot_delay_s)

    def set_volume(self, volume: int) -> None:
        """Set output volume, 0-30."""
        volume = max(0, min(VOLUME_MAX, volume))
        self._send(CMD_SET_VOLUME, volume)

    def play(self, folder: int, track: int) -> None:
        """Play `/<folder:02d>/<track:03d>.mp3` by filename."""
        self._send(CMD_PLAY_FOLDER_FILE, folder_file_param(folder, track))

    def stop(self) -> None:
        self._send(CMD_STOP)

    def pause(self) -> None:
        self._send(CMD_PAUSE)


# ── CLI smoke test ───────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="DFPlayer Mini smoke test")
    parser.add_argument(
        "--port", default=None, help="serial port (default: settings.dfplayer_port)"
    )
    parser.add_argument("--folder", type=int, default=1)
    parser.add_argument("--track", type=int, default=1)
    parser.add_argument("--volume", type=int, default=None)
    parser.add_argument("--wait", type=float, default=4.0, help="seconds to hold the port open")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s │ %(levelname)-7s │ %(message)s",
        datefmt="%H:%M:%S",
    )

    from speechllm_core.settings import settings

    port = args.port or settings.dfplayer_port
    volume = args.volume if args.volume is not None else settings.dfplayer_volume

    with DFPlayer(port) as player:
        player.set_volume(volume)
        print(f"Playing /{args.folder:02d}/{args.track:03d}.mp3 at volume {volume}")
        player.play(args.folder, args.track)
        time.sleep(args.wait)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
