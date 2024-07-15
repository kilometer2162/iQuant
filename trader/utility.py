# -*- coding: utf-8 -*-
import dataclasses
import json
import logging
import os
import sys
import random
from pathlib import Path
from typing import Callable, Dict, Tuple, Union
from decimal import Decimal
from math import floor, ceil
import multiprocessing
import multiprocessing.dummy as threading

# import numpy as np
# import pandas as pd
# import talib, os
import time
import sys

from datetime import datetime, timedelta

log_formatter = logging.Formatter('[%(asctime)s] %(message)s')
file_handlers: Dict[str, logging.FileHandler] = {}




'''
动态创建类对象
@:param module_name 包名.文件名
@:param class_name 类名
'''


def create_class(module_name, class_name, *args, **kwargs):
	module_meta = __import__(module_name, globals(), locals(), [class_name])
	class_meta = getattr(module_meta, class_name)
	obj = class_meta(*args, **kwargs)
	return obj


def _get_file_logger_handler(filename: str) -> logging.FileHandler:
	handler = file_handlers.get(filename, None)
	if handler is None:
		handler = logging.FileHandler(filename)
		file_handlers[filename] = handler  # Am i need a lock?
	return handler


def get_file_logger(filename: str) -> logging.Logger:
	"""
	return a logger that writes records into a file.
	"""
	logger = logging.getLogger(filename)
	handler = _get_file_logger_handler(filename)  # get singleton handler.
	handler.setFormatter(log_formatter)
	logger.addHandler(handler)  # each handler will be added only once.
	return logger


def run_multiprocessing(func, params: list, max_worker: int = None, join=True):
	pool = multiprocessing.Pool(max_worker)

	if not params:
		return
	if isinstance(params[0], tuple):
		pool.starmap(func, params)
	else:
		pool.map(func, params)
	pool.close()
	if join:
		pool.join()


def run_multithreading(func, params: list, max_worker: int = None, join=True):
	pool = threading.Pool(max_worker)

	if isinstance(params[0], tuple):
		pool.starmap(func, params)
	else:
		pool.map(func, params)
	pool.close()

	if join:
		pool.join()


def get_now_datetime():
	return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def get_random():
	return int(random.random() * 1000)


def run_shell(cmd):
	f = os.popen(cmd)
	txt = f.readlines()
	# for line in txt:
	# 	colum = line.split()


'''
将10位的时间戳转化为时间
'''


def timestamp_to_datetime(timestamp):
	if len(str(timestamp)) == 13:
		timestamp = timestamp[0:10]
	if not isinstance(timestamp, int):
		timestamp = int(timestamp)
	return datetime.fromtimestamp(timestamp)


def str_to_datetime(str_datetime):
	return datetime.strptime(str_datetime, "%Y-%m-%d %H:%M:%S")


def datetime_to_str(_datetime):
	return datetime.strftime(_datetime, '%Y-%m-%d %H:%M:%S')


def datetime_to_timestamp(dt):
	# 时间转为时间戳
	# dt = "2019-4-13 10:02:23"
	time_array = time.strptime(dt, "%Y-%m-%d %H:%M:%S")
	# 转为时间戳
	time_stamp = int(time.mktime(time_array))
	return time_stamp


# ===为了达到成交的目的，计算实际委托价格会向上或者向下浮动一定比例默认为0.003
def cal_order_price(price, order_type, ratio=0.002):
	# 开多/平空时价格挂高
	if order_type in [1, 4]:
		return price * (1 + ratio)
	# 开空/平多时价格挂低
	elif order_type in [2, 3]:
		return price * (1 - ratio)


# 定义一个进度条
def process_bar(num, total):
	rate = float(num) / total
	ratenum = int(100 * rate)
	r = '\r[{}{}]{}%'.format('*' * ratenum, ' ' * (100 - ratenum), ratenum)
	sys.stdout.write(r)
	sys.stdout.flush()


'''
dataclass转化为json:
foo = Foo(x="bar")
print(json.dumps(foo, cls=EnhancedJSONEncoder))

json转化为dataclass:


class Person:
	def __init__(self, name, age,ts):
		self.name = name
		self.age = age
		self.ts = ts


person_string = '{"name": "Bob", "age": 25,"ts":{"a":1}}'

person_dict = json.loads(person_string)
person_object = Person(**person_dict)

print(person_object.name)
print(person_object.age)
print(person_object.ts)
'''


def return_drawdown_ratio(equity_curve):
	"""
	:param equity_curve: 带资金曲线的df
	:param trade: transfer_equity_curve_to_trade的输出结果，每笔交易的df
	:return:
	"""

	# ===计算年化收益
	annual_return = (equity_curve['equity_curve'].iloc[-1] / equity_curve['equity_curve'].iloc[0]) ** (
			'1 days 00:00:00' / (equity_curve['candle_begin_time'].iloc[-1] - equity_curve['candle_begin_time'].iloc[0]) * 365) - 1

	# ===计算最大回撤，最大回撤的含义：《如何通过3行代码计算最大回撤》https://mp.weixin.qq.com/s/Dwt4lkKR_PEnWRprLlvPVw
	# 计算当日之前的资金曲线的最高点
	equity_curve['max2here'] = equity_curve['equity_curve'].expanding().max()
	# 计算到历史最高值到当日的跌幅，drowdwon
	equity_curve['dd2here'] = equity_curve['equity_curve'] / equity_curve['max2here'] - 1
	# 计算最大回撤，以及最大回撤结束时间
	end_date, max_draw_down = tuple(equity_curve.sort_values(by=['dd2here']).iloc[0][['candle_begin_time', 'dd2here']])

	# ===年化收益/回撤比
	sharpe = annual_return / abs(max_draw_down)

	return annual_return, max_draw_down, sharpe


class EnhancedJSONEncoder(json.JSONEncoder):
	def default(self, o):
		if dataclasses.is_dataclass(o):
			return dataclasses.asdict(o)
		return super().default(o)


# obj = create_class('strategy.test','abc')
# obj.pr()
# open_array: np.ndarray = np.zeros(0)
# print(open_array)

# d = np.insert(open_array, len(open_array), 55)
# print(d[::-1])
