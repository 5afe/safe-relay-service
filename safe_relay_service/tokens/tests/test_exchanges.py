from django.test import TestCase

import pytest

from ..exchanges import (Binance, DutchX, ExchangeApiException, Huobi, Kraken,
                         get_price_oracle)


class TestExchanges(TestCase):
    def test_get_price_oracle(self):
        self.assertIsInstance(get_price_oracle('Binance'), Binance)
        self.assertIsInstance(get_price_oracle('BINANCE'), Binance)
        self.assertIsInstance(get_price_oracle('KRAKEN'), Kraken)
        self.assertIsInstance(get_price_oracle('kraKen'), Kraken)
        self.assertIsInstance(get_price_oracle('DutchX'), DutchX)
        self.assertIsInstance(get_price_oracle('Huobi'), Huobi)
        self.assertIsInstance(get_price_oracle('huobI'), Huobi)
        with self.assertRaises(NotImplementedError):
            get_price_oracle('Another')

    def exchange_helper(self, exchange, tickers, bad_tickers):
        for ticker in tickers:
            price = exchange.get_price(ticker)
            self.assertIsInstance(price, float)
            self.assertGreater(price, .0)

        for ticker in bad_tickers:
            with self.assertRaises(ExchangeApiException):
                exchange.get_price(ticker)

    def test_binance(self):
        exchange = Binance()
        self.exchange_helper(exchange, ['BTCUSDT', 'ETHUSDT'], ['BADTICKER'])

    @pytest.mark.xfail
    def test_dutchx(self):
        exchange = DutchX()
        # Dai address is 0x89d24a6b4ccb1b6faa2625fe562bdd9a23260359
        self.exchange_helper(exchange, ['WETH-0x89d24a6b4ccb1b6faa2625fe562bdd9a23260359', 'RDN-WETH', 'WETH-DAI'],
                             ['WETH-0x11abca6b4ccb1b6faa2625fe562bdd9a23260359'])

    def test_huobi(self):
        exchange = Huobi()
        # Dai address is 0x89d24a6b4ccb1b6faa2625fe562bdd9a23260359
        self.exchange_helper(exchange, ['ethusdt', 'btcusdt'], ['BADTICKER'])

    def test_kraken(self):
        exchange = Kraken()
        self.exchange_helper(exchange, ['ETHEUR', 'GNOETH'], ['BADTICKER'])
