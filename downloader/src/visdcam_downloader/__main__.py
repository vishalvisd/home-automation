import argparse
import logging
import threading
import webbrowser

import uvicorn

from visdcam_downloader.config import HOST, PORT


def main() -> None:
    parser = argparse.ArgumentParser(description="visdcam downloader")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser")
    arguments = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    url = f"http://{HOST}:{arguments.port}"

    if not arguments.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    print(f"visdcam downloader: {url}  (Ctrl+C to stop)")

    uvicorn.run(
        "visdcam_downloader.api.app:app",
        host=HOST,
        port=arguments.port,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
