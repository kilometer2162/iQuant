# -*- coding: utf-8 -*-
import traceback
from threading import Lock

from strategy.template import StrategyTemplate, StgVariable
from trader.utility import cal_order_price, get_now_datetime
from trader.object import StrategySetting


# 默认信号标记
SIGNAL_INIT = -1
SYMBOL_FACE_VALUE_COIN_BASE = {'BTC': 0.01, 'EOS': 10, 'ETH': 0.1, 'LTC': 1, 'XRP': 100}
SYMBOL_FACE_VALUE_USDT_BASE = {'BTC': 100, 'EOS': 10, 'ETH': 10, 'LTC': 10, 'XRP': 10}

'''
币本位合约开仓手续费=面值*开仓张数/开仓价格*手续费费率
币本位合约平仓手续费=面值*平仓张数/平仓价格*手续费费率

追加资金导致份额变动
最新净值 = 最新资金 / 总份额
最新份额 = 总资金 / 最新净值
变动份额 = 变动资金 / 最新净值
'''


class bolling(StrategyTemplate):
	def __init__(self, setting: StrategySetting, parameter: dict):
		super(bolling, self).__init__(setting, parameter)

		# 多空仓位
		self.l_pos = 0
		self.s_pos = 0

		self.l_canbuy = False
		self.s_canbuy = False

		# 开多、空信号
		self.c_signal_long = SIGNAL_INIT
		self.signal_long_lock = Lock()
		self.c_signal_short = SIGNAL_INIT
		self.signal_short_lock = Lock()

		# 总资金
		self.c_total_cash = float(parameter['total_cash'])
		# 追加/赎回资金，将变动金额传入，以修改份额重新计算净值
		if 'change_cash' in parameter and float(parameter['change_cash']) > 0:
			self.c_total_cash = self.c_total_cash + float(parameter['change_cash'])
		# 总份额
		self.c_total_share = self.c_total_cash
		# 当前可用资金
		self.avail_cash = 0

		# 帐户净值
		self.c_net_value = 1
		# 帐户净值最小值
		self.c_net_value_min = 1

		# 账户持仓盈亏最大值
		self.c_max_profit = 0
		# 账户持仓盈亏
		self.c_profit = 0
		# 账户持仓盈亏最小值
		self.c_min_profit = 0

		# 是否开空
		self.c_short_open = parameter['short_open']

		for c in self.g_parameter["instrument"]:
			e = self.g_parameter["instrument"][c]

			self.size = e['size']
			self.patch_size = 0
			self.fee = e['fee']

			self.n = int(e['n'])
			self.g_kline_min_size = int(self.n*1.5)
			self.m = float(e['m'])
			self.bias_pct = float(e['bias_pct'])

			self.coin = c
			self.enable_cache_switch(True)

			self.g_notify_active = True
			self.do_notify(c)
		self.this = self

	def on_bar(self, data):
		coin, _, price, __ = super().on_bar(data)
		this = self.g_indicator_factory[coin][self.g_cycle]
		if this.is_new_bar:
			self.logger.info(f"is_new_bar:{this.is_new_bar}")
			self.logger.info(f"close:{this.close_array}")
			process = self.is_instrument_on_me(coin, self.coin)
			self.logger.info(f" ==============> process: {process}")
			if process:

				upper, median, lower = this.boll(self.n, self.m)
				close = this.close_array[-1]
				prev_close = this.close_array[-2]

				bias = close / median.iloc[-1,0] - 1
				self.logger.info(f"close:{close} upper:{upper.iloc[-1,0]} median:{median.iloc[-1,0]} lower:{lower.iloc[-1,0]} bias:{bias}")

				if self.l_pos == 0:
					self.logger.info(f"pre_upper:{upper.iloc[-2, 0]}")
					if close > upper.iloc[-1,0] and prev_close <= upper.iloc[-2, 0]:
						self.l_canbuy = True
					if self.l_canbuy and bias < self.bias_pct:
						self.l_canbuy = False
						with self.signal_long_lock:
							self.logger.info(f" signal_long ===> 1 close:{close} upper:{upper.iloc[-1,0]} bias:{bias}")
							self.c_signal_long = 1
				elif self.l_pos > 0 and close < median.iloc[-1,0] and prev_close >= median.iloc[-2, 0]:
					with self.signal_long_lock:
						self.logger.info(f" signal_long ===> 0 close:{close} median:{median.iloc[-1,0]}")
						self.c_signal_long = 0

				if self.c_short_open:
					if self.s_pos == 0:
						self.logger.info(f"pre_low:{lower.iloc[-2, 0]}")
						if close < lower.iloc[-1,0] and prev_close >= lower.iloc[-2, 0]:
							self.s_canbuy = True
						if self.s_canbuy and bias > self.bias_pct * -1:
							self.s_canbuy = False
							with self.signal_short_lock:
								self.logger.info(f" signal_short ===> 1 close:{close} lower:{lower.iloc[-1, 0]} bias:{bias}")
								self.c_signal_short = 1
					elif self.s_pos > 0 :
						self.logger.info(f"median: {median}")
						self.logger.info(f"close:{close} median:{median.iloc[-1, 0]} prev_close:{prev_close} pre_median:{median.iloc[-2, 0]} ")
						if close > median.iloc[-1,0] and prev_close <= median.iloc[-2, 0]:
							with self.signal_short_lock:
								self.logger.info(f" signal_short ===> 0 close:{close} median:{median.iloc[-1, 0]} bias:{bias}")
								self.c_signal_short = 0

	def on_depth(self, data):
		args = None
		try:
			coin = data.symbol
			process = self.is_instrument_on_me(coin, self.coin)
			if process:
				size = self.size if self.patch_size == 0 else self.patch_size
				# 做多开仓
				if self.c_signal_long == 1:
					args = self.make_order(coin, "buy", "long", cal_order_price(data.bid_price_1, 1), size)
				# 做多平仓
				elif self.c_signal_long == 0:
					args = self.make_order(coin, "sell", "long", cal_order_price(data.ask_price_1, 3), size)
				if self.c_short_open:
					# 做空开仓
					if self.c_signal_short == 1:
						args = self.make_order(coin, "sell", "short", cal_order_price(data.ask_price_1, 2), size)
					# 做空平仓
					elif self.c_signal_short == 0:
						args = self.make_order(coin, "buy", "short", cal_order_price(data.bid_price_1, 4), size)
				if args:
					args.update({"patch": coin})
					self.send_order(args)
		except:
			self.logger.error("on_depth_data error,traceback=\n%s" % traceback.format_exc())

	def on_order(self, data):
		self.logger.info("on_order ===>" + str(data))
		for row in data:
			coin = row["symbol"]
			process = self.is_instrument_on_me(coin, self.coin)
			if process:
				self.logger.info("on_order ===>" + str(data))
				side = row["side"]
				price = row['price']
				size = row['size']
				ord_id = row["orderid"]
				posSide = row['posside']

				p = {"i":coin}
				# 成交
				if row["status"] == 'filled':
					if size == self.size:
						# 全部成交
						pass
					else:
						ps = self.size - size
						if posSide == 'long':
							p.update({"w": "sl", "s": ps, "v": 1 if side == 'buy' else 0})
						else:
							p.update({"w": "ss", "s": ps, "v": 0 if side == 'buy' else 1})
						# 撤单
						self.cancel_order({"instId": coin, "ordId": ord_id, "patch": p})

						self.logger.info("on_order set patch_size = %d " % self.patch_size)
					self.logger.info(f"filled order ===> side:{side} posSide:{posSide} price:{price} size:{size}")
					order = {"coin": coin,
						 "time": get_now_datetime(),
						 "type": side,
						 "price": price,
						 "size": size,
						 "fee": row['fee']}
					self.save_order(order)

					if side == 'sell':
						# 计算盈亏
						self.c_profit = self.avail_cash - self.c_total_cash
						if self.c_profit > self.c_max_profit:
							self.c_max_profit = self.c_profit
						elif self.c_profit < self.c_min_profit:
							self.c_min_profit = self.c_profit

						order.update({'net_value': self.c_net_value, 'profit': self.c_profit})
						self.save_curve(order)
				# self.send_ding_msg(msg)

				elif row["status"] == 'live':
					pass
					# if posSide == 'long':
					# 	p.update({"w": "sl","v": 1 if side == 'buy' else 0})
					# else:
					# 	p.update({"w": "ss","v": 0 if side == 'buy' else 1})
					# # 撤单
					# self.cancel_order({"instId": coin, "ordId": ord_id, "patch": p})

				elif row["status"] == 'canceled':
					pass

	def cancel_order(self, args: dict):
		self.logger.info("cancel_order ===> %s" % str(args))
		super().cancel_order(args)

	def on_cancel_order(self, data, patch=None):
		if patch is not None and len(patch) > 0:
			has_canceled = '514' == data["data"]['data'][0]["sCode"][0:3]
			coin = patch["i"]
			process = self.is_instrument_on_me(coin, self.coin)
			if process:
				if order_success(data) or has_canceled:
					if 's' in patch:
						self.patch_size = patch['s']
					if patch['w'] == "sl":
						with self.signal_long_lock:
							self.c_signal_long = patch['v']
					elif patch['w'] == "ss":
						with self.signal_short_lock:
							self.c_signal_short = patch['v']

	def send_order(self, args: dict):
		self.logger.info("send_order ===> %s" % str(args))
		super().send_order(args)

		process = self.is_instrument_on_me(args['patch'], self.coin)
		if process:
			# 下单命令发起后屏蔽下单信号
			with self.signal_long_lock:
				self.c_signal_long = SIGNAL_INIT
			if self.c_short_open:
				with self.signal_short_lock:
					self.c_signal_short = SIGNAL_INIT

	def on_send_order(self, data, patch=None):
		self.logger.info("bolling on_send_order data=> %s" % (str(data)))
		if 'patch' in data:
			process = self.is_instrument_on_me(data['patch'], self.coin)
			if process:
				if self.patch_size > 0:
					self.logger.info("on_send_order set patch_size = 0 ")
					self.patch_size = 0

	def on_position(self, data):
		# self.logger.info("on_position ===>" + str(data))
		for row in data:
			pos = int(row['size'])
			if row['posside'] == 'long':
				if pos != self.l_pos:
					self.l_pos = pos
					self.logger.info("on_position set l_pos=> %s" % (self.l_pos))
			else:
				if pos != self.s_pos:
					self.s_pos = int(row['size'])
					self.logger.info("on_position set s_pos=> %s" % (self.s_pos))

	def on_account(self, data):
		self.logger.info("on_account ===>" + str(data))
		for row in data:
			self.avail_cash = float(row['total'])
			self.c_net_value = self.avail_cash / self.c_total_share
			if self.c_net_value < self.c_net_value_min:
				self.c_net_value_min = self.c_net_value
		if not self.stg_inited:
			self.enable_cache_switch(True)
			self.stg_inited = True

	def after_strategy_cache(self):
		self.c_total_share = self.c_total_cash / self.c_net_value
		self.logger.info("after_strategy_cache ===> total_share is ", self.c_total_share)

	def make_order(self, instId, side, posSide, px, sz, ordType="limit"):
		return {"instId": instId,
			"side": side,
			"tdMode":"cross",
			"posSide": posSide,
			"px": px,
			"sz": sz,
			"ordType": ordType
			}


def order_success(data):
	return data['data']['data'][0]['sCode'] == "0"
