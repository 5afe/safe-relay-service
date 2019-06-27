from typing import Optional

from django.conf import settings

from redis import Redis

from gnosis.eth import EthereumClient


class RedisRepository:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = super().__new__(cls)
        return cls.instance

    def __init__(self):
        self.redis = Redis.from_url(settings.REDIS_URL)

    def nonce_lock(self, ethereum_client: EthereumClient, address: str, timeout: Optional[int] = None):
        return EthereumNonceLock(self.redis, ethereum_client, address, timeout=timeout)


#TODO Test this using multiple threads
class EthereumNonceLock:
    def __init__(self, redis: Redis, ethereum_client: EthereumClient, address: str, timeout: Optional[int] = None):
        self.redis = redis
        self.ethereum_client = ethereum_client
        self.address = address
        self.timeout = timeout

    @property
    def nonce_key(self):
        return f'ethereum:nonce:{self.address}'

    @property
    def redis_lock(self):
        return f'ethereum:locks:{self.address}'

    def __enter__(self):
        with self.redis.lock(self.redis_lock, timeout=self.timeout):
            tx_nonce = self.redis.incr(self.nonce_key)
            if tx_nonce == 1:
                tx_nonce = self.ethereum_client.get_nonce_for_account(self.address, block_identifier='pending')
                self.redis.set(self.nonce_key, tx_nonce)
            return tx_nonce

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type:
            self.redis.delete(self.nonce_key)
