from brownie import chain, Contract, web3, ZERO_ADDRESS
from scripts.generate_proof import generate_proof
import json
from pathlib import Path

START_BLOCK = 18040000
END_BLOCK = 18480405

# deployer address is excluded from the airdrop
DEPLOYER = "0xd8531a94100f15af7521a7B6E724aC4959E0A025"

DEPOSIT_TOKENS = [
    "0x71aD6c1d92546065B13bf701a7524c69B409E25C",
    "0x5F8D4319C27a940B5783b4495cCa6626E880532E",
    "0x6D3cD0dD2c05FA4Eb8d1159159BEF445593a93fc",
    "0x0Ae09f649e9dA1b6aEA0c10527aC4e8a88a37480",
    "0xf6aA46869220Ae703924d5331D88A21DceF3b19d",
    "0x3D56E0Ea536A78976503618d663921c97A3cBA3C",
]


def main():
    fetch_raw_data()
    user_trove_points, user_sp_points, user_lp_points = calculate_points()

    total_trove_points = sum(user_trove_points.values())
    sp_divisor = sum(user_sp_points.values()) / (total_trove_points / 8)
    lp_divisor = sum(user_lp_points.values()) / (total_trove_points / 8)

    user_sp_points = {k: v / sp_divisor for k, v in user_sp_points.items()}
    user_lp_points = {k: v / lp_divisor for k, v in user_lp_points.items()}

    final = {
        k: int((user_trove_points[k] + user_sp_points[k] + user_lp_points[k]) * 10**18)
        for k in user_trove_points
    }

    proof = generate_proof(final, "0x2C533357664d8750e5F851f39B2534147F5578af", 6_000_000)
    json.dump(
        proof,
        open("proofs/proof-0x2c533357664d8750e5f851f39b2534147f5578af.json", "w"),
        sort_keys=True,
        indent=2,
    )


def _get_txhash_from_events(contract, fn_name, height):
    contract = web3.eth.contract(contract.address, abi=contract.abi)
    event = getattr(contract.events, fn_name)()
    return [
        (i.blockNumber, i.transactionIndex, i.transactionHash.hex())
        for i in event.getLogs(fromBlock=height, toBlock=min(height + 10000, END_BLOCK))
    ]


def get_trove_balances(trove_data=None):
    bo = Contract("0x72c590349535ad52e6953744cb2a36b409542719")
    factory = Contract("0x70b66E20766b775B2E9cE5B718bbD285Af59b7E1")
    trove_managers = [Contract(factory.troveManagers(i)) for i in range(4)]

    if trove_data:
        start_block = max(int(x) for v in trove_data.values() for x in v) + 1
    else:
        start_block = START_BLOCK
        trove_data = {i.address: {} for i in trove_managers}

    tx_list = []
    for height in range(start_block, END_BLOCK + 1, 10000):
        print(f"{height}/{END_BLOCK}")
        tx_list.extend(_get_txhash_from_events(bo, "TroveUpdated", height))
        for tm in trove_managers:
            tx_list.extend(_get_txhash_from_events(tm, "CollateralSent", height))

    tx_list = sorted(set(tx_list), key=lambda k: (k[0], k[1]))
    for c, (block, _, txid) in enumerate(tx_list):
        print(f"{c}/{len(tx_list)}")
        tx = chain.get_transaction(txid)
        trove_addr = set(i.address for i in tx.events if i.address in trove_managers)
        assert len(trove_addr) == 1
        tm = trove_addr.pop()
        trove_data[tm].setdefault(str(block), {})
        for item in tx.events["TroveUpdated"]:
            trove_data[tm][str(block)][item["_borrower"]] = item["_debt"]

    return trove_data


def get_sp_balances(sp_balances=None):
    sp = Contract("0xed8B26D99834540C5013701bB3715faFD39993Ba")
    contract = web3.eth.contract(sp.address, abi=sp.abi)
    if not sp_balances:
        sp_balances = {}

    start_block = max(sp_balances, default=START_BLOCK) + 1
    for height in range(start_block, END_BLOCK + 1, 10000):
        print(f"{height}/{END_BLOCK}")
        logs = contract.events.UserDepositChanged().getLogs(
            fromBlock=height, toBlock=min(height + 10000, END_BLOCK)
        )
        for item in logs:
            block = item.blockNumber
            sp_balances.setdefault(block, {})
            sp_balances[block][item.args._depositor] = item.args._newDeposit

    return sp_balances


def get_lp_balances(token, token_balances=None):
    if not isinstance(token, Contract):
        token = Contract(token)
    current = {}
    if not token_balances:
        token_balances = {}

    for key in sorted(token_balances, reverse=True):
        for addr, amount in token_balances[key].items():
            if addr not in current:
                current[addr] = amount

    contract = web3.eth.contract(token.address, abi=token.abi)
    start_block = max(token_balances, default=START_BLOCK) + 1
    for height in range(start_block, END_BLOCK + 1, 10000):
        print(f"{height}/{END_BLOCK}")
        logs = contract.events.Transfer().getLogs(
            fromBlock=height, toBlock=min(height + 10000, END_BLOCK)
        )
        for item in logs:
            block = item.blockNumber
            token_balances.setdefault(block, {})
            sender = item.args["from"]
            recv = item.args.to
            amount = item.args.value
            if sender not in [ZERO_ADDRESS, DEPLOYER]:
                current[sender] -= amount
                token_balances[block][sender] = current[sender]

            if recv not in [ZERO_ADDRESS, DEPLOYER]:
                current.setdefault(recv, 0)
                current[recv] += amount
                token_balances[block][recv] = current[recv]

    return token_balances


def fetch_raw_data():
    fp = Path("data/trove-debt.json")
    if not fp.exists():
        print("Troves")
        trove_data = get_trove_balances()
        json.dump(trove_data, fp.open("w"), sort_keys=True, indent=2)

    fp = Path("data/sp-deposits.json")
    if not fp.exists():
        print("\nStability Pool")
        sp_data = get_sp_balances()
        json.dump(sp_data, fp.open("w"), sort_keys=True, indent=2)

    for token in DEPOSIT_TOKENS:
        fp = Path(f"data/lp-balances-{token}.json")
        if not fp.exists():
            print(f"\nDeposit token: {token}")
            data = get_lp_balances(token)
            json.dump(data, fp.open("w"), sort_keys=True, indent=2)


def calculate_points():
    trove_data = json.load(open("data/trove-debt.json"))
    user_list = set(z for v in trove_data.values() for x in v.values() for z in x)
    user_list.discard(DEPLOYER)

    # calculate points based on debt
    user_trove_points = {i: 0 for i in user_list}
    user_balances = {}
    total = 0

    for block in range(START_BLOCK, END_BLOCK + 1):
        if not int(block) % 10000:
            print(f"{block} / {END_BLOCK}")

        for data in trove_data.values():
            if str(block) in data:
                for user, debt in data[str(block)].items():
                    if user == DEPLOYER:
                        continue
                    if user in user_balances:
                        total += debt - user_balances[user]
                        user_balances[user] = debt
                    else:
                        user_balances[user] = debt
                        total += debt

        for user, balance in user_balances.items():
            user_trove_points[user] += balance / total

    # get blocks where each account has at least one trove open
    user_active = {k: [] for k in user_list}
    for user in user_list:
        active_blocks = []
        for data in trove_data.values():
            active_from = 0
            for block, activity in data.items():
                if user in activity:
                    debt = activity[user]
                    if debt > 0 and active_from == 0:
                        active_from = int(block)
                    elif debt == 0 and active_from > 0:
                        active_blocks.append([active_from, int(block)])
                        active_from = 0
            if active_from > 0:
                active_blocks.append([active_from, END_BLOCK])

        active_blocks = sorted(active_blocks, key=lambda k: k[0], reverse=True)

        if len(active_blocks) == 1:
            user_active[user] = active_blocks
        else:
            current = active_blocks.pop()
            for value in active_blocks[::-1]:
                if value[0] <= current[1]:
                    current[1] = max(current[1], value[1])
                else:
                    user_active[user].append(current)
                    current = value
            user_active[user].append(current)

    # calculate SP points
    print("Calculating stability pool points...")
    user_sp_points = _get_secondary_points("data/sp-deposits.json", user_list, user_active)

    user_lp_points = {i: 0 for i in user_list}
    for token in DEPOSIT_TOKENS:
        print(f"LP Deposits: {token}")
        user_points = _get_secondary_points(
            f"data/lp-balances-{token}.json", user_list, user_active
        )
        for user, points in user_points.items():
            user_lp_points[user] += points

    return user_trove_points, user_sp_points, user_lp_points


def _get_secondary_points(snapshot_filename, user_list, user_active):
    snapshot_data = json.load(open(snapshot_filename))
    start_block = min(int(i) for i in snapshot_data.keys())
    user_balances = {}
    user_points = {i: 0 for i in user_list}
    total = 0
    for block in range(start_block, END_BLOCK + 1):
        if not int(block) % 10000:
            print(f"{block} / {END_BLOCK}")
        if str(block) in snapshot_data:
            for user, balance in snapshot_data[str(block)].items():
                if user not in user_list:
                    continue
                if user in user_balances:
                    total += balance - user_balances[user]
                    user_balances[user] = balance
                else:
                    user_balances[user] = balance
                    total += balance

        for user, balance in user_balances.items():
            if balance and _is_active(user_active[user], int(block)):
                user_points[user] += balance / total

    return user_points


def _is_active(user_active, block):
    for start, end in user_active:
        if start <= block <= end:
            return True
    return False
