import pytest


def test_init(mocker, m5stickv):
    from krux.krux_settings import Settings

    s = Settings()

    assert isinstance(s, Settings)


# @pytest.fixture
# def mocker_sd_card(mocker):
#     mocker.patch(
#         "os.listdir",
#         new=mocker.MagicMock(return_value=["somefile", "otherfile"]),
#     )


def test_store_init(mocker, m5stickv):
    from krux.settings import Store, SETTINGS_FILENAME, SD_PATH

    cases = [
        (None, {}),
        ("""{"settings":{"network":"test"}}""", {"settings": {"network": "test"}}),
    ]
    for case in cases:
        mo = mocker.mock_open(read_data=case[0])
        mocker.patch("builtins.open", mo)
        s = Store()

        assert isinstance(s, Store)
        mo.assert_called_with("/" + SD_PATH + "/" + SETTINGS_FILENAME, "r")
        assert s.settings == case[1]


def test_store_get(mocker, m5stickv):
    mo = mocker.mock_open()
    mocker.patch("builtins.open", mo)
    from krux.settings import Store

    s = Store()

    cases = [
        ("ns1", "setting", "call1_defaultvalue1", "call2_defaultvalue1"),
        ("ns1.ns2", "setting", "call1_defaultvalue2", "call2_defaultvalue2"),
        ("ns1.ns2.ns3", "setting", "call1_defaultvalue3", "call2_defaultvalue3"),
    ]
    for case in cases:
        # First call, setting does not exist, so default value becomes the value
        assert s.get(case[0], case[1], case[2]) == case[2]
        # Second call, setting does exist, so default value is ignored
        assert s.get(case[0], case[1], case[3]) == case[2]


def test_store_set(mocker, m5stickv):
    mo = mocker.mock_open()
    mocker.patch("builtins.open", mo)
    from krux.settings import Store

    s = Store()

    cases = [
        ("ns1", "setting", "call1_value1", 1, "call3_value1"),
        ("ns1.ns2", "setting", "call1_value2", 2, "call3_value2"),
        ("ns1.ns2.ns3", "setting", "call1_value3", 3, "call3_value3"),
    ]
    for case in cases:
        s.set(case[0], case[1], case[2])
        assert s.get(case[0], case[1], "default") == case[2]

        s.set(case[0], case[1], case[3])
        assert s.get(case[0], case[1], "default") == case[3]

        s.set(case[0], case[1], case[4])
        assert s.get(case[0], case[1], "default") == case[4]


def test_setting(mocker, m5stickv):
    mo = mocker.mock_open()
    mocker.patch("builtins.open", mo)
    from krux.settings import Setting

    class TestClass:
        namespace = "test"
        some_setting = Setting("some_setting", 1)

    t = TestClass()

    assert t.some_setting == 1
    t.some_setting = 2
    assert t.some_setting == 2


def test_all_labels(mocker, m5stickv):
    from krux.krux_settings import (
        BitcoinSettings,
        I18nSettings,
        LoggingSettings,
        EncryptionSettings,
        PrinterSettings,
        ThermalSettings,
        AdafruitPrinterSettings,
        CNCSettings,
        GRBLSettings,
        PersistSettings,
        ThemeSettings,
        ScreensaverSettings,
        TouchSettings,
        EncoderSettings,
    )

    bitcoin = BitcoinSettings()
    i18n = I18nSettings()
    logging = LoggingSettings()
    encryption = EncryptionSettings()
    printer = PrinterSettings()
    thermal = ThermalSettings()
    adafruit = AdafruitPrinterSettings()
    cnc = CNCSettings()
    gbrl = GRBLSettings()
    persist = PersistSettings()
    appearance = ThemeSettings()
    screensaver = ScreensaverSettings()
    touch = TouchSettings()
    encoder = EncoderSettings()

    assert bitcoin.label("network")
    assert i18n.label("locale")
    assert logging.label("level")
    assert encryption.label("version")
    assert printer.label("thermal")
    assert thermal.label("adafruit")
    assert adafruit.label("tx_pin")
    assert cnc.label("invert")
    assert gbrl.label("tx_pin")
    assert persist.label("location")
    assert appearance.label("theme")
    assert screensaver.label("time")
    assert touch.label("threshold")
    assert encoder.label("debounce")
