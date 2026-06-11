# The MIT License (MIT)

# Copyright (c) 2021-2024 Krux contributors

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import lcd
import sensor
import time
from . import Page, FLASH_MSG_TIME
from ..wdt import wdt
from ..krux_settings import t
from ..camera import BINARY_GRID_MODE
from ..kboard import kboard
from .tiny_seed import to_words, check_sum_bg

# Stackbit 1248 full plate: 85mm x 54mm, 16 columns x 12 rows, 12 words
GRID_COLS = 16
GRID_ROWS = 12
# Each half stores 6 words, one per pair of rows: an engraved index column,
# a thousands column and three column pairs in 1248 code
WORDS_PER_HALF = 6
HALF_COL_OFFSETS = (0, 8)
# Plate aspect ratio = 85 / 54 ~ 1.57
ASPECT_LOW = 1.3
ASPECT_HIGH = 1.85
# Checksum masks: 4 bits for 12 words, 8 bits for 24 words
CHECKSUM_12W_MASK = 0b00000001111
CHECKSUM_24W_MASK = 0b00011111111


class StackbitScanner(Page):
    """Uses the camera to read the punch pattern of a Stackbit 1248 metal plate"""

    def __init__(self, ctx):
        super().__init__(ctx, None)
        self.ctx = ctx
        self.capturing = False  # Flag used for first page of 24 words seed
        self.x_regions = []
        self.y_regions = []
        self.blob_otsu = 0x80
        self.punch_threshold = 0x80
        self.previous_numbers = [0] * 12

    def _detect_plate(self, img):
        """Detects the plate as a bright blob with the 1248 plate aspect ratio"""
        try:
            self.blob_otsu = img.get_histogram().get_threshold().value()
        except Exception:
            pass
        blobs = img.find_blobs(
            [(self.blob_otsu, 255)], x_stride=10, y_stride=10, area_threshold=5000
        )
        best_rect = None
        best_diff = float("inf")
        medium_aspect = (ASPECT_LOW + ASPECT_HIGH) / 2
        for blob in blobs:
            rect = blob.rect()
            if not rect[3]:
                continue
            aspect = rect[2] / rect[3]
            if (
                rect[0] >= 0
                and rect[1] >= 0
                and rect[0] + rect[2] < img.width()
                and rect[1] + rect[3] < img.height()
                and ASPECT_LOW < aspect < ASPECT_HIGH
            ):
                diff = abs(aspect - medium_aspect)
                if diff < best_diff:
                    best_diff = diff
                    best_rect = rect
        if best_rect:
            img.draw_rectangle(best_rect, lcd.WHITE, thickness=2)
        return best_rect

    def _map_punches_region(self, rect):
        """Maps the 16x12 grid cell boundaries over the detected plate"""
        x, y, w, h = rect
        self.x_regions = [x + (i * w) // GRID_COLS for i in range(GRID_COLS + 1)]
        self.y_regions = [y + (i * h) // GRID_ROWS for i in range(GRID_ROWS + 1)]

    def _read_cell(self, img, col, row):
        """Evaluates a cell's luminosity and draws feedback if punched"""
        x = self.x_regions[col]
        y = self.y_regions[row]
        inset_x = (self.x_regions[col + 1] - x) // 4
        inset_y = (self.y_regions[row + 1] - y) // 4
        eval_rect = (
            x + inset_x,
            y + inset_y,
            self.x_regions[col + 1] - x - 2 * inset_x,
            self.y_regions[row + 1] - y - 2 * inset_y,
        )
        if img.get_statistics(roi=eval_rect).median() < self.punch_threshold:
            img.draw_rectangle(eval_rect, color=lcd.WHITE)
            return True
        return False

    def _decode_word(self, img, col_offset, row):
        """Decodes one word number from its pair of rows, 0 if punches are invalid"""
        # Thousands digit: upper row=1, lower row=2
        digits = [
            self._read_cell(img, col_offset + 1, row)
            + 2 * self._read_cell(img, col_offset + 1, row + 1)
        ]
        # Hundreds, tens and units digits: upper row=1|2, lower row=4|8
        for col in range(col_offset + 2, col_offset + 8, 2):
            digits.append(
                self._read_cell(img, col, row)
                + 2 * self._read_cell(img, col + 1, row)
                + 4 * self._read_cell(img, col, row + 1)
                + 8 * self._read_cell(img, col + 1, row + 1)
            )
        if digits[0] > 2 or max(digits[1:]) > 9:
            return 0
        return digits[0] * 1000 + digits[1] * 100 + digits[2] * 10 + digits[3]

    def _detect_punches(self, img, rect):
        """Reads all plate cells and returns 12 word numbers"""
        try:
            self.punch_threshold = img.get_histogram(roi=rect).get_threshold().value()
        except Exception:
            pass
        numbers = []
        for col_offset in HALF_COL_OFFSETS:
            for word in range(WORDS_PER_HALF):
                numbers.append(self._decode_word(img, col_offset, 2 * word))
        return numbers

    def _checksum_ok(self, numbers):
        """Checks the BIP39 checksum bits punched on the last word"""
        mask = CHECKSUM_12W_MASK if len(numbers) == 12 else CHECKSUM_24W_MASK
        return check_sum_bg(numbers) == (numbers[-1] - 1) & mask

    def _stable(self, numbers):
        """True only if the reading repeats the previous frame"""
        if numbers == self.previous_numbers:
            return True
        self.previous_numbers = numbers
        return False

    def _check_buttons(self, w24, page):
        if self.ctx.input.enter_event() or self.ctx.input.touch_event(
            validate_position=False
        ):
            if w24 and page == 0:
                self.capturing = True
            else:
                return True
        if self.ctx.input.page_event() or self.ctx.input.page_prev_event():
            return True
        return False

    def _run_camera(self):
        """Turns camera on and rotates screen to landscape"""
        sensor.run(1)
        self.ctx.display.clear()
        self.ctx.display.to_landscape()

    def _exit_camera(self):
        sensor.run(0)
        self.ctx.display.to_portrait()
        self.ctx.display.clear()

    def _capture_first_page(self, numbers):
        """Captures the first plate face once stable and triggered by the user"""
        if not (self._stable(numbers) and self.capturing):
            return None
        self.capturing = False
        self.previous_numbers = [0] * 12
        self._exit_camera()
        self.flash_text(t("Scanning words 13-24") + "\n\n" + t("Wait for the capture"))
        self._run_camera()
        return numbers

    def scanner(self, w24=False):
        """Scans a Stackbit 1248 plate, one face for 12 words or both for 24"""
        page = 0
        first_page_numbers = []
        self.ctx.display.clear()
        message = t("TOUCH or ENTER to capture") if w24 else t("Wait for the capture")
        self.ctx.display.draw_centered_text(message)
        precamera_ticks = time.ticks_ms()
        self.ctx.camera.initialize_run(mode=BINARY_GRID_MODE)
        self.ctx.camera.zoom_mode()
        self.ctx.display.to_landscape()
        postcamera_ticks = time.ticks_ms()
        delay = precamera_ticks + FLASH_MSG_TIME - postcamera_ticks
        if delay > 0:
            time.sleep_ms(delay)
        self.ctx.input.reset_ios_state()
        self.ctx.display.clear()

        words = None
        while True:
            wdt.feed()
            numbers = None
            img = self.ctx.camera.snapshot()
            rect = self._detect_plate(img)
            if rect:
                self._map_punches_region(rect)
                numbers = self._detect_punches(img, rect)
            if kboard.is_m5stickv:
                img.lens_corr(strength=1.0, zoom=0.56)
            if kboard.is_amigo:
                lcd.display(img, oft=(80, 40))
            else:
                lcd.display(img)
            if numbers and all(0 < number <= 2048 for number in numbers):
                if not w24:
                    if self._checksum_ok(numbers) and self._stable(numbers):
                        words = to_words(numbers)
                        break
                elif page == 0:
                    if self._capture_first_page(numbers):
                        first_page_numbers = numbers
                        page = 1
                else:
                    full_numbers = first_page_numbers + numbers
                    if self._checksum_ok(full_numbers) and self._stable(numbers):
                        words = to_words(full_numbers)
                        break
            if self._check_buttons(w24, page):
                break

        self._exit_camera()
        if words:
            self.ctx.display.draw_centered_text(
                t("Review scanned data, edit if necessary")
            )
            self.ctx.input.wait_for_button()
            self.ctx.display.clear()
        return words
