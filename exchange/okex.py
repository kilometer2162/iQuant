import base64
import hashlib
import hmac
import json
import sys
import threading
import time
import requests
from datetime import datetime
from datetime import timedelta
from threading import Lock
from urllib.parse import urlencode

from requests import ConnectionError
from pytz import utc as UTC_TZ
import pandas as pd

from net.rest import Request, RestClient
from net.websocket import WebsocketClient

from exchange.base import BaseExchange
from trader.object import ExchangeSetting, PositionData, AccountData, OrderData, BarData, TickData, DepthData
from trader.utility import timestamp_to_datetime, datetime_to_str

_ = lambda x: x  # noqa
REST_HOST = "https://www.okex.com"
WEBSOCKET_HOST = "wss://ws.okex.com:8443/ws/v5"


class Okex(BaseExchange):
	def __init__(self):
		super(Okex, self).__init__()

		self.orders = {}
		self.rest_api = None
		self.ws_private_api = None
		self.ws_public_api = None

	def init(self, logger):
		super().init(logger)
		self.rest_api = OkexRestApi(self)
		self.ws_public_api = OkexPublicWebsocketApi(self)
		self.ws_private_api = OkexPrivateWebsocketApi(self)

	def connect(self, config: ExchangeSetting) -> None:
		super().connect(config)
		get_real_contract(config)

		t = threading.Thread(target=self.rest_api.connect, args=(config,), daemon=True)
		t.start()
		time.sleep(1)
		self.ws_public_api.connect(config)
		self.ws_private_api.connect(config)

	def send_order(self, req: dict):
		if 'ws' in req and req['ws']:
			self.ws_private_api.send_order(req)
		else:
			self.rest_api.send_order(req)

	def cancel_order(self, req: dict):
		if 'ws' in req and req['ws']:
			self.ws_private_api.cancel_order(req)
		else:
			self.rest_api.cancel_order(req)

	def query_bar(self, req: dict):
		self.rest_api.query_bar(req)

	def query_account(self):
		self.rest_api.query_account()

	def query_order(self):
		self.rest_api.query_order()

	def query_position(self):
		self.rest_api.query_position()

	def query_history(self, req: dict):
		self.rest_api.query_history(req)

	def close(self):
		self.rest_api.stop()
		self.ws_public_api.stop()
		self.ws_private_api.stop()

	def get_order(self, orderid: str):
		return self.orders.get(orderid, None)


class OkexRestApi(RestClient):
	"""
	OKEX REST API
	主要实现功能：K线、查仓位、查挂单(程序启动时需要全量数据)
	"""

	def __init__(self, exchange: BaseExchange):

		super(OkexRestApi, self).__init__()

		self.exchange = exchange
		self.key = ""
		self.secret = ""
		self.passphrase = ""
		self.symbols = None
		self.cycles = []

		self.order_count = 10000
		self.order_count_lock = Lock()

		self.connect_time = 0

	def sign(self, request):
		timestamp = generate_timestamp()
		request.data = json.dumps(request.data)

		if request.params:
			path = request.path + "?" + urlencode(request.params)
		else:
			path = request.path

		msg = timestamp + request.method + path + request.data
		signature = generate_signature(msg, self.secret)

		request.headers = {
			"Content-Type": "application/json",
			'Accept': 'application/json',
			'Cookie': 'local=zh_CN',
			"OK-ACCESS-KEY": self.key,
			"OK-ACCESS-SIGN": signature,
			"OK-ACCESS-TIMESTAMP": timestamp,
			"OK-ACCESS-PASSPHRASE": self.passphrase
		}
		return request

	def connect(self, config: ExchangeSetting):
		"""
		Initialize connection to REST server.
		"""
		self.key = config.public_key
		self.secret = config.private_key
		self.passphrase = config.phrase
		self.symbols = config.instrument
		self.cycles = config.cycles

		self.connect_time = int(datetime.now().strftime("%y%m%d%H%M%S"))

		self.init(REST_HOST)
		self.start(config.session_number)
		self.exchange.write_log("REST API启动成功")

		self.query_time()

	def query_time(self):
		self.add_request(
			"GET",
			"/api/v5/public/time",
			callback=self.on_query_time
		)

	def on_query_time(self, data, request):
		server_time = timestamp_to_datetime(data['data'][0]["ts"])
		local_time = datetime.utcnow().isoformat()
		msg = f"服务器时间：{server_time}，本机时间：{local_time}"
		self.exchange.write_log(msg)

	def query_account(self):
		coin = []
		for ins in self.symbols:
			ca = ins.split('-')[0]
			cb = ins.split('-')[1]
			if ca not in coin:
				coin.append(ca)
			if cb not in coin:
				coin.append(cb)
		coins = ",".join(coin)
		self.add_request(
			"GET",
			"/api/v5/account/balance?ccy=%s" % coins,
			callback=self.on_query_account
		)

	def on_query_account(self, data, request):
		accounts = []
		self.exchange.write_log(f"on_query_account data is =====>{data}")
		for asset in data['data'][0]['details']:
			account = _parse_account_info(asset)
			accounts.append(account)
		self.exchange.write_log("账户资金查询成功")
		if len(accounts) > 0:
			self.exchange.broadcast({"method": "on_account", "data": accounts})

	def query_bar(self, data):
		headers = {
			'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.190 Safari/537.36',

		}
		session = requests.session()
		max_try_amount = 5
		# 获取当前时间
		now_milliseconds = int(time.time() * 1e3)
		kbar_size = data['ks']
		for symbol in self.cycles:
			for time_interval in self.cycles[symbol]:

				time_segment = 60
				# 每根K线的间隔时间
				time_interval_int = int(time_interval[:-1])  # 若15m，则time_interval_int = 15；若2h，则time_interval_int = 2
				if time_interval.endswith('m'):
					time_segment = time_interval_int * 60 * 1000  # 15分钟 * 每分钟60s
				elif time_interval.endswith('h'):
					time_segment = time_interval_int * 60 * 60 * 1000  # 2小时 * 每小时60分钟 * 每分钟60s

				# 计算开始和结束的时间
				end = now_milliseconds - time_segment
				since = end - kbar_size * time_segment

				# 循环获取历史数据
				all_kline_data = []
				while end - since >= time_segment:
					kline_data = []
					klineUrl = REST_HOST + '/api/v5/market/history-candles?instId={symbol}&before={before}&after={after}&bar={bar}&limit=100'.format(
						symbol=symbol, before=since, after=int(since + 100 * time_segment), bar=time_interval)

					# 获取K线使，要多次尝试
					for i in range(max_try_amount):
						try:
							kline_data = session.get(klineUrl, headers=headers, timeout=3).json()['data']
							break
						except Exception as e:
							time.sleep(2)
							if i == (max_try_amount - 1):
								self.exchange.write_log("【获取需要交易币种的历史数据】错误")

					if kline_data:
						since = int(kline_data[0][0])  # 更新since，为下次循环做准备
						all_kline_data += reversed(kline_data)

				# 对数据进行整理
				df = pd.DataFrame(all_kline_data, dtype=float)
				df.rename(columns={0: 'time', 1: 'open', 2: 'high', 3: 'low', 4: 'close', 5: 'volume'}, inplace=True)
				# df['candle_begin_time'] = pd.to_datetime(df['MTS'], unit='ms')
				# df['time'] = df['candle_begin_time'] + timedelta(hours=8)  # GMT8 中国时区
				# df = df[['time', 'open', 'high', 'low', 'close', 'volume']]
				df.drop_duplicates(subset=['time'], keep='last', inplace=True)
				df.reset_index(drop=True, inplace=True)

				bars = []
				for i, row in df.iterrows():
					bar = BarData(symbol=symbol, cycle=time_interval, ts=row["time"], open_price=float(row["open"]), high_price=float(row["high"]),
						      low_price=float(row["low"]), close_price=float(row["close"]), volume=float(row["volume"]))
					bars.append(bar)
				if len(bars) > 0:
					self.exchange.broadcast({"method": "on_bar", "data": bars})

	def on_query_bar(self, data, request):
		bars = []
		for d in data['data']:
			bar = BarData(symbol=request.extra[0], cycle=request.extra[1], ts=d[0], open_price=float(d[1]), high_price=float(d[2]), low_price=float(d[3]),
				      close_price=float(d[4]), volume=float(d[5]))
			bars.append(bar)
		if len(bars) > 0:
			self.exchange.broadcast({"method": "on_bar", "data": bars})

	def query_position(self):
		for ins in self.symbols:
			self.add_request(
				"GET",
				"/api/v5/account/positions?instId=%s" % ins,
				callback=self.on_query_position
			)

	def on_query_position(self, datas, request):
		positions = []
		for holding in datas['data']:
			positions.append(_parse_position_holding(holding))
		if len(positions) > 0:
			self.exchange.broadcast({"method": "on_position", "data": positions})

	def query_order(self):
		for ins in self.symbols:
			self.add_request(
				"GET",
				"/api/v5/trade/orders-pending?instId=%s" % ins,
				callback=self.on_query_order
			)

	def on_query_order(self, datas, request):
		orders = []
		for order in datas['data']:
			orders.append(_parse_order_info(order))
		if len(orders) > 0:
			self.exchange.broadcast({"method": "on_order", "data": orders})

	def send_order(self, req: dict):
		self.exchange.write_log("send_order ===> %s" % str(req))
		method = 'order'
		if 'ordId' in req and 'newSz' in req and 'newPx' in req:
			method = 'amend-order'
		if 'tdMode' not in req:
			req['tdMode'] = 'cash'
		if 'ordType' not in req:
			req['ordType'] = 'limit'
		self.add_request(
			"POST",
			"/api/v5/trade/%s" % method,
			callback=self.on_send_order,
			data=req,
			on_error=self.on_send_order_error
		)

	def cancel_order(self, req: dict):
		rs = req.copy()
		if 'patch' in req:
			del rs["patch"]
		self.add_request(
			"POST",
			"/api/v5/trade/cancel-order",
			callback=self.on_cancel_order,
			on_error=self.on_cancel_order_error,
			params=rs,
			data=rs
		)

	def query_history(self, req: dict):
		args = '?instId=%s&instType=%s' % (req['instId'], req['instType'])
		if 'limit' in req:
			args = args + "&limit=%d" % req['limit']
		self.add_request(
			"GET",
			"/api/v5/trade/orders-history%s" % args,
			callback=self.on_query_history,
			data=req
		)

	def on_send_order(self, data, request):
		self.exchange.write_log("on_send_order data=> %s" % (str(data)))
		self.exchange.write_log("on_send_order request=> %s" % (str(request)))

		error_msg = f'{data["data"][0]["sCode"]} {data["data"][0]["sMsg"]}'
		if data["code"] != "0":
			self.exchange.write_log(f"REST 下单委托失败：{error_msg}")
		patch = json.loads(request.data)['patch']

		self.exchange.write_log(
			"on_send_order send ==> %s" % str(
				{"method": "on_send_order", "data": data, "response": {"code": int(data["data"][0]["sCode"]), "error": error_msg}, "patch": patch}))
		self.exchange.broadcast({"method": "on_send_order", "data": data, "response": {"code": int(data["data"][0]["sCode"]), "error": error_msg}, "patch": patch})

	def on_send_order_error(self, exception_type: type, exception_value: Exception, tb, request: Request):
		self.exchange.write_log("on_send_order error")
		patch = json.loads(request.data)['patch']
		self.exchange.write_log(
			"on_send_order error send ==> %s" % str({"method": "on_send_order", "data": "", "response": {"code": "1", "error": str(exception_value)}, "patch": patch}))
		self.exchange.broadcast({"method": "on_send_order", "data": "", "response": {"code": "1", "error": str(exception_value)}, "patch": patch})
		if not issubclass(exception_type, ConnectionError):
			self.on_error(exception_type, exception_value, tb, request)

	def on_cancel_order(self, data, request):
		error_msg = f'{data["data"][0]["sCode"]} {data["data"][0]["sMsg"]}'
		result = json.loads(request.data)
		if 'patch' in result:
			patch = result['patch']
		else:
			patch = ""
		self.exchange.broadcast({"method": "on_cancel_order", "data": data, "response": {"code": int(data["data"][0]["sCode"]), "error": error_msg}, "patch": patch})

	def on_cancel_order_error(self, exception_type: type, exception_value: Exception, tb, request: Request):
		patch = json.loads(request.data)['patch']
		self.exchange.broadcast({"method": "on_cancel_order", "data": "", "response": {"code": "1", "error": str(exception_value)}, "patch": patch})
		if not issubclass(exception_type, ConnectionError):
			self.on_error(exception_type, exception_value, tb, request)

	def on_query_history(self, data, request):
		error_msg = f'{data["code"]} {data["msg"]}'
		if error_msg:
			self.exchange.write_log(f"查询历史订单失败：{error_msg}")
		if len(data) > 0:
			result = json.loads(request.data)
			if 'patch' in result:
				patch = result['patch']
			else:
				patch = ""
			self.exchange.broadcast({"method": "on_query_history", "data": data, "response": {"code": int(data["code"]), "error": error_msg}, "patch": patch})

	def on_failed(self, status_code: int, request: Request):
		msg = f"请求失败，状态码：{status_code}，信息：{request.response.text}"
		self.exchange.write_log(msg)

	def on_error(self, exception_type: type, exception_value: Exception, tb, request: Request):
		"""
		Callback to handler request exception.
		"""
		msg = f"触发异常，状态码：{exception_type}，信息：{exception_value}"
		self.exchange.write_log(msg)

		sys.stderr.write(
			self.exception_detail(exception_type, exception_value, tb, request)
		)

	def _new_order_id(self):
		with self.order_count_lock:
			self.order_count += 1
			return self.order_count


class OkexPublicWebsocketApi(WebsocketClient):
	def __init__(self, exchange):

		super(OkexPublicWebsocketApi, self).__init__()
		self.ping_interval = 20

		self.exchange = exchange
		self._last_trade_id = 10000
		self.connect_time = 0

		self.callbacks = {}
		self.ticks = {}
		self.symbols = []
		self.cycles = []

	def connect(self, config: ExchangeSetting):
		self.symbols = config.instrument
		self.cycles = config.cycles

		self.connect_time = int(datetime.now().strftime("%y%m%d%H%M%S"))
		# self.init(f"{WEBSOCKET_HOST}/public", self.ping_interval, "127.0.0.1", 1080)
		self.init(f"{WEBSOCKET_HOST}/public", self.ping_interval)
		self.start()

	def subscribe(self):
		subs = []
		# self.exchange.write_log('ws symbols => %s' % (self.symbols))
		for ins in self.symbols:
			# subs.append({"channel": "tickers", "instId": ins})
			subs.append({"channel": "books5", "instId": ins})
		for cy in self.cycles:
			for c in self.cycles[cy]:
				subs.append({"channel": "candle%s" % c, "instId": cy})
				self.callbacks["candle%s" % c] = self.on_bar
		self.exchange.write_log('subs => %s' % (subs))
		self.callbacks["books5"] = self.on_depth
		self.callbacks["tickers"] = self.on_tick
		req = {
			"op": "subscribe",
			"args": subs
		}
		self.exchange.write_log('public send => %s' % str(req))
		self.send_packet(req)

	def on_connected(self):
		self.exchange.write_log("Websocket public API连接成功")
		self.subscribe()

	def on_disconnected(self):
		self.exchange.write_log("Websocket public API连接断开")

	def on_packet(self, packet: dict):
		# self.exchange.write_log('packet => %s' % str(packet))
		if "event" in packet:
			event = packet["event"]
			if event == "subscribe":
				return
			elif event == "error":
				msg = packet["msg"]
				self.exchange.write_log(f"Websocket public API请求异常：{packet['code']} {msg}")
		else:
			channel = packet["arg"].get('channel')
			callback = self.callbacks.get(channel, None)

			if callback:
				callback(packet)

	def on_error(self, exception_type: type, exception_value: Exception, tb):
		msg = f"触发异常，状态码：{exception_type}，信息：{exception_value}"
		self.exchange.write_log(msg)

		sys.stderr.write(self.exception_detail(exception_type, exception_value, tb))

	def on_bar(self, d):
		symbol = d['arg']["instId"]
		cycle = d['arg']['channel'].replace('candle', '')
		for r in d['data']:
			bar = BarData(symbol=symbol, cycle=cycle, ts=r[0], open_price=float(r[1]), high_price=float(r[2]), low_price=float(r[3]), close_price=float(r[4]),
				      volume=float(r[5]))
			self.exchange.broadcast({"method": "on_bar", "data": bar})

	def on_tick(self, d):
		symbol = d['arg']["instId"]
		for r in d['data']:
			ticker = TickData(symbol=symbol, ts=r['ts'], bidprice=float(r['bidPx']), askprice=float(r['askPx']), bidvolume=float(r['lastSz']),
					  askvolume=float(r['askSz']), last_price=float(r['last']), last_volume=float(r['lastSz']), open_24h=float(r['open24h']),
					  high_24h=float(r['high24h']), low_24h=float(r['low24h']), volume_24h=float(r['vol24h']))
			self.exchange.broadcast({"method": "on_tick", "data": ticker})

	def on_depth(self, d):
		symbol = d['arg']["instId"]
		for r in d['data']:
			bids = r["bids"]
			asks = r["asks"]
			ts = r['ts']
			depth = DepthData(symbol=symbol, ts=ts)
			for n, buf in enumerate(bids):
				price, volume, _, __ = buf
				depth.__setattr__("bid_price_%s" % (n + 1), float(price))
				depth.__setattr__("bid_volume_%s" % (n + 1), float(volume))

			for n, buf in enumerate(asks):
				price, volume, _, __ = buf
				depth.__setattr__("ask_price_%s" % (n + 1), float(price))
				depth.__setattr__("ask_volume_%s" % (n + 1), float(volume))

			self.exchange.broadcast({"method": "on_depth", "data": depth})


class OkexPrivateWebsocketApi(WebsocketClient):
	"""
	仓位、订单、账户推送；下单、撤单、修改订单
	"""

	def __init__(self, exchange):
		super(OkexPrivateWebsocketApi, self).__init__()
		self.ping_interval = 20

		self.exchange = exchange

		self.key = ""
		self.secret = ""
		self.passphrase = ""

		self._last_trade_id = 10000
		self.connect_time = 0

		self.callbacks = {}
		self.ticks = {}
		self.symbols = []

	def connect(self, config: ExchangeSetting):
		self.key = config.public_key
		self.secret = config.private_key
		self.passphrase = config.phrase
		self.symbols = config.instrument

		self.connect_time = int(datetime.now().strftime("%y%m%d%H%M%S"))
		# self.init(f"{WEBSOCKET_HOST}/private", self.ping_interval, "127.0.0.1", 1080)
		self.init(f"{WEBSOCKET_HOST}/private", self.ping_interval)
		self.start()

	def subscribe(self):
		subs = []
		for ins in self.symbols:
			subs.append({"channel": "orders", "instId": ins, "instType": 'ANY'})
			subs.append({"channel": "positions", "instId": ins, "instType": 'ANY'})
			subs.append({"channel": "account", "ccy": ins.split('-')[0]})

		self.callbacks["account"] = self.on_account
		self.callbacks["orders"] = self.on_order
		self.callbacks["positions"] = self.on_position
		self.callbacks["order"] = self.on_send_order
		self.callbacks["amend-order"] = self.on_send_order
		self.callbacks["cancel-order"] = self.on_cancel_order
		req = {
			"op": "subscribe",
			"args": subs
		}
		# self.exchange.write_log('private send => %s'%str(req))
		self.send_packet(req)

	def send_order(self, req):
		if 'ordId' in req:
			op = 'amend-order'
		else:
			op = 'order'
			if 'tdMode' not in req:
				req['tdMode'] = 'cash'
			if 'ordType' not in req:
				req['ordType'] = 'limit'
		data = {"id": str(int(time.time())), "op": op, "args": [req]}
		self.send_packet(data)

	def on_send_order(self, data):
		error_msg = f'{data["sCode"]} {data["sMsg"]}'
		if data["sCode"] != "0":
			self.exchange.write_log(f"Ws 下单委托失败：{error_msg}")
		self.exchange.broadcast({"method": "on_send_order", "data": data, "response": {"code": int(data["sCode"])}})

	def cancel_order(self, req):
		data = {"id": str(int(time.time())), "op": "cancel-order", "args": [req]}
		self.send_packet(data)

	def on_cancel_order(self, data):
		error_msg = f'{data["sCode"]} {data["sMsg"]}'
		if data["sCode"] != "0":
			self.exchange.write_log(f"Ws 撤单委托失败：{error_msg}")
		self.exchange.broadcast({"method": "on_cancel_order", "data": data, "response": {"code": int(data["sCode"])}})

	def on_connected(self):
		self.exchange.write_log("Websocket private API连接成功")
		self.login()

	def on_disconnected(self):
		self.exchange.write_log("Websocket private API连接断开")

	def on_packet(self, packet: dict):
		# print('recv => %s' % (str(packet)))
		if "event" in packet:
			event = packet["event"]
			if event == "subscribe":
				return
			elif event == "error":
				msg = packet["msg"]
				self.exchange.write_log(f"Websocket private API请求异常：{packet['code']} {msg}")
			elif event == "login":
				self.on_login(packet)
		else:
			channel = packet["arg"].get('channel')
			callback = self.callbacks.get(channel, None)
			if callback:
				callback(packet)

	def on_error(self, exception_type: type, exception_value: Exception, tb):
		msg = f"触发异常，状态码：{exception_type}，信息：{exception_value}"
		self.exchange.write_log(msg)

		sys.stderr.write(self.exception_detail(exception_type, exception_value, tb))

	def login(self):
		timestamp = str(int(time.time()))

		msg = timestamp + "GET" + "/users/self/verify"
		signature = generate_signature(msg, self.secret)

		req = {
			"op": "login",
			"args": [{"apiKey": self.key, "passphrase": self.passphrase, "timestamp": timestamp, "sign": signature.decode("utf-8")}]
		}
		# self.exchange.write_log("login => %s"%(str(req)))
		self.send_packet(req)
		self.callbacks["login"] = self.on_login

	def on_login(self, data: dict):
		success = data.get("code") == "0"
		if success:
			self.exchange.write_log("Websocket private API登录成功")
			self.subscribe()
		else:
			self.exchange.write_log("Websocket private API登录失败")

	def on_order(self, data):
		orders = []
		for o in data['data']:
			orders.append(_parse_order_info(o))
		if len(orders) > 0:
			self.exchange.broadcast({"method": "on_order", "data": orders})

	def on_account(self, data):
		accounts = []
		for asset in data['data']:
			for d in asset['details']:
				self.exchange.write_log(f"on_account data is =====>{d}")
				account = _parse_account_info(d)
				accounts.append(account)
		if len(accounts) > 0:
			self.exchange.broadcast({"method": "on_account", "data": accounts})

	def on_position(self, data):
		positions = []
		for holding in data['data']:
			positions.append(_parse_position_holding(holding))
		if len(positions) > 0:
			self.exchange.broadcast({"method": "on_position", "data": positions})


def get_real_contract(config: ExchangeSetting):
	symbols = config.instrument
	ci_symbols = symbols
	default_cycle = config.default_cycle
	cycles = {}
	chg_symbols = []
	ins = {}
	# 如果有交割合约的标的，转换成实际合约名
	found = False

	for s in symbols:
		if 'WEEK' in s or 'QUARTER' in s:
			found = True
			break
	if found:
		result = requests.get(f"{REST_HOST}/api/v5/public/instruments?instType=FUTURES")
		data = result.json()
		for row in data['data']:
			if row['uly'] in ins:
				ins[row['uly']][row["alias"].upper()] = row['instId']
			else:
				ins[row['uly']] = {row["alias"].upper(): row['instId']}
		for s in symbols:
			real = s
			if 'WEEK' in s or 'QUARTER' in s:
				arr = s.upper().split('-')
				real = ins["-".join(arr[0:2])][arr[2]]
			chg_symbols.append(real)
		symbols = chg_symbols
	for s in symbols:
		print("symbols:", symbols)
		if s not in ci_symbols or len(ci_symbols[s]) == 0:
			cycles[s] = [default_cycle]
		else:
			cycles[s] = ci_symbols[s]
	config.instrument = symbols
	config.cycles = cycles


def generate_signature(msg: str, secret_key: str):
	return base64.b64encode(hmac.new(secret_key.encode(), msg.encode(), hashlib.sha256).digest())


def generate_timestamp():
	now = datetime.utcnow()
	timestamp = now.isoformat("T", "milliseconds")
	return timestamp + "Z"


def _parse_timestamp(timestamp):
	"""parse timestamp into local time."""
	dt = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")
	dt = dt.replace(tzinfo=UTC_TZ)
	return dt


def _parse_position_holding(holding):
	position = float(holding["pos"])
	pos = PositionData(
		symbol=holding['instId'],
		posside=holding['posSide'],
		size=position,
		frozen=position - float(holding["availPos"]),
		price=float(holding['avgPx']),
		upl=float(holding['upl'])
	)
	return pos


def _parse_account_info(info):
	account = AccountData(
		coin=info['ccy'],
		total=float(info["eq"]),
		available=float(info["availEq"]),
		frozen=float(info["ordFrozen"])
	)
	return account


def _parse_order_info(order_info):
	order = OrderData(
		orderid=order_info["ordId"],
		symbol=order_info["instId"],
		ordertype=order_info["ordType"],
		side=order_info["side"],
		posside=order_info["posSide"],
		filled=float(order_info["fillSz"]),
		price=float(order_info["px"]),
		size=float(order_info["sz"]),
		time=datetime_to_str(timestamp_to_datetime(order_info["uTime"])),
		status=order_info["state"],
		fee=0 if len(order_info["fee"]) == 0 else order_info["fee"],
		feeCcy=order_info["feeCcy"],
		clientid=order_info["clOrdId"]
	)
	return order
