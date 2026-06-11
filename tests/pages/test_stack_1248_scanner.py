from . import create_ctx

TEST_12_WORDS_NUMBERS = [1] * 11 + [4]
TEST_12_WORDS = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon about"
)


def test_detect_plate(m5stickv, mocker):
    """Picks the brightest blob matching the 1248 plate aspect ratio"""
    import lcd
    from krux.pages.stack_1248_scanner import StackbitScanner

    PLATE_RECT = (10, 10, 157, 100)  # aspect ~1.57

    def mock_blob(rect):
        blob = mocker.MagicMock()
        blob.rect.return_value = rect
        return blob

    ctx = create_ctx(mocker, [])
    scanner = StackbitScanner(ctx)
    img = mocker.MagicMock()
    img.width.return_value = 320
    img.height.return_value = 240
    img.get_histogram.return_value.get_threshold.return_value.value.return_value = 0x80
    img.find_blobs.return_value = [
        mock_blob((10, 10, 50, 0)),  # zero height
        mock_blob((10, 10, 100, 100)),  # square, wrong aspect
        mock_blob((200, 10, 157, 100)),  # out of image bounds
        mock_blob(PLATE_RECT),
    ]

    rect = scanner._detect_plate(img)

    assert rect == PLATE_RECT
    img.draw_rectangle.assert_called_once_with(PLATE_RECT, lcd.WHITE, thickness=2)


def test_detect_plate_not_found(m5stickv, mocker):
    """Returns None when no blob matches the plate aspect ratio"""
    from krux.pages.stack_1248_scanner import StackbitScanner

    ctx = create_ctx(mocker, [])
    scanner = StackbitScanner(ctx)
    img = mocker.MagicMock()
    img.width.return_value = 320
    img.height.return_value = 240
    img.get_histogram.return_value.get_threshold.side_effect = Exception
    img.find_blobs.return_value = []

    assert scanner._detect_plate(img) is None
    img.draw_rectangle.assert_not_called()


def test_detect_punches(m5stickv, mocker):
    """Decodes 12 word numbers from a punched plate image"""
    from krux.pages.stack_1248_scanner import StackbitScanner

    PUNCHED = 0x30
    NON_PUNCHED = 0xA0
    # abandon (0001) x11 + about (0004): units digit on column 6 (left half)
    # and column 14 (right half), bit 1 on the upper row, bit 4 on the lower
    PUNCHED_CELLS = {(6, 2 * word) for word in range(6)}
    PUNCHED_CELLS |= {(14, 2 * word) for word in range(5)}
    PUNCHED_CELLS.add((14, 11))

    def mock_statistics(roi):
        stats = mocker.MagicMock()
        cell = (roi[0] // 10, roi[1] // 10)
        stats.median.return_value = NON_PUNCHED
        if cell in PUNCHED_CELLS:
            stats.median.return_value = PUNCHED
        return stats

    ctx = create_ctx(mocker, [])
    scanner = StackbitScanner(ctx)
    rect = (0, 0, 160, 120)
    scanner._map_punches_region(rect)
    img = mocker.MagicMock()
    # Failing to compute Otsu threshold keeps the previous one (0x80 default)
    img.get_histogram.return_value.get_threshold.side_effect = Exception
    img.get_statistics.side_effect = mock_statistics

    assert scanner._detect_punches(img, rect) == TEST_12_WORDS_NUMBERS


def test_decode_word_invalid_punches(m5stickv, mocker):
    """Invalid punch combinations decode to 0"""
    from krux.pages.stack_1248_scanner import StackbitScanner

    cases = [
        # (label, punched cells, expected number)
        ("Valid 2048", {(1, 1), (4, 1), (7, 1)}, 2048),
        ("Both thousands rows", {(1, 0), (1, 1)}, 0),
        ("Digit above 9", {(3, 0), (3, 1)}, 0),  # 2 + 8 = 10
    ]
    ctx = create_ctx(mocker, [])
    scanner = StackbitScanner(ctx)
    img = mocker.MagicMock()

    for i, (label, punched_cells, expected) in enumerate(cases):
        print("Case %d: %s" % (i, label))
        mocker.patch.object(
            scanner,
            "_read_cell",
            new=lambda img, col, row, cells=punched_cells: (col, row) in cells,
        )
        assert scanner._decode_word(img, 0, 0) == expected


def test_scanner_12w(multiple_devices, mocker):
    """Skips invalid readings and returns the mnemonic after two stable ones"""
    from krux.pages.stack_1248_scanner import StackbitScanner
    from krux.input import BUTTON_ENTER

    BTN_SEQUENCE = [BUTTON_ENTER]  # Review scanned data message
    PLATE_RECT = (10, 10, 157, 100)
    NUMBERS_SEQUENCE = [
        [0] * 12,  # Out of range reading
        [1] * 11 + [5],  # Wrong checksum reading
        TEST_12_WORDS_NUMBERS,
        TEST_12_WORDS_NUMBERS,
    ]

    ctx = create_ctx(mocker, BTN_SEQUENCE)
    mocker.patch.object(ctx.input, "enter_event", new=lambda: False)
    mocker.patch.object(
        ctx.input, "touch_event", new=lambda validate_position=False: False
    )
    mocker.patch.object(ctx.input, "page_event", new=lambda: False)
    mocker.patch.object(ctx.input, "page_prev_event", new=lambda: False)
    scanner = StackbitScanner(ctx)
    mocker.patch.object(scanner, "_detect_plate", new=lambda img: PLATE_RECT)
    scanner._detect_punches = mocker.MagicMock(side_effect=NUMBERS_SEQUENCE)

    words = scanner.scanner()

    assert ctx.input.wait_for_button.call_count == len(BTN_SEQUENCE)
    assert " ".join(words) == TEST_12_WORDS


def test_scanner_24w(multiple_devices, mocker):
    """Captures the first face on user trigger, the second by the 24w checksum"""
    from krux.pages.stack_1248_scanner import StackbitScanner
    from krux.input import BUTTON_ENTER

    BTN_SEQUENCE = [BUTTON_ENTER]  # Review scanned data message
    PLATE_RECT = (10, 10, 157, 100)
    WORDS_NUMBERS_1_12 = [
        1090,
        792,
        1005,
        1978,
        408,
        569,
        1498,
        589,
        192,
        134,
        617,
        663,
    ]
    WORDS_NUMBERS_13_24 = [
        1275,
        1982,
        1747,
        978,
        509,
        1588,
        1456,
        15,
        1592,
        1612,
        1056,
        771,
    ]
    NUMBERS_SEQUENCE = [WORDS_NUMBERS_1_12] * 2 + [WORDS_NUMBERS_13_24] * 2
    ENTER_SEQ = [True] + [False] * 3
    TEST_24_WORDS = (
        "market glass laugh warm cream either robot end blood awful escape fan "
        "palm waste surge kick display shoe remove achieve shoulder siren loop gate"
    )

    ctx = create_ctx(mocker, BTN_SEQUENCE)
    ctx.input.enter_event = mocker.MagicMock(side_effect=ENTER_SEQ)
    mocker.patch.object(
        ctx.input, "touch_event", new=lambda validate_position=False: False
    )
    mocker.patch.object(ctx.input, "page_event", new=lambda: False)
    mocker.patch.object(ctx.input, "page_prev_event", new=lambda: False)
    scanner = StackbitScanner(ctx)
    mocker.patch.object(scanner, "_detect_plate", new=lambda img: PLATE_RECT)
    scanner._detect_punches = mocker.MagicMock(side_effect=NUMBERS_SEQUENCE)

    words = scanner.scanner(w24=True)

    assert ctx.input.wait_for_button.call_count == len(BTN_SEQUENCE)
    assert " ".join(words) == TEST_24_WORDS


def test_scanner_canceled(m5stickv, mocker):
    """Returns None when the user presses a button to leave the scanner"""
    from krux.pages.stack_1248_scanner import StackbitScanner

    cases = [
        # (label, enter_event, page_event)
        ("Canceled with ENTER", True, False),
        ("Canceled with PAGE", False, True),
    ]

    for i, (label, enter_event, page_event) in enumerate(cases):
        print("Case %d: %s" % (i, label))
        ctx = create_ctx(mocker, [])
        mocker.patch.object(ctx.input, "enter_event", new=lambda e=enter_event: e)
        mocker.patch.object(
            ctx.input, "touch_event", new=lambda validate_position=False: False
        )
        mocker.patch.object(ctx.input, "page_event", new=lambda e=page_event: e)
        mocker.patch.object(ctx.input, "page_prev_event", new=lambda: False)
        scanner = StackbitScanner(ctx)
        mocker.patch.object(scanner, "_detect_plate", new=lambda img: None)

        assert scanner.scanner() is None


def test_load_key_from_camera_menu_stackbit(m5stickv, mocker):
    """Selecting Stackbit 1248 on the camera submenu calls its handler"""
    from krux.pages.mnemonic_loader import MnemonicLoader
    from krux.pages import MENU_CONTINUE
    from krux.input import BUTTON_ENTER, BUTTON_PAGE

    BTN_SEQUENCE = [
        *([BUTTON_PAGE] * 4),  # Move to "Stackbit 1248"
        BUTTON_ENTER,  # Select "Stackbit 1248"
        BUTTON_PAGE,  # Move to back
        BUTTON_ENTER,  # Press back
    ]
    ctx = create_ctx(mocker, BTN_SEQUENCE)
    loader = MnemonicLoader(ctx)
    mocker.patch.object(loader, "load_key_from_1248_scan", return_value=MENU_CONTINUE)

    loader.load_key_from_camera()

    loader.load_key_from_1248_scan.assert_called_once()
    assert ctx.input.wait_for_button.call_count == len(BTN_SEQUENCE)


def test_load_key_from_1248_scan(m5stickv, mocker):
    """Scanned words are loaded, a failed scan flashes an error"""
    from krux.pages.mnemonic_loader import MnemonicLoader
    from krux.pages import MENU_CONTINUE
    from krux.input import BUTTON_ENTER, BUTTON_PAGE

    TEST_WORDS = TEST_12_WORDS.split()
    cases = [
        # (label, btn_sequence, w24, scanned words, load calls, error calls)
        (
            "12 words scan succeeded",
            [BUTTON_ENTER, BUTTON_ENTER],
            False,
            TEST_WORDS,
            1,
            0,
        ),
        (
            "24 words scan failed",
            [BUTTON_PAGE, BUTTON_ENTER, BUTTON_ENTER],
            True,
            None,
            0,
            1,
        ),
    ]

    for i, (
        label,
        btn_sequence,
        w24,
        scanned_words,
        load_calls,
        error_calls,
    ) in enumerate(cases):
        print("Case %d: %s" % (i, label))
        ctx = create_ctx(mocker, btn_sequence)
        loader = MnemonicLoader(ctx)
        scanner_mock = mocker.patch(
            "krux.pages.stack_1248_scanner.StackbitScanner.scanner",
            return_value=scanned_words,
        )
        mocker.patch.object(loader, "_load_key_from_words", return_value=MENU_CONTINUE)
        mocker.spy(loader, "flash_error")

        result = loader.load_key_from_1248_scan()

        scanner_mock.assert_called_once_with(w24)
        assert loader._load_key_from_words.call_count == load_calls
        if load_calls:
            loader._load_key_from_words.assert_called_once_with(TEST_WORDS)
        assert loader.flash_error.call_count == error_calls
        assert result == MENU_CONTINUE
        assert ctx.input.wait_for_button.call_count == len(btn_sequence)


def test_load_key_from_1248_scan_declined(m5stickv, mocker):
    """Declining the length choice or the intro returns without scanning"""
    from krux.pages.mnemonic_loader import MnemonicLoader
    from krux.pages import MENU_CONTINUE
    from krux.input import BUTTON_ENTER, BUTTON_PAGE, BUTTON_PAGE_PREV

    cases = [
        # (label, btn_sequence)
        ("Declined length choice", [BUTTON_PAGE_PREV, BUTTON_ENTER]),
        ("Declined scan intro", [BUTTON_ENTER, BUTTON_PAGE]),
    ]

    for i, (label, btn_sequence) in enumerate(cases):
        print("Case %d: %s" % (i, label))
        ctx = create_ctx(mocker, btn_sequence)
        loader = MnemonicLoader(ctx)
        scanner_mock = mocker.patch(
            "krux.pages.stack_1248_scanner.StackbitScanner.scanner"
        )

        result = loader.load_key_from_1248_scan()

        scanner_mock.assert_not_called()
        assert result == MENU_CONTINUE
        assert ctx.input.wait_for_button.call_count == len(btn_sequence)
