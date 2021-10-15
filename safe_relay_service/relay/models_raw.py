import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from django.db import connection, models

from gnosis.eth.constants import ERC20_721_TRANSFER_TOPIC


def parse_row(row):
    """
    Remove Decimal from Raw SQL queries
    """
    for r in row:
        if isinstance(r, Decimal):
            if r.as_integer_ratio()[1] == 1:
                yield int(r)
            else:
                yield float(r)
        else:
            yield r


def run_raw_query(query: str, *arguments):
    with connection.cursor() as cursor:
        cursor.execute(query, arguments)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, parse_row(row))) for row in cursor.fetchall()]


class SafeContractManagerRaw(models.Manager):
    def get_average_deploy_time(
        self, from_date: datetime.datetime, to_date: datetime.datetime
    ) -> datetime.timedelta:
        query = """
        SELECT AVG(A.created - B.first_transfer) FROM
          (SELECT address, timestamp as created
           FROM relay_safecontract S JOIN relay_internaltx I ON S.address = I.contract_address
           JOIN relay_ethereumtx E ON I.ethereum_tx_id = E.tx_hash
           JOIN relay_ethereumblock B ON E.block_id = B.number) A JOIN
          (SELECT address, MIN(timestamp) as first_transfer
           FROM relay_safecontract S JOIN relay_internaltx I
           ON S.address = I.to JOIN relay_ethereumtx E ON I.ethereum_tx_id = E.tx_hash
           JOIN relay_ethereumblock B ON E.block_id = B.number GROUP BY address) B ON A.address = B.address
        WHERE A.created BETWEEN  %s AND %s
        """

        with connection.cursor() as cursor:
            cursor.execute(query, [from_date, to_date])
            return cursor.fetchone()[0]

    def get_average_deploy_time_grouped(
        self, from_date: datetime.datetime, to_date: datetime.datetime
    ) -> Dict:
        query = """
        SELECT DATE(A.created) as created_date, AVG(A.created - B.first_transfer) as average_deploy_time FROM
          (SELECT address, timestamp as created
           FROM relay_safecontract S JOIN relay_internaltx I ON S.address = I.contract_address
           JOIN relay_ethereumtx E ON I.ethereum_tx_id = E.tx_hash
           JOIN relay_ethereumblock B ON E.block_id = B.number) A JOIN
          (SELECT address, MIN(timestamp) as first_transfer
           FROM relay_safecontract S JOIN relay_internaltx I
           ON S.address = I.to JOIN relay_ethereumtx E ON I.ethereum_tx_id = E.tx_hash
           JOIN relay_ethereumblock B ON E.block_id = B.number GROUP BY address) B ON A.address = B.address
        WHERE A.created BETWEEN  %s AND %s
        GROUP BY DATE(A.created)
        """
        return run_raw_query(query, from_date, to_date)

    def get_average_deploy_time_total(
        self, from_date: datetime.datetime, to_date: datetime.datetime
    ) -> datetime.timedelta:
        query = """
        SELECT AVG(EB.timestamp - SC.created)
        FROM (SELECT created, tx_hash FROM relay_safecreation
              UNION SELECT created, tx_hash FROM relay_safecreation2) AS SC
        JOIN relay_ethereumtx as ET ON SC.tx_hash=ET.tx_hash JOIN relay_ethereumblock as EB ON ET.block_id=EB.number
        WHERE SC.created BETWEEN %s AND %s
        """
        with connection.cursor() as cursor:
            cursor.execute(query, [from_date, to_date])
            return cursor.fetchone()[0]

    def get_average_deploy_time_total_grouped(
        self, from_date: datetime.datetime, to_date: datetime.datetime
    ) -> Dict:
        query = """
        SELECT DATE(SC.created) as created_date, AVG(EB.timestamp - SC.created) as average_deploy_time
        FROM (SELECT created, tx_hash FROM relay_safecreation
              UNION SELECT created, tx_hash FROM relay_safecreation2) AS SC
        JOIN relay_ethereumtx as ET ON SC.tx_hash=ET.tx_hash JOIN relay_ethereumblock as EB ON ET.block_id=EB.number
        WHERE SC.created BETWEEN %s AND %s
        GROUP BY DATE(SC.created)
        ORDER BY DATE(SC.created)
        """

        return run_raw_query(query, from_date, to_date)

    def get_total_balance_grouped(
        self, from_date: datetime.datetime, to_date: datetime.datetime
    ) -> int:
        """
        :return: Dictionary of {date: datetime.date, balance: decimal}
        """
        query = """
        SELECT * FROM
        (SELECT DISTINCT date, SUM(value) OVER(ORDER BY date) as balance
         FROM (SELECT DATE(EB.timestamp) as date, IT.value as value FROM
                (SELECT value, error, call_type, ethereum_tx_id
                 FROM relay_safecontract
                 JOIN relay_internaltx ON address="to" UNION
                 SELECT -value, error, call_type, ethereum_tx_id
                 FROM relay_safecontract
                 JOIN relay_internaltx ON address="_from"
                ) AS IT
                JOIN relay_ethereumtx ET ON IT.ethereum_tx_id=ET.tx_hash
                JOIN relay_ethereumblock EB ON ET.block_id=EB.number
                WHERE IT.error IS NULL AND IT.call_type != 1
               UNION SELECT DATE(dd), 0
                     FROM generate_series(%s, %s, '1 day'::interval) dd
              ) AS PREPARED
        ) AS RESULT
        WHERE RESULT.date BETWEEN %s AND %s
        ORDER BY RESULT.date
        """
        return run_raw_query(query, from_date, to_date, from_date, to_date)

    def get_total_token_balance(
        self, from_date: datetime.datetime, to_date: datetime.datetime
    ) -> Dict[str, Any]:
        """
        :return: Dictionary of {token_address: str, balance: decimal}
        """
        query = """
        SELECT token_address, SUM(EE.value) as balance FROM
          (SELECT SC.created, ethereum_tx_id, address, token_address, -(arguments->>'value')::decimal AS value
           FROM relay_safecontract SC JOIN relay_ethereumevent EV
           ON SC.address = EV.arguments->>'from'
           WHERE arguments ? 'value' AND topic='{0}'
           UNION SELECT SC.created, ethereum_tx_id, address, token_address, (arguments->>'value')::decimal
           FROM relay_safecontract SC JOIN relay_ethereumevent EV
           ON SC.address = EV.arguments->>'to'
           WHERE arguments ? 'value' AND topic='{0}') AS EE
        WHERE EE.created BETWEEN %s AND %s
        GROUP BY token_address
        """.format(
            ERC20_721_TRANSFER_TOPIC.replace("0x", "")
        )  # No risk of SQL Injection

        return run_raw_query(query, from_date, to_date)

    def get_total_token_balance_grouped(
        self, from_date: datetime.datetime, to_date: datetime.datetime
    ) -> Dict[str, Any]:
        """
        :return: Dictionary of {date: datetime.date, token_address: str, balance: decimal}
        """
        query = """
        SELECT * FROM
        (SELECT DISTINCT date, token_address, SUM(value) OVER(PARTITION BY token_address ORDER BY date) as balance
         FROM (SELECT DATE(EB.timestamp) as date, EE.value as value, EE.token_address as token_address FROM
               (SELECT SC.created, ethereum_tx_id, address, token_address, -(arguments->>'value')::decimal AS value
                FROM relay_safecontract SC JOIN relay_ethereumevent EV
                ON SC.address = EV.arguments->>'from'
                WHERE arguments ? 'value' AND topic='{0}'
                UNION SELECT SC.created, ethereum_tx_id, address, token_address, (arguments->>'value')::decimal
                FROM relay_safecontract SC JOIN relay_ethereumevent EV
                ON SC.address = EV.arguments->>'to'
                WHERE arguments ? 'value' AND topic='{0}'
               ) AS EE
               JOIN relay_ethereumtx ET ON EE.ethereum_tx_id=ET.tx_hash
               JOIN relay_ethereumblock EB ON ET.block_id=EB.number
               UNION SELECT DATE(dd), 0, T.token_address
                     FROM generate_series(%s, %s, '1 day'::interval) dd,
                          (SELECT DISTINCT token_address FROM relay_ethereumevent WHERE arguments ? 'value'
                                                                                        AND topic='{0}' ) AS T
               ) AS PREPARED
        ) AS RESULT
        WHERE RESULT.date BETWEEN %s AND %s
        ORDER BY RESULT.date;
       """.format(
            ERC20_721_TRANSFER_TOPIC.replace("0x", "")
        )  # No risk of SQL Injection

        return run_raw_query(query, from_date, to_date, from_date, to_date)

    def get_total_volume(
        self, from_date: datetime.datetime, to_date: datetime.datetime
    ) -> Optional[int]:
        from .models import EthereumTxCallType

        query = """
        SELECT SUM(IT.value) AS value
        FROM relay_safecontract SC
        JOIN relay_internaltx IT ON SC.address=IT."_from" OR SC.address=IT."to"
        JOIN relay_ethereumtx ET ON IT.ethereum_tx_id=ET.tx_hash
        JOIN relay_ethereumblock EB ON ET.block_id=EB.number
        WHERE IT.call_type != {0}
              AND error IS NULL
              AND EB.timestamp BETWEEN %s AND %s
        """.format(
            EthereumTxCallType.DELEGATE_CALL.value
        )
        with connection.cursor() as cursor:
            cursor.execute(query, [from_date, to_date])
            value = cursor.fetchone()[0]
            if value is not None:
                return int(value)
        return None

    def get_total_volume_grouped(
        self, from_date: datetime.datetime, to_date: datetime.datetime
    ) -> int:
        from .models import EthereumTxCallType

        query = """
        SELECT DATE(EB.timestamp) as date,
               SUM(IT.value) AS value
        FROM relay_safecontract SC
        JOIN relay_internaltx IT ON SC.address=IT."_from" OR SC.address=IT."to"
        JOIN relay_ethereumtx ET ON IT.ethereum_tx_id=ET.tx_hash
        JOIN relay_ethereumblock EB ON ET.block_id=EB.number
        WHERE IT.call_type != {0}
              AND error IS NULL
              AND EB.timestamp BETWEEN %s AND %s
        GROUP BY DATE(EB.timestamp)
        ORDER BY DATE(EB.timestamp)
        """.format(
            EthereumTxCallType.DELEGATE_CALL.value
        )

        return run_raw_query(query, from_date, to_date)

    def get_total_token_volume(
        self, from_date: datetime.datetime, to_date: datetime.datetime
    ):
        """
        :return: Dictionary of {token_address: str, volume: int}
        """
        query = """
        SELECT EV.token_address, SUM((EV.arguments->>'value')::decimal) AS value
        FROM relay_safecontract SC
        JOIN relay_ethereumevent EV ON SC.address = EV.arguments->>'from' OR SC.address = EV.arguments->>'to'
        JOIN relay_ethereumtx ET ON EV.ethereum_tx_id=ET.tx_hash
        JOIN relay_ethereumblock EB ON ET.block_id=EB.number
        WHERE arguments ? 'value'
              AND topic='{0}'
              AND EB.timestamp BETWEEN %s AND %s
        GROUP BY token_address""".format(
            ERC20_721_TRANSFER_TOPIC.replace("0x", "")
        )  # No risk of SQL Injection

        return run_raw_query(query, from_date, to_date)

    def get_total_token_volume_grouped(
        self, from_date: datetime.datetime, to_date: datetime.datetime
    ):
        """
        :return: Dictionary of {token_address: str, volume: int}
        """
        query = """
        SELECT DATE(EB.timestamp) as date, EV.token_address, SUM((EV.arguments->>'value')::decimal) AS value
        FROM relay_safecontract SC
        JOIN relay_ethereumevent EV ON SC.address = EV.arguments->>'from' OR SC.address = EV.arguments->>'to'
        JOIN relay_ethereumtx ET ON EV.ethereum_tx_id=ET.tx_hash
        JOIN relay_ethereumblock EB ON ET.block_id=EB.number
        WHERE arguments ? 'value'
              AND topic='{0}'
              AND EB.timestamp BETWEEN %s AND %s
        GROUP BY DATE(EB.timestamp), token_address
        ORDER BY DATE(EB.timestamp)""".format(
            ERC20_721_TRANSFER_TOPIC.replace("0x", "")
        )  # No risk of SQL Injection

        return run_raw_query(query, from_date, to_date)

    def get_creation_tokens_usage(
        self, from_date: datetime.datetime, to_date: datetime.datetime
    ) -> Optional[List[Dict[str, Any]]]:
        query = """
        SELECT DISTINCT payment_token, COUNT(*) OVER(PARTITION BY payment_token) as number,
                        100.0 * COUNT(*) OVER(PARTITION BY payment_token) / COUNT(*) OVER() as percentage
        FROM (SELECT tx_hash, payment_token, created FROM relay_safecreation
              UNION SELECT tx_hash, payment_token, created FROM relay_safecreation2) SC
        JOIN relay_ethereumtx ET ON SC.tx_hash = ET.tx_hash
        WHERE SC.created BETWEEN %s AND %s
        """

        return run_raw_query(query, from_date, to_date)

    def get_creation_tokens_usage_grouped(
        self, from_date: datetime.datetime, to_date: datetime.datetime
    ) -> Optional[List[Dict[str, Any]]]:
        query = """
        SELECT DISTINCT DATE(SC.created), payment_token,
                        COUNT(*) OVER(PARTITION BY DATE(SC.created), payment_token) as number,
                        100.0 * COUNT(*) OVER(PARTITION BY DATE(SC.created), payment_token) /
                                COUNT(*) OVER(PARTITION BY DATE(SC.created)) as percentage
        FROM (SELECT tx_hash, payment_token, created FROM relay_safecreation
              UNION SELECT tx_hash, payment_token, created FROM relay_safecreation2) SC
        JOIN relay_ethereumtx ET ON SC.tx_hash = ET.tx_hash
        WHERE SC.created BETWEEN %s AND %s
        ORDER BY(DATE(SC.created))
        """
        # Returns list of {'date': date, 'payment_token': Optional[str], 'number': int, percentage: 'float')
        return run_raw_query(query, from_date, to_date)


class SafeContractQuerySetRaw(models.QuerySet):
    def with_token_balance(self):
        """
        :return: Dictionary of {address: str, token_address: str and balance: int}
        """
        query = """
        SELECT address, token_address, SUM(value) as balance FROM
          (SELECT address, token_address, -(arguments->>'value')::decimal AS value
           FROM relay_safecontract JOIN relay_ethereumevent
           ON relay_safecontract.address = relay_ethereumevent.arguments->>'from'
           WHERE arguments ? 'value' AND topic='{0}'
           UNION SELECT address, token_address, (arguments->>'value')::decimal
           FROM relay_safecontract JOIN relay_ethereumevent
           ON relay_safecontract.address = relay_ethereumevent.arguments->>'to'
           WHERE arguments ? 'value' AND topic='{0}') AS X
        GROUP BY address, token_address
        """.format(
            ERC20_721_TRANSFER_TOPIC.replace("0x", "")
        )

        return run_raw_query(query)
