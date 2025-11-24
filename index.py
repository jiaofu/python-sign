import requests
import pandas as pd # 仍用于 AHR999 的 MA200 计算
import math
from datetime import datetime, date, timedelta
import re
import json
from bs4 import BeautifulSoup

# --- 配置 ---
BARK_KEY = "5vMdJU9YEoLmQLKne6kSoE"

# --- ETF 基础数据 (供信号判断使用) ---
ETF_CODES = ["513500", "159612", "159632", "513100"]
ETF_NAMES = {"513500":"博时标普500", "159612":"国泰标普500", "159632":"华安纳斯达克100", "513100":"国泰纳斯达克100"}

# ====================================================================
# 【工具函数】
# ====================================================================

def bark(title, body):
    """通过 Bark 推送通知"""
    try:
        requests.post(f"https://api.day.app/{BARK_KEY}/",
                      json={"title": title, "body": body, "group": "投资信号", "sound": "anticipate"},
                      timeout=10)
    except Exception as e:
        print(f"Bark error: {str(e)}")


def get_ahr999_from_binance():
    """使用币安 API 计算 AHR999 指数"""
    # ... (AHR999 逻辑代码同上，为简洁省略) ...
    SYMBOL = 'BTCUSDT'
    INTERVAL = '1d'
    LIMIT = 210
    API_URL = "https://api.binance.com/api/v3/klines"
    MA_WINDOW = 200
    BIRTH_DATE = date(2009, 1, 3)
    TODAY = date.today()
    try:
        params = {'symbol': SYMBOL, 'interval': INTERVAL, 'limit': LIMIT}
        response = requests.get(API_URL, params=params, timeout=10)
        response.raise_for_status()
        klines_data = response.json()
        if not klines_data: return None
        df = pd.DataFrame(klines_data)
        df['Close'] = df[4].astype(float)
        current_price = df['Close'].iloc[-1]
        ma200 = df['Close'].rolling(window=MA_WINDOW).mean().iloc[-1]
        age_days = (TODAY - BIRTH_DATE).days
        log_days = math.log10(age_days)
        log_price = 5.84 * log_days - 17.01
        target_price = 10 ** log_price
        if ma200 > 0 and target_price > 0:
            ahr999_index = (current_price / ma200) * (current_price / target_price)
            return ahr999_index
        return None
    except Exception as e:
        print(f"AHR999 计算逻辑错误: {e}")
        return None


# ====================================================================
# 【A 股 ETF 溢价率函数 - 返回字符串列表和字典】
# ====================================================================

def get_etf_premium_rates_from_haoetf(codes, names):
    """
    使用 haoetf.com 网页抓取逻辑获取 ETF 溢价率。
    返回: (formatted_results_list, raw_etf_map)
        formatted_results_list: 用于推送消息体 (List[str])
        raw_etf_map: 用于信号判断 (Dict[str, str])
    """
    raw_etf_map = {} # 存储 code -> 溢价率字符串 (+X.XX%)
    formatted_results = []

    for code in codes:
        try:
            url = f"https://www.haoetf.com/qdii/{code}"
            headers = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(url, headers=headers, timeout=12)
            soup = BeautifulSoup(resp.text, 'html.parser')

            premium_text = None
            tds = soup.find_all('td')

            for td in tds:
                if '%' in td.get_text():
                    premium_text = td.get_text(strip=True)
                    break

            match = re.search(r'([+-]?\d+\.?\d*)%', premium_text) if premium_text else None

            if match:
                premium_str = f"{float(match.group(1)):+.2f}%"
                raw_etf_map[code] = premium_str

                # 格式化输出
                premium_val = float(match.group(1))
                signal = f"❗溢价高" if premium_val > 0.5 else f"✅折价大" if premium_val < -0.5 else f"持平"
                formatted_results.append(f"{names.get(code, code)} ({code}): {premium_str} ({signal})")
            else:
                raw_etf_map[code] = "获取失败"
                formatted_results.append(f"{names.get(code, code)} ({code}): 溢价率未找到")

        except Exception as e:
            raw_etf_map[code] = "获取失败"
            formatted_results.append(f"{names.get(code, code)} ({code}): 抓取失败")
            continue

    return formatted_results, raw_etf_map


# ====================================================================
# 【主执行函数：整合所有信号和判断】
# ====================================================================

def handler(event, context):

    # --- 1. 数据获取 ---

    # BTC 价格/跌幅
    cur, high, drop = 0, 0, 0.0 # 初始化为数字类型
    fg_value, level = 0, "无法判断" # 恐慌指数 (fg_value 为 Int)
    ahr_value = None # AHR999 值 (float)

    try:
        klines = requests.get("https://api.binance.com/api/v3/klines", params={"symbol":"BTCUSDT","interval":"1M","limit":1000}, timeout=10).json()
        highs = [float(k[2]) for k in klines]
        high_price = max(max(highs), 126000)
        high = int(high_price)
        cur_price = float(requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol":"BTCUSDT"}, timeout=10).json()["price"])
        cur = int(cur_price)
        drop = round((cur - high) / high * 100, 2)
    except Exception as e:
        print(f"BTC 价格/跌幅计算错误: {str(e)}")

    try:
        d = requests.get("https://api.alternative.me/fng/?limit=1", timeout=8).json()
        fg_value = int(d["data"][0]["value"])
        level = d["data"][0]["value_classification"]
    except Exception as e:
        print(f"Fear & Greed error: {str(e)}")

    ahr_value = get_ahr999_from_binance()

    # ETF 溢价率
    etf_results, etf_raw_map = get_etf_premium_rates_from_haoetf(ETF_CODES, ETF_NAMES)
    etf_body = "\n    " + "\n    ".join(etf_results)

    # --- 2. 智能信号判断 (您的逻辑) ---

    signals = []

    # BTC 信号
    if isinstance(drop, float):
        if drop <= -20:
            signals.append("【BTC 买入信号】已从高点下跌超20%！")
        if drop <= -50:
            signals.append("【山寨币买入信号】BTC 已跌超50%，山寨季来临！")

    # ETF 信号
    high_premium = []
    low_premium = []

    for code in ETF_CODES:
        premium_str = etf_raw_map.get(code, "获取失败")

        if "获取失败" not in premium_str:
            # 移除百分号并转换为浮点数
            premium_val = float(premium_str[:-1])

            if premium_val >= 10:
                high_premium.append(ETF_NAMES.get(code))
            elif 0 <= premium_val <= 1.5:
                low_premium.append(ETF_NAMES.get(code))

    if high_premium:
        signals.append(f"【ETF 卖出信号】{','.join(high_premium)} 溢价≥10%，可套利卖出")
    if low_premium:
        signals.append(f"【ETF 买入信号】{','.join(low_premium)} 溢价≤1.5%，可申购")

    # 恐慌指数信号
    if isinstance(fg_value, int):
        if fg_value <= 15:
            signals.append(f"【极度恐慌抄底】恐慌指数仅 {fg_value}！历史级别大底信号！")
        elif fg_value >= 85:
            signals.append(f"【极度贪婪逃顶】恐慌指数高达 {fg_value}！历史级别阶段顶部！")

    # AHR999 信号判断
    if isinstance(ahr_value, float) and ahr_value > 0:
        if ahr_value < 0.45:
            signals.append(f"【AHR999 极度低估】值 {ahr_value:.4f}：重仓买入！历史大底信号")
        elif 0.45 <= ahr_value < 0.8:
            signals.append(f"【AHR999 低估】值 {ahr_value:.4f}：加大定投，合理成本区间")
        elif 0.8 <= ahr_value < 1.2:
            signals.append(f"【AHR999 中性】值 {ahr_value:.4f}：正常持有")
        elif 1.2 <= ahr_value < 2.0:
            signals.append(f"【AHR999 高估】值 {ahr_value:.4f}：逐步减仓，锁定利润")
        else:
            signals.append(f"【AHR999 极度高估】值 {ahr_value:.4f}：清仓卖出！历史顶部信号")

    # --- 3. 推送通知 ---

    title = f"📢 综合信号 - BTC: {cur:,} USD"

    # 将所有信号加入推送消息体
    signal_body = "\n    ".join([f"**{s}**" for s in signals])

    body = f"""
    --- 🔥 智能交易信号 ---
    {signal_body}

    --- 📊 BTC/加密货币数据 ---
    💵 当前价格: {cur:,} USD
    📈 历史高点: {high:,} USD
    📉 价格变动: {drop}%
    😱 恐慌指数: {fg_value} ({level})
    🚀 AHR999: {ahr_value:.4f}

    --- 📈 QDII ETF 溢价率 (haoetf) ---{etf_body}
    """

    print(title)
    print(body)

    #
    bark(title, body) # 请取消注释此行以启用推送

    return "OK"
