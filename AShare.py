import requests
import pandas as pd
from datetime import datetime
import akshare as ak
import time  # 新增 time 模块用于重试等待

# --- 配置 ---
BARK_KEY = "5vMdJU9YEoLmQLKne6kSoE"

# ====================================================================
# 【工具函数】
# ====================================================================

def bark(title, body):
    """通过 Bark 推送通知 (加入 3 次重试抗网络波动机制)"""
    url = f"https://api.day.app/{BARK_KEY}/"
    payload = {"title": title, "body": body, "group": "A股资金雷达", "sound": "anticipate"}

    max_retries = 3
    for attempt in range(max_retries):
        try:
            # 把 timeout 延长到了 20 秒，给足服务器反应时间
            response = requests.post(url, json=payload, timeout=20)
            if response.status_code == 200:
                print("✅ Bark 推送成功！")
                return  # 成功就直接结束
            else:
                print(f"⚠️ Bark 返回异常状态码: {response.status_code}")
        except Exception as e:
            print(f"⚠️ Bark 推送超时或异常 (第 {attempt + 1}/{max_retries} 次尝试): {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(2)  # 失败了等 2 秒再重试

    print("❌ Bark 推送最终失败，已达到最大重试次数。")

# ====================================================================
# 【A 股拥挤度获取函数 - 返回核心数据供 Handler 判断】
# ====================================================================

def get_ashare_crowding_data(top_n=5):
    """
    获取 A 股行业资金拥挤度，内置多源降级容错机制。
    返回: (source_name, total_turnover, df_result, has_tilt)
    """
    def normalize_unit(df, col_name):
        df['成交额'] = pd.to_numeric(df[col_name], errors='coerce')
        df = df.dropna(subset=['成交额'])
        total_val = df['成交额'].sum()
        if total_val < 50000:          # 亿元
            df['成交额'] = df['成交额'] * 100000000
        elif total_val < 500000000:    # 万元
            df['成交额'] = df['成交额'] * 10000
        return df

    # 1. 尝试主源：东方财富 (含市值，可算资金倾斜度)
    try:
        df_em = ak.stock_board_industry_spot_em()
        turnover_col = [c for c in df_em.columns if "成交额" in c or "总额" in c or "成交金额" in c][0]
        df_em = normalize_unit(df_em, turnover_col)
        df_em['总市值'] = pd.to_numeric(df_em['总市值'], errors='coerce')
        df_em = df_em.dropna(subset=['成交额', '总市值'])

        total_turnover = df_em['成交额'].sum()
        df_em['成交额占比(%)'] = (df_em['成交额'] / total_turnover) * 100
        df_em['资金倾斜度'] = df_em['成交额占比(%)'] / ((df_em['总市值'] / df_em['总市值'].sum()) * 100)

        df_result = df_em.sort_values(by='成交额占比(%)', ascending=False).head(top_n)
        return "东方财富", total_turnover, df_result, True
    except Exception:
        pass # 静默降级

    # 2. 尝试备用源一：同花顺
    try:
        df_ths = ak.stock_board_industry_summary_ths()
        turnover_col = [c for c in df_ths.columns if "成交额" in c][0]
        df_ths = normalize_unit(df_ths, turnover_col)

        total_turnover = df_ths['成交额'].sum()
        df_ths['成交额占比(%)'] = (df_ths['成交额'] / total_turnover) * 100

        df_result = df_ths.sort_values(by='成交额占比(%)', ascending=False).head(top_n)
        return "同花顺 (降级模式)", total_turnover, df_result, False
    except Exception:
        pass

    # 3. 尝试备用源二：新浪财经
    try:
        df_sina = ak.stock_sector_spot(indicator="新浪行业")
        turnover_col = [c for c in df_sina.columns if "成交额" in c][0]
        df_sina = normalize_unit(df_sina, turnover_col)

        total_turnover = df_sina['成交额'].sum()
        df_sina['成交额占比(%)'] = (df_sina['成交额'] / total_turnover) * 100

        df_result = df_sina.sort_values(by='成交额占比(%)', ascending=False).head(top_n)
        return "新浪财经 (降级模式)", total_turnover, df_result, False
    except Exception as e:
        print(f"所有接口获取失败: {e}")
        return "获取失败", 0, None, False


# ====================================================================
# 【主执行函数：整合信号并推送 Bark】
# ====================================================================

def handler(event, context):

    # --- 0. 获取当前时间 ---
    current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # --- 1. 获取基础数据 ---
    source, total_turnover, df_result, has_tilt = get_ashare_crowding_data(top_n=5)

    if df_result is None:
        error_title = "❌ A股资金雷达运行失败"
        error_body = "所有数据源接口均遭拦截或超时，请检查函数环境网络。"
        print(error_body)
        bark(error_title, error_body)
        return "Error"

    # --- 2. 智能信号判断与排版 ---
    signals = []
    top_list_str = []

    df_result = df_result.reset_index(drop=True)
    for index, row in df_result.iterrows():
        name = row.get('板块名称', row.get('板块', '未知板块'))
        turnover_ratio = row['成交额占比(%)']
        turnover_amt = row['成交额'] / 100000000

        # 信号判断
        alert_tag = ""
        if turnover_ratio >= 12:
            signals.append(f"💀【{name} 死亡红线】占比破12%！随时崩盘，无条件清仓！")
            alert_tag = " 💀"
        elif turnover_ratio >= 10:
            signals.append(f"🚨【{name} 极度拥挤】占比破10%！增量枯竭，逢高大减仓！")
            alert_tag = " 🚨"
        elif turnover_ratio >= 8:
            signals.append(f"⚠️【{name} 高危警戒】占比破8%！进入鱼尾行情，已经火热！")
            alert_tag = " ⚠️"

        # 详情排版
        tilt_info = ""
        if has_tilt:
            tilt = row['资金倾斜度']
            if tilt >= 2.5:
                alert_tag += " 🔥"
            tilt_info = f"\n   ▶ 资金倾斜: {tilt:.2f} 倍"

        list_item = f"TOP {index+1}: 【{name}】{alert_tag}\n   ▶ 成交占比: {turnover_ratio:.2f}% (吸血 {turnover_amt:.2f} 亿){tilt_info}"
        top_list_str.append(list_item)

    # --- 3. 组装推送通知 ---
    title = f"🇨🇳 A股拥挤度雷达 ({datetime.now().strftime('%H:%M')})"

    signal_body = "\n\n".join([f"**{s}**" for s in signals]) if signals else "今日无触发 8% 以上警戒线的板块，相对安全。"
    ranking_body = "\n\n".join(top_list_str)

    body = f"""[生成时间: {current_time_str}]
数据源: {source}
A股总成交额: {total_turnover / 100000000:.2f} 亿元

--- 🔥 极端交易信号 ---
{signal_body}

--- 📊 行业吸血 TOP 5 ---
{ranking_body}
"""

    print(title)
    print(body)

    bark(title, body)

    return "OK"