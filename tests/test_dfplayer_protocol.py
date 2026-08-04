"""
Tests for the DFPlayer Mini wire protocol.

Frame construction is pure, so it is fully testable without the module attached.
Expected byte sequences are taken from the DFPlayer datasheet's worked examples.
"""

import pytest
from speechllm_device.hardware.dfplayer import (
    CMD_PLAY_FOLDER_FILE,
    CMD_RESET,
    CMD_SET_VOLUME,
    FRAME_SIZE,
    NOTIFY_ERROR,
    NOTIFY_TRACK_FINISHED,
    build_frame,
    checksum,
    folder_file_param,
    parse_frame,
)


class TestFrameStructure:
    def test_frame_is_ten_bytes(self):
        assert len(build_frame(CMD_SET_VOLUME, 20)) == FRAME_SIZE

    def test_frame_delimiters(self):
        frame = build_frame(CMD_SET_VOLUME, 20)
        assert frame[0] == 0x7E
        assert frame[1] == 0xFF
        assert frame[2] == 0x06
        assert frame[-1] == 0xEF

    def test_command_and_params_land_in_the_right_slots(self):
        frame = build_frame(CMD_PLAY_FOLDER_FILE, folder_file_param(2, 5))
        assert frame[3] == CMD_PLAY_FOLDER_FILE
        assert frame[5] == 2   # PARAM_H = folder
        assert frame[6] == 5   # PARAM_L = file

    def test_ack_byte_toggles(self):
        assert build_frame(CMD_RESET, ack=False)[4] == 0x00
        assert build_frame(CMD_RESET, ack=True)[4] == 0x01


class TestChecksum:
    def test_known_value(self):
        # Set volume to 30: 7E FF 06 06 00 00 1E EF where checksum = -(FF+06+06+00+00+1E)
        expected = (-(0xFF + 0x06 + 0x06 + 0x00 + 0x00 + 0x1E)) & 0xFFFF
        assert checksum(0x06, 0x00, 0x00, 0x1E) == expected

    def test_checksum_is_placed_big_endian(self):
        frame = build_frame(CMD_SET_VOLUME, 30)
        chk = checksum(CMD_SET_VOLUME, 0x00, 0x00, 30)
        assert frame[7] == (chk >> 8) & 0xFF
        assert frame[8] == chk & 0xFF

    def test_checksum_fits_in_two_bytes(self):
        for cmd in range(0x00, 0x50):
            for param in (0, 1, 255, 3000, 0xFFFF):
                value = checksum(cmd, 0, (param >> 8) & 0xFF, param & 0xFF)
                assert 0 <= value <= 0xFFFF

    def test_built_frames_are_self_consistent(self):
        # Every frame we emit must parse back to the command we asked for.
        for cmd, param in [(CMD_RESET, 0), (CMD_SET_VOLUME, 15), (CMD_PLAY_FOLDER_FILE, 0x0107)]:
            parsed = parse_frame(build_frame(cmd, param))
            assert parsed is not None
            assert parsed.cmd == cmd
            assert parsed.param == param


class TestFolderFileParam:
    def test_packs_folder_high_file_low(self):
        assert folder_file_param(1, 7) == 0x0107
        assert folder_file_param(2, 255) == 0x02FF

    @pytest.mark.parametrize("folder", [0, 100, -1])
    def test_rejects_bad_folder(self, folder):
        with pytest.raises(ValueError):
            folder_file_param(folder, 1)

    @pytest.mark.parametrize("file", [0, 256, -1])
    def test_rejects_bad_file(self, file):
        with pytest.raises(ValueError):
            folder_file_param(1, file)

    def test_covers_the_whole_phrase_bank(self):
        from speechllm_core.bank.numbering import BANK_FOLDER, iter_bank_entries

        for entry in iter_bank_entries():
            assert folder_file_param(BANK_FOLDER, entry.track) > 0


class TestParsing:
    def test_rejects_wrong_length(self):
        assert parse_frame(b"\x7e\xff\x06") is None

    def test_rejects_bad_delimiters(self):
        bad = bytearray(build_frame(CMD_RESET))
        bad[0] = 0x00
        assert parse_frame(bytes(bad)) is None

    def test_decodes_track_finished(self):
        frame = build_frame(NOTIFY_TRACK_FINISHED, 42)
        parsed = parse_frame(frame)
        assert parsed.cmd == NOTIFY_TRACK_FINISHED
        assert parsed.param == 42
        assert not parsed.is_error

    def test_decodes_error_with_text(self):
        parsed = parse_frame(build_frame(NOTIFY_ERROR, 0x06))
        assert parsed.is_error
        assert "not found" in parsed.error_text

    def test_unknown_error_code_still_reports(self):
        parsed = parse_frame(build_frame(NOTIFY_ERROR, 0xEE))
        assert parsed.is_error
        assert "0xEE" in parsed.error_text

    def test_bad_checksum_is_tolerated(self):
        # Clone modules miscompute checksums on notifications; rejecting those
        # frames outright would make the device unusable.
        corrupted = bytearray(build_frame(NOTIFY_TRACK_FINISHED, 1))
        corrupted[7] ^= 0xFF
        parsed = parse_frame(bytes(corrupted))
        assert parsed is not None
        assert parsed.cmd == NOTIFY_TRACK_FINISHED
