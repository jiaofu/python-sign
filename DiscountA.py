#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
获取AH股折价率数据
计算A股相对于H股的折价率，并按折价率从高到低排序
"""

import requests
import json
import re
from datetime import datetime
import time


def get_exchange_rate():
    """
    获取港元兑人民币汇率
    """
    try:
        url = "http://qt.gtimg.cn/q=fx_shkdcny"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }

        response = requests.get(url, headers=headers, timeout=5)
        response.encoding = 'gbk'

        if response.status_code == 200:
            content = response.text
            match = re.search(r'"[^"]*~[^~]*~[^~]*~([0-9.]+)', content)
            if match:
                rate = float(match.group(1))
                if 0.8 < rate < 1.0:
                    print(f"✓ 获取到实时汇率: 1 HKD = {rate:.4f} CNY")
                    return rate

        print("✓ 使用默认汇率: 1 HKD = 0.9200 CNY")
        return 0.92

    except Exception as e:
        print(f"! 获取汇率失败，使用默认汇率 0.92")
        return 0.92


def get_ah_premium_rate():
    """
    获取AH股折价率数据
    逻辑：
    1. 如果折价率>=10%的公司数量 > 8个，就输出所有>=10%的公司
    2. 否则，输出折价率最大的前8个公司（按溢价率从低到高排序，包括溢价股票）
    """
    try:
        print("\n【步骤1】正在获取港元兑人民币汇率...")
        exchange_rate = get_exchange_rate()

        print("\n【步骤2】正在获取AH股列表...")
        ah_stocks = get_ah_stocks_list()

        if not ah_stocks:
            print("✗ 未能获取到AH股列表")
            return "无法获取AH股数据"

        print(f"✓ 获取到 {len(ah_stocks)} 只AH股")

        # 批量获取股票数据
        print(f"\n【步骤3】开始批量查询实时价格...")
        result_list = get_all_stock_prices_batch(ah_stocks, exchange_rate)

        if not result_list:
            print("\n✗ 没有获取到有效数据")
            return "无法获取AH股数据，请检查网络连接"

        print(f"\n✓ 成功获取 {len(result_list)} 只股票的数据")

        # 筛选出折价的股票
        discount_stocks = [item for item in result_list if item['is_discount']]

        print(f"\n【步骤4】数据分析...")
        print(f"✓ 找到 {len(discount_stocks)} 只折价股票（A股价格 < H股价格×汇率）")

        # 按溢价率从低到高排序（折价的排在前面）
        result_list.sort(key=lambda x: x['premium_rate'])

        # 应用逻辑：
        # 1. 统计折价率>=10%的公司数量
        high_discount_stocks = [stock for stock in result_list if stock['discount_rate'] >= 10]

        # 2. 如果折价率>=10%的公司数量 > 8，输出所有>=10%的公司
        if len(high_discount_stocks) > 8:
            result = high_discount_stocks
            print(f"\n【应用逻辑】折价率>=10%的公司有 {len(high_discount_stocks)} 只(>8)，输出所有>=10%的公司")
        else:
            # 否则输出前8个（按溢价率从低到高，即折价率从高到低）
            result = result_list[:8]
            print(f"\n【应用逻辑】折价率>=10%的公司有 {len(high_discount_stocks)} 只(≤8)，输出溢价率最低的前8个公司")

        # 格式化输出
        output = format_output(result, exchange_rate, len(result_list), len(discount_stocks))
        return output

    except Exception as e:
        print(f"\n✗ 请求失败: {e}")
        import traceback
        traceback.print_exc()
        return f"获取数据时出错: {e}"


def get_all_stock_prices_batch(ah_stocks, exchange_rate):
    """
    批量获取所有股票的价格（每次请求20只股票）
    """
    result_list = []
    batch_size = 20  # 每批20只股票
    total = len(ah_stocks)

    for i in range(0, total, batch_size):
        batch = ah_stocks[i:i + batch_size]

        # 构建批量查询代码
        a_codes = [stock['a_code'] for stock in batch]
        h_codes = [stock['h_code'] for stock in batch]
        all_codes = a_codes + h_codes
        codes_str = ','.join(all_codes)

        try:
            url = f"http://qt.gtimg.cn/q={codes_str}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer": "http://stockhtm.finance.qq.com/"
            }

            response = requests.get(url, headers=headers, timeout=10)
            response.encoding = 'gbk'

            if response.status_code == 200:
                content = response.text
                lines = content.strip().split('\n')

                # 解析数据，建立代码到价格的映射
                price_map = {}
                for line in lines:
                    match = re.search(r'v_(\w+)="([^"]+)"', line)
                    if match:
                        code = match.group(1)
                        data = match.group(2).split('~')
                        if len(data) > 3:
                            price = float(data[3]) if data[3] else 0
                            price_map[code] = price

                # 匹配每只股票的A股和H股价格
                for stock in batch:
                    a_code = stock['a_code']
                    h_code = stock['h_code']
                    name = stock['name']

                    # 提取代码（去掉sh/sz/hk前缀）
                    a_code_key = a_code
                    h_code_key = h_code

                    a_price = price_map.get(a_code_key, 0)
                    h_price = price_map.get(h_code_key, 0)

                    if a_price > 0 and h_price > 0:
                        h_price_cny = h_price * exchange_rate
                        premium_rate = ((a_price - h_price_cny) / h_price_cny) * 100
                        discount_rate = -premium_rate if premium_rate < 0 else 0

                        result_list.append({
                            'name': name,
                            'a_code': a_code.replace('sh', '').replace('sz', ''),
                            'h_code': h_code.replace('hk', ''),
                            'a_price': a_price,
                            'h_price': h_price,
                            'h_price_cny': h_price_cny,
                            'premium_rate': premium_rate,
                            'discount_rate': discount_rate,
                            'is_discount': premium_rate < 0
                        })

            # 显示进度
            processed = min(i + batch_size, total)
            print(f"  进度: {processed}/{total} 只股票...")

            # 稍微延迟避免请求过快
            time.sleep(0.1)

        except Exception as e:
            print(f"  批量请求失败: {e}")
            continue

    return result_list


def get_ah_stocks_list():
    """
    根据用户截图整理的AH股完整列表
    """
    ah_stocks = [
        # 银行类
        {'name': '工商银行', 'a_code': 'sh601398', 'h_code': 'hk01398'},
        {'name': '建设银行', 'a_code': 'sh601939', 'h_code': 'hk00939'},
        {'name': '中国银行', 'a_code': 'sh601988', 'h_code': 'hk03988'},
        {'name': '农业银行', 'a_code': 'sh601288', 'h_code': 'hk01288'},
        {'name': '交通银行', 'a_code': 'sh601328', 'h_code': 'hk03328'},
        {'name': '招商银行', 'a_code': 'sh600036', 'h_code': 'hk03968'},
        {'name': '中信银行', 'a_code': 'sh601998', 'h_code': 'hk00998'},
        {'name': '光大银行', 'a_code': 'sh601818', 'h_code': 'hk06818'},
        {'name': '民生银行', 'a_code': 'sh600016', 'h_code': 'hk01988'},
        {'name': '邮储银行', 'a_code': 'sh601658', 'h_code': 'hk01658'},
        {'name': '浙商银行', 'a_code': 'sh601916', 'h_code': 'hk02016'},
        {'name': '青岛银行', 'a_code': 'sz002948', 'h_code': 'hk03866'},
        {'name': '渝农商行', 'a_code': 'sh601077', 'h_code': 'hk03618'},

        # 保险类
        {'name': '中国平安', 'a_code': 'sh601318', 'h_code': 'hk02318'},
        {'name': '中国人寿', 'a_code': 'sh601628', 'h_code': 'hk02628'},
        {'name': '中国太保', 'a_code': 'sh601601', 'h_code': 'hk02601'},
        {'name': '新华保险', 'a_code': 'sh601336', 'h_code': 'hk01336'},

        # 能源化工
        {'name': '中国石油', 'a_code': 'sh601857', 'h_code': 'hk00857'},
        {'name': '中国石化', 'a_code': 'sh600028', 'h_code': 'hk00386'},
        {'name': '中国神华', 'a_code': 'sh601088', 'h_code': 'hk01088'},
        {'name': '华能国际', 'a_code': 'sh600011', 'h_code': 'hk00902'},
        {'name': '中煤能源', 'a_code': 'sh601898', 'h_code': 'hk01898'},

        # 材料工业
        {'name': '海螺水泥', 'a_code': 'sh600585', 'h_code': 'hk00914'},
        {'name': '中国铝业', 'a_code': 'sh601600', 'h_code': 'hk02600'},
        {'name': '洛阳钼业', 'a_code': 'sh603993', 'h_code': 'hk03993'},
        {'name': '紫金矿业', 'a_code': 'sh601899', 'h_code': 'hk02899'},
        {'name': '赤峰黄金', 'a_code': 'sh600988', 'h_code': 'hk02686'},
        {'name': '山东黄金', 'a_code': 'sh600547', 'h_code': 'hk01787'},

        # 交通运输
        {'name': '中国国航', 'a_code': 'sh601111', 'h_code': 'hk00753'},
        {'name': '南方航空', 'a_code': 'sh600029', 'h_code': 'hk01055'},
        {'name': '东方航空', 'a_code': 'sh600115', 'h_code': 'hk00670'},
        {'name': '中远海控', 'a_code': 'sh601919', 'h_code': 'hk01919'},
        {'name': '中国外运', 'a_code': 'sh601598', 'h_code': 'hk00598'},

        # 高速公路
        {'name': '深高速', 'a_code': 'sh600548', 'h_code': 'hk00548'},
        {'name': '宁沪高速', 'a_code': 'sh600377', 'h_code': 'hk00177'},
        {'name': '四川成渝', 'a_code': 'sh601107', 'h_code': 'hk00107'},
        {'name': '皖通高速', 'a_code': 'sh600012', 'h_code': 'hk00995'},

        # 证券类
        {'name': '中信证券', 'a_code': 'sh600030', 'h_code': 'hk06030'},
        {'name': '广发证券', 'a_code': 'sz000776', 'h_code': 'hk01776'},
        {'name': '华泰证券', 'a_code': 'sh601688', 'h_code': 'hk06886'},
        {'name': '招商证券', 'a_code': 'sh600999', 'h_code': 'hk06099'},

        # 工业制造
        {'name': '中国中车', 'a_code': 'sh601766', 'h_code': 'hk01766'},
        {'name': '中国中铁', 'a_code': 'sh601390', 'h_code': 'hk00390'},
        {'name': '潍柴动力', 'a_code': 'sz000338', 'h_code': 'hk02338'},
        {'name': '广汽集团', 'a_code': 'sh601238', 'h_code': 'hk02238'},
        {'name': '比亚迪', 'a_code': 'sz002594', 'h_code': 'hk01211'},
        {'name': '上海电气', 'a_code': 'sh601727', 'h_code': 'hk02727'},
        {'name': '东方电气', 'a_code': 'sh600875', 'h_code': 'hk01072'},
        {'name': '中联重科', 'a_code': 'sz000157', 'h_code': 'hk01157'},
        {'name': '三一重工', 'a_code': 'sh600031', 'h_code': 'hk00631'},
        {'name': '海尔智家', 'a_code': 'sh600690', 'h_code': 'hk06690'},
        {'name': '美的集团', 'a_code': 'sz000333', 'h_code': 'hk00300'},
        {'name': '海信家电', 'a_code': 'sz000921', 'h_code': 'hk00921'},
        {'name': '重庆钢铁', 'a_code': 'sh601005', 'h_code': 'hk01053'},

        # 基建类
        {'name': '中国交建', 'a_code': 'sh601800', 'h_code': 'hk01800'},
        {'name': '中国铁建', 'a_code': 'sh601186', 'h_code': 'hk01186'},
        {'name': '中国电建', 'a_code': 'sh601669', 'h_code': 'hk03996'},

        # 医药类
        {'name': '复星医药', 'a_code': 'sh600196', 'h_code': 'hk02196'},
        {'name': '上海医药', 'a_code': 'sh601607', 'h_code': 'hk02607'},
        {'name': '药明康德', 'a_code': 'sh603259', 'h_code': 'hk02359'},
        {'name': '药明生物', 'a_code': 'sh688278', 'h_code': 'hk02269'},
        {'name': '康希诺', 'a_code': 'sh688185', 'h_code': 'hk06185'},
        {'name': '丽珠集团', 'a_code': 'sz000513', 'h_code': 'hk01513'},
        {'name': '凯莱英', 'a_code': 'sz002821', 'h_code': 'hk06821'},

        # 科技类
        {'name': '宁德时代', 'a_code': 'sz300750', 'h_code': 'hk03750'},
        {'name': '兆易创新', 'a_code': 'sh603986', 'h_code': 'hk03986'},
        {'name': '中芯国际', 'a_code': 'sh688981', 'h_code': 'hk00981'},
        {'name': '华虹公司', 'a_code': 'sh688347', 'h_code': 'hk01347'},
        {'name': '中兴通讯', 'a_code': 'sz000063', 'h_code': 'hk00763'},
        {'name': '澜起科技', 'a_code': 'sh688008', 'h_code': 'hk08008'},
        {'name': '先导智能', 'a_code': 'sz300450', 'h_code': 'hk09688'},

        # 新能源/锂电
        {'name': '天齐锂业', 'a_code': 'sz002466', 'h_code': 'hk09696'},
        {'name': '赣锋锂业', 'a_code': 'sz002460', 'h_code': 'hk01772'},

        # 消费类
        {'name': '青岛啤酒', 'a_code': 'sh600600', 'h_code': 'hk00168'},
        {'name': '福耀玻璃', 'a_code': 'sh600660', 'h_code': 'hk03606'},
        {'name': '海天味业', 'a_code': 'sh603288', 'h_code': 'hk06288'},
        {'name': '安井食品', 'a_code': 'sh603345', 'h_code': 'hk09345'},

        # 其他
        {'name': '中集集团', 'a_code': 'sz000039', 'h_code': 'hk02039'},
        {'name': '中国移动', 'a_code': 'sh600941', 'h_code': 'hk00941'},
        {'name': '中国中免', 'a_code': 'sh601888', 'h_code': 'hk01880'},
        {'name': '顺丰控股', 'a_code': 'sz002352', 'h_code': 'hk06936'},
        {'name': '牧原股份', 'a_code': 'sz002714', 'h_code': 'hk02714'},
    ]

    return ah_stocks


def format_output(data_list, exchange_rate, total_count, discount_count):
    """
    格式化输出结果
    """
    if not data_list:
        return "没有找到数据"

    output = []
    output.append("\n" + "=" * 125)
    output.append(f"{'AH股折价率排行榜':^120}")
    output.append(f"{'更新时间: ' + datetime.now().strftime('%Y-%m-%d %H:%M:%S'):^120}")
    output.append(f"{'(统计 ' + str(total_count) + ' 只AH股，其中 ' + str(discount_count) + ' 只折价)':^120}")
    output.append("=" * 125)
    output.append(f"{'排名':^6}{'股票名称':^14}{'A股代码':^12}{'H股代码':^12}{'A股价格':^12}{'H股价格(HKD)':^15}{'H股比A股':^15}{'A股溢价率':^12}")
    output.append("-" * 125)

    for idx, item in enumerate(data_list, 1):
        # A股溢价率（就是原来的premium_rate）
        a_premium_rate = item['premium_rate']
        # H股比A股的溢价率 = (H股CNY - A股) / A股 * 100%
        h_vs_a_rate = ((item['h_price_cny'] - item['a_price']) / item['a_price']) * 100

        output.append(
            f"{idx:^6}"
            f"{item['name']:^14}"
            f"{item['a_code']:^12}"
            f"{item['h_code']:^12}"
            f"{item['a_price']:>10.2f}  "
            f"{item['h_price']:>13.2f}  "
            f"{h_vs_a_rate:>13.2f}%  "
            f"{a_premium_rate:>10.2f}%  "
        )

    output.append("=" * 125)
    output.append(f"\n💡 【说明】")
    output.append(f"  • H股比A股: 正数表示H股比A股贵，负数表示H股比A股便宜")
    output.append(f"  • A股溢价率: 负数表示A股折价(便宜)，正数表示A股溢价(贵)")
    output.append(f"  • 当前汇率: 1 港元 = {exchange_rate:.4f} 人民币")
    output.append(f"  • H股比A股 = (H股价格×汇率 - A股价格) ÷ A股价格 × 100%")
    output.append(f"  • A股溢价率 = (A股价格 - H股价格×汇率) ÷ (H股价格×汇率) × 100%")
    output.append(f"\n📊 【输出逻辑】")

    # 统计>=10%的数量
    high_discount_count = len([item for item in data_list if item['discount_rate'] >= 10])

    if len(data_list) > 8:
        output.append(f"  • 折价率>=10%的公司有 {high_discount_count} 只(>8)，已输出所有折价率>=10%的公司")
    else:
        output.append(f"  • 折价率>=10%的公司有 {high_discount_count} 只(≤8)，输出溢价率最低的前8个公司（含折价和溢价）")

    return "\n".join(output)


def main():
    """
    主函数
    """
    print("\n" + "=" * 70)
    print(f"{'🔍 AH股折价率查询系统 🔍':^65}")
    print(f"{'(批量请求优化版)':^65}")
    print("=" * 70)

    result = get_ah_premium_rate()
    print(result)

    print("\n" + "=" * 70)
    print(f"{'✅ 查询完成！':^65}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
