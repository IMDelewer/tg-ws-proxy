import platform


def main():
    system = platform.system()

    if system == "Windows":
        from tg_ws_proxy.platforms.windows import main as run
    elif system == "Darwin":
        from tg_ws_proxy.platforms.macos import main as run
    else:
        print(f"Unsupported OS: {system}")
        return

    run()