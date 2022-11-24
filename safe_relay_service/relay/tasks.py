from datetime import timedelta
from typing import List

from django.conf import settings
from django.utils import timezone

from celery import app
from celery.utils.log import get_task_logger
from redis.exceptions import LockError
from web3 import Web3

from gnosis.eth import EthereumClientProvider, TransactionAlreadyImported
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.utils import mk_contract_address

from safe_relay_service.gas_station.gas_station import GasStationProvider

from .models import (
    SafeContract,
    SafeCreation,
    SafeCreation2,
    SafeFunding,
    SafeMultisigTx,
)
from .repositories.redis_repository import RedisRepository
from .services import (
    Erc20EventsServiceProvider,
    FundingServiceProvider,
    NotificationServiceProvider,
    SafeCreationServiceProvider,
    TransactionServiceProvider,
    CirclesService,
    GraphQLService,
)
from .services.safe_creation_service import NotEnoughFundingForCreation

logger = get_task_logger(__name__)


# Lock timeout of 2 minutes (just in the case that the application hangs to avoid a redis deadlock)
LOCK_TIMEOUT = 60 * 2


@app.shared_task(bind=True, max_retries=3, soft_time_limit=LOCK_TIMEOUT)
def fund_deployer_task(self, safe_address: str, retry: bool = True) -> None:
    """
    Check if user has sent enough ether or tokens to the safe account
    If every condition is met ether is sent to the deployer address and `check_deployer_funded_task`
    is called to check that that tx is mined
    If everything goes well in SafeFunding `safe_funded=True` and `deployer_funded_tx_hash=tx_hash` are set
    :param safe_address: safe account
    :param retry: if True, retries are allowed, otherwise don't retry
    """

    safe_contract = SafeContract.objects.get(address=safe_address)
    try:
        safe_creation = SafeCreation.objects.get(safe=safe_address)
    except SafeCreation.DoesNotExist:
        deploy_create2_safe_task.delay(safe_address)
        return

    deployer_address = safe_creation.deployer
    payment = safe_creation.payment

    # These asserts just to make sure we are not wasting money
    assert Web3.isChecksumAddress(safe_address)
    assert Web3.isChecksumAddress(deployer_address)
    assert mk_contract_address(deployer_address, 0) == safe_address
    assert payment > 0

    redis = RedisRepository().redis
    with redis.lock("locks:fund_deployer_task", timeout=LOCK_TIMEOUT):
        ethereum_client = EthereumClientProvider()
        safe_funding, _ = SafeFunding.objects.get_or_create(safe=safe_contract)

        # Nothing to do if everything is funded and mined
        if safe_funding.is_all_funded():
            logger.debug("Nothing to do here for safe %s. Is all funded", safe_address)
            return

        # If receipt exists already, let's check
        if safe_funding.deployer_funded_tx_hash and not safe_funding.deployer_funded:
            logger.debug(
                "Safe %s deployer has already been funded. Checking tx_hash %s",
                safe_address,
                safe_funding.deployer_funded_tx_hash,
            )
            check_deployer_funded_task.delay(safe_address)
        elif not safe_funding.deployer_funded:
            confirmations = settings.SAFE_FUNDING_CONFIRMATIONS
            last_block_number = ethereum_client.current_block_number

            assert (last_block_number - confirmations) > 0

            if (
                safe_creation.payment_token
                and safe_creation.payment_token != NULL_ADDRESS
            ):
                safe_balance = ethereum_client.erc20.get_balance(
                    safe_address, safe_creation.payment_token
                )
            else:
                safe_balance = ethereum_client.get_balance(
                    safe_address, last_block_number - confirmations
                )

            if safe_balance >= payment:
                logger.info("Found %d balance for safe=%s", safe_balance, safe_address)
                safe_funding.safe_funded = True
                safe_funding.save()

                # Check deployer has no eth. This should never happen
                balance = ethereum_client.get_balance(deployer_address)
                if balance:
                    logger.error(
                        "Deployer=%s for safe=%s has eth already (%d wei)",
                        deployer_address,
                        safe_address,
                        balance,
                    )
                else:
                    logger.info(
                        "Safe=%s. Transferring deployment-cost=%d to deployer=%s",
                        safe_address,
                        safe_creation.wei_deploy_cost(),
                        deployer_address,
                    )
                    tx_hash = FundingServiceProvider().send_eth_to(
                        deployer_address, safe_creation.wei_deploy_cost(), retry=True
                    )
                    if tx_hash:
                        tx_hash = tx_hash.hex()
                        logger.info(
                            "Safe=%s. Transferred deployment-cost=%d to deployer=%s with tx-hash=%s",
                            safe_address,
                            safe_creation.wei_deploy_cost(),
                            deployer_address,
                            tx_hash,
                        )
                        safe_funding.deployer_funded_tx_hash = tx_hash
                        safe_funding.save()
                        logger.debug(
                            "Safe=%s deployer has just been funded. tx_hash=%s",
                            safe_address,
                            tx_hash,
                        )
                        check_deployer_funded_task.apply_async(
                            (safe_address,), countdown=20
                        )
                    else:
                        logger.error(
                            "Cannot send payment=%d to deployer safe=%s",
                            payment,
                            deployer_address,
                        )
                        if retry:
                            raise self.retry(countdown=30)
            else:
                logger.info(
                    "Not found required balance=%d for safe=%s", payment, safe_address
                )
                if retry:
                    raise self.retry(countdown=30)


@app.shared_task(
    bind=True,
    soft_time_limit=LOCK_TIMEOUT,
    max_retries=settings.SAFE_CHECK_DEPLOYER_FUNDED_RETRIES,
    default_retry_delay=settings.SAFE_CHECK_DEPLOYER_FUNDED_DELAY,
)
def check_deployer_funded_task(self, safe_address: str, retry: bool = True) -> None:
    """
    Check the `deployer_funded_tx_hash`. If receipt can be retrieved, in SafeFunding `deployer_funded=True`.
    If not, after the number of retries `deployer_funded_tx_hash=None`
    :param safe_address: safe account
    :param retry: if True, retries are allowed, otherwise don't retry
    """
    try:
        redis = RedisRepository().redis
        with redis.lock(
            f"tasks:check_deployer_funded_task:{safe_address}",
            blocking_timeout=1,
            timeout=LOCK_TIMEOUT,
        ):
            ethereum_client = EthereumClientProvider()
            logger.debug(
                "Starting check deployer funded task for safe=%s", safe_address
            )
            safe_funding = SafeFunding.objects.get(safe=safe_address)
            deployer_funded_tx_hash = safe_funding.deployer_funded_tx_hash

            if safe_funding.deployer_funded:
                logger.warning(
                    "Tx-hash=%s for safe %s is already checked",
                    deployer_funded_tx_hash,
                    safe_address,
                )
                return
            elif not deployer_funded_tx_hash:
                logger.error("No deployer_funded_tx_hash for safe=%s", safe_address)
                return

            logger.debug(
                "Checking safe=%s deployer tx-hash=%s",
                safe_address,
                deployer_funded_tx_hash,
            )
            if ethereum_client.get_transaction_receipt(deployer_funded_tx_hash):
                logger.info(
                    "Found transaction to deployer of safe=%s with receipt=%s",
                    safe_address,
                    deployer_funded_tx_hash,
                )
                safe_funding.deployer_funded = True
                safe_funding.save()
            else:
                logger.debug(
                    "Not found transaction receipt for tx-hash=%s",
                    deployer_funded_tx_hash,
                )
                # If no more retries
                if not retry or (self.request.retries == self.max_retries):
                    safe_creation = SafeCreation.objects.get(safe=safe_address)
                    balance = ethereum_client.get_balance(safe_creation.deployer)
                    if balance >= safe_creation.wei_deploy_cost():
                        logger.warning(
                            "Safe=%s. Deployer=%s. Cannot find transaction receipt with tx-hash=%s, "
                            "but balance is there. This should never happen",
                            safe_address,
                            safe_creation.deployer,
                            deployer_funded_tx_hash,
                        )
                        safe_funding.deployer_funded = True
                        safe_funding.save()
                    else:
                        logger.error(
                            "Safe=%s. Deployer=%s. Transaction receipt with tx-hash=%s not mined after %d "
                            "retries. Setting `deployer_funded_tx_hash` back to `None`",
                            safe_address,
                            safe_creation.deployer,
                            deployer_funded_tx_hash,
                            self.request.retries,
                        )
                        safe_funding.deployer_funded_tx_hash = None
                        safe_funding.save()
                else:
                    logger.debug(
                        "Retry finding transaction receipt %s", deployer_funded_tx_hash
                    )
                    if retry:
                        raise self.retry(
                            countdown=self.request.retries * 10 + 15
                        )  # More countdown every retry
    except LockError:
        logger.info("check_deployer_funded_task is locked for safe=%s", safe_address)


@app.shared_task(soft_time_limit=LOCK_TIMEOUT)
def deploy_safes_task(retry: bool = True) -> None:
    """
    Deploy pending safes (deployer funded and tx-hash checked). Then raw creation tx is sent to the ethereum network.
    If something goes wrong (maybe a reorg), `deployer_funded` will be set False again and `check_deployer_funded_task`
    is called again.
    :param retry: if True, retries are allowed, otherwise don't retry
    """
    try:
        redis = RedisRepository().redis
        with redis.lock(
            "tasks:deploy_safes_task", blocking_timeout=1, timeout=LOCK_TIMEOUT
        ):
            ethereum_client = EthereumClientProvider()
            logger.debug("Starting deploy safes task")
            pending_to_deploy = SafeFunding.objects.pending_just_to_deploy()
            logger.debug("%d safes pending to deploy", len(pending_to_deploy))

            for safe_funding in pending_to_deploy:
                safe_contract = safe_funding.safe
                safe_address = safe_contract.address
                safe_creation = SafeCreation.objects.get(safe=safe_contract)
                safe_deployed_tx_hash = safe_funding.safe_deployed_tx_hash

                if not safe_deployed_tx_hash:
                    # Deploy the Safe
                    try:
                        creation_tx_hash = ethereum_client.send_raw_transaction(
                            safe_creation.signed_tx
                        )
                        if creation_tx_hash:
                            creation_tx_hash = creation_tx_hash.hex()
                            logger.info(
                                "Safe=%s creation tx has just been sent to the network with tx-hash=%s",
                                safe_address,
                                creation_tx_hash,
                            )
                            safe_funding.safe_deployed_tx_hash = creation_tx_hash
                            safe_funding.save()
                    except TransactionAlreadyImported:
                        logger.warning(
                            "Safe=%s transaction was already imported by the node",
                            safe_address,
                        )
                        safe_funding.safe_deployed_tx_hash = safe_creation.tx_hash
                        safe_funding.save()
                    except ValueError:
                        # Usually "ValueError: {'code': -32000, 'message': 'insufficient funds for gas*price+value'}"
                        # A reorg happened
                        logger.warning(
                            "Safe=%s was affected by reorg, let's check again receipt for tx-hash=%s",
                            safe_address,
                            safe_funding.deployer_funded_tx_hash,
                            exc_info=True,
                        )
                        safe_funding.deployer_funded = False
                        safe_funding.save()
                        check_deployer_funded_task.apply_async(
                            (safe_address,), {"retry": retry}, countdown=20
                        )
                else:
                    # Check if safe proxy deploy transaction has already been sent to the network
                    logger.debug(
                        "Safe=%s creation tx has already been sent to the network with tx-hash=%s",
                        safe_address,
                        safe_deployed_tx_hash,
                    )

                    if ethereum_client.check_tx_with_confirmations(
                        safe_deployed_tx_hash, settings.SAFE_FUNDING_CONFIRMATIONS
                    ):
                        logger.info("Safe=%s was deployed", safe_funding.safe.address)
                        safe_funding.safe_deployed = True
                        safe_funding.save()
                        # Send creation notification
                        send_create_notification.delay(
                            safe_address, safe_creation.owners
                        )
                    elif safe_funding.modified + timedelta(
                        minutes=10
                    ) < timezone.now() and not ethereum_client.get_transaction_receipt(
                        safe_deployed_tx_hash
                    ):
                        # A reorg happened
                        logger.warning(
                            "Safe=%s deploy tx=%s was not found after 10 minutes. Trying deploying again...",
                            safe_funding.safe.address,
                            safe_deployed_tx_hash,
                        )
                        safe_funding.safe_deployed_tx_hash = None
                        safe_funding.save()
    except LockError:
        pass


@app.shared_task(bind=True, soft_time_limit=LOCK_TIMEOUT, max_retries=3)
def deploy_create2_safe_task(self, safe_address: str, retry: bool = True) -> None:
    """
    Check if user has sent enough ether or tokens to the safe account
    If every condition is met safe is deployed
    :param safe_address: safe account
    :param retry: if True, retries are allowed, otherwise don't retry
    """

    assert Web3.isChecksumAddress(safe_address)

    redis = RedisRepository().redis
    lock_name = f"locks:deploy_create2_safe:{safe_address}"
    try:
        with redis.lock(lock_name, blocking_timeout=1, timeout=LOCK_TIMEOUT):
            try:
                SafeCreationServiceProvider().deploy_create2_safe_tx(safe_address)
            except NotEnoughFundingForCreation:
                if retry:
                    raise self.retry(countdown=30)
    except LockError:
        logger.warning(
            "Cannot get lock={} for deploying safe={}".format(lock_name, safe_address)
        )


@app.shared_task(soft_time_limit=LOCK_TIMEOUT)
def check_create2_deployed_safes_task() -> None:
    """
    Check if create2 safes were deployed and store the `blockNumber` if there are enough confirmations
    """
    try:
        redis = RedisRepository().redis
        with redis.lock(
            "tasks:check_create2_deployed_safes_task",
            blocking_timeout=1,
            timeout=LOCK_TIMEOUT,
        ):
            ethereum_client = EthereumClientProvider()
            confirmations = 6
            current_block_number = ethereum_client.current_block_number
            for safe_creation2 in SafeCreation2.objects.pending_to_check():
                safe_address = safe_creation2.safe_id
                ethereum_tx = TransactionServiceProvider().create_or_update_ethereum_tx(
                    safe_creation2.tx_hash
                )
                if ethereum_tx and ethereum_tx.block_id is not None:
                    block_number = ethereum_tx.block_id
                    if (current_block_number - block_number) >= confirmations:
                        logger.info(
                            "Safe=%s with tx-hash=%s was confirmed in block-number=%d",
                            safe_address,
                            safe_creation2.tx_hash,
                            block_number,
                        )
                        safe_creation2.block_number = block_number
                        safe_creation2.save(update_fields=["block_number"])
                else:
                    # If safe was not included in any block after 30 minutes (mempool limit is 30 minutes)
                    # try to increase a little the gas price
                    if safe_creation2.modified + timedelta(minutes=30) < timezone.now():
                        logger.warning(
                            "Safe=%s with tx-hash=%s was not deployed after 30 minutes. "
                            "Increasing the gas price",
                            safe_address,
                            safe_creation2.tx_hash,
                        )
                        safe_creation2 = (
                            SafeCreationServiceProvider().deploy_again_create2_safe_tx(
                                safe_address
                            )
                        )
                        logger.warning(
                            "Safe=%s has a new tx-hash=%s with increased gas price.",
                            safe_address,
                            safe_creation2.tx_hash,
                        )

            for safe_creation2 in SafeCreation2.objects.not_deployed().filter(
                created__gte=timezone.now() - timedelta(days=10)
            ):
                deploy_create2_safe_task.delay(safe_creation2.safe.address, retry=False)
    except LockError:
        pass


@app.shared_task(soft_time_limit=300)
def send_create_notification(safe_address: str, owners: List[str]) -> None:
    """
    Send create notification to owner
    :param safe_address: Address of the safe created
    :param owners: List of owners of the safe
    """
    logger.info(
        "Safe=%s creation ended, sending notification to %s", safe_address, owners
    )
    return NotificationServiceProvider().send_create_notification(safe_address, owners)


@app.shared_task(soft_time_limit=300)
def check_balance_of_accounts_task() -> bool:
    """
    Checks if balance of relayer accounts (tx sender, safe funder) are less than the configured threshold
    :return: True if every account have enough ether, False otherwise
    """
    balance_warning_wei = settings.SAFE_ACCOUNTS_BALANCE_WARNING
    addresses = (
        FundingServiceProvider().funder_account.address,
        TransactionServiceProvider().tx_sender_account.address,
    )

    ethereum_client = EthereumClientProvider()
    result = True
    for address in addresses:
        balance_wei = ethereum_client.get_balance(address)
        if balance_wei <= balance_warning_wei:
            logger.error(
                "Relayer account=%s current balance=%d . Balance must be greater than %d",
                address,
                balance_wei,
                balance_warning_wei,
            )
            result = False
    return result


@app.shared_task(soft_time_limit=60 * 30)
def find_erc_20_721_transfers_task() -> int:
    """
    Find and process internal txs for existing safes
    :return: Number of safes processed
    """
    number_safes = 0
    try:
        redis = RedisRepository().redis
        with redis.lock(
            "tasks:find_internal_txs_task", blocking_timeout=1, timeout=60 * 30
        ):
            number_safes = Erc20EventsServiceProvider().process_all()
            logger.info("Find ERC20/721 task processed %d safes", number_safes)
    except LockError:
        pass
    return number_safes


@app.shared_task(soft_time_limit=60)
def check_pending_transactions() -> int:
    """
    Find txs that have not been mined after a while and resend again
    :return: Number of pending transactions
    """
    number_txs = 0
    try:
        redis = RedisRepository().redis
        with redis.lock(
            "tasks:check_pending_transactions", blocking_timeout=1, timeout=60
        ):
            tx_not_mined_alert = settings.SAFE_TX_NOT_MINED_ALERT_MINUTES
            multisig_txs = SafeMultisigTx.objects.pending(
                older_than=tx_not_mined_alert * 60
            ).select_related("ethereum_tx")
            for multisig_tx in multisig_txs:
                gas_price = GasStationProvider().get_gas_prices().fast
                old_fee = multisig_tx.ethereum_tx.fee
                ethereum_tx = TransactionServiceProvider().resend(
                    gas_price, multisig_tx
                )
                if ethereum_tx:
                    logger.error(
                        "Safe=%s - Tx with tx-hash=%s and safe-tx-hash=%s has not been mined after "
                        "a while, created=%s. Sent again with tx-hash=%s. Old fee=%d and new fee=%d",
                        multisig_tx.safe_id,
                        multisig_tx.ethereum_tx_id,
                        multisig_tx.safe_tx_hash,
                        multisig_tx.created,
                        ethereum_tx.tx_hash,
                        old_fee,
                        ethereum_tx.fee,
                    )
                else:
                    logger.error(
                        "Safe=%s - Tx with tx-hash=%s and safe-tx-hash=%s has not been mined after "
                        "a while, created=%s",
                        multisig_tx.safe_id,
                        multisig_tx.ethereum_tx_id,
                        multisig_tx.safe_tx_hash,
                        multisig_tx.created,
                    )
                number_txs += 1
    except LockError:
        pass
    return number_txs


@app.shared_task(soft_time_limit=60)
def check_and_update_pending_transactions() -> int:
    """
    Check if pending txs have been mined and update them
    :return: Number of pending transactions
    """
    number_txs = 0
    try:
        redis = RedisRepository().redis
        with redis.lock(
            "tasks:check_and_update_pending_transactions",
            blocking_timeout=1,
            timeout=60,
        ):
            transaction_service = TransactionServiceProvider()
            multisig_txs = SafeMultisigTx.objects.pending(
                older_than=150
            ).select_related("ethereum_tx")
            for multisig_tx in multisig_txs:
                ethereum_tx = transaction_service.create_or_update_ethereum_tx(
                    multisig_tx.ethereum_tx_id
                )
                if ethereum_tx and ethereum_tx.block_id:
                    if ethereum_tx.success:
                        logger.info(
                            "Safe=%s - Tx with tx-hash=%s was mined on block=%d ",
                            multisig_tx.safe_id,
                            ethereum_tx.tx_hash,
                            ethereum_tx.block_id,
                        )
                    else:
                        logger.error(
                            "Safe=%s - Tx with tx-hash=%s was mined on block=%d and failed",
                            multisig_tx.safe_id,
                            ethereum_tx.tx_hash,
                            ethereum_tx.block_id,
                        )
                    number_txs += 1
    except LockError:
        pass
    return number_txs


@app.shared_task(bind=True, soft_time_limit=LOCK_TIMEOUT, max_retries=6)
def begin_circles_onboarding_task(self, safe_address: str) -> None:
    """
    Starts a multi-step onboarding task for Circles users which 1. funds
    deploys a Gnosis Safe for them 2. funds the deployment of their Token.
    :param safe_address: Address of the safe to-be-created
    """

    assert Web3.isChecksumAddress(safe_address)

    redis = RedisRepository().redis
    lock_name = f"locks:begin_circles_onboarding_task:{safe_address}"
    try:
        with redis.lock(lock_name, blocking_timeout=1, timeout=LOCK_TIMEOUT):
            ethereum_client = EthereumClientProvider()

            # Do nothing if Token is already deployed
            if CirclesService(ethereum_client).is_token_deployed(safe_address):
                logger.info("Token is already deployed for {}".format(safe_address))
                return

            logger.info(
                "No token found, start onboarding for Circles Safe {}".format(
                    safe_address
                )
            )
            # Deploy Safe when it does not exist yet
            safe_creation2 = SafeCreation2.objects.get(safe=safe_address)
            if not safe_creation2.tx_hash:
                logger.info(
                    "Safe does not exist yet, start deploying it {}".format(
                        safe_address
                    )
                )
                circles_onboarding_safe_task.delay(safe_address)
            else:
                logger.info(
                    "Safe exists, we are done with safe {}".format(safe_address)
                )
    except LockError:
        pass


@app.shared_task(bind=True, soft_time_limit=LOCK_TIMEOUT, max_retries=3)
def circles_onboarding_safe_task(self, safe_address: str) -> None:
    """
    Check if create2 Safe has enough incoming trust connections to fund and
    deploy it
    :param safe_address: Address of the safe to-be-created
    """

    assert Web3.isChecksumAddress(safe_address)

    try:
        redis = RedisRepository().redis
        lock_name = f"locks:circles_onboarding_safe_task:{safe_address}"
        with redis.lock(lock_name, blocking_timeout=1, timeout=LOCK_TIMEOUT):
            logger.info("Check deploying Safe .. {}".format(safe_address))
            try:
                SafeCreationServiceProvider().deploy_create2_safe_tx(safe_address)
            except SafeCreation2.DoesNotExist:
                pass
            except NotEnoughFundingForCreation:
                logger.info(
                    "Safe does not have enough fund for deployment, "
                    "check trust connections {}".format(safe_address)
                )
                # If we have enough trust connections, fund safe
                if GraphQLService().check_trust_connections(safe_address):
                    logger.info("Fund Safe deployment for {}".format(safe_address))
                    ethereum_client = EthereumClientProvider()
                    safe_creation = SafeCreation2.objects.get(safe=safe_address)
                    # Estimate costs of safe creation
                    safe_deploy_cost = safe_creation.wei_estimated_deploy_cost()
                    logger.info("Estimating %d for safe creation", safe_deploy_cost)
                    # Estimate costs of token creation
                    transaction_service = TransactionServiceProvider()
                    token_deploy_cost = transaction_service.estimate_circles_signup_tx(
                        safe_address
                    )
                    logger.info("Estimating %d for token deployment", token_deploy_cost)
                    # Find total onboarding costs
                    payment = safe_deploy_cost + token_deploy_cost
                    # Get current safe balance
                    safe_balance = ethereum_client.get_balance(safe_address)
                    logger.info(
                        "Found %d balance for token deployment of safe=%s. Required=%d",
                        safe_balance,
                        safe_address,
                        payment,
                    )
                    if safe_balance >= payment:
                        logger.info(
                            "Onboarding is already funded {}".format(safe_address)
                        )
                        return

                    FundingServiceProvider().send_eth_to(
                        safe_address, payment, gas=30000
                    )
                    # Retry later to check for enough funding and successful deployment
                    raise self.retry(countdown=30)
                else:
                    logger.info(
                        "Not enough trust connections for funding deployment {}".format(
                            safe_address
                        )
                    )
    except LockError:
        pass


@app.shared_task(bind=True, soft_time_limit=LOCK_TIMEOUT, max_retries=6)
def begin_circles_onboarding_organization_task(
    self, safe_address: str, owner_address: str
) -> None:
    """
    Starts a multi-step onboarding task for Circles organizations which 1. funds
    deploys a Gnosis Safe for them 2. funds the deployment of their Organization.
    :param safe_address: Address of the safe to-be-created
    :param owner_address: Address of the first safe owner
    """

    assert Web3.isChecksumAddress(safe_address)
    assert Web3.isChecksumAddress(owner_address)

    redis = RedisRepository().redis
    lock_name = f"locks:begin_circles_onboarding_organization_task:{safe_address}"
    try:
        with redis.lock(lock_name, blocking_timeout=1, timeout=LOCK_TIMEOUT):
            logger.info(
                "Start onboarding for Circles Organization Safe {}".format(safe_address)
            )
            # Deploy Safe when it does not exist yet
            safe_creation2 = SafeCreation2.objects.get(safe=safe_address)
            if not safe_creation2.tx_hash:
                logger.info(
                    "Safe does not exist yet, start deploying it {}".format(
                        safe_address
                    )
                )
                circles_onboarding_organization_safe_task.delay(
                    safe_address, owner_address
                )
                # Retry later to check for signup funding
                raise self.retry(countdown=30)
            else:
                logger.info(
                    "Safe exists, start funding organizationSignup for {}".format(
                        safe_address
                    )
                )
                # Fund deployment when Organization does not exist yet
                circles_onboarding_organization_signup_task.delay(safe_address)
    except LockError:
        pass


@app.shared_task(soft_time_limit=LOCK_TIMEOUT, max_retries=3)
def circles_onboarding_organization_safe_task(
    safe_address: str, owner_address: str
) -> None:
    """
    Check if create2 Safe is being created by a trusted user
    :param safe_address: Address of the safe to-be-created
    :param owner_address: Address of the first safe owner
    """

    assert Web3.isChecksumAddress(safe_address)
    assert Web3.isChecksumAddress(owner_address)

    try:
        redis = RedisRepository().redis
        lock_name = f"locks:circles_onboarding_organization_safe_task:{safe_address}"
        with redis.lock(lock_name, blocking_timeout=1, timeout=LOCK_TIMEOUT):
            logger.info(
                "Check deploying Safe for organization .. {}".format(safe_address)
            )
            try:
                SafeCreationServiceProvider().deploy_create2_safe_tx(safe_address)
            except SafeCreation2.DoesNotExist:
                pass
            except NotEnoughFundingForCreation:
                logger.info(
                    "Safe does not have enough fund for deployment, "
                    "check owner {}".format(owner_address)
                )
                # If we have enough trust connections, fund safe
                if GraphQLService().check_trust_connections_by_user(owner_address):
                    logger.info(
                        "Fund Safe deployment for organization {}".format(safe_address)
                    )
                    safe_creation = SafeCreation2.objects.get(safe=safe_address)
                    safe_deploy_cost = safe_creation.wei_estimated_deploy_cost()
                    FundingServiceProvider().send_eth_to(
                        safe_address, safe_deploy_cost, gas=30000
                    )
                else:
                    logger.info(
                        "Owner {} does not have a deployed safe".format(owner_address)
                    )
    except LockError:
        pass


@app.shared_task(soft_time_limit=LOCK_TIMEOUT)
def circles_onboarding_organization_signup_task(safe_address: str) -> None:
    """
    Check if Organization Safe is already registered in the Hub, if not, fund it
    :param safe_address: Address of the created safe
    """

    assert Web3.isChecksumAddress(safe_address)

    # Additional funds for organization deployments (it should at least cover
    # one `trust` method call) next to the `organizationSignup` method
    ADDITIONAL_START_FUNDS = 100000000000000

    try:
        redis = RedisRepository().redis
        lock_name = f"locks:circles_onboarding_organization_signup_task:{safe_address}"
        with redis.lock(lock_name, blocking_timeout=1, timeout=LOCK_TIMEOUT):
            logger.info("Fund organizationSignup task for {}".format(safe_address))

            ethereum_client = EthereumClientProvider()

            # Do nothing if account already exists in Hub
            if CirclesService(ethereum_client).is_organization_deployed(safe_address):
                logger.info(
                    "Organization is already deployed for {}".format(safe_address)
                )
                return

            # Do nothing if the signup is already funded
            transaction_service = TransactionServiceProvider()

            # Sum `organizationSignup` and additional `trust` transactions
            # costs as the organization needs to trust at least one user in the
            # beginning to receive more funds
            payment = (
                transaction_service.estimate_circles_organization_signup_tx(
                    safe_address
                )
                + ADDITIONAL_START_FUNDS
            )
            safe_balance = ethereum_client.get_balance(safe_address)
            logger.info(
                "Found %d balance for organization deployment of safe=%s. Required=%d",
                safe_balance,
                safe_address,
                payment,
            )
            if safe_balance >= payment:
                logger.info("Organization is already funded {}".format(safe_address))
                return

            # Otherwise fund deployment
            logger.info("Fund Organization {}".format(safe_address))
            FundingServiceProvider().send_eth_to(
                safe_address, payment - safe_balance, gas=30000, retry=True
            )
    except LockError:
        pass
