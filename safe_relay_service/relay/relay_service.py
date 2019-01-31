from typing import Tuple, Union

from django_eth.constants import NULL_ADDRESS
from gnosis.safe.safe_service import (GasPriceTooLow, InvalidRefundReceiver,
                                      SafeService, SafeServiceProvider)

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

    # FIXME Estimate everything in one method, same with Safe info
    def estimate_tx_gas_price(self, gas_token: Union[str, None]=None):
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
                         tx_gas=None) -> Tuple[str, any]:
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
            tx_gas_price=tx_gas_price)

    def send_multisig_subtx(self,
                         safe_address: str,
                         sub_module_address: str,
                         to: str,
                         value: int,
                         data: bytes,
                         operation: int,
                         safe_tx_gas: int,
                         data_gas: int,
                         gas_price: int,
                         gas_token: str,
                         refund_receiver: str,
                         meta: bytes,
                         signatures: bytes,
                         tx_sender_private_key=None,
                         tx_gas=None) -> Tuple[str, any]:
        """
        This function calls the `send_multisig_subtx` of the SafeService, but has some limitations to prevent abusing
        the relay
        :return: Tuple(tx_hash, tx)
        :raises: InvalidMultisigTx: If user tx cannot go through the Safe
        """

        data = data or b''
        meta = meta or b''
        gas_token = gas_token or NULL_ADDRESS
        refund_receiver = refund_receiver or NULL_ADDRESS
        to = to or NULL_ADDRESS

        # Make sure refund receiver is set to 0x0 so that the contract refunds the gas costs to tx.origin
        if not self._check_refund_receiver(refund_receiver):
            raise InvalidRefundReceiver(refund_receiver)

        # TODO check to see if recipient contract is a merchant reciever contract, if so, gas_price of 0 is allowed,
        # TODO otherwise make sure a gas_price is set to charge the cx accordingly for a non network subscription
        # if gas_price == 0:
        #    raise RefundMustBeEnabled('Tx internal gas price cannot be 0')

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

        return self.safe_service.send_multisig_subtx(
            safe_address,
            sub_module_address,
            to,
            value,
            data,
            operation,
            safe_tx_gas,
            data_gas,
            gas_price,
            gas_token,
            refund_receiver,
            meta,
            signatures,
            tx_sender_private_key=tx_sender_private_key,
            tx_gas=tx_gas,
            tx_gas_price=tx_gas_price)
