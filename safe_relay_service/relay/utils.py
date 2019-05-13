import logging
from typing import List


class IgnoreCheckUrl(logging.Filter):
    def filter(self, record):
        return not (record.status_code == 200 and record.args and record.args[0].startswith('GET /check/'))


def chunks(l: List[any], n: int):
    """
    :param l: List
    :param n: Number of elements per chunk
    :return: Yield successive n-sized chunks from l
    """
    for i in range(0, len(l), n):
        yield l[i:i + n]
