# -*- coding: utf-8 -*-
import time
import traceback
from threading import Lock

from trader import utility
# from trader.utility import get_random
from trader.object import StrategySetting
from strategy.template import StrategyTemplate, StgVariable

'''
垒币躺平不止损，有盈利时固定点数回撤止盈
'''


class AccumulateVariable(StgVariable):
	def __init__(self, stg):
		super(AccumulateVariable, self).__init__(stg)
		self._available = 0
		self.init_balance = 0
		self.init_size = 0
		self.size = 0
		self.max_size = 0
		self.max_balance = 0
		self.continuous_draw = 0
		self.avg_price = 0
		
		self.buy_timestamp = 0
		self._max_price = 0
		self.earn = 0
		self.draw = 0
		self.max_draw = 0
		self.win = 0
		self.trade_count = 0
		self.peak = 0
		self.valley = 0
		self._ordering = False
		self._ordering_lock = Lock()
		self.continuous_buy = 0

		self.candle = {'timestamp': '', 'close': 0}
		self._bars = []
		self._vols = []
		self.open_state = 0
		self._open_state_lock = Lock()
		self.close_state = 0
		self._close_state_lock = Lock()

		self.ignore_candle = 0
		self.stop_pnl_ratio = 0
		self.fee = 0

		self.invest_asset = 0
		self.pos = 0
		self.order_cnt = 0


class accumulate(StrategyTemplate):
	def __init__(self, setting: StrategySetting, parameter: dict):
		super(accumulate, self).__init__(setting, parameter)
		self.this = self
		self.usdt_available = 0

		for c in self.g_parameter["instrument"]:
			ap = AccumulateVariable(self.this)
			e = self.g_parameter["instrument"][c]

			ap.size = e['size']
			ap.max_size = e['max_size']
			ap.stop_pnl_ratio = e['stop_pnl_ratio']
			ap.fee = e['fee']

			ap.coin = c
			ap.enable_cache_switch(True)
			self.STV[c] = ap
			self.g_notify_active = True
			self.do_notify(c)

	def on_bar(self, data):
		super().on_bar(data)

		if not isinstance(data, list):
			coin = data.symbol
			if coin in self.STV:

				_self = self.STV[coin]

				down_trend = 0
				up_trend = 0

				if coin in self.g_indicator_factory:
					this = self.g_indicator_factory[coin][self.g_cycle]
					if len(_self._bars) == 0:
						ca_list = this.close_array

						if len(ca_list) > 12:
							_self._bars = [ca_list[-11],
								      ca_list[-10],
								      ca_list[-9],
								      ca_list[-8],
								      ca_list[-7],
								      ca_list[-6],
								      ca_list[-5],
								      ca_list[-4],
								      ca_list[-3],
								      ca_list[-2],
								      ca_list[-1]
								      ]

						va_list = this.volume_array

						if len(va_list) > 12:
							_self._vols = [va_list[-11],
								       va_list[-10],
								       va_list[-9],
								       va_list[-8],
								       va_list[-7],
								       va_list[-6],
								       va_list[-5],
								       va_list[-4],
								       va_list[-3],
								       va_list[-2],
								       va_list[-1]
								       ]
					else:
						if this.is_new_bar:
							self.logger.info("on_bar===>" + str(data))
							c = this.bar_kv['px']
							_self._bars.append(c)
							_self._bars = _self._bars[1:]

							if _self._bars[-2] < _self._bars[-3] and _self._bars[-2] < _self._bars[-4] and _self._bars[-2] < _self._bars[-5] and _self._bars[-2] < _self._bars[-6] and _self._bars[-2] < _self._bars[-7]:
								down_trend += 1
							if _self._bars[-2] > _self._bars[-3] > _self._bars[-4] > _self._bars[-5] and _self._bars[-5] < _self._bars[-6] < _self._bars[-7] < _self._bars[-8] < _self._bars[-9]:
								down_trend += 1
							if _self._bars[-2] < _self._bars[-3] < _self._bars[-4] < _self._bars[-5] < _self._bars[-6] < _self._bars[-7] < _self._bars[-8] < _self._bars[-9]:
								down_trend += 1
							if _self._bars[-1] < _self._bars[-2] and _self._bars[-1] < _self._bars[-3] and _self._bars[-1] < _self._bars[-4] and _self._bars[-1] < _self._bars[-5]:
								down_trend += 1
							if _self._bars[-1] < _self._bars[-2] and _self._bars[-1] < _self._bars[-4] and _self._bars[-1] < _self._bars[-6] and _self._bars[-1] < _self._bars[-8] and _self._bars[-1] < _self._bars[-10]:
								down_trend += 1
							if _self._bars[-3] < _self._bars[-4] < _self._bars[-5] < _self._bars[-6] and _self._bars[-7] < _self._bars[-8] < _self._bars[-9] < _self._bars[-10]:
								down_trend += 1
							if _self._bars[-1] < _self._bars[-2] < _self._bars[-3] < _self._bars[-8] < _self._bars[-9] < _self._bars[-10]:
								down_trend += 1

							if _self._bars[-1] > _self._bars[-7] and _self._bars[-1] / _self._bars[-7] - 1 > abs(_self.stop_pnl_ratio)*3:
								up_trend = 1
							if _self._bars[-1] > _self._bars[-5] and _self._bars[-1] / _self._bars[-5] - 1 > abs(_self.stop_pnl_ratio)*2:
								up_trend += 1
							if _self._bars[-1] > _self._bars[-2] and _self._bars[-1] / _self._bars[-2] - 1 > abs(_self.stop_pnl_ratio):
								up_trend += 2

							self.logger.info("bar[-1]: %f bar[-2]: %f " % (_self._bars[-1], _self._bars[-2]))

							up_std = 1
							down_std = 3
							if _self.continuous_buy > 3:
								up_std = 3
								down_std = 5

							self.logger.info('avg_prie: %f down_trend: %d  up_trend: %d ## down_std: %d  up_std: %d' % ( _self.avg_price, down_trend,  up_trend,  down_std, up_std))
							if down_trend > down_std or up_trend > up_std:
								# '开仓' , 防止频繁重复开仓，5条K线后再次判断趋势
								if _self.ignore_candle > 0:
									_self.ignore_candle -= 1
								else:
									with _self._open_state_lock:
										_self.open_state = 1
									_self.ignore_candle = 5

							if _self.pos > 0:
								if _self._max_price < c:
									_self._max_price = c
								pnl = self.calc_pnl(_self.avg_price, c)
								if pnl > 0.015:
									# 从高点回落N个点止盈
									if _self.avg_price < c:
										pnl_down = self.calc_pnl(c, _self._max_price)
										self.logger.info("avg_price is: %f,  close is : %f ,max_price is: %f ,pnl_down is: %f" % ( _self.avg_price, c, _self._max_price, pnl_down))
										if pnl_down <= _self.stop_pnl_ratio:
											# '平仓'
											with _self._close_state_lock:
												_self.close_state = 1
											if _self.ignore_candle > 1:
												_self.ignore_candle = 0

	def on_depth(self, data):
		try:
			# self.logger.info("on_depth===>" + str(data))
			coin = data.symbol
			if coin in self.STV:
				_self = self.STV[coin]

				if not _self._ordering:

					if _self.open_state == 1 and _self.pos < _self.max_size:
						if self.usdt_available > _self.size * data.bid_price_1:
							now = int(time.time())
							# 防止频繁买入、拉大吃单间距
							if _self.buy_timestamp > 0 and now - _self.buy_timestamp < 300 and abs(_self.avg_price - data.bid_price_1) / _self.avg_price < abs(_self.stop_pnl_ratio):
								self.logger.info("%s ask1price: %f tight distance to avg_price: %f" % (coin, data.bid_price_1, _self.avg_price))
								return
							self.logger.info("%s buy price: %f amount: %f" % (coin, data.bid_price_3, _self.size))

						client_oid = self.gen_client_orderid(coin, 'acm')
						self.send_order({"instId": coin, "clOrdId": client_oid, "side": 'buy', "px": data.bid_price_3, "sz": _self.size, "patch": {"coin": coin, "side":"buy", "amount": _self.size}})

					if _self.close_state == 1 and _self.pos >= _self.size:
						if _self.pos > _self.size:
							self.logger.info("%s sell price: %f amount: %f" % (coin, data.ask_price_5, _self.size))

						client_oid = self.gen_client_orderid(coin, 'acm')
						self.send_order({"instId": coin, "clOrdId": client_oid, "side": 'sell', "px": data.ask_price_5, "sz": _self.size, "patch": {"coin": coin, "side":"sell", "amount": _self.size}})

		except:
			self.logger.error("on_depth_data error,traceback=\n%s" % traceback.format_exc())

	def send_order(self, args: dict):
		_self = self.STV[args['patch']['coin']]
		with _self._ordering_lock:
			_self._ordering = True
		super().send_order(args)

	def on_send_order(self, data, patch=None):
		coin = patch['coin']
		if coin in self.STV:
			_self = self.STV[coin]
			if patch["side"] == 'buy' and order_success(data):
				with _self._open_state_lock:
					_self.open_state = 0

			elif patch["side"] == 'sell' and order_success(data):
				with _self._close_state_lock:
					_self.close_state = 0

			with _self._ordering_lock:
				_self._ordering = False

	def on_order(self, data):
		for row in data:
			coin = row["symbol"]
			if coin in self.STV:
				self.logger.info("on_order===>" + str(data))
				_self = self.STV[coin]
				side = row["side"]
				# ord_id = row["orderid"]
				if row["status"] == 'filled':
					tag = row["clientid"][0:3]
					price = row["price"]
					size = row['size']

					self.logger.info('tag is :%s' % tag)
					if tag == 'acm':
						if side == 'buy':
							_self.buy_timestamp = int(time.time())

							_self.continuous_buy += 1
							_self.order_cnt += 1
							_self.invest_asset += size * price
							fee = size * _self.fee

							_self.pos += size - fee
							_self.avg_price = _self.invest_asset / _self.order_cnt

							self.logger.info("buy avg_price ===> " + str(_self.avg_price))
							self.save_order({"coin": coin,
									 "time": utility.get_now_datetime(),
									 "type": "buy",
									 "price": price,
									 "size": size,
									 "fee": fee,
									 "pnl": 0})
							# self.send_ding_msg({"coin": coin, "type": "buy", "price": price, "vol": size})
						else:
							_self.continuous_buy = 0
							_self._max_price = 0

							_self.order_cnt -= 1
							has_sell_asset = price * size
							_self.invest_asset -= has_sell_asset
							fee = has_sell_asset * _self.fee

							_self.pos -= size
							_self.avg_price = _self.invest_asset / _self.order_cnt
							self.logger.info("sell avg_price ===> " + str(_self.avg_price))
							pnl = (price - _self.avg_price) * size - fee
							self.save_order({"coin": coin,
									 "time": utility.get_now_datetime(),
									 "type": "sell",
									 "price": price,
									 "size": size,
									 "fee": fee,
									 "pnl": pnl})
							# self.send_ding_msg({"coin": coin, "type": "sell", "price": price, "vol": size, "pnl": pnl})
				elif row["status"] == 'live':
					pass

	def on_position(self, data):
		# self.logger.info("on_position===>" + str(data))
		pass

	def on_account(self, data):
		# self.logger.info("on_account===>" + str(data))
		for d in data:
			if d["coin"] == 'USDT':
				self.usdt_available = d["available"]
			else:
				if d["coin"] + "-USDT" in self.STV:
					_self = self.STV[d["coin"] + "-USDT"]
					_self._available = d["available"]

	def on_cancel_order(self, data, patch=None):
		pass
		# if patch is not None and len(patch) > 0:
		# 	_self = self.STV[patch.split('_')[0]]

	def calc_pnl(self, close_price, open_price):
		return (close_price - open_price) / open_price

	def gen_client_orderid(self, coin, tag):
		return "%s%s%d%d" % (tag, coin.replace('-', ''), int(time.time()), utility.get_random())


def order_success(data):
	return data['data']['data'][0]['sCode'] == "0"
