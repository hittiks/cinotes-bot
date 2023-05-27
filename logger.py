import os
from enum import Enum
from pathlib import Path
from datetime import datetime
from rgb_colorizer import colorize, RGBColor


class LogMode(Enum):
    OK = RGBColor(color_name="green")
    INFO = RGBColor(color_name="blue")
    TIME = RGBColor(color_name="yellow")
    ERROR = RGBColor(color_name="red")
    DEFAULT = RGBColor(color_name="white")
    WARNING = RGBColor(color_name="violet")


def log(text: str, mode: "LogMode | RGBColor") -> None:
    log_time = colorize(str(datetime.now()), RGBColor(color_name="yellow"))

    color = mode if isinstance(mode, RGBColor) else mode.value

    log_text = log_time + " " + colorize(text, color)

    if os.environ["cinotes_log_to_file"] == "True":
        if not Path("../cinotes-bot_logs").exists():
            Path("../cinotes-bot_logs").mkdir()

        with open(f"../cinotes-bot_logs/log_{datetime.now().date()}.txt", "a") as f:
            f.write(log_text + "\n")
    else:
        print(log_text)
