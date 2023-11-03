from brownie import web3
from itertools import zip_longest
from collections import deque
from fractions import Fraction
from eth_abi.packed import encode_abi_packed
from eth_utils import encode_hex


class MerkleTree:
    def __init__(self, elements):
        self.elements = sorted(set(web3.keccak(hexstr=el) for el in elements))
        self.layers = MerkleTree.get_layers(self.elements)

    @property
    def root(self):
        return self.layers[-1][0]

    def get_proof(self, el):
        el = web3.keccak(hexstr=el)
        idx = self.elements.index(el)
        proof = []
        for layer in self.layers:
            pair_idx = idx + 1 if idx % 2 == 0 else idx - 1
            if pair_idx < len(layer):
                proof.append(encode_hex(layer[pair_idx]))
            idx //= 2
        return proof

    @staticmethod
    def get_layers(elements):
        layers = [elements]
        while len(layers[-1]) > 1:
            layers.append(MerkleTree.get_next_layer(layers[-1]))
        return layers

    @staticmethod
    def get_next_layer(elements):
        return [
            MerkleTree.combined_hash(a, b) for a, b in zip_longest(elements[::2], elements[1::2])
        ]

    @staticmethod
    def combined_hash(a, b):
        if a is None:
            return b
        if b is None:
            return a
        return web3.keccak(b"".join(sorted([a, b])))


def generate_proof(balances, total_distribution):
    assert (
        total_distribution < 1e18
    ), "Total distribution must be / 1e18 to account for LOCK_TO_TOKEN_RATIO"
    total_vecrv = sum(balances.values())
    balances = {
        k.lower(): int(Fraction(v * total_distribution, total_vecrv)) for k, v in balances.items()
    }

    # handle any rounding errors
    addresses = sorted(balances, key=lambda k: balances[k], reverse=True)
    while sum(balances.values()) < total_distribution:
        balances[addresses.pop()] += 1

    assert sum(balances.values()) == total_distribution

    elements = [
        (index, account, balances[account]) for index, account in enumerate(sorted(balances))
    ]
    nodes = [encode_hex(encode_abi_packed(["uint", "address", "uint"], el)) for el in elements]
    tree = MerkleTree(nodes)
    distribution = {
        "merkleRoot": encode_hex(tree.root),
        "tokenTotal": hex(sum(balances.values())),
        "claims": {
            user: {"index": index, "amount": hex(amount), "proof": tree.get_proof(nodes[index])}
            for index, user, amount in elements
        },
    }
    print(f"merkle root: {encode_hex(tree.root)}")
    return distribution
