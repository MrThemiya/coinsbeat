import logging
import aiohttp
import psycopg2
import time
import os

logger = logging.getLogger(__name__)

SYMBOLS = {
    'btc': 'bitcoin',
    'eth': 'ethereum',
    'xrp': 'ripple',
    'bnb': 'binancecoin',
    'sol': 'solana',
    'trx': 'tron',
    'doge': 'dogecoin',
    'ada': 'cardano',
    'hype': 'hyperliquid',
    'sui': 'sui',
    'bch': 'bitcoin-cash',
    'link': 'chainlink',
    'leo': 'leo-token',
    'avax': 'avalanche-2',
    'ton': 'the-open-network',
    'xlm': 'stellar',
    'shib': 'shiba-inu',
    'ltc': 'litecoin',
    'wbt': 'whitebit',
    'hbar': 'hedera-hashgraph',
    'xmr': 'monero',
    'bgb': 'bitget-token',
    'dot': 'polkadot',
    'uni': 'uniswap',
    'aave': 'aave',
    'pepe': 'pepe',
    'pi': 'pi-network',
    'okb': 'okb',
    'tao': 'bittensor',
    'apt': 'aptos',
    'near': 'near',
    'icp': 'internet-computer',
    'cro': 'crypto-com-chain',
    'etc': 'ethereum-classic',
    'ondo': 'ondo-finance',
    'kas': 'kaspa',
    'ftn': 'fasttoken',
    'mnt': 'mantle',
    'gt': 'gatechain-token',
    'atom': 'cosmos',
    'vet': 'vechain',
    'fet': 'fetch-ai',
    'trump': 'official-trump',
    'bonk': 'bonk',
    'render': 'render-token',
    'sky': 'sky',
    'pol': 'polygon-ecosystem-token',
    'ena': 'ethena',
    'arb': 'arbitrum',
    'tkx': 'tokenize-xchange',
    'qnt': 'quant-network',
    'fil': 'filecoin',
    'algo': 'algorand',
    'wld': 'worldcoin-wld',
    'sei': 'sei-network',
    'kcs': 'kucoin-shares',
    'jup': 'jupiter-exchange-solana',
    'nexo': 'nexo',
    'fartcoin': 'fartcoin',
    'flr': 'flare-networks',
    'spx': 'spx6900',
    'xdc': 'xdce-crowd-sale',
    'tia': 'celestia',
    'inj': 'injective-protocol',
    'pengu': 'pudgy-penguins',
    'virtual': 'virtual-protocol',
    'stx': 'blockstack',
    's': 'sonic-3',
    'op': 'optimism',
    'paxg': 'pax-gold',
    'kaia': 'kaia',
    'pyusd': 'paypal-usd',
    'wif': 'dogwifcoin',
    'ip': 'story-2',
    'grt': 'the-graph',
    'imx': 'immutable-x',
    'cake': 'pancakeswap-token',
    'floki': 'floki',
    'ousg': 'ousg',
    'theta': 'theta-token',
    'jto': 'jito-governance-token',
    'ldo': 'lido-dao',
    'gala': 'gala',
    'zec': 'zcash',
    'ens': 'ethereum-name-service',
    'aero': 'aerodrome-finance',
    'iota': 'iota',
    'btt': 'bittorrent',
    'sand': 'the-sandbox',
    'jasmy': 'jasmycoin',
    'syrup': 'syrup',
    'ray': 'raydium',
    'tbtc': 'tbtc',
    'wal': 'walrus-2',
    'pyth': 'pyth-network',
    'xtz': 'tezos',
    'pendle': 'pendle',
    'dog' : 'dog-go-to-the-moon-rune',
    'ar' : 'arweave'

   

    


}

DEX_URLS = {
    'btc': 'https://api.dexscreener.com/latest/dex/pairs/tron/TTQpJqQuJMjJf3maVWwvURN3YrRXg2QUTm',
    'eth': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0xbe141893e4c6ad9272e8c04bab7e6a10604501a5',
    'bnb': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0x47a90a2d92a8367a91efa1906bfc8c1e05bf10c4',
    'pepe': 'https://api.dexscreener.com/latest/dex/pairs/solana/FCEnsxYJFrsKsz6TasUeNcsfGwKgKh6yURN1AmMyHhZN',
    'celo': 'https://api.dexscreener.com/latest/dex/pairs/celo/0x2d70cbabf4d8e61d5317b62cbe912935fd94e0fe',
    'dog': 'https://api.dexscreener.com/latest/dex/pairs/solana/47WiAW991PWxFwJF2P8upmpDn6FHDvn6iiM1D8DSCm1q',
    'sol': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0x9f5a0ad81fe7fd5dfb84ee7a0cfb83967359bd90',
    'xrp': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0x71f5a8f7d448e59b1ede00a19fe59e05d125e742',
    'trx': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0x1f7df58c60a56bc8322d3e42d7d37a0383d42746',
    'ada': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0x29c5ba7dbb67a4af999a28cc380ad234fe7c1b86',
    'hype': 'https://api.dexscreener.com/latest/dex/pairs/multiversx/erd1qqqqqqqqqqqqqpgq44ctuneycrq77yf08xswqcgzznyvt5ka2jps2ulap4',
    'link': 'https://api.dexscreener.com/latest/dex/pairs/polygon/0x79e4240e33c121402dfc9009de266356c91f241d',
    'sui': 'https://api.dexscreener.com/latest/dex/pairs/sui/0x86ed41e9b4c6cce36de4970cfd4ae3e98d6281f13a1b16aa31fc73ec90079c3d',
    'bch': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0x1fd22fa7274bafebdfb1881321709f1219744829',
    'avax': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0x9f11264d6d0d9671dab2cc485eb6ec1b502c4025',
    'ton': 'https://api.dexscreener.com/latest/dex/pairs/solana/7rqvzaqnkzolfmwcbsvwb4bqnmjupgnzr8ebwsk4b8q1',
    'xlm': 'https://api.dexscreener.com/latest/dex/pairs/solana/gsw1og5wnaqysq9bzbgvb86xm84oav4wkcw2fztr3xae',
    'shib': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0x14c594222106283dd6d155b9d00a943b94153066',
    'ltc': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0x6b9e3825e39203277f8fd33371e36b5188b26410',
    'hbar': 'https://api.dexscreener.com/latest/dex/pairs/solana/9diphq6pqndxtwmqaxzmx1isv7kfrr86ty6cbkd9nkpv',
    'xmr': 'https://api.dexscreener.com/latest/dex/pairs/pulsechain/0x1807c1d7e54e43f5ede58a7a189e2018232d3ace',
    'dot': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0xdf981badb118d2f2dea12a1a584cccfbf595987a',
    'uni': 'https://api.dexscreener.com/latest/dex/pairs/polygon/0x7acf7fc43677739ea451aa561c44c80c59087391',
    'aave': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0x8e3ecc0b261f1a4db62321090575eb299844f077',
    'okb': 'https://api.dexscreener.com/latest/dex/pairs/ethereum/0x6368172f9df8ff70ac7e2fc6b30cb964158d0090',
    'apt': 'https://api.dexscreener.com/latest/dex/pairs/aptos/liquidswap-335',
    'near': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0x0937457332f801e459dc186872c69689737b71cb',
    'icp': 'https://api.dexscreener.com/latest/dex/pairs/solana/75gvrxvvj3u1km7mvhpp5vgwxdt42jdyyxjtfk9bxzxu',
    'cro': 'https://api.dexscreener.com/latest/dex/pairs/pulsechain/0x4087d0e6e513f260de87408bee9334a5742cfdf4',
    'etc': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0x2c0d74d5389a7076dc76f7084ad333112ba11ae0',
    'ondo': 'https://api.dexscreener.com/latest/dex/pairs/ethereum/0x39f9ff86479579952e7218c27ab9d2a9ff9bfe3e',
    'kas': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0x92fb8463ac6bc0f700b20cd67cdee7c753947f66',
    'mnt': 'https://api.dexscreener.com/latest/dex/pairs/mantle/0xd08c50f7e69e9aeb2867deff4a8053d9a855e26a',
    'atom': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0x096671ac04fb54da0cf8ce6dc12a8c26655771a8',
    'vet': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0x1af417fa1065d5b5198d7bc7b270208dadc05680',
    'fet': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0x93094ed1c907e4bca7eb041cb659da94f7e1b58e',
    'render': 'https://api.dexscreener.com/latest/dex/pairs/solana/6fq5kyyxxk7qmn4sn5kyxdsbgkukdvettqifwbngbkth',
    'ena': 'https://api.dexscreener.com/latest/dex/pairs/ethereum/0x4185d2952eb74a28ef550a410ba9b8e210ee9391',
    'fil': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0x52a499333a7837a72a9750849285e0bb8552de5a',
    'algo': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0xd5940da2a2eadf03feab23d057168565b682152a',
    'wld': 'https://api.dexscreener.com/latest/dex/pairs/optimism/0xd59c46786f2db194ca9067945c8e66dfe76a9118',
    'pengu': 'https://api.dexscreener.com/latest/dex/pairs/solana/8cwbzycair5dmec4nspnngmwotphjb8z4mvykq3wfgwo',
    'floki': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0xc7c78f4eb03db672d379e96e9fcf89a6ff0eb8f2',
    'jto': 'https://api.dexscreener.com/latest/dex/pairs/solana/hmgdqs9ce7pk6njatkcnx6uu2xdu7ivscswtytrfuxg5',
    'gala': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0xb91c780792eb5168263a21b583fdcde50446ff1c',
    'btt': 'https://api.dexscreener.com/latest/dex/pairs/tron/tlkyq7ej4ykbs3tgevobjwkaxwyqkwo2nn',
    'ens': 'https://api.dexscreener.com/latest/dex/pairs/ethereum/0x09aa63b7a22eefc372196aacd5b53441ed390bfb',
    'ray': 'https://api.dexscreener.com/latest/dex/pairs/solana/dva7qmb5ct9rcpau7utpsaf3gvmyz17vnvu67xpdcrut',
    'flow': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0xc08bc2278b487312be6eec5c03dddf6f30d90195',
    'mana': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0x284f871d6f2d4fe070f1e18c355ef2825e676aa2',
    'ape': 'https://api.dexscreener.com/latest/dex/pairs/ethereum/0xb27c7b131cf4915bec6c4bc1ce2f33f9ee434b9f',
    'venom': 'https://api.dexscreener.com/latest/dex/pairs/venom/0:56a3f53b5d07da8266c38eb7b4fe1b0e3f3dac6b88ef23a1634d4b9bd4eb2bbe',
    'strk': 'https://api.dexscreener.com/latest/dex/pairs/starknet/0x019861bfd8e79d75ec46d9413f00bcd6cbee54bda2da60c80934c911c6cb5a0b',
    'move': 'https://api.dexscreener.com/latest/dex/pairs/aptos/pcs-1102',
    'comp': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0xfea51617bd466d5ff4e76ecd2adefc91fb893144',
    'egld': 'https://api.dexscreener.com/latest/dex/pairs/multiversx/erd1qqqqqqqqqqqqqpgq5crkgmnhyj64gp2u0kzlxxh2nvz9dpav2jpswrfu6h',
    'aioz': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0x3ad197a4e7b3e81e31e16e9acbf2d975d26f93e0',
    'xec': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0x9427ed673bcfd398463eba9d04d84f392906354d',
    'eos': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0xfd0c89e96648082469b0b9a1c7390c54fd16f25a',
    'zk': 'https://api.dexscreener.com/latest/dex/pairs/zksync/0xc1fcd2a14df1a10f91cdd0d9b6191ca264356eec',
    'sun': 'https://api.dexscreener.com/latest/dex/pairs/tron/ttdecobmyxhffbyuzbiqqbz56zrfkse5dg',
    'twt': 'https://api.dexscreener.com/latest/dex/pairs/bsc/0x54364201320d03b1980e5da763a852b035233c9c',
    'matic': 'https://api.dexscreener.com/latest/dex/pairs/polygonzkevm/0x5eaae02cce922deb3f356974b01d2031dea06bd2',
    "zro": "https://api.dexscreener.com/latest/dex/pairs/optimism/0xd9dd34576c7034beb0b11a99afffc49e91011235",
    "zil": "https://api.dexscreener.com/latest/dex/pairs/bsc/0xde272b909b43bf1e90d0dfbb298a02472f677142",
    "1inch": "https://api.dexscreener.com/latest/dex/pairs/bsc/0xf624649736a106f2aa16e8027ce9aeed1bcd22f9",
    "sfp": "https://api.dexscreener.com/latest/dex/pairs/bsc/0xa809687d97ea8632b70fbcb8aa3075aa011de97a",
    "elf": "https://api.dexscreener.com/latest/dex/pairs/bsc/0x19eeb20cfbf0c41eba965a86f1be21acdbfad3b6"
}


CACHE_EXPIRY = 15  # seconds

# Database setup
conn = psycopg2.connect(os.environ["DATABASE_URL"])
c = conn.cursor()
c.execute("""
    CREATE TABLE IF NOT EXISTS price_cache (
        symbol TEXT PRIMARY KEY,
        price REAL,
        timestamp INTEGER
    )
""")
conn.commit()

def get_cached_price(symbol):
    c.execute("SELECT price, timestamp FROM price_cache WHERE symbol=%s", (symbol,))
    row = c.fetchone()
    if row:
        price, ts = row
        if time.time() - ts < CACHE_EXPIRY:
            return price
    return None

def set_cached_price(symbol, price):
    ts = int(time.time())
    c.execute("INSERT INTO price_cache (symbol, price, timestamp) VALUES (%s, %s, %s) ON CONFLICT (symbol) DO UPDATE SET price = EXCLUDED.price, timestamp = EXCLUDED.timestamp", (symbol, price, ts))
    conn.commit()

async def fetch_prices():
    prices = {}
    failed_symbols = []

    async with aiohttp.ClientSession() as session:
        # First try to get from cache
        for symbol in SYMBOLS:
            cached = get_cached_price(symbol)
            if cached is not None:
                prices[symbol] = cached
            else:
                failed_symbols.append(symbol)

        if failed_symbols:
            # Combine CoinGecko API call into one request
            token_ids = ','.join([SYMBOLS[s] for s in failed_symbols])
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={token_ids}&vs_currencies=usd"
            try:
                async with session.get(url) as response:
                    if response.status == 429:
                        logger.warning("❌ CoinGecko rate limited (HTTP 429)")
                    elif response.status != 200:
                        logger.warning(f"❌ CoinGecko failed: HTTP {response.status}")
                    else:
                        data = await response.json()
                        for symbol in failed_symbols[:]:
                            token_id = SYMBOLS[symbol]
                            price = data.get(token_id, {}).get("usd")
                            if price is not None:
                                prices[symbol] = price
                                set_cached_price(symbol, price)
                                failed_symbols.remove(symbol)
                            else:
                                logger.warning(f"❌ Missing price for {symbol} from CoinGecko")
            except Exception as e:
                logger.warning(f"❌ CoinGecko error: {e}")

        # Fallback to DexScreener
        if failed_symbols:
            logger.warning("⚠️ Falling back to DexScreener for missing symbols...")
            for symbol in failed_symbols:
                url = DEX_URLS.get(symbol)
                if not url:
                    continue
                try:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            pair = data.get("pair")
                            if pair and pair.get("priceUsd"):
                                price = float(pair["priceUsd"])
                                prices[symbol] = price
                                set_cached_price(symbol, price)
                            else:
                                logger.error(f"DexScreener failed for {symbol}: No price data")
                        else:
                            logger.error(f"DexScreener HTTP error for {symbol}: {resp.status}")
                except Exception as e:
                    logger.error(f"DexScreener exception for {symbol}: {e}")

    logger.info("✅ Prices fetched successfully")
    return prices

