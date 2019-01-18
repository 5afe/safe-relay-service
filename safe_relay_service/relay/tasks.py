from datetime import timedelta
from typing import List

from django.conf import settings
from django.utils import timezone

from celery import app
from celery.utils.log import get_task_logger
from ethereum.utils import check_checksum, checksum_encode, mk_contract_address

from gnosis.eth import EthereumServiceProvider, TransactionAlreadyImported
from gnosis.eth.constants import NULL_ADDRESS

from safe_relay_service.relay.models import (SafeContract, SafeCreation,
                                             SafeFunding)

from .notification import NotificationServiceProvider
from .services.redis_service import RedisService

logger = get_task_logger(__name__)

ethereum_service = EthereumServiceProvider()
redis = RedisService().redis
notification_service = NotificationServiceProvider()

# Lock timeout of 2 minutes (just in the case that the application hangs to avoid a redis deadlock)
LOCK_TIMEOUT = 60 * 2


# TODO Control ConnectionError: HTTPConnectionPool for web3


@app.shared_task(bind=True, max_retries=3)
def fund_deployer_task(self, safe_address: str, retry: bool=True) -> None:
    """
    Check if user has sent enough ether or tokens to the safe account
    If every condition is met ether is sent to the deployer address and `check_deployer_funded_task`
    is called to check that that tx is mined
    If everything goes well in SafeFunding `safe_funded=True` and `deployer_funded_tx_hash=tx_hash` are set
    :param safe_address: safe account
    :param retry: if True, retries are allowed, otherwise don't retry
    """

    safe_contract = SafeContract.objects.get(address=safe_address)
    safe_creation = SafeCreation.objects.get(safe=safe_address)

    deployer_address = safe_creation.deployer
    payment = safe_creation.payment

    # These asserts just to make sure we are not wasting money
    assert check_checksum(safe_address)
    assert check_checksum(deployer_address)
    assert checksum_encode(mk_contract_address(sender=deployer_address, nonce=0)) == safe_address
    assert payment > 0

    with redis.lock('locks:fund_deployer_task', timeout=LOCK_TIMEOUT):
        safe_funding, _ = SafeFunding.objects.get_or_create(safe=safe_contract)

        # Nothing to do if everything is funded and mined
        if safe_funding.is_all_funded():
            logger.debug('Nothing to do here for safe %s. Is all funded', safe_address)
            return

        # If receipt exists already, let's check
        if safe_funding.deployer_funded_tx_hash and not safe_funding.deployer_funded:
            logger.debug('Safe %s deployer has already been funded. Checking tx_hash %s',
                         safe_address,
                         safe_funding.deployer_funded_tx_hash)
            check_deployer_funded_task.delay(safe_address)
        elif not safe_funding.deployer_funded:
            confirmations = settings.SAFE_FUNDING_CONFIRMATIONS
            last_block_number = ethereum_service.current_block_number

            assert (last_block_number - confirmations) > 0

            if safe_creation.payment_token and safe_creation.payment_token != NULL_ADDRESS:
                # FIXME Add block number for confirmations
                safe_balance = ethereum_service.get_erc20_balance(safe_address, safe_creation.payment_token)
            else:
                safe_balance = ethereum_service.get_balance(safe_address, last_block_number - confirmations)

            if safe_balance >= payment:
                logger.info('Found %d balance for safe=%s', safe_balance, safe_address)
                safe_funding.safe_funded = True
                safe_funding.save()

                # Check deployer has no eth. This should never happen
                balance = ethereum_service.get_balance(deployer_address)
                if balance:
                    logger.error('Deployer=%s for safe=%s has eth already (%d wei)!',
                                 deployer_address, safe_address, balance)
                else:
                    logger.info('Safe=%s. Transferring deployment-cost=%d to deployer=%s',
                                safe_address, safe_creation.wei_deploy_cost(), deployer_address)
                    tx_hash = ethereum_service.send_eth_to(deployer_address, safe_creation.gas_price,
                                                           safe_creation.wei_deploy_cost(),
                                                           retry=True, block_identifier='pending')
                    if tx_hash:
                        tx_hash = tx_hash.hex()
                        logger.info('Safe=%s. Transferred deployment-cost=%d to deployer=%s with tx-hash=%s',
                                    safe_address, safe_creation.wei_deploy_cost(), deployer_address, tx_hash)
                        safe_funding.deployer_funded_tx_hash = tx_hash
                        safe_funding.save()
                        logger.debug('Safe=%s deployer has just been funded. tx_hash=%s', safe_address, tx_hash)
                        check_deployer_funded_task.apply_async((safe_address,), countdown=20)
                    else:
                        logger.error('Cannot send payment=%d to deployer safe=%s', payment, deployer_address)
                        if retry:
                            raise self.retry(countdown=30)
            else:
                logger.info('Not found required balance=%d for safe=%s', payment, safe_address)
                if retry:
                    raise self.retry(countdown=30)


@app.shared_task(bind=True,
                 max_retries=settings.SAFE_CHECK_DEPLOYER_FUNDED_RETRIES,
                 default_retry_delay=settings.SAFE_CHECK_DEPLOYER_FUNDED_DELAY)
def check_deployer_funded_task(self, safe_address: str, retry: bool=True) -> None:
    """
    Check the `deployer_funded_tx_hash`. If receipt can be retrieved, in SafeFunding `deployer_funded=True`.
    If not, after the number of retries `deployer_funded_tx_hash=None`
    :param safe_address: safe account
    :param retry: if True, retries are allowed, otherwise don't retry
    """
    lock = redis.lock("tasks:check_deployer_funded_task:%s" % safe_address, timeout=LOCK_TIMEOUT)
    have_lock = lock.acquire(blocking=False)
    if not have_lock:
        logger.info('check_deployer_funded_task is locked for safe=%s', safe_address)
        return
    try:
        logger.debug('Starting check deployer funded task for safe=%s', safe_address)
        safe_funding = SafeFunding.objects.get(safe=safe_address)
        deployer_funded_tx_hash = safe_funding.deployer_funded_tx_hash

        if safe_funding.deployer_funded:
            logger.warning('Tx-hash=%s for safe %s is already checked!', deployer_funded_tx_hash, safe_address)
            return
        elif not deployer_funded_tx_hash:
            logger.error('No deployer_funded_tx_hash for safe=%s', safe_address)
            return

        logger.debug('Checking safe=%s deployer tx-hash=%s', safe_address, deployer_funded_tx_hash)
        if ethereum_service.get_transaction_receipt(deployer_funded_tx_hash):
            logger.info('Found transaction to deployer of safe=%s with receipt=%s', safe_address,
                        deployer_funded_tx_hash)
            safe_funding.deployer_funded = True
            safe_funding.save()
        else:
            logger.debug('Not found transaction receipt for tx-hash=%s', deployer_funded_tx_hash)
            # If no more retries
            if not retry or (self.request.retries == self.max_retries):
                safe_creation = SafeCreation.objects.get(safe=safe_address)
                balance = ethereum_service.get_balance(safe_creation.deployer)
                if balance >= safe_creation.wei_deploy_cost():
                    logger.warning('Safe=%s. Deployer=%s. Cannot find transaction receipt with tx-hash=%s, '
                                   'but balance is there. This should never happen',
                                   safe_address, safe_creation.deployer, deployer_funded_tx_hash)
                    safe_funding.deployer_funded = True
                    safe_funding.save()
                else:
                    logger.error('Safe=%s. Deployer=%s. Transaction receipt with tx-hash=%s not mined after %d '
                                 'retries. Setting `deployer_funded_tx_hash` back to `None`',
                                 safe_address,
                                 safe_creation.deployer,
                                 deployer_funded_tx_hash,
                                 self.request.retries)
                    safe_funding.deployer_funded_tx_hash = None
                    safe_funding.save()
            else:
                logger.debug('Retry finding transaction receipt %s', deployer_funded_tx_hash)
                if retry:
                    raise self.retry(countdown=self.request.retries * 10 + 15)  # More countdown every retry
    finally:
        if have_lock:
            lock.release()


@app.shared_task()
def deploy_safes_task(retry: bool=True) -> None:
    """
    Deploy pending safes (deployer funded and tx-hash checked). Then raw creation tx is sent to the ethereum network.
    If something goes wrong (maybe a reorg), `deployer_funded` will be set False again and `check_deployer_funded_task`
    is called again.
    :param retry: if True, retries are allowed, otherwise don't retry
    """
    lock = redis.lock("tasks:deploy_safes_task", timeout=LOCK_TIMEOUT)
    have_lock = lock.acquire(blocking=False)
    if not have_lock:
        return
    try:
        logger.debug('Starting deploy safes task')
        pending_to_deploy = SafeFunding.objects.pending_just_to_deploy()
        logger.debug('%d safes pending to deploy', len(pending_to_deploy))

        for safe_funding in pending_to_deploy:
            safe_contract = safe_funding.safe
            safe_address = safe_contract.address
            safe_creation = SafeCreation.objects.get(safe=safe_contract)
            safe_deployed_tx_hash = safe_funding.safe_deployed_tx_hash

            if not safe_deployed_tx_hash:
                # Deploy the Safe
                try:
                    creation_tx_hash = ethereum_service.send_raw_transaction(safe_creation.signed_tx)
                    if creation_tx_hash:
                        creation_tx_hash = creation_tx_hash.hex()
                        logger.info('Safe=%s creation tx has just been sent to the network with tx-hash=%s',
                                    safe_address, creation_tx_hash)
                        safe_funding.safe_deployed_tx_hash = creation_tx_hash
                        safe_funding.save()
                except TransactionAlreadyImported:
                    logger.warning("Safe=%s transaction was already imported by the node", safe_address)
                    safe_funding.safe_deployed_tx_hash = safe_creation.tx_hash
                    safe_funding.save()
                except ValueError:
                    # Usually "ValueError: {'code': -32000, 'message': 'insufficient funds for gas * price + value'}"
                    # A reorg happened
                    logger.warning("Safe=%s was affected by reorg, let's check again receipt for tx-hash=%s",
                                   safe_address, safe_funding.deployer_funded_tx_hash, exc_info=True)
                    safe_funding.deployer_funded = False
                    safe_funding.save()
                    check_deployer_funded_task.apply_async((safe_address,), {'retry': retry}, countdown=20)
            else:
                # Check if safe proxy deploy transaction has already been sent to the network
                logger.debug('Safe=%s creation tx has already been sent to the network with tx-hash=%s',
                             safe_address, safe_deployed_tx_hash)

                if ethereum_service.check_tx_with_confirmations(safe_deployed_tx_hash,
                                                                settings.SAFE_FUNDING_CONFIRMATIONS):
                    logger.info('Safe=%s was deployed!', safe_funding.safe.address)
                    safe_funding.safe_deployed = True
                    safe_funding.save()
                    # Send creation notification
                    send_create_notification.delay(safe_address, safe_creation.owners)
                elif (safe_funding.modified + timedelta(minutes=10) < timezone.now()
                      and not ethereum_service.get_transaction_receipt(safe_deployed_tx_hash)):
                    # A reorg happened
                    logger.warning('Safe=%s deploy tx=%s was not found after 10 minutes. Trying deploying again...',
                                   safe_funding.safe.address, safe_deployed_tx_hash)
                    safe_funding.safe_deployed_tx_hash = None
                    safe_funding.save()
    finally:
        if have_lock:
            lock.release()


@app.shared_task()
def send_create_notification(safe_address: str, owners: List[str]) -> None:
    """
    Send create notification to owner
    :param safe_address: Address of the safe created
    :param owners: List of owners of the safe
    """
    logger.info('Safe=%s creation ended, sending notification to %s', safe_address, owners)
    return notification_service.send_create_notification(safe_address, owners)
