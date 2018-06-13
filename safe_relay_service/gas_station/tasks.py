from celery import app
from celery.utils.log import get_task_logger
from django.conf import settings

from .gas_station import GasStation
from .models import GasPrice

logger = get_task_logger(__name__)


@app.shared_task(bind=True)
def calculate_gas_prices(self) -> GasPrice:
    logger.info('Starting Gas Price Calculation')
    gas_price = GasStation(settings.ETHEREUM_NODE_URL, settings.GAS_STATION_NUMBER_BLOCKS).calculate_gas_prices()
    logger.info(gas_price)
