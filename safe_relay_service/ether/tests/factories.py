import os

from ethereum import utils


def get_eth_address_with_key() -> (str, bytes):

    # import secp256k1
    # private_key = secp256k1.PrivateKey().private_key

    private_key = utils.sha3(os.urandom(4096))

    public_key = utils.checksum_encode(utils.privtoaddr(private_key))

    # If you want to use secp256k1 to calculate public_key
    # utils.checksum_encode(utils.sha3(p.pubkey.serialize(compressed=False)[1:])[-20:])

    return (public_key,
            private_key)
