from typing import List


def chunks(l: List[any], n: int):
    """
    :param l: List
    :param n: Number of elements per chunk
    :return: Yield successive n-sized chunks from l
    """
    for i in range(0, len(l), n):
        yield l[i:i + n]
