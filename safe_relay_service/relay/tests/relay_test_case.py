from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from safe_relay_service.gas_station.gas_station import GasStationProvider

from ..relay_service import RelayServiceProvider


class RelayTestCaseMixin(SafeTestCaseMixin):
    @classmethod
    def prepare_safe_tests(cls):
        super().prepare_safe_tests()
        cls.gas_station = GasStationProvider()
        RelayServiceProvider.del_singleton()
        cls.relay_service = RelayServiceProvider()
