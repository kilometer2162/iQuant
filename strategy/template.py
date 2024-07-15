# -*- coding: utf-8 -*-
import json
import threading
import time
import requests
from abc import ABC, abstractmethod
import traceback, os
from collections import namedtuple
from queue import Empty, Queue

from trader.indicator import IndicatorFactory
from trader.logger import logger
from trader.object import StrategySetting

import zmq

'''
客户端策略基模板，不引入交易所API，完全通过消息收发操作
'''


class StgVariable(ABC):
	cache_switch = False

	def __init__(self, stg):
		self.coin = ""
		self.stg = stg

	def __setattr__(self, key, value):
		self.__dict__[key] = value
		if self.cache_switch and len(self.coin) > 0 and key[0:2] == 'c_':
			self.stg.put_cache(self.coin, key, value)

	def enable_cache_switch(self, val):
		self.cache_switch = val


class StrategyTemplate(ABC):
	cache_switch = False

	def __init__(self, setting: StrategySetting, parameter: dict):
		self.g_setting = setting
		self.g_parameter = parameter
		self.g_kline_min_size = 200
		self.g_indicator_factory = {}
		if "cycle" in parameter:
			self.g_cycle = parameter["cycle"]
		else:
			self.g_cycle = "15m"
		self.g_subscribe_active = False
		self.g_command_active = False
		self.g_notify_active = False
		self.STV = {}

		self.g_st_name = f"{setting.strategy}_{setting.exchange}_{setting.account}_{self.g_cycle}"
		log_path = os.path.join(os.getcwd(), "log", f"{self.g_st_name}.log")
		self.logger = logger(f"{setting.strategy}", log_path).logger

		self.r_context = None
		self.r_socket = None
		self.s_context = None
		self.s_socket = None
		self.s_queue = None

		self.stg_inited = False
		self.this = self

	def __setattr__(self, key, value):
		self.__dict__[key] = value
		if self.cache_switch and key[0:2] == 'c_':
			self.put_cache("stg", key, value)

	def start(self):
		t1 = threading.Thread(target=self.command, args=(), daemon=False)
		t1.start()
		time.sleep(2)
		t2 = threading.Thread(target=self.subscribe, args=(), daemon=False)
		t2.start()

	'''
	接收服务端订阅消息
	'''

	def subscribe(self):

		self.r_context = zmq.Context()
		self.r_socket = self.r_context.socket(zmq.SUB)
		self.r_socket.connect(f"tcp://127.0.0.1:{self.g_setting.zmq.recv_port}")
		self.r_socket.setsockopt(zmq.SUBSCRIBE, ''.encode('utf-8'))  # 接收所有消息

		# self.query_account()
		# self.query_position()
		# self.query_order()
		self.query_bar()
		# self.query_cache()

		self.g_subscribe_active = True
		try:
			while self.g_subscribe_active:
				try:
					message = self.r_socket.recv_string()  # recv_multipart()
					# print('--------------------client receive msg is --------------------')
					# print(message)
					# print('--------------------client receive end --------------------')
					# data = json.loads(message[-1].decode('utf8').replace("'", '"'))
					data = json.loads(message)
					if 'method' in data:
						if data['method'] == 'on_send_order':
							self.logger.error('--------------------client receive msg is --------------------')
							self.logger.error(data)
							self.logger.error('--------------------client receive end --------------------')

						if 'response' in data:
							patch = data['patch'] if 'patch' in data else ""
							self.msg_response_back(data, data['method'], patch)
						else:
							mtd = getattr(self.this, data['method'])
							data = data['data']
							if isinstance(data, dict):
								data = namedtuple("ObjectName", data.keys())(*data.values())

							if data is None or len(data) == 0:
								t = threading.Thread(target=mtd, args=(), daemon=True)
							else:
								t = threading.Thread(target=mtd, args=(data,), daemon=True)
							t.start()
					else:
						self.logger.error("subscribe receive message invalid!")
				except Exception:
					self.logger.error("StrategyTemplate start loop fail,traceback=\n%s" % traceback.format_exc())
					self.logger.error("error json is : %s" % (message))
		except Exception as e:
			self.logger.error("StrategyTemplate zmq fail,traceback=\n%s" % traceback.format_exc())
		finally:
			self.s_socket.close()
			self.s_context.term()

	'''
	发送服务端命令
	'''

	def command(self):
		self.s_context = zmq.Context()
		self.s_socket = self.s_context.socket(zmq.PUB)
		self.s_socket.bind(f"tcp://127.0.0.1:{self.g_setting.zmq.command_port}")
		self.s_queue: Queue = Queue()

		self.logger.info(f"{self.g_st_name} inited !")
		self.logger.info(f"发送端口:{self.g_setting.zmq.command_port}")

		self.g_command_active = True
		try:
			while self.g_command_active:
				try:
					if not self.s_socket.closed:
						try:
							data = self.s_queue.get(block=True, timeout=1)
							if data['method'] != "save_cache":
								self.logger.info('----------------> client send message: %s' % (str(data)))
							self.s_socket.send_json(data, flags=zmq.NOBLOCK)
						except Empty:
							pass
					else:
						self.logger.error("sock is closed,can't receive any message...")
						break
				except Exception:
					self.logger.error("StrategyTemplate send_msg fail,traceback=\n%s" % traceback.format_exc())
				finally:
					time.sleep(1)
		except Exception as e:
			self.logger.error("StrategyTemplate zmq fail,traceback=\n%s" % traceback.format_exc())
		finally:
			self.r_socket.close()
			self.r_context.term()

	def notify(self, coin, period):
		try:
			notify_time = ''
			while self.g_notify_active:
				file = f"curve/{self.g_st_name}_{coin}.csv"
				fe = os.path.isfile(file)
				if fe:
					time.sleep(period)
					with open(file, mode='r', encoding='utf-8') as f:
						data = f.readlines()
						if len(data) > 1:
							row = data[-1].split(",")
							if notify_time != row[0]:
								self.send_ding_msg(f"{self.g_st_name}: 最新净值：{row[1]} 最新盈亏：{row[2]}")
								notify_time = row[0]
		except Exception:
			self.logger.error("notify fail,traceback=\n%s" % traceback.format_exc())

	# 钉钉定时盈亏、净值通知
	def do_notify(self, coin, period=86400):
		t = threading.Thread(target=self.notify, args=(coin, period), daemon=False)
		t.start()

	def msg_response_back(self, data, method, patch=None):
		if data["response"]['code'] != 0:
			self.logger.error(f'{data["method"]} output=> {data["response"]["error"]}')
		if len(method) > 0:
			mtd = getattr(self.this, method)
			mtd(data, patch)

	def on_bar(self, data ):
		self.logger.info("on_bar===>" + str(data))
		if isinstance(data, list):
			sym = data[0]['symbol']
			cycle = data[0]['cycle']
			close_price = data[0]['close_price']
			volume = data[0]['volume']
			if sym not in self.g_indicator_factory:
				self.g_indicator_factory[sym] = {}
				if cycle not in self.g_indicator_factory:
					self.g_indicator_factory[sym][cycle] = IndicatorFactory(self.logger,self.g_kline_min_size)

			self.logger.info("on_bar 全量===>" + str(data))
			self.g_indicator_factory[sym][cycle].init_bar(data)
		# self.logger.info("init bar: %s" % str(self.g_indicator_factory[sym][cycle].close_array))
		else:
			sym = data.symbol
			cycle = data.cycle
			close_price = data.close_price
			volume = data.volume
			if sym not in self.g_indicator_factory:
				self.g_indicator_factory[sym] = {}
				if cycle not in self.g_indicator_factory:
					self.g_indicator_factory[sym][cycle] = IndicatorFactory(self.logger,self.g_kline_min_size)
			self.logger.info("on_bar 增量===>" + str(data))
			self.g_indicator_factory[sym][cycle].update_bar(data)
		# if self.g_indicator_factory[sym][cycle].is_new_bar:
		# 	self.logger.info("new bar: %s" %str(self.g_indicator_factory[sym][cycle].close_array))
		return sym, cycle, close_price, volume

	def on_depth(self, data):
		pass

	def on_order(self, data):
		pass

	def on_position(self, data):
		pass

	def on_account(self, data):
		pass

	def send_order(self, args: dict):
		self.s_queue.put({"method": "send_order", "data": args})

	@abstractmethod
	def on_send_order(self, data, patch=None):
		pass

	def cancel_order(self, args: dict):
		self.s_queue.put({"method": "cancel_order", "data": args})

	@abstractmethod
	def on_cancel_order(self, data, patch=None):
		pass

	def query_bar(self):
		self.logger.info(" ==========> g_kline_min_size: %s"%self.g_kline_min_size)
		self.query("query_bar",{"ks":self.g_kline_min_size})

	def query_account(self):
		self.query("query_account")

	def query_position(self):
		self.query("query_position")

	def query_order(self):
		self.query("query_order")

	def query_cache(self):
		self.query("query_cache", {"s": self.g_st_name})

	def query_history(self, req):
		self.query("query_history", req)

	def query(self, method, data=None):
		time.sleep(1.2)
		self.s_queue.put({"method": method, "data": data})

	def on_tick(self, data):
		pass

	def on_cache(self, data):
		if data.s == self.g_st_name:
			result = data.data
			self.logger.info("on_cache===>" + str(data))
			for c in result:
				_self = result[c]
				if c in self.STV:
					_self.enable_cache_switch(False)
					for k, v in _self:
						self.this.STV[c].__setattr__(k, v)
					_self.enable_cache_switch(True)
				elif c == 'stg':
					self.enable_cache_switch(False)
					for k, v in _self:
						self.this.__setattr__(k, v)
						self.this.after_strategy_cache()
					self.enable_cache_switch(True)

	'''
	加载缓存后执行
	'''

	@abstractmethod
	def after_strategy_cache(self):
		pass

	def get_stv(self, coin):
		return self.STV[coin] if coin in self.STV else None

	def is_instrument_on_me(self,coin,cfg_coin):
		if "-".join(coin.split('-')[0:2]) == "-".join(cfg_coin.split('-')[0:2]):
			return True

	def put_cache(self, coin, key, value):
		# self.logger.info(f"put_cache {coin} ===> {key} : {value}")
		self.s_queue.put({"method": "save_cache", "data": {"s": self.g_st_name, "c": coin, "k": key, "v": value}})

	def enable_cache_switch(self, val):
		self.cache_switch = val

	def save_order(self, data):
		file = f"order/{self.g_st_name}_{data['coin']}.csv"
		file_exists = os.path.isfile(file)
		if not file_exists:
			with open(file, mode='w', encoding='utf-8') as f:
				f.write(f"time,type,price,size,fee,pnl\r\n{data['time']},{data['type']},{data['price']},{data['size']},{data['fee']},{data['pnl']}\r\n")
		else:
			with open(file, mode='a', encoding='utf-8') as f:
				f.write(f"{data['time']},{data['type']},{data['price']},{data['size']},{data['fee']},{data['pnl']}\r\n")

	def save_curve(self, data):
		file = f"curve/{self.g_st_name}_{data['coin']}.csv"
		file_exists = os.path.isfile(file)
		if not file_exists:
			with open(file, mode='w', encoding='utf-8') as f:
				f.write(f"time,equity_curve,profit\r\n{data['time']},{data['net_value']},0\r\n")
		else:
			with open(file, mode='a', encoding='utf-8') as f:
				f.write(f"{data['time']},{data['net_value']},{data['profit']}\r\n")

	def send_ding_msg(self, msg):
		try:
			# 请求的URL，WebHook地址
			webhook = "https://oapi.dingtalk.com/robot/send?access_token=17ed46d2edf6affa6964cb1445a9c8af123c9dc35dc57e560655b0d3c5c388e5"
			# 构建请求头部
			header = {
				"Content-Type": "application/json",
				"Charset": "UTF-8"
			}
			# msg = f"{self.g_st_name}: buy[coin:{data['coin']},price:{data['price']},vol:{data['vol']}]"
			# if data['type'] == 'sell':
			# 	msg = f"{self.g_st_name}: sell[coin:{data['coin']},price:{data['price']},vol:{data['vol']}] net_value:{data['net_value']} profit:{data['profit']} "
			# 构建请求数据
			message = {
				"msgtype": "text",
				"text": {
					"content": msg
				},
				# "atMobiles": [
				# 	"130xxxxxxxx"  # 如果需要@某人，这里写他的手机号
				# ],
				# "at": {
				#
				# 	"isAtAll": True
				# }

			}
			# 对请求的数据进行json封装
			message_json = json.dumps(message)
			# 发送请求
			info = requests.post(url=webhook, data=message_json, headers=header)
			# 打印返回的结果
			self.logger.info('dingmessage result:', info.text)
		except:
			self.logger.error("send_ding_msg error:", traceback.format_exc())
