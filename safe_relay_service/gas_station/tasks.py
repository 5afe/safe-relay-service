from celery import app
from celery.utils.log import get_task_logger
from requests.exceptions import ConnectionError as RequestsConnectionError

from .gas_station import GasStationProvider
from .models import GasPrice

logger = get_task_logger(__name__)


@app.shared_task(soft_time_limit=180)  # 3 minutes of limit
def calculate_gas_prices() -> GasPrice:
    logger.info("Starting Gas Price Calculation")
    try:
        gas_price = GasStationProvider().calculate_gas_prices()
        logger.info(gas_price)
    except RequestsConnectionError:
        logger.warning(
            "Problem connecting to node, cannot calculate gas price", exc_info=True
        )
