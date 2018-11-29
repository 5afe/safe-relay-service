from gnosis.safe.contracts import get_safe_contract
from gnosis.safe.ethereum_service import EthereumServiceProvider
from gnosis.safe.safe_service import SafeServiceProvider

from ..relay_service import RelayService
from safe_relay_service.gas_station.gas_station import GasStationMock


class TestCaseWithSafeContractMixin:
    @classmethod
    def prepare_safe_tests(cls):
        cls.safe_service = SafeServiceProvider()
        cls.ethereum_service = EthereumServiceProvider()
        cls.gas_station = GasStationMock()
        cls.relay_service = RelayService(cls.safe_service, cls.gas_station)
        cls.w3 = cls.ethereum_service.w3

        cls.safe_deployer = cls.w3.eth.accounts[0]
        cls.safe_contract_address = cls.safe_service.deploy_master_contract(deployer_account=cls.safe_deployer)
        cls.safe_service.master_copy_address = cls.safe_contract_address
        cls.safe_service.valid_master_copy_addresses = [cls.safe_contract_address]
        cls.safe_contract = get_safe_contract(cls.w3, cls.safe_contract_address)
