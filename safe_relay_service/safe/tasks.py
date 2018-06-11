from celery import app
from celery.utils.log import get_task_logger
from django.conf import settings
from ethereum.utils import check_checksum, checksum_encode, mk_contract_address
from redis import Redis
from web3 import HTTPProvider, Web3

from safe_relay_service.safe.models import (SafeContract, SafeCreation,
                                            SafeFunding)

from .helpers import check_tx_with_confirmations, send_eth_to

logger = get_task_logger(__name__)

w3 = Web3(HTTPProvider(settings.ETHEREUM_NODE_URL))

redis = Redis.from_url(settings.REDIS_URL)


@app.shared_task(bind=True, max_retries=3)
def fund_deployer_task(self, safe_address: str, deployer_address: str, payment: int) -> None:
    """
    Check if user has sent enough ether to the safe account
    If every condition is met ether is sent to the deployer address and `check_deployer_funded_task`
    is called to check that that tx is mined
    :param safe_address: safe account
    :param deployer_address: deployer address
    :param payment: minimum ether required to create the safe (wei)
    """

    # These asserts just to make sure we are not wasting money
    assert check_checksum(safe_address)
    assert check_checksum(deployer_address)
    assert checksum_encode(mk_contract_address(sender=deployer_address, nonce=0)) == safe_address

    safe_contract = SafeContract.objects.get(address=safe_address)
    safe_creation = SafeCreation.objects.get(safe=safe_address)

    with redis.lock('locks:fund_deployer_task', timeout=60 * 5):
        safe_funding, _ = SafeFunding.objects.get_or_create(safe=safe_contract)

        # Nothing to do if everything is funded and mined
        if safe_funding.is_all_funded():
            logger.debug('Nothing to do here for safe %s. Is all funded', safe_address)
            return

        # If receipt exists already, let's check
        if safe_funding.deployer_funded_tx_hash:
            logger.debug('Safe %s deployer has already been funded. Checking tx_hash %s',
                         safe_address,
                         safe_funding.deployer_funded_tx_hash)
            check_deployer_funded_task.delay(safe_address)
        elif not safe_funding.deployer_funded:
            # Timeout of 5 minutes (just in the case that the application hangs to avoid a deadlock)
            confirmations = settings.SAFE_FUNDING_CONFIRMATIONS
            last_block_number = w3.eth.blockNumber

            assert (last_block_number - confirmations) > 0

            safe_balance = w3.eth.getBalance(safe_address, last_block_number - confirmations)

            if safe_balance >= payment:
                logger.info('Found %d balance for safe=%s', safe_balance, safe_address)
                safe_funding.safe_funded = True
                safe_funding.save()
                logger.info('Transferring payment=%d to deployer=%s for safe=%s', payment, deployer_address,
                            safe_address)

                # Check deployer has no eth. This should never happen
                balance = w3.eth.getBalance(deployer_address)
                if balance:
                    logger.error('Deployer=%s for safe=%s has funds already!', deployer_address, safe_address)
                else:
                    tx_hash = send_eth_to(w3, deployer_address, safe_creation.gas_price, payment)
                    if tx_hash:
                        tx_hash = tx_hash.hex()[2:]
                        safe_funding.deployer_funded_tx_hash = tx_hash
                        safe_funding.save()
                        logger.debug('Safe %s deployer has just been funded. Checking tx_hash %s', safe_address,
                                     tx_hash)
                        check_deployer_funded_task.apply_async((safe_address,), countdown=1 * 60)
                    else:
                        logger.error('Cannot send payment=%d to deployer safe=%s', payment, deployer_address)
                        raise self.retry(countdown=1 * 60)
            else:
                logger.info('Not found required balance=%d for safe=%s', payment, safe_address)
                raise self.retry(countdown=1 * 60)


@app.shared_task(bind=True,
                 max_retries=settings.SAFE_CHECK_DEPLOYER_FUNDED_RETRIES,
                 default_retry_delay=settings.SAFE_CHECK_DEPLOYER_FUNDED_DELAY)
def check_deployer_funded_task(self, safe_address: str) -> None:
    lock = redis.lock("tasks:check_deployer_funded_task:%s" % safe_address, timeout=60 * 5)
    have_lock = lock.acquire(blocking=False)
    if not have_lock:
        return
    try:
        logger.debug('Starting check deployer funded task for safe %s', safe_address)
        safe_funding = SafeFunding.objects.get(safe=safe_address)
        tx_hash = safe_funding.deployer_funded_tx_hash

        if not tx_hash:
            logger.error('No deployer_funded_tx_hash for safe %s', safe_address)
            return

        logger.debug('Checking safe %s deployer tx receipt %s', safe_address, tx_hash)
        if safe_funding.deployer_funded:
            logger.warning('Tx %s for safe %s is already checked!', tx_hash, safe_address)
        else:
            if check_tx_with_confirmations(w3, tx_hash, settings.SAFE_FUNDING_CONFIRMATIONS):
                logger.debug('Found transaction for receipt %s', tx_hash)
                safe_funding.deployer_funded = True
                safe_funding.save()
            else:
                logger.debug('Not found transaction for receipt %s', tx_hash)
                # If no more retries
                if self.request.retries == self.max_retries:
                    logger.error('Transaction with receipt %s not mined after %d retries. Setting back to empty',
                                 self.request.retries,
                                 tx_hash)
                    safe_funding.deployer_funded_tx_hash = ''
                    safe_funding.save()
                else:
                    logger.debug('Retry finding transaction receipt %s', tx_hash)
                    raise self.retry()
    finally:
        if have_lock:
            lock.release()


@app.shared_task()
def deploy_safes_task() -> None:
    lock = redis.lock("tasks:deploy_safes_task", timeout=60 * 5)
    have_lock = lock.acquire(blocking=False)
    if not have_lock:
        return

    try:
        logger.debug('Starting deploy safes task')

        pending_to_deploy = SafeFunding.objects.pending_to_deploy()

        logger.debug('%d safes pending to deploy', len(pending_to_deploy))

        for safe_funding in pending_to_deploy:
            safe_contract = safe_funding.safe
            safe_creation = SafeCreation.objects.get(safe=safe_contract)

            # Check if safe proxy deploy transaction has already been sent to the network
            tx_hash = safe_funding.safe_deployed_tx_hash
            if tx_hash:
                logger.debug('Safe %s creation tx has already been sent to the network with receipt %s',
                             safe_contract.address,
                             tx_hash)

                if check_tx_with_confirmations(w3, safe_funding.safe_deployed_tx_hash, settings.SAFE_FUNDING_CONFIRMATIONS):
                    logger.info('Safe %s was deployed!', safe_funding.safe.address)
                    safe_funding.safe_deployed = True
                    safe_funding.save()
                    return
            else:
                tx_hash = w3.eth.sendRawTransaction(bytes(safe_creation.signed_tx))
                if tx_hash:
                    tx_hash = tx_hash.hex()[2:]
                    logger.debug('Safe %s creation tx has just been sent to the network with receipt %s',
                                 safe_contract.address,
                                 tx_hash)
                    safe_funding.safe_deployed_tx_hash = tx_hash
                    safe_funding.save()
    finally:
        if have_lock:
            lock.release()
