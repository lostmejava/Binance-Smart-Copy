import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import math
import csv
import os
from datetime import datetime
from binance.client import Client
from dotenv import load_dotenv, set_key

# 加载本地环境变量
ENV_FILE = ".env"
if not os.path.exists(ENV_FILE):
    print(f"错误: 未找到 {ENV_FILE} 配置文件，请先创建。")
    exit()

load_dotenv(ENV_FILE)

API_KEY = os.getenv('API_KEY')
API_SECRET = os.getenv('API_SECRET')
TOP_TRADER_ID = os.getenv('TOP_TRADER_ID')
PROXY_PORT = os.getenv('PROXY_PORT')

MY_TOTAL_CAPITAL = float(os.getenv('MY_TOTAL_CAPITAL', 50))
MAX_USDT_PER_ORDER = float(os.getenv('MAX_USDT_PER_ORDER', 15))
MIN_USDT_PER_ORDER = float(os.getenv('MIN_USDT_PER_ORDER', 10.0))
FORCE_MIN_ORDER = os.getenv('FORCE_MIN_ORDER', 'True').lower() in ('true', '1')
POLL_INTERVAL = int(os.getenv('POLL_INTERVAL', 10))

BINANCE_COOKIE = os.getenv('BINANCE_COOKIE')
BINANCE_CSRFTOKEN = os.getenv('BINANCE_CSRFTOKEN')

CSV_LOG_FILE = "trade_history.csv"
INFO_URL = "https://www.binance.com/bapi/futures/v2/public/future/leaderboard/getOtherLeaderboardBaseInfo"
POSITION_URL = "https://www.binance.com/bapi/asset/v1/private/future/smart-money/profile/query-positions"

PROXIES = {
    "http": f"http://127.0.0.1:{PROXY_PORT}",
    "https": f"http://127.0.0.1:{PROXY_PORT}"
} if PROXY_PORT else None


#自动化拦截与持久化上下文逻辑
def update_credentials():
    """使用持久化状态浏览器"""
    global BINANCE_COOKIE, BINANCE_CSRFTOKEN
    print("\n[凭证管理] 启动持久化状态浏览器（再次启动可免登录）...")

    captured_csrf = None

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            user_data_dir = os.path.join(os.getcwd(), "binance_user_data")

            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                args=["--disable-blink-features=AutomationControlled"]
            )

            page = context.pages[0] if context.pages else context.new_page()

            def handle_request(request):
                nonlocal captured_csrf
                headers = {k.lower(): v for k, v in request.headers.items()}
                if "csrftoken" in headers:
                    captured_csrf = headers["csrftoken"]

            page.on("request", handle_request)
            page.goto("https://www.binance.com/zh-CN/smart-money")

            print("\n👉 [操作提示]")
            print("1. 请在弹出的浏览器中登录币安账号，并确保进入了‘聪明钱’持仓页面。")
            print("2. 确认页面加载出持仓数据后，回到此终端输入 'yes' 并回车。")

            while True:
                user_input = input("\n是否登录完毕并开始跟踪？(输入 yes 确认): ").strip().lower()
                if user_input == 'yes':
                    break

            cookies = context.cookies()
            if cookies:
                BINANCE_COOKIE = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

            if captured_csrf:
                BINANCE_CSRFTOKEN = captured_csrf
            else:
                for c in cookies:
                    if c['name'] in ['cr00', 'r20t']:
                        BINANCE_CSRFTOKEN = c['value']
                        break

            context.close()

    except ImportError:
        print("未检测到 playwright 环境，请执行 pip install playwright 安装。")
        exit()
    except Exception as e:
        print(f"自动抓取发生异常: {e}")

    if BINANCE_COOKIE and BINANCE_CSRFTOKEN:
        set_key(ENV_FILE, "BINANCE_COOKIE", BINANCE_COOKIE)
        set_key(ENV_FILE, "BINANCE_CSRFTOKEN", BINANCE_CSRFTOKEN)
        print("[成功] 凭证已成功保存至 .env 文件，开始跟单流...")
    else:
        print("❌ 错误：未能获取到有效的 Cookie 或 CSRFTOKEN，请检查是否成功加载数据。")
        exit()


if not BINANCE_COOKIE or not BINANCE_CSRFTOKEN:
    update_credentials()

#初始化币安客户端与会话
if PROXIES:
    client = Client(API_KEY, API_SECRET, requests_params={'proxies': PROXIES})
else:
    client = Client(API_KEY, API_SECRET)

symbol_precision_cache = {}
symbol_min_notional_cache = {}

http_session = requests.Session()
if PROXIES:
    http_session.proxies.update(PROXIES)

retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["HEAD", "GET", "OPTIONS", "POST"]
)
adapter = HTTPAdapter(max_retries=retry_strategy)
http_session.mount("https://", adapter)
http_session.mount("http://", adapter)


#核心业务逻辑
def init_csv_log():
    if not os.path.exists(CSV_LOG_FILE):
        with open(CSV_LOG_FILE, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(
                ['记录时间', '操作类型', '交易对', '方向', '下单数量', '订单价值(U)', '杠杆', '状态', '订单号/备注'])
        print(f"已创建日志文件: {CSV_LOG_FILE}")
    else:
        print(f"载入日志文件: {CSV_LOG_FILE}")


def write_log(action_type, symbol, side, quantity, value_usdt, leverage, status, notes=""):
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(CSV_LOG_FILE, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(
                [current_time, action_type, symbol, side, quantity, f"{value_usdt:.2f}", f"{leverage}x", status, notes])
    except Exception as e:
        print(f"写入 CSV 日志失败: {e}")


def init_exchange_info():
    print("正在初始化币安合约交易规则...")
    try:
        info = client.futures_exchange_info()
        for symbol_data in info['symbols']:
            symbol = symbol_data['symbol']
            for filter_data in symbol_data['filters']:
                if filter_data['filterType'] == 'LOT_SIZE':
                    symbol_precision_cache[symbol] = float(filter_data['stepSize'])
                if filter_data['filterType'] == 'MIN_NOTIONAL':
                    symbol_min_notional_cache[symbol] = float(filter_data['notional'])
        print(f"成功加载 {len(symbol_precision_cache)} 个交易对的规则体系。")
    except Exception as e:
        print(f"初始化交易规则失败: {e}")
        exit()


def get_leader_balance():
    params = {"encryptedUid": TOP_TRADER_ID}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = http_session.post(INFO_URL, json=params, headers=headers, timeout=15)
        data = response.json()
        if data.get("success"):
            return float(data["data"]["umMarginBalance"])
    except Exception:
        pass
    return None


def get_all_leader_positions():
    """获取交易员所有持仓，失败时返回 None 触发上层重试，不再错误返回空字典"""
    global BINANCE_COOKIE, BINANCE_CSRFTOKEN
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cookie": BINANCE_COOKIE,
        "csrftoken": BINANCE_CSRFTOKEN,
        "clienttype": "web"
    }
    all_positions = {}
    current_page = 1

    while True:
        params = {"topTraderId": TOP_TRADER_ID, "marketType": "UM", "page": current_page, "rows": 50}
        try:
            response = http_session.get(POSITION_URL, params=params, headers=headers, timeout=15)
            data = response.json()

            if data.get("success") or data.get("code") == "000000":
                items = data.get("data", [])
                if not items: break

                for pos in items:
                    symbol = pos.get("symbol")
                    amount = float(pos.get("amount", 0))
                    if amount != 0:
                        all_positions[symbol] = {
                            "amount": amount,
                            "type": "LONG" if amount > 0 else "SHORT",
                            "leverage": int(pos.get("leverage", 5))
                        }

                if len(items) < params["rows"]: break
                current_page += 1
                time.sleep(0.5)
            else:
                print(f"[凭证失效] 动态持仓抓取失败，自动重新唤起浏览器补齐凭证...")
                update_credentials()
                return None
        except Exception as e:
            print(f"网络请求异常: {e}")
            return None
    return all_positions


def execute_open_order(symbol, leader_type, leader_amount, copy_ratio, leader_leverage):
    print(f"\n---> 准备开仓: {symbol} | 方向: {leader_type} | 理论跟随比例: {copy_ratio:.4f}")
    try:
        client.futures_change_leverage(symbol=symbol, leverage=leader_leverage)
    except Exception as e:
        print(f"调整杠杆失败使用默认值: {e}")

    target_quantity = abs(leader_amount) * copy_ratio

    try:
        ticker = client.futures_mark_price(symbol=symbol)
        current_price = float(ticker['markPrice'])
        order_value = target_quantity * current_price

        if order_value > MAX_USDT_PER_ORDER:
            target_quantity = MAX_USDT_PER_ORDER / current_price
            print(f"[风控] 订单价值超过上限，已缩减至 {MAX_USDT_PER_ORDER} U")

        elif order_value < MIN_USDT_PER_ORDER:
            if FORCE_MIN_ORDER:
                target_quantity = MIN_USDT_PER_ORDER / current_price
                print(f"[测试兜底] 理论金额低，强制提升目标至 {MIN_USDT_PER_ORDER} U")
            else:
                print(f"订单价值不足限制 ({order_value:.2f} U)，放弃开仓")
                return

        step_size = symbol_precision_cache.get(symbol, 1.0)
        real_min_notional = symbol_min_notional_cache.get(symbol, 5.0) + 0.05
        precision = int(round(-math.log(step_size, 10), 0)) if step_size < 1 else 0

        final_quantity = math.floor(target_quantity / step_size) * step_size
        final_quantity = round(final_quantity, precision)
        actual_value = final_quantity * current_price

        if actual_value < real_min_notional and FORCE_MIN_ORDER:
            final_quantity = math.ceil(target_quantity / step_size) * step_size
            final_quantity = round(final_quantity, precision)
            actual_value = final_quantity * current_price

        if final_quantity <= 0 or actual_value < (real_min_notional - 0.05):
            print(f"最终价值仍不足币安底线 ({actual_value:.2f} U)，放弃开仓")
            return

        side = "BUY" if leader_type == "LONG" else "SELL"
        position_side = leader_type

        print(f"正式发送开仓请求: {side} {final_quantity} {symbol} ({position_side}仓位)")

        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            positionSide=position_side,
            type='MARKET',
            quantity=final_quantity
        )

        order_id = order['orderId']
        print(f"开仓成功! 订单号: {order_id}")
        write_log("开仓", symbol, side, final_quantity, actual_value, leader_leverage, "成功",
                  f"{order_id} ({position_side})")

    except Exception as e:
        error_msg = str(e)
        print(f"开仓执行失败: {error_msg}")
        write_log("开仓", symbol, leader_type, target_quantity, 0, leader_leverage, "失败", error_msg)


def execute_close_order(symbol):
    print(f"\n---> 准备平仓: {symbol}")
    try:
        positions = client.futures_position_information(symbol=symbol)
        for pos in positions:
            position_amt = float(pos['positionAmt'])
            pos_side = pos.get('positionSide', 'BOTH')

            if position_amt != 0:
                close_qty = abs(position_amt)

                if pos_side == "LONG":
                    side = "SELL"
                    order = client.futures_create_order(
                        symbol=symbol, side=side, positionSide="LONG", type='MARKET', quantity=close_qty
                    )
                elif pos_side == "SHORT":
                    side = "BUY"
                    order = client.futures_create_order(
                        symbol=symbol, side=side, positionSide="SHORT", type='MARKET', quantity=close_qty
                    )
                else:
                    side = "SELL" if position_amt > 0 else "BUY"
                    order = client.futures_create_order(
                        symbol=symbol, side=side, type='MARKET', quantity=close_qty, reduceOnly=True
                    )

                order_id = order['orderId']
                print(f"平仓成功! 订单号: {order_id}")
                write_log("平仓", symbol, side, close_qty, 0, "-", "成功", f"{order_id} ({pos_side})")
                return

        print(f"本地无 {symbol} 持仓，无需操作。")
    except Exception as e:
        error_msg = str(e)
        print(f"平仓执行失败: {error_msg}")
        write_log("平仓", symbol, "未知", 0, 0, "-", "失败", error_msg)


def monitor():
    print("========================================")
    print(f"开始监控目标交易员: {TOP_TRADER_ID}")

    prev_positions = None
    while prev_positions is None:
        prev_positions = get_all_leader_positions()
        if prev_positions is None:
            time.sleep(3)

    print(f"初始状态加载完毕，成功获取交易员当前持有的 {len(prev_positions)} 个原始仓位（已自动过滤，不进行追单）。")
    print("监控循环启动，开始监听后续的全新开仓信号...")

    while True:
        time.sleep(POLL_INTERVAL)

        curr_positions = get_all_leader_positions()
        if curr_positions is None:
            continue

        # 检查平仓
        for symbol in prev_positions:
            if symbol not in curr_positions:
                print(f"\n[平仓信号] 交易员已平仓 {symbol}")
                execute_close_order(symbol)

        # 检查新开仓
        new_open_symbols = [s for s in curr_positions if s not in prev_positions]
        if new_open_symbols:
            leader_balance = get_leader_balance()
            dynamic_ratio = (MY_TOTAL_CAPITAL / leader_balance) if leader_balance else 0.01

            for symbol in new_open_symbols:
                pos_data = curr_positions[symbol]
                print(f"\n[开仓信号] 交易员新开 {symbol} ({pos_data['leverage']}x)")
                execute_open_order(symbol, pos_data['type'], pos_data['amount'], dynamic_ratio, pos_data['leverage'])

        prev_positions = curr_positions


if __name__ == "__main__":
    if not API_KEY or not API_SECRET:
        print("核心错误: .env 文件中缺少 API_KEY 或 API_SECRET 配置！")
        exit()
    init_csv_log()
    init_exchange_info()
    monitor()