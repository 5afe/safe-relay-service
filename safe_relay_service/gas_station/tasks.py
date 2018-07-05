from celery import app
from celery.utils.log import get_task_logger

from .gas_station import GasStationProvider
from .models import GasPrice

logger = get_task_logger(__name__)


@app.shared_task(bind=True)
def calculate_gas_prices(self) -> GasPrice:
    logger.info('Starting Gas Price Calculation')
    gas_price = GasStationProvider().calculate_gas_prices()
    logger.info(gas_price)
