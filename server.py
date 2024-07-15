# -*- coding: utf-8 -*-

import os

'''
服务端负责核心功能：
	发送->
		K线、深度行情
		订单、仓位、账户
	<-接收
		下单、撤单、余额查询
'''

import sys, json, traceback

from trader.object import ExchangeSetting, ZMQServer
from trader.utility import run_multiprocessing,create_class
from trader.logger import logger

'''
启动交易所
      
'''


def bootstrap(setting: ExchangeSetting):
	serve = Via(setting)
	serve.start()


def lauch(config_file):
	try:
		with open(f'./config/{config_file}.json') as f:
			data = json.load(f)

		if data is not None:
			cfs = []
			for ex in data:
				for acc in data[ex]:
					row = data[ex][acc]
					z = ZMQServer(row["zmq"]['port'], row["zmq"]['client'])
					if 'phrase' not in row:
						row['phrase'] = ''
					exchange_config = ExchangeSetting(exchange=ex,
									  account=acc,
									  public_key=row['public_key'],
									  private_key=row['private_key'],
									  phrase=row['phrase'],
									  instrument=row['instrument'],
									  default_cycle=row['default_cycle'],
									  zmq=z)
					cfs.append(exchange_config)

			run_multiprocessing(bootstrap, [cf for cf in cfs], len(cfs))
		else:
			print(f'{config_file}.json no data !!!')

	except:
		print(f'server lauch error: {traceback.format_exc()}')


'''
服务端交易所调用路由
'''


class Via:
	def __init__(self, setting: ExchangeSetting):
		self.exchange = None
		self.logger = None
		self.setting = setting

	def start(self):
		log_path = os.path.join(os.getcwd(), "log", f"{self.setting.exchange}_{self.setting.account}.log")
		self.logger = logger(f"{self.setting.exchange}", log_path).logger

		self.exchange = create_class(f"exchange.{self.setting.exchange}", self.setting.exchange[0].upper() + self.setting.exchange[1:])

		if self.exchange is None:
			self.logger.error(f"Create exchage: {self.setting.exchange} failed !")
			return False
		self.exchange.init(self.logger)
		self.exchange.connect(self.setting)
		self.exchange.start()


if __name__ == "__main__":
	print(len(sys.argv))
	if len(sys.argv) < 2:
		print("Usage: %s server_okex_quanwang.json" % (sys.argv[0]))
		sys.exit(0)
	lauch(sys.argv[1])