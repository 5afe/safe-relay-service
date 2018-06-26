from ..contracts import get_safe_personal_contract
from ..ethereum_service import EthereumServiceProvider
from ..safe_service import SafeServiceProvider


class TestCaseWithSafeContractMixin:
    @classmethod
    def prepare_safe_tests(cls):
        cls.safe_service = SafeServiceProvider()
        cls.ethereum_service = EthereumServiceProvider()
        cls.w3 = cls.ethereum_service.w3

        cls.safe_personal_deployer = cls.w3.eth.accounts[0]
        cls.safe_personal_contract_address = cls.safe_service.deploy_master_contract(deployer_account=
                                                                                     cls.safe_personal_deployer)
        cls.safe_personal_contract = get_safe_personal_contract(cls.w3, cls.safe_personal_contract_address)
