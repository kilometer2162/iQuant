# -*- coding: utf-8 -*-
import json
import threading,time,os
from abc import ABC, abstractmethod
import zmq, traceback

from trader.object import ExchangeSetting
from trader.utility import EnhancedJSONEncoder


class BaseExchange(ABC):
	def __init__(self):
		self.s_context = None
		self.s_socket = None
		self.s_topic = None

		self.r_context_list = []
		self.r_socket_list = []
		self.logger = None

		self.m_active: bool = False
		self.m_cache = {}

	def init(self, logger):
		self.logger = logger

	def write_log(self,context):
		self.logger.info(context)

	def connect(self, setting: ExchangeSetting):
		self.s_context = zmq.Context()
		self.s_socket = self.s_context.socket(zmq.PUB)
		self.s_socket.bind(f"tcp://127.0.0.1:{setting.zmq.port}")

		# self.write_log("订阅端口: %s" % str(setting.zmq.client))
		for c in setting.zmq.client:
			context = zmq.Context()
			socket = context.socket(zmq.SUB)
			socket.connect("tcp://127.0.0.1:%s" % c)
			socket.setsockopt(zmq.SUBSCRIBE, ''.encode('utf-8'))  # 接收所有消息
			self.write_log("订阅客户端端口: %s" %c)
			self.r_socket_list.append(socket)
			self.r_context_list.append(context)

		if len(self.r_socket_list) > 0:
			self.m_active = True
		else:
			self.write_log("未建立与客户端命令接收连接!!!")

	def start(self):
		# pass
		t1 = threading.Thread(target=self.get_command, args=(), daemon=False)
		t1.start()
		time.sleep(5)
		t2 = threading.Thread(target=self.persist_cache, args=(), daemon=False)
		t2.start()

	def get_command(self):
		try:
			while self.m_active:
				# self.write_log('--------------------r_socket_list is : %s--------------------' % (str(len(self.r_socket_list))))
				for socket in self.r_socket_list:
					# self.write_log('--------------------socket is : %s--------------------' %(str(socket.closed)))
					try:

						if not socket.closed:
							data = socket.recv_json(flags=zmq.NOBLOCK)
							self.write_log('--------------------server receive msg is --------------------')
							self.write_log(data)
							self.write_log('--------------------server receive end --------------------')

							if 'method' in data:
								if 'response' in data:
									self.msg_response_back(data, data['method'])
								else:
									mtd = getattr(self, data['method'])
									if data['data'] is None or len(data['data']) == 0:
										t = threading.Thread(target=mtd, args=(), daemon=True)
									else:
										t = threading.Thread(target=mtd, args=(data['data'],), daemon=True)
									t.start()
							else:
								self.logger.error("BaseExchange receive message invalid!")

					# except:
					# 	self.logger.error("BaseExchange start loop fail,traceback=\n%s" % traceback.format_exc())
					# 	self.logger.error("error json is : %s" %(str(data)))
					except zmq.Again as e:
						# No messages waiting to be processed
						pass
				time.sleep(1)
		except Exception as e:
			self.logger.error("BaseExchange zmq fail,traceback=\n%s" % traceback.format_exc())
		finally:
			self.s_socket.close()
			self.s_context.term()
			for item in self.r_socket_list:
				item.close()
			for item in self.r_context_list:
				item.term()

	def broadcast(self, data):
		try:
			if len(data) == 0:
				return

			# self.logger.info('----------------> send message: %s' % str(data))
			# self.s_socket.send_multipart([self.s_topic, json.dumps(data, cls=EnhancedJSONEncoder).encode("utf-8")])
			self.s_socket.send_string(json.dumps(data, cls=EnhancedJSONEncoder),copy=False)
		except Exception:
			self.logger.error("BaseExchange broadcast fail,traceback=\n%s" % traceback.format_exc())

	def msg_response_back(self, data, callback):
		if data["response"]['code'] != 0:
			self.logger.error(f'{data["method"]} return :{data["response"]["error"]}')
		if len(callback) > 0:
			mtd = getattr(self, callback)
			mtd(data)

	def persist_cache(self):
		while self.m_active:
			try:

				self.logger.info("m_cache ===>" + str(self.m_cache))
				for s in self.m_cache:
					file = f"cache/{s}.json"
					with open(file, mode='w', encoding='utf-8') as f:
						f.write(str(self.m_cache[s]))
			except Exception:
				self.logger.error("persist_cache fail,traceback=\n%s" % traceback.format_exc())
			finally:
				time.sleep(60)

	def save_cache(self, data):
		self.logger.info("save_cache===>" + str(data))
		s = data['s']
		if s not in self.m_cache:
			file = f"cache/{s}.json"
			if os.path.exists(file):
				with open(file, 'r') as f:
					res = f.readlines()
					if len(res) > 0:
						self.m_cache[s] = json.loads("".join(res))
			if len(self.m_cache) == 0:
				self.m_cache = {s:{}}
		c = data["c"]
		k = data["k"]
		v = data["v"]
		if c not in self.m_cache[s]:
			self.m_cache[s][c] = {}
		self.m_cache[s][c][k] = v

	def query_cache(self, data):
		s = data["s"]
		if s in self.m_cache:
			self.broadcast({"method": "on_cache", "data": {"s": s, "data": self.m_cache[s]}})

	@abstractmethod
	def send_order(self, req: dict):
		pass

	@abstractmethod
	def cancel_order(self, req: dict):
		pass

	@abstractmethod
	def query_bar(self, req: dict):
		pass

	@abstractmethod
	def query_account(self):
		pass

	@abstractmethod
	def query_order(self):
		pass

	@abstractmethod
	def query_position(self):
		pass

	@abstractmethod
	def query_history(self, req: dict):
		pass
