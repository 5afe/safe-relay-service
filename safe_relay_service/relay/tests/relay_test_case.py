from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from safe_relay_service.gas_station.gas_station import GasStationProvider

from ..services.safe_creation_service import SafeCreationServiceProvider
from ..services.transaction_service import TransactionServiceProvider


class RelayTestCaseMixin(SafeTestCaseMixin):
    @classmethod
    def prepare_safe_tests(cls):
        super().prepare_safe_tests()
        cls.gas_station = GasStationProvider()
        SafeCreationServiceProvider.del_singleton()
        TransactionServiceProvider.del_singleton()
        cls.relay_service = SafeCreationServiceProvider()
        cls.transaction_service = TransactionServiceProvider()
