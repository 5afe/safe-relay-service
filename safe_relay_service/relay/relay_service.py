from typing import Tuple, Union, NamedTuple, List, Iterable, Dict

from django.conf import settings

from gnosis.eth.constants import NULL_ADDRESS
from gnosis.safe.safe_service import (GasPriceTooLow, InvalidRefundReceiver,
                                      SafeCreationEstimate, SafeService,
                                      SafeServiceProvider, SafeServiceException)

from .models import SafeMultisigTx, SafeContract, SafeCreation
from safe_relay_service.gas_station.gas_station import (GasStation,
                                                        GasStationProvider)
from safe_relay_service.tokens.models import Token


class RelayServiceException(Exception):
    pass


class RefundMustBeEnabled(RelayServiceException):
    pass


class InvalidGasToken(RelayServiceException):
    pass


class SignaturesNotFound(RelayServiceException):
    pass


class SafeMultisigTxExists(Exception):
    pass


class SafeMultisigTxError(Exception):
    pass


class SafeInfo(NamedTuple):
    address: str
    nonce: int
    threshold: int
    owners: List[str]
    master_copy: str


class TransactionEstimation(NamedTuple):
    safe_tx_gas: int
    data_gas: int
    operational_gas: int
    gas_price: int
    gas_token: str
    last_used_nonce: int


class RelayServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = RelayService(SafeServiceProvider(), GasStationProvider())
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class RelayService:
    def __init__(self, safe_service: SafeService, gas_station: GasStation):
        self.safe_service = safe_service
        self.gas_station = gas_station

    def __getattr__(self, attr):
        return getattr(self.safe_service, attr)

    def _check_refund_receiver(self, refund_receiver: str) -> bool:
        """
        We only support tx.origin as refund receiver right now
        In the future we can also accept transactions where it is set to our service account to receive the payments.
        This would prevent that anybody can front-run our service
        """
        return refund_receiver == NULL_ADDRESS

    def _estimate_tx_gas_price(self, gas_token: Union[str, None]=None):
        gas_token = gas_token or NULL_ADDRESS
        gas_price_fast = self.gas_station.get_gas_prices().fast

        if gas_token != NULL_ADDRESS:
            try:
                gas_token_model = Token.objects.get(address=gas_token, gas=True)
                return gas_token_model.calculate_gas_price(gas_price_fast)
            except Token.DoesNotExist:
                raise InvalidGasToken('Gas token %s not valid' % gas_token)
        else:
            return gas_price_fast

    def create_safe_tx(self, s: int, owners: Iterable[str], threshold: int, payment_token: Union[str, None],
                       payment_token_eth_value: float = 1.0,
                       fixed_creation_cost: Union[int, None] = None) -> SafeCreation:
        """
        Create models for safe tx
        :param s: Random s value for ecdsa signature
        :param owners: Owners of the new Safe
        :param threshold: Minimum number of users required to operate the Safe
        :param payment_token: Address of the payment token, if ether is not used
        :param payment_token_eth_value: Value of payment_token per 1 ether
        :param fixed_creation_cost: Fixed creation cost of Safe (Wei)
        :rtype: SafeCreation
        """

        relay_service = RelayServiceProvider()
        gas_station = GasStationProvider()
        fast_gas_price: int = gas_station.get_gas_prices().fast
        safe_creation_tx = relay_service.build_safe_creation_tx(s, owners, threshold, fast_gas_price, payment_token,
                                                                payment_token_eth_value=payment_token_eth_value,
                                                                fixed_creation_cost=fixed_creation_cost)

        safe_contract = SafeContract.objects.create(address=safe_creation_tx.safe_address,
                                                    master_copy=safe_creation_tx.master_copy)

        return SafeCreation.objects.create(
            deployer=safe_creation_tx.deployer_address,
            safe=safe_contract,
            master_copy=safe_creation_tx.master_copy,
            funder=safe_creation_tx.funder,
            owners=owners,
            threshold=threshold,
            payment=safe_creation_tx.payment,
            tx_hash=safe_creation_tx.tx_hash.hex(),
            gas=safe_creation_tx.gas,
            gas_price=safe_creation_tx.gas_price,
            payment_token=None if safe_creation_tx.payment_token == NULL_ADDRESS else safe_creation_tx.payment_token,
            value=safe_creation_tx.tx_pyethereum.value,
            v=safe_creation_tx.v,
            r=safe_creation_tx.r,
            s=safe_creation_tx.s,
            data=safe_creation_tx.tx_pyethereum.data,
            signed_tx=safe_creation_tx.tx_raw
        )

    def create_multisig_tx(self,
                           safe_address: str,
                           to: str,
                           value: int,
                           data: bytes,
                           operation: int,
                           safe_tx_gas: int,
                           data_gas: int,
                           gas_price: int,
                           gas_token: str,
                           refund_receiver: str,
                           nonce: int,
                           signatures: List[Dict[str, int]]) -> SafeMultisigTx:
        """
        :return: Database model of SafeMultisigTx
        :raises: SafeMultisigTxExists: If Safe Multisig Tx with nonce already exists
        :raises: SafeMultisigTxError: If Safe Tx is not valid (not sorted owners, bad signature, bad nonce...)
        """

        if SafeMultisigTx.objects.filter(safe=safe_address, nonce=nonce).exists():
            raise SafeMultisigTxExists

        signature_pairs = [(s['v'], s['r'], s['s']) for s in signatures]
        signatures_packed = self.safe_service.signatures_to_bytes(signature_pairs)
        safe_tx_hash = self.safe_service.get_hash_for_safe_tx(safe_address, to, value, data,
                                                              operation, safe_tx_gas, data_gas, gas_price,
                                                              gas_token, refund_receiver, nonce)

        try:
            tx_hash, tx = self.send_multisig_tx(
                safe_address,
                to,
                value,
                data,
                operation,
                safe_tx_gas,
                data_gas,
                gas_price,
                gas_token,
                refund_receiver,
                signatures_packed
            )
        except (SafeServiceException, RelayServiceException) as exc:
            raise SafeMultisigTxError(str(exc)) from exc

        safe_contract = SafeContract.objects.get(address=safe_address)

        return SafeMultisigTx.objects.create(
            safe=safe_contract,
            to=to,
            value=value,
            data=data,
            operation=operation,
            safe_tx_gas=safe_tx_gas,
            data_gas=data_gas,
            gas_price=gas_price,
            gas_token=None if gas_token == NULL_ADDRESS else gas_token,
            refund_receiver=refund_receiver,
            nonce=nonce,
            signatures=signatures_packed,
            gas=tx['gas'],
            safe_tx_hash=safe_tx_hash,
            tx_hash=tx_hash.hex(),
            tx_mined=False
        )

    def retrieve_safe_info(self, address: str) -> SafeInfo:
        nonce = self.safe_service.retrieve_nonce(address)
        threshold = self.safe_service.retrieve_threshold(address)
        owners = self.safe_service.retrieve_owners(address)
        master_copy = self.safe_service.retrieve_master_copy_address(address)
        return SafeInfo(address, nonce, threshold, owners, master_copy)

    def estimate_safe_creation(self, number_owners: int, payment_token: Union[str, None]) -> SafeCreationEstimate:
        if payment_token and payment_token != NULL_ADDRESS:
            try:
                token = Token.objects.get(address=payment_token, gas=True)
                payment_token_eth_value = token.get_eth_value()
            except Token.DoesNotExist:
                raise InvalidGasToken(payment_token)
        else:
            payment_token_eth_value = 1.0

        gas_price = self.gas_station.get_gas_prices().fast
        fixed_creation_cost = settings.SAFE_FIXED_CREATION_COST
        return self.safe_service.estimate_safe_creation(number_owners, gas_price, payment_token,
                                                        payment_token_eth_value=payment_token_eth_value,
                                                        fixed_creation_cost=fixed_creation_cost)

    def estimate_tx_cost(self, address: str, to: str, value: int, data: str, operation: int,
                         gas_token: Union[str, None]) -> TransactionEstimation:
        last_used_nonce = SafeMultisigTx.objects.get_last_nonce_for_safe(address)
        safe_tx_gas = self.safe_service.estimate_tx_gas(address, to, value, data, operation)
        safe_data_tx_gas = self.safe_service.estimate_tx_data_gas(address, to, value, data, operation, gas_token,
                                                                  safe_tx_gas)
        safe_operational_tx_gas = self.safe_service.estimate_tx_operational_gas(address,
                                                                                len(data) if data else 0)
        # Can throw RelayServiceException
        gas_price = self._estimate_tx_gas_price(gas_token)
        return TransactionEstimation(safe_tx_gas, safe_data_tx_gas, safe_operational_tx_gas, gas_price,
                                     gas_token or NULL_ADDRESS, last_used_nonce)

    def send_multisig_tx(self,
                         safe_address: str,
                         to: str,
                         value: int,
                         data: bytes,
                         operation: int,
                         safe_tx_gas: int,
                         data_gas: int,
                         gas_price: int,
                         gas_token: str,
                         refund_receiver: str,
                         signatures: bytes,
                         tx_sender_private_key=None,
                         tx_gas=None,
                         block_identifier='pending') -> Tuple[str, any]:
        """
        This function calls the `send_multisig_tx` of the SafeService, but has some limitations to prevent abusing
        the relay
        :return: Tuple(tx_hash, tx)
        :raises: InvalidMultisigTx: If user tx cannot go through the Safe
        """

        data = data or b''
        gas_token = gas_token or NULL_ADDRESS
        refund_receiver = refund_receiver or NULL_ADDRESS
        to = to or NULL_ADDRESS

        # Make sure refund receiver is set to 0x0 so that the contract refunds the gas costs to tx.origin
        if not self._check_refund_receiver(refund_receiver):
            raise InvalidRefundReceiver(refund_receiver)

        if gas_price == 0:
            raise RefundMustBeEnabled('Tx internal gas price cannot be 0')

        threshold = self.retrieve_threshold(safe_address)
        number_signatures = len(signatures) // 65  # One signature = 65 bytes
        if number_signatures < threshold:
            raise SignaturesNotFound('Need at least %d signatures' % threshold)

        # If gas_token is specified, we see if the `gas_price` matches the current token value and use as the
        # external tx gas the fast gas price from the gas station.
        # If not, we just use the internal tx gas_price for the gas_price
        # Gas price must be at least >= standard gas price
        current_gas_prices = self.gas_station.get_gas_prices()
        current_fast_gas_price = current_gas_prices.fast
        current_standard_gas_price = current_gas_prices.standard

        if gas_token != NULL_ADDRESS:
            try:
                gas_token_model = Token.objects.get(address=gas_token, gas=True)
                estimated_gas_price = gas_token_model.calculate_gas_price(current_standard_gas_price)
                if gas_price < estimated_gas_price:
                    raise GasPriceTooLow('Required gas-price>=%d to use gas-token' % estimated_gas_price)
                # We use gas station tx gas price. We cannot use internal tx's because is calculated
                # based on the gas token
            except Token.DoesNotExist:
                raise InvalidGasToken('Gas token %s not valid' % gas_token)
        else:
            if gas_price < current_standard_gas_price:
                raise GasPriceTooLow('Required gas-price>=%d' % current_standard_gas_price)

        # We use fast tx gas price, if not txs could we stuck
        tx_gas_price = current_fast_gas_price

        return self.safe_service.send_multisig_tx(
            safe_address,
            to,
            value,
            data,
            operation,
            safe_tx_gas,
            data_gas,
            gas_price,
            gas_token,
            refund_receiver,
            signatures,
            tx_sender_private_key=tx_sender_private_key,
            tx_gas=tx_gas,
            tx_gas_price=tx_gas_price,
            block_identifier=block_identifier)
