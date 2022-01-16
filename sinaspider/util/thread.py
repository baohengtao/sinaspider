from pathlib import Path
from queue import Queue
from threading import Thread

from loguru import logger

from sinaspider.util.helper import get_url, write_xmp


class ClosableQueue(Queue):
    SENTINEL = object()

    def close(self):
        self.put(self.SENTINEL)

    def __iter__(self):
        while True:
            item = self.get()
            try:
                if item is self.SENTINEL:
                    return
                yield item
            finally:
                self.task_done()


class StoppableWorker(Thread):
    def __init__(self, queue: ClosableQueue):
        super().__init__()
        self.queue = queue

    def run(self):
        for item in self.queue:
            download_single_file(**item)


def start_threads(count, *args):
    threads = [StoppableWorker(*args) for _ in range(count)]
    for thread in threads:
        thread.start()
    return threads


def stop_threads(closable_queue, threads):
    for _ in threads:
        closable_queue.close()
    closable_queue.join()

    for thread in threads:
        thread.join()


def download_single_file(url, filepath: Path, filename, xmp_info=None):
    filepath.mkdir(parents=True, exist_ok=True)
    img = filepath / filename
    if img.exists():
        logger.warning(
            f'{img} already exists..skip {url}')
        return
    while True:
        downloaded = get_url(url).content
        if len(downloaded) == 153:
            continue
        else:
            if len(downloaded) < 1024:
                logger.critical([len(downloaded), url, filepath])
            break

    img.write_bytes(downloaded)
    if xmp_info:
        write_xmp(xmp_info, img)
