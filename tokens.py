# tokens.py

# SOL mint address
SYSTEM_SOL = "So11111111111111111111111111111111111111112"

# Mint → Symbol
TOKEN_MINTS = {
    SYSTEM_SOL: "SOL",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "9n4nbM75f5Ui33ZbPYXn59EwSgE8CGsHtAeTH5YFeJ9E": "BTC",
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "BONK",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    "2sXXcMa8UY7G28kH2r7SytRD8W7AqH4G9oZax1qsnURe": "SRM",
    "4k3Dyjzvzp8eYbWwTfSPd7d7VndV1TJv8W1g2mVQHdqF": "RAY",
    "2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv" : "PENGU",
    "H3QSHQNPUR6ES36ZQYAy5UocxfH8A2GE2NvA9SEk46wq": "TRUMPUP",
    "LinkhB3afbBKb2EQQu7s7umdZceV3wcvAUJhQAfQ23L"  : "Link",
    "rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof" : "RENDER",
    "J3NKxxXZcnNiMjKw9hYb2K4LUxgwB6t1FtPtQVsv3KFr" : "SPX",
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN":  "JUP",
    "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm" : "WIF",
    "4qQeZ5LwSz6HuupUu8jCtgXyW1mYQcNbFAW1sWZp89HL" : "CAKE",
    "3iQL8BFS2vE7mww4ehAqQHAsbmRNCrPxizWAT2Zfyr9y" : "VIRTUAL",
    "2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo": "PYUSD",
    "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3" : "PYTH",
    "i7u4r16TcsJTgq1kAG8opmVZyVnAKBwLKu6ZPMwzxNc" : "OUSG",
    "hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux" : "HNT",
    "ZBCNpuD7YMXzTHB2fhGkGi78MNsHGLRXUhRewNRm9RU" : "ZBCN",
    "vQoYWru2pbUdcVkUrRH74ktQDJgVjRcDvsoDbUzM5n9" : "REKT",
    "85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ" : "W",
    "Dm5BxyMetG3Aq5PaG1BrG7rBYqEMtnkjvPNMExfacVk7" : "ATH",
    "6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN" : "TRUMP",
    "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr": "POPCAT",
    "EPeUFDgHRxs9xxEPVaL6kfGQvCon7jmAWKVUHuux1Tpz":  "BAT",
    "u9nmK5sQovm6ACVCQbbq8xUMpFqdPSYxdxVwXUX4sjY" : "ORDI",
    "HeLp6NuQkmYB4pYWo2zYs22mESHXPQYzXbB8n4V98jwC" : "AI16Z",
    "ukHH6c7mMyiWCf1b9pnWe25TSpkDDt3H5pQZgZ74J82"  :"BOME",
    "BZLbGTNCSFfoth2GYDtwr7e4imWzpR5jqcUuGEwr646K" :"IO",

}

# Reverse: Symbol → Mint
SYMBOL_TO_MINT = {v: k for k, v in TOKEN_MINTS.items()}

