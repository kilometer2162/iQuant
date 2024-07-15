# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

'''
指标计算
'''


class IndicatorFactory(object):
	def __init__(self, logger, size: int = 200):
		self.logger = logger
		self.size: int = size
		self.inited = False
		self.is_new_bar = False
		self.open_array: np.ndarray = np.zeros(0)
		self.high_array: np.ndarray = np.zeros(0)
		self.low_array: np.ndarray = np.zeros(0)
		self.close_array: np.ndarray = np.zeros(0)
		self.volume_array: np.ndarray = np.zeros(0)

		self.bar_kv = {}
		self.latest_ts = 0

	def init_bar(self, data: list):
		self.open_array: np.ndarray = np.zeros(0)
		self.high_array: np.ndarray = np.zeros(0)
		self.low_array: np.ndarray = np.zeros(0)
		self.close_array: np.ndarray = np.zeros(0)
		self.volume_array: np.ndarray = np.zeros(0)

		for d in data:
			self.open_array = np.insert(self.open_array, len(self.open_array), d['open_price'])
			self.high_array = np.insert(self.high_array, len(self.high_array), d['high_price'])
			self.low_array = np.insert(self.low_array, len(self.low_array), d['low_price'])
			self.close_array = np.insert(self.close_array, len(self.close_array), d['close_price'])
			self.volume_array = np.insert(self.volume_array, len(self.volume_array), d['volume'])

		self.logger.info(f">>>>>>>>>>>>>>>>>>>> init close_array is: {self.close_array}")

	def update_bar(self, data):
		t = data.ts

		if t not in self.bar_kv:
			self.bar_kv[t] = {}
		self.bar_kv[t]['open'] = data.open_price
		self.bar_kv[t]['high'] = data.high_price
		self.bar_kv[t]['low'] = data.low_price
		self.bar_kv[t]['close'] = data.close_price
		self.bar_kv[t]['vol'] = data.volume

		self.is_new_bar = False
		if self.latest_ts != 0 and t > self.latest_ts:
			self.open_array = np.insert(self.open_array, len(self.open_array), self.bar_kv[self.latest_ts]['open'])
			if len(self.open_array) > self.size:
				self.open_array = self.open_array[1:]

			self.high_array = np.insert(self.high_array, len(self.high_array), self.bar_kv[self.latest_ts]['high'])
			if len(self.high_array) > self.size:
				self.high_array = self.high_array[1:]

			self.low_array = np.insert(self.low_array, len(self.low_array), self.bar_kv[self.latest_ts]['low'])
			if len(self.low_array) > self.size:
				self.low_array = self.low_array[1:]

			self.close_array = np.insert(self.close_array, len(self.close_array), self.bar_kv[self.latest_ts]['close'])
			if len(self.close_array) > self.size:
				self.close_array = self.close_array[1:]

			self.volume_array = np.insert(self.volume_array, len(self.volume_array), self.bar_kv[self.latest_ts]['vol'])
			if len(self.volume_array) > self.size:
				self.volume_array = self.volume_array[1:]

			if not self.inited and len(self.close_array) >= self.size:
				self.inited = True
			if self.inited:
				self.is_new_bar = True

			del self.bar_kv[self.latest_ts]
		self.latest_ts = t

	def boll(self, n: int, dev: float):
		has_zero = np.any(self.close_array == 0)
		if has_zero:
			return 0, 0, 0
		else:
			df = pd.DataFrame(self.close_array)

			ma = df.rolling(window=n).mean()
			std = df.rolling(window=n).std(ddof=0)
			upper = ma + (std * dev)
			lower = ma - (std * dev)

			upper.dropna(inplace=True)
			ma.dropna(inplace=True)
			lower.dropna(inplace=True)

			# return upper.tail(1).values[0][0], ma.tail(1).values[0][0], lower.tail(1).values[0][0]
			return upper, ma, lower

	def ma(self, n: int):
		has_zero = np.any(self.close_array == 0)
		if has_zero:
			return 0
		else:
			df = pd.DataFrame(self.close_array)
			ma = df.rolling(window=n).mean()
			return ma.tail(1).values[0][0]

	def rsi(self):
		result = {}
		# ticks.append(price)
		# print('close is :',self.close_array)
		last_close_px = self.close_array[0]
		days = [4, 6, 12, 24]
		if 0 in self.close_array:
			for d in days:
				sn = str(d)
				result['rsi' + sn] = [0]
			return result

		for i in range(0, len(self.close_array)):
			c = self.close_array[i]
			m = max(c - last_close_px, 0)
			a = abs(c - last_close_px)

			for d in days:
				sn = str(d)
				if 'rsi' + sn not in result:
					result['lastSm' + sn] = 0
					result['lastSa' + sn] = 0
					result['rsi' + sn] = [0]
				else:
					result['lastSm' + sn] = (m + (d - 1) * result['lastSm' + sn]) / d
					result['lastSa' + sn] = (a + (d - 1) * result['lastSa' + sn]) / d
					if result['lastSa' + sn] != 0:
						result['rsi' + sn].append(result['lastSm' + sn] / result['lastSa' + sn] * 100)
					else:
						result['rsi' + sn].append(0)
			last_close_px = c
		return result


import random

# df = pd.DataFrame([1,2,3,4,5,6])
# ma = df.rolling(window=3).mean()
# v = ma.tail(1).values[0][0]
# print(v)
