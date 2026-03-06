#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股资金雷达 + AH股折价率监控
整合版本，推送到Bark
"""

import requests
import pandas as pd
from datetime import datetime
import akshare as ak
import time
import re

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
            response = requests.post(url, json=payload, timeout=20)
            if response.status_code == 200:
                print("✅ Bark 推送成功！")
                return
            else:
                print(f"⚠️ Bark 返回异常状态码: {response.status_code}")
        except Exception as e:
            print(f"⚠️ Bark 推送超时或异常 (第 {attempt + 1}/{max_retries} 次尝试): {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(2)
    print("❌ Bark 推送最终失败，已达到最大重试次数。")


# ====================================================================
# 【A 股拥挤度获取函数】
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
        if total_val < 50000:
            df['成交额'] = df['成交额'] * 100000000
        elif total_val < 500000000:
            df['成交额'] = df['成交额'] * 10000
        return df

    # 1. 尝试主源：东方财富
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
        pass

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
# 【AH股折价率获取函数】
# ====================================================================
def get_exchange_rate():
    """获取港元兑人民币汇率"""
    try:
        url = "http://qt.gtimg.cn/q=fx_shkdcny"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=5)
        response.encoding = 'gbk'
        
        if response.status_code == 200:
            content = response.text
            match = re.search(r'"[^"]*~[^~]*~[^~]*~([0-9.]+)', content)
            if match:
                rate = float(match.group(1))
                if 0.8 < rate < 1.0:
                    return rate
        return 0.92
    except Exception:
        return 0.92


def get_ah_stocks_list():
    """获取AH股列表（精简版，只保留主要股票）"""
    return [
        # 科技类
        {'name': '宁德时代', 'a_code': 'sz300750', 'h_code': 'hk03750'},
        {'name': '兆易创新', 'a_code': 'sh603986', 'h_code': 'hk03986'},
        {'name': '中芯国际', 'a_code': 'sh688981', 'h_code': 'hk00981'},
        
        # 银行类
        {'name': '工商银行', 'a_code': 'sh601398', 'h_code': 'hk01398'},
        {'name': '建设银行', 'a_code': 'sh601939', 'h_code': 'hk00939'},
        {'name': '中国银行', 'a_code': 'sh601988', 'h_code': 'hk03988'},
        {'name': '招商银行', 'a_code': 'sh600036', 'h_code': 'hk03968'},
        
        # 医药类
        {'name': '药明康德', 'a_code': 'sh603259', 'h_code': 'hk02359'},
        
        # 制造业
        {'name': '潍柴动力', 'a_code': 'sz000338', 'h_code': 'hk02338'},
        {'name': '美的集团', 'a_code': 'sz000333', 'h_code': 'hk00300'},
        {'name': '比亚迪', 'a_code': 'sz002594', 'h_code': 'hk01211'},
        
        # 其他
        {'name': '紫金矿业', 'a_code': 'sh601899', 'h_code': 'hk02899'},
        {'name': '福耀玻璃', 'a_code': 'sh600660', 'h_code': 'hk03606'},
        {'name': '青岛啤酒', 'a_code': 'sh600600', 'h_code': 'hk00168'},
        {'name': '中国平安', 'a_code': 'sh601318', 'h_code': 'hk02318'},
    ]


def get_all_stock_prices_batch(ah_stocks, exchange_rate):
    """批量获取股票价格"""
    result_list = []
    batch_size = 15
    total = len(ah_stocks)
    
    for i in range(0, total, batch_size):
        batch = ah_stocks[i:i + batch_size]
        a_codes = [stock['a_code'] for stock in batch]
        h_codes = [stock['h_code'] for stock in batch]
        all_codes = a_codes + h_codes
        codes_str = ','.join(all_codes)
        
        try:
            url = f"http://qt.gtimg.cn/q={codes_str}"
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Referer": "http://stockhtm.finance.qq.com/"
            }
            
            response = requests.get(url, headers=headers, timeout=10)
            response.encoding = 'gbk'
            
            if response.status_code == 200:
                content = response.text
                lines = content.strip().split('\n')
                
                price_map = {}
                for line in lines:
                    match = re.search(r'v_(\w+)="([^"]+)"', line)
                    if match:
                        code = match.group(1)
                        data = match.group(2).split('~')
                        if len(data) > 3:
                            price = float(data[3]) if data[3] else 0
                            price_map[code] = price
                
                for stock in batch:
                    a_code = stock['a_code']
                    h_code = stock['h_code']
                    name = stock['name']
                    
                    a_price = price_map.get(a_code, 0)
                    h_price = price_map.get(h_code, 0)
                    
                    if a_price > 0 and h_price > 0:
                        h_price_cny = h_price * exchange_rate
                        premium_rate = ((a_price - h_price_cny) / h_price_cny) * 100
                        discount_rate = -premium_rate if premium_rate < 0 else 0
                        
                        result_list.append({
                            'name': name,
                            'a_price': a_price,
                            'h_price': h_price,
                            'h_price_cny': h_price_cny,
                            'premium_rate': premium_rate,
                            'discount_rate': discount_rate,
                            'is_discount': premium_rate < 0
                        })
            
            time.sleep(0.1)
            
        except Exception as e:
            print(f"批量请求失败: {e}")
            continue
    
    return result_list


def get_ah_discount_data(top_n=8):
    """
    获取AH股折价率数据
    返回: (exchange_rate, result_list, discount_count)
    """
    try:
        print("开始获取AH股折价率数据...")
        exchange_rate = get_exchange_rate()
        ah_stocks = get_ah_stocks_list()
        
        result_list = get_all_stock_prices_batch(ah_stocks, exchange_rate)
        
        if not result_list:
            return exchange_rate, [], 0
        
        # 筛选折价股票
        discount_stocks = [item for item in result_list if item['is_discount']]
        
        # 按溢价率从低到高排序
        result_list.sort(key=lambda x: x['premium_rate'])
        
        # 应用逻辑
        high_discount_stocks = [stock for stock in result_list if stock['discount_rate'] >= 10]
        
        if len(high_discount_stocks) > top_n:
            result = high_discount_stocks
        else:
            result = result_list[:top_n]
        
        print(f"成功获取 {len(result_list)} 只AH股数据，其中 {len(discount_stocks)} 只折价")
        return exchange_rate, result, len(discount_stocks)
        
    except Exception as e:
        print(f"获取AH股数据失败: {e}")
        return 0.92, [], 0


# ====================================================================
# 【主执行函数：整合A股拥挤度 + AH股折价率】
# ====================================================================
def handler(event=None, context=None):
    """主处理函数"""
    current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # --- 1. 获取A股拥挤度数据 ---
    source, total_turnover, df_result, has_tilt = get_ashare_crowding_data(top_n=5)
    
    crowding_body = ""
    if df_result is not None:
        signals = []
        top_list_str = []
        df_result = df_result.reset_index(drop=True)
        
        for index, row in df_result.iterrows():
            name = row.get('板块名称', row.get('板块', '未知板块'))
            turnover_ratio = row['成交额占比(%)']
            turnover_amt = row['成交额'] / 100000000
            
            alert_tag = ""
            if turnover_ratio >= 12:
                signals.append(f"💀 {name} 死亡红线 ({turnover_ratio:.1f}%)")
                alert_tag = "💀"
            elif turnover_ratio >= 10:
                signals.append(f"🚨 {name} 极度拥挤 ({turnover_ratio:.1f}%)")
                alert_tag = "🚨"
            elif turnover_ratio >= 8:
                signals.append(f"⚠️ {name} 高危警戒 ({turnover_ratio:.1f}%)")
                alert_tag = "⚠️"
            
            tilt_info = ""
            if has_tilt:
                tilt = row['资金倾斜度']
                if tilt >= 2.5:
                    alert_tag += "🔥"
                    tilt_info = f" 倾斜{tilt:.1f}x"
            
            top_list_str.append(f"{index+1}. {name}{alert_tag}: {turnover_ratio:.1f}%{tilt_info}")
        
        signal_body = "\n".join(signals) if signals else "✅ 无板块触发8%警戒线"
        ranking_body = "\n".join(top_list_str)
        
        crowding_body = f"""📊 A股拥挤度
总成交: {total_turnover / 100000000:.0f}亿 | {source}

🔥 极端信号:
{signal_body}

📈 TOP5板块:
{ranking_body}
"""
    else:
        crowding_body = "❌ A股拥挤度数据获取失败"
    
    # --- 2. 获取AH股折价率数据 ---
    exchange_rate, ah_result, discount_count = get_ah_discount_data(top_n=8)
    
    ah_body = ""
    if ah_result:
        ah_lines = []
        ah_signals = []
        
        for idx, item in enumerate(ah_result[:8], 1):
            name = item['name']
            premium = item['premium_rate']
            
            # 信号判断
            if premium <= -20:
                ah_signals.append(f"🔥 {name} 深度折价 ({premium:.1f}%)")
                emoji = "🔥"
            elif premium <= -10:
                ah_signals.append(f"⭐ {name} 折价机会 ({premium:.1f}%)")
                emoji = "⭐"
            elif premium < 0:
                emoji = "✓"
            else:
                emoji = "✗"
            
            ah_lines.append(f"{idx}. {name}{emoji}: {premium:+.1f}%")
        
        signal_body = "\n".join(ah_signals) if ah_signals else "✅ 无深度折价机会"
        ah_list_body = "\n".join(ah_lines)
        
        ah_body = f"""
💰 AH股折价率
汇率: 1港元={exchange_rate:.3f}元 | {discount_count}只折价

🎯 交易机会:
{signal_body}

📋 TOP8股票:
{ah_list_body}
"""
    else:
        ah_body = "\n❌ AH股数据获取失败"
    
    # --- 3. 整合推送 ---
    title = f"🇨🇳 A股雷达+AH折价 ({datetime.now().strftime('%H:%M')})"
    body = f"""[{current_time_str}]

{crowding_body}{ah_body}

负数=A股便宜 | 正数=A股贵
"""
    
    print(title)
    print(body)
    bark(title, body)
    
    return "OK"


# ====================================================================
# 【本地测试入口】
# ====================================================================
if __name__ == "__main__":
    handler()
