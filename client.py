# -*- coding: utf-8 -*-

'''
客户端负责核心功能：
	发送->
		下单、撤单、余额查询
	<-接收
		K线、深度行情
		订单、仓位、账户
'''
import sys, json, traceback
from trader.object import StrategySetting, ZMQClient
from trader.utility import create_class

'''
装配参数，启动策略
'''


def bootstrap(setting, parameter):
	stg_instance = create_class(f"strategy.{setting.strategy}", setting.strategy, setting, parameter)
	stg_instance.start()


def lauch(config_file):
	try:
		with open(f'./config/{config_file}.json') as f:
			data = json.load(f)
		if data is not None:
			exchange = data['exchange']
			strategy = data['strategy']
			account = data['account']
			z = ZMQClient(command_port=data["zmq"]['command_port'],recv_port=data["zmq"]['recv_port'])
			setting = StrategySetting(exchange, strategy, account, z)
			bootstrap(setting,data["parameter"])
		else:
			print(f'{config_file}.json no data !!!')
	except:
		print(f'client run error: {traceback.format_exc()}')


if __name__ == "__main__":
	print(len(sys.argv))
	if len(sys.argv) < 2:
		print("Usage: %s pyramid_okex_quanwang_1m.json" % (sys.argv[0]))
		sys.exit(0)
	lauch(sys.argv[1])
	# lauch("okex_pyramid_quanwang")
