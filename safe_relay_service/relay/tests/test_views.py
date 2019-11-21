import datetime
import logging

from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import dateparse, timezone

from eth_account import Account
from ethereum.utils import check_checksum
from faker import Faker
from rest_framework import status
from rest_framework.test import APITestCase

from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.utils import (get_eth_address_with_invalid_checksum,
                              get_eth_address_with_key)
from gnosis.safe import SafeOperation, SafeTx
from gnosis.safe.signatures import signatures_to_bytes
from gnosis.safe.tests.utils import generate_valid_s

from safe_relay_service.gas_station.tests.factories import GasPriceFactory
from safe_relay_service.tokens.tests.factories import TokenFactory

from ..models import SafeContract, SafeCreation, SafeMultisigTx
from ..serializers import SafeCreationSerializer
from ..services.safe_creation_service import SafeCreationServiceProvider
from .factories import (EthereumEventFactory, EthereumTxFactory,
                        InternalTxFactory, SafeContractFactory,
                        SafeCreation2Factory, SafeFundingFactory,
                        SafeMultisigTxFactory)
from .relay_test_case import RelayTestCaseMixin

faker = Faker()

logger = logging.getLogger(__name__)


class TestViews(RelayTestCaseMixin, APITestCase):
    def test_about(self):
        response = self.client.get(reverse('v1:about'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_gas_station(self):
        response = self.client.get(reverse('v1:gas-station'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_gas_station_history(self):
        response = self.client.get(reverse('v1:gas-station-history'), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

        first_datetime = timezone.now() - datetime.timedelta(hours=3)
        second_datetime = timezone.now() - datetime.timedelta(hours=2)
        third_datetime = timezone.now() - datetime.timedelta(hours=1)
        for date in (first_datetime, second_datetime, third_datetime):
            GasPriceFactory(created=date)

        response = self.client.get(reverse('v1:gas-station-history'), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 3)

        iso_format = second_datetime.isoformat().replace('+00:00', 'Z')
        response = self.client.get(reverse('v1:gas-station-history') + f'?fromDate={iso_format}',
                                   format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)

        response = self.client.get(reverse('v1:gas-station-history') + f'?toDate={iso_format}',
                                   format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 2)

    def test_safe_balances(self):
        safe_address = Account.create().address
        response = self.client.get(reverse('v1:safe-balances', args=(safe_address, )))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        SafeContractFactory(address=safe_address)
        value = 7
        self.send_ether(safe_address, 7)
        response = self.client.get(reverse('v1:safe-balances', args=(safe_address, )))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 1)
        self.assertIsNone(response.json()[0]['tokenAddress'])
        self.assertEqual(response.json()[0]['balance'], str(value))

        tokens_value = 12
        erc20 = self.deploy_example_erc20(tokens_value, safe_address)
        response = self.client.get(reverse('v1:safe-balances', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 1)

        EthereumEventFactory(token_address=erc20.address, to=safe_address)
        response = self.client.get(reverse('v1:safe-balances', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual(response.json(), [{'tokenAddress': None, 'balance': str(value)},
                                                {'tokenAddress': erc20.address, 'balance': str(tokens_value)}])

    def test_safe_multisig_tx_post(self):
        # Create Safe ------------------------------------------------
        w3 = self.ethereum_client.w3
        safe_balance = w3.toWei(0.01, 'ether')
        owner0_balance = safe_balance
        accounts = [self.create_account(initial_wei=owner0_balance), self.create_account(initial_wei=owner0_balance)]
        # Signatures must be sorted!
        accounts.sort(key=lambda account: account.address.lower())
        owners = [x.address for x in accounts]
        threshold = len(accounts)

        safe_creation = self.deploy_test_safe(owners=owners, threshold=threshold, initial_funding_wei=safe_balance)
        my_safe_address = safe_creation.safe_address
        SafeContractFactory(address=my_safe_address)

        # Safe prepared --------------------------------------------
        to, _ = get_eth_address_with_key()
        value = safe_balance // 2
        tx_data = None
        operation = 0
        refund_receiver = None
        nonce = 0

        data = {
            "to": to,
            "value": value,
            "data": tx_data,
            "operation": operation,
        }

        # Get estimation for gas
        response = self.client.post(reverse('v1:safe-multisig-tx-estimate', args=(my_safe_address,)),
                                    data=data,
                                    format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        estimation_json = response.json()

        safe_tx_gas = estimation_json['safeTxGas'] + estimation_json['operationalGas']
        data_gas = estimation_json['dataGas']
        gas_price = estimation_json['gasPrice']
        gas_token = estimation_json['gasToken']

        multisig_tx_hash = SafeTx(
            None,
            my_safe_address,
            to,
            value,
            tx_data,
            operation,
            safe_tx_gas,
            data_gas,
            gas_price,
            gas_token,
            refund_receiver,
            safe_nonce=nonce
        ).safe_tx_hash

        signatures = [account.signHash(multisig_tx_hash) for account in accounts]
        signatures_json = [{'v': s['v'], 'r': s['r'], 's': s['s']} for s in signatures]

        data = {
            "to": to,
            "value": value,
            "data": tx_data,
            "operation": operation,
            "safe_tx_gas": safe_tx_gas,
            "data_gas": data_gas,
            "gas_price": gas_price,
            "gas_token": gas_token,
            "nonce": nonce,
            "signatures": signatures_json
        }

        response = self.client.post(reverse('v1:safe-multisig-txs', args=(my_safe_address,)),
                                    data=data,
                                    format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        tx_hash = response.json()['transactionHash'][2:]  # Remove leading 0x
        safe_multisig_tx = SafeMultisigTx.objects.get(ethereum_tx__tx_hash=tx_hash)
        self.assertEqual(safe_multisig_tx.to, to)
        self.assertEqual(safe_multisig_tx.value, value)
        self.assertEqual(safe_multisig_tx.data, tx_data)
        self.assertEqual(safe_multisig_tx.operation, operation)
        self.assertEqual(safe_multisig_tx.safe_tx_gas, safe_tx_gas)
        self.assertEqual(safe_multisig_tx.data_gas, data_gas)
        self.assertEqual(safe_multisig_tx.gas_price, gas_price)
        self.assertEqual(safe_multisig_tx.gas_token, None)
        self.assertEqual(safe_multisig_tx.nonce, nonce)
        signature_pairs = [(s['v'], s['r'], s['s']) for s in signatures]
        signatures_packed = signatures_to_bytes(signature_pairs)
        self.assertEqual(bytes(safe_multisig_tx.signatures), signatures_packed)

        # Send the same tx again
        response = self.client.post(reverse('v1:safe-multisig-txs', args=(my_safe_address,)),
                                    data=data,
                                    format='json')
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertTrue('exists' in response.data['exception'])

    def test_safe_multisig_tx_get(self):
        safe = SafeContractFactory()
        my_safe_address = safe.address
        response = self.client.get(reverse('v1:safe-multisig-txs', args=(my_safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        safe_multisig_tx = SafeMultisigTxFactory(safe=safe)
        response = self.client.get(reverse('v1:safe-multisig-txs', args=(my_safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        self.assertEqual(response_json['count'], 1)
        self.assertEqual(len(response_json['results']), 1)
        response_tx = response_json['results'][0]
        self.assertIsNone(response_tx['gasToken'])
        self.assertEqual(response_tx['data'], safe_multisig_tx.data.hex())
        self.assertEqual(response_tx['dataGas'], safe_multisig_tx.data_gas)
        self.assertIsInstance(response_tx['ethereumTx']['gas'], str)
        self.assertEqual(int(response_tx['ethereumTx']['gas']), safe_multisig_tx.ethereum_tx.gas)
        self.assertEqual(response_tx['nonce'], safe_multisig_tx.nonce)
        self.assertEqual(response_tx['operation'], SafeOperation(safe_multisig_tx.operation).name)
        self.assertEqual(response_tx['refundReceiver'], safe_multisig_tx.refund_receiver)
        self.assertEqual(response_tx['safeTxGas'], safe_multisig_tx.safe_tx_gas)
        self.assertEqual(response_tx['safeTxHash'], safe_multisig_tx.safe_tx_hash.hex())
        self.assertEqual(response_tx['to'], safe_multisig_tx.to)
        self.assertEqual(response_tx['txHash'], safe_multisig_tx.ethereum_tx.tx_hash.hex())
        self.assertEqual(response_tx['value'], safe_multisig_tx.value)

        safe_multisig_tx2 = SafeMultisigTxFactory(safe=safe)
        safe_multisig_tx3 = SafeMultisigTxFactory(safe=safe)
        response = self.client.get(reverse('v1:safe-multisig-txs', args=(my_safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['count'], 3)

        # Test filter by `to`
        response = self.client.get(reverse('v1:safe-multisig-txs', args=(my_safe_address,)),
                                   {'to': safe_multisig_tx3.to})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['count'], 1)

        value = safe_multisig_tx.value + safe_multisig_tx2.value + safe_multisig_tx3.value
        safe_multisig_tx4 = SafeMultisigTxFactory(safe=safe, value=value)

        # Test filter by `value >`
        response = self.client.get(reverse('v1:safe-multisig-txs', args=(my_safe_address,)),
                                   {'value__gt': value - 1})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['count'], 1)
        self.assertEqual(response.json()['results'][0]['to'], safe_multisig_tx4.to)

        # Test sorting
        response = self.client.get(reverse('v1:safe-multisig-txs', args=(my_safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['count'], 4)
        self.assertEqual(response.json()['results'][0]['to'], safe_multisig_tx4.to)

        # Test reverse sorting
        response = self.client.get(reverse('v1:safe-multisig-txs', args=(my_safe_address,)),
                                   {'ordering': 'created'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['count'], 4)
        self.assertEqual(response.json()['results'][0]['to'], safe_multisig_tx.to)

    def test_safe_multisig_tx_post_gas_token(self):
        # Create Safe ------------------------------------------------
        w3 = self.ethereum_client.w3
        safe_balance = w3.toWei(0.01, 'ether')
        owner0_balance = safe_balance
        owner_account = self.create_account(initial_wei=owner0_balance)
        self.assertEqual(self.w3.eth.getBalance(owner_account.address), owner0_balance)
        owner = owner_account.address
        threshold = 1

        safe_creation = self.deploy_test_safe(owners=[owner], threshold=threshold, initial_funding_wei=safe_balance)
        my_safe_address = safe_creation.safe_address
        SafeContractFactory(address=my_safe_address)

        # Get tokens for the safe
        safe_token_balance = int(1e18)
        erc20_contract = self.deploy_example_erc20(safe_token_balance, my_safe_address)

        # Safe prepared --------------------------------------------
        to, _ = get_eth_address_with_key()
        value = safe_balance
        tx_data = None
        operation = 0
        refund_receiver = None
        nonce = 0
        gas_token = erc20_contract.address

        data = {
            "to": to,
            "value": value,
            "data": tx_data,
            "operation": operation,
            "gasToken": gas_token
        }

        # Get estimation for gas. Token does not exist
        response = self.client.post(reverse('v1:safe-multisig-tx-estimate', args=(my_safe_address,)),
                                    data=data,
                                    format='json')
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual('InvalidGasToken: %s' % gas_token, response.json()['exception'])

        # Create token
        token_model = TokenFactory(address=gas_token)
        response = self.client.post(reverse('v1:safe-multisig-tx-estimate', args=(my_safe_address,)),
                                    data=data,
                                    format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        estimation_json = response.json()

        safe_tx_gas = estimation_json['safeTxGas'] + estimation_json['operationalGas']
        data_gas = estimation_json['dataGas']
        gas_price = estimation_json['gasPrice']
        gas_token = estimation_json['gasToken']

        multisig_tx_hash = SafeTx(
            None,
            my_safe_address,
            to,
            value,
            tx_data,
            operation,
            safe_tx_gas,
            data_gas,
            gas_price,
            gas_token,
            refund_receiver,
            safe_nonce=nonce
        ).safe_tx_hash

        signatures = [w3.eth.account.signHash(multisig_tx_hash, private_key)
                      for private_key in [owner_account.privateKey]]
        signatures_json = [{'v': s['v'], 'r': s['r'], 's': s['s']} for s in signatures]

        data = {
            "to": to,
            "value": value,
            "data": tx_data,
            "operation": operation,
            "safe_tx_gas": safe_tx_gas,
            "data_gas": data_gas,
            "gas_price": gas_price,
            "gas_token": gas_token,
            "nonce": nonce,
            "signatures": signatures_json
        }

        response = self.client.post(reverse('v1:safe-multisig-txs', args=(my_safe_address,)),
                                    data=data,
                                    format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        tx_hash = response.json()['transactionHash'][2:]  # Remove leading 0x
        safe_multisig_tx = SafeMultisigTx.objects.get(ethereum_tx__tx_hash=tx_hash)
        self.assertEqual(safe_multisig_tx.to, to)
        self.assertEqual(safe_multisig_tx.value, value)
        self.assertEqual(safe_multisig_tx.data, tx_data)
        self.assertEqual(safe_multisig_tx.operation, operation)
        self.assertEqual(safe_multisig_tx.safe_tx_gas, safe_tx_gas)
        self.assertEqual(safe_multisig_tx.data_gas, data_gas)
        self.assertEqual(safe_multisig_tx.gas_price, gas_price)
        self.assertEqual(safe_multisig_tx.gas_token, gas_token)
        self.assertEqual(safe_multisig_tx.nonce, nonce)

    def test_safe_multisig_tx_errors(self):
        my_safe_address = get_eth_address_with_invalid_checksum()
        response = self.client.post(reverse('v1:safe-multisig-txs', args=(my_safe_address,)),
                                    data={},
                                    format='json')
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        my_safe_address, _ = get_eth_address_with_key()
        response = self.client.post(reverse('v1:safe-multisig-txs', args=(my_safe_address,)),
                                    data={},
                                    format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        my_safe_address = self.create2_test_safe_in_db().safe.address
        response = self.client.post(reverse('v1:safe-multisig-txs', args=(my_safe_address,)),
                                    data={},
                                    format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_safe_multisig_tx_estimate(self):
        my_safe_address = get_eth_address_with_invalid_checksum()
        response = self.client.post(reverse('v1:safe-multisig-tx-estimate', args=(my_safe_address,)),
                                    data={},
                                    format='json')
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        my_safe_address, _ = get_eth_address_with_key()
        response = self.client.post(reverse('v1:safe-multisig-tx-estimate', args=(my_safe_address,)),
                                    data={},
                                    format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        initial_funding = self.w3.toWei(0.0001, 'ether')
        to, _ = get_eth_address_with_key()
        data = {
            'to': to,
            'value': initial_funding // 2,
            'data': '0x',
            'operation': 1
        }

        safe_creation = self.deploy_test_safe(number_owners=3, threshold=2, initial_funding_wei=initial_funding)
        my_safe_address = safe_creation.safe_address
        SafeContractFactory(address=my_safe_address)

        response = self.client.post(reverse('v1:safe-multisig-tx-estimate', args=(my_safe_address,)),
                                    data=data,
                                    format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = response.json()
        self.assertGreater(response['safeTxGas'], 0)
        self.assertGreater(response['dataGas'], 0)
        self.assertGreater(response['gasPrice'], 0)
        self.assertIsNone(response['lastUsedNonce'])
        self.assertEqual(response['gasToken'], NULL_ADDRESS)

        to, _ = get_eth_address_with_key()
        data = {
            'to': to,
            'value': initial_funding // 2,
            'data': None,
            'operation': 0
        }
        response = self.client.post(reverse('v1:safe-multisig-tx-estimate', args=(my_safe_address,)),
                                    data=data,
                                    format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_safe_multisig_tx_estimates(self):
        my_safe_address = get_eth_address_with_invalid_checksum()
        response = self.client.post(reverse('v1:safe-multisig-tx-estimates', args=(my_safe_address,)),
                                    data={},
                                    format='json')
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        my_safe_address, _ = get_eth_address_with_key()
        response = self.client.post(reverse('v1:safe-multisig-tx-estimates', args=(my_safe_address,)),
                                    data={},
                                    format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        initial_funding = self.w3.toWei(0.0001, 'ether')

        safe_creation = self.deploy_test_safe(number_owners=3, threshold=2, initial_funding_wei=initial_funding)
        my_safe_address = safe_creation.safe_address
        SafeContractFactory(address=my_safe_address)

        to = Account.create().address
        tx = {
            'to': to,
            'value': initial_funding // 2,
            'data': '0x',
            'operation': 1
        }
        response = self.client.post(reverse('v1:safe-multisig-tx-estimates', args=(my_safe_address,)),
                                    data=tx,
                                    format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = response.json()
        self.assertGreater(int(response['safeTxGas']), 0)
        self.assertEqual(response['operationalGas'], '0')
        self.assertIsNone(response['lastUsedNonce'])
        self.assertEqual(len(response['estimations']), 1)
        estimation = response['estimations'][0]
        self.assertGreater(int(estimation['baseGas']), 0)
        self.assertGreater(int(estimation['gasPrice']), 0)
        self.assertEqual(estimation['gasToken'], NULL_ADDRESS)

        valid_token = TokenFactory(address=Account.create().address, gas=True, fixed_eth_conversion=2)
        response = self.client.post(reverse('v1:safe-multisig-tx-estimates', args=(my_safe_address,)),
                                    data=tx,
                                    format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = response.json()
        self.assertGreater(int(response['safeTxGas']), 0)
        self.assertEqual(response['operationalGas'], '0')
        self.assertIsNone(response['lastUsedNonce'])
        self.assertEqual(len(response['estimations']), 2)
        estimation_ether = response['estimations'][0]
        self.assertGreater(int(estimation_ether['baseGas']), 0)
        self.assertGreater(int(estimation_ether['gasPrice']), 0)
        self.assertEqual(estimation_ether['gasToken'], NULL_ADDRESS)
        estimation_token = response['estimations'][1]
        self.assertGreater(int(estimation_token['baseGas']), int(estimation_ether['baseGas']))
        self.assertAlmostEqual(int(estimation_token['gasPrice']), int(estimation_ether['gasPrice']) // 2, delta=1.0)
        self.assertEqual(estimation_token['gasToken'], valid_token.address)

    def test_get_all_txs(self):
        safe_address = Account().create().address
        SafeContractFactory(address=safe_address)

        response = self.client.get(reverse('v1:safe-all-txs', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        db_ethereum_tx = EthereumTxFactory(to=safe_address)
        response = self.client.get(reverse('v1:safe-all-txs', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()['results']), 1)
        ethereum_tx = response.json()['results'][0]
        self.assertEqual(ethereum_tx['from'], db_ethereum_tx._from)
        self.assertEqual(ethereum_tx['to'], safe_address)
        self.assertEqual(ethereum_tx['data'], db_ethereum_tx.data.hex())
        self.assertEqual(ethereum_tx['gas'], str(db_ethereum_tx.gas))
        self.assertEqual(ethereum_tx['gasPrice'], str(db_ethereum_tx.gas_price))
        self.assertEqual(ethereum_tx['txHash'], db_ethereum_tx.tx_hash.hex())
        self.assertEqual(ethereum_tx['value'], str(db_ethereum_tx.value))

        EthereumTxFactory(_from=safe_address)
        EthereumTxFactory()
        response = self.client.get(reverse('v1:safe-all-txs', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()['results']), 2)

        db_internal_tx = InternalTxFactory(to=safe_address)
        InternalTxFactory(_from=safe_address)
        InternalTxFactory()
        InternalTxFactory(contract_address=safe_address)
        response = self.client.get(reverse('v1:safe-all-txs', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()['results']), 5)

        at_least_one = False
        for ethereum_tx in response.json()['results']:
            if db_internal_tx.ethereum_tx.tx_hash.hex() == ethereum_tx['txHash']:
                self.assertEqual(len(ethereum_tx['internalTxs']), 1)
                self.assertEqual(ethereum_tx['internalTxs'][0]['from'], db_internal_tx._from)
                self.assertEqual(ethereum_tx['internalTxs'][0]['to'], safe_address)
                at_least_one = True
        self.assertTrue(at_least_one)

    def test_erc20_view(self):
        safe_address = Account().create().address
        SafeContractFactory(address=safe_address)

        response = self.client.get(reverse('v1:erc20-txs', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        ethereum_erc20_event = EthereumEventFactory(to=safe_address)
        response = self.client.get(reverse('v1:erc20-txs', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_ethereum_erc20_event = response.json()['results'][0]
        self.assertEqual(ethereum_erc20_event.token_address, response_ethereum_erc20_event['tokenAddress'])
        self.assertEqual(ethereum_erc20_event.arguments['to'], response_ethereum_erc20_event['to'])
        self.assertEqual(ethereum_erc20_event.arguments['from'], response_ethereum_erc20_event['from'])
        self.assertEqual(ethereum_erc20_event.arguments['value'], int(response_ethereum_erc20_event['value']))
        self.assertEqual(ethereum_erc20_event.ethereum_tx.to, response_ethereum_erc20_event['ethereumTx']['to'])

        EthereumEventFactory(from_=safe_address)
        EthereumEventFactory()
        response = self.client.get(reverse('v1:erc20-txs', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['count'], 2)

    def test_erc721_view(self):
        safe_address = Account().create().address
        SafeContractFactory(address=safe_address)

        response = self.client.get(reverse('v1:erc721-txs', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        ethereum_erc721_event = EthereumEventFactory(to=safe_address, erc721=True)
        response = self.client.get(reverse('v1:erc721-txs', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_ethereum_erc721_event = response.json()['results'][0]
        self.assertEqual(ethereum_erc721_event.token_address, response_ethereum_erc721_event['tokenAddress'])
        self.assertEqual(ethereum_erc721_event.arguments['to'], response_ethereum_erc721_event['to'])
        self.assertEqual(ethereum_erc721_event.arguments['from'], response_ethereum_erc721_event['from'])
        self.assertEqual(ethereum_erc721_event.arguments['tokenId'], int(response_ethereum_erc721_event['tokenId']))
        self.assertEqual(ethereum_erc721_event.ethereum_tx.to, response_ethereum_erc721_event['ethereumTx']['to'])

        EthereumEventFactory(from_=safe_address, erc721=True)
        EthereumEventFactory(erc721=True)
        response = self.client.get(reverse('v1:erc721-txs', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['count'], 2)

    def test_internal_tx_view(self):
        safe_address = Account().create().address
        SafeContractFactory(address=safe_address)

        response = self.client.get(reverse('v1:internal-txs', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        internal_tx = InternalTxFactory(to=safe_address)
        response = self.client.get(reverse('v1:internal-txs', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_internal_tx = response.json()['results'][0]
        self.assertEqual(internal_tx._from, response_internal_tx['from'])
        self.assertEqual(internal_tx.to, response_internal_tx['to'])
        self.assertEqual(internal_tx.data.hex(), response_internal_tx['data'])
        self.assertEqual(internal_tx.value, int(response_internal_tx['value']))
        self.assertEqual(internal_tx.ethereum_tx.to, response_internal_tx['ethereumTx']['to'])

        InternalTxFactory(_from=safe_address)
        InternalTxFactory()
        response = self.client.get(reverse('v1:internal-txs', args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['count'], 2)

    def test_private_safes_view(self):
        url = reverse('v1:private-safes')
        username, password = 'admin', 'mypass'
        user = User.objects.create_superuser(username, 'admin@admin.com', password)
        self.client.force_authenticate(user=user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['count'], 0)

        safe_contract = SafeContractFactory()
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['count'], 0)

        # Safe must be deployed
        SafeCreation2Factory(safe=safe_contract, block_number=2)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['count'], 1)
        results = response.json()['results']
        safe_response = results[0]
        self.assertEqual(safe_response['address'], safe_contract.address)
        self.assertEqual(dateparse.parse_datetime(safe_response['created']), safe_contract.created)

        # Add balance
        ether_balance = 7
        self.send_ether(safe_contract.address, ether_balance)
        # Balance of safe_contract must be 15 - 8 = 7 now
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['count'], 1)
        results = response.json()['results']
        safe_response = results[0]
        self.assertEqual(safe_response['address'], safe_contract.address)
        self.assertIsNone(safe_response['tokensWithBalance'][0]['tokenAddress'])
        self.assertEqual(safe_response['tokensWithBalance'][0]['balance'], ether_balance)

        # Add token transfers
        token_balance = 8
        example_erc20_1 = self.deploy_example_erc20(token_balance, safe_contract.address)
        example_erc20_2 = self.deploy_example_erc20(token_balance, safe_contract.address)
        EthereumEventFactory(to=safe_contract.address, value=19, token_address=example_erc20_1.address)
        EthereumEventFactory(to=safe_contract.address, value=4, token_address=example_erc20_2.address)
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['count'], 1)
        results = response.json()['results']
        safe_response = results[0]
        self.assertEqual(safe_response['address'], safe_contract.address)
        self.assertCountEqual(safe_response['tokensWithBalance'], [
            {'tokenAddress': None, 'balance': ether_balance},
            {'tokenAddress': example_erc20_1.address, 'balance': token_balance},
            {'tokenAddress': example_erc20_2.address, 'balance': token_balance},
        ])
        self.client.force_authenticate(user=None)

    def test_api_token_auth(self):
        username, password = 'admin', 'mypass'

        # No user created
        response = self.client.post(reverse('v1:api-token-auth'), format='json', data={'username': username,
                                                                                       'password': password})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Create user
        User.objects.create_superuser(username, 'admin@admin.com', password)
        response = self.client.post(reverse('v1:api-token-auth'), format='json', data={'username': username,
                                                                                       'password': password})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        token = response.json()['token']

        # Test protected endpoint
        response = self.client.get(reverse('v1:private-safes'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        response = self.client.get(reverse('v1:private-safes'), HTTP_AUTHORIZATION='Token ' + token)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
