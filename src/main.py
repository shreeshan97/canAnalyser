"""Entry point: python src/main.py [--virtual] [--bitrate N] [--channel CH]."""
import argparse
import os
import sys

from PySide6.QtWidgets import QApplication

from main_window import MainWindow


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="canAnalyser — PySide6 CAN RX + simple TX")
    ap.add_argument("--virtual", action="store_true", help="use virtual bus")
    ap.add_argument("--backend", default="candle", choices=["candle", "virtual", "socketcan"])
    ap.add_argument("--channel", default=None)
    ap.add_argument("--bitrate", type=int, default=500000)
    ap.add_argument("--theme", default="system", choices=["system", "light", "dark"])
    ap.add_argument("--loop-back", dest="loop_back", action="store_true",
                    default=False,
                    help="silicon-internal loopback (no wiring); default off, "
                         "assumes TX/RX physically connected")
    args = ap.parse_args(argv)
    if args.virtual:
        args.backend = "virtual"
    if args.channel is None:
        args.channel = "test" if args.backend == "virtual" else (
            "can0" if args.backend == "socketcan" else 0)
    return args


def main(argv=None):
    args = parse_args(argv)
    # Keep the desktop platform theme (e.g. Mint qt5ct dark) from overriding
    # our Fusion palette so Light/Dark selection actually takes effect.
    QApplication.setDesktopSettingsAware(False)
    os.environ.pop("QT_QPA_PLATFORMTHEME", None)
    app = QApplication(sys.argv)
    from theme import apply_theme
    apply_theme(app, args.theme)
    win = MainWindow(backend=args.backend, channel=args.channel,
                     bitrate=args.bitrate, loop_back=args.loop_back)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
