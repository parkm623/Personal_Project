import ccxt
import pandas as pd
import time
import warnings
import sys
import os
import json
import logging
from datetime import datetime
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands
from ta.trend import SMAIndicator

warnings.filterwarnings("ignore")

# ==========================================
# [Configuration] 봇 설정 및 파라미터
# ==========================================
API_KEY = ''
SECRET_KEY = ''

TRADE_MARGIN_USDT = 10     # 포지션 진입 시 사용할 증거금 (USDT)
LEVERAGE = 5               # 레버리지 배수
MAX_RISK_PERCENT = 40      # 허용 가능한 최대 손절폭 (%)

MIN_RISE_PERCENT = 5       # 24시간 대비 최소 상승률 조건 (%)
SL_BUFFER = 0.015          # 손절선 여유 버퍼 (1.5%)
COOLDOWN_SEC = 120         # 동일 종목 재진입 방지 쿨다운 (초)

STATE_FILE = "active_trades_live.json"   # 실시간 포지션 상태 저장 파일
HISTORY_FILE = "trade_history_live.csv"  # 공식 PnL 장부 파일

SCAN_INTERVAL = 300        # 신규 종목 스캔 주기 (초)
FAST_TICK = 10             # 포지션 감시 및 호가 갱신 주기 (초)

cooldowns = {} 

# ==========================================
# [Logging] 로깅 시스템 초기화
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("bot_trading.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# ==========================================
# [Exchange] Bybit 거래소 객체 초기화
# ==========================================
exchange = ccxt.bybit({
    'apiKey': API_KEY,
    'secret': SECRET_KEY,
    'enableRateLimit': True,
    'options': {'defaultType': 'linear', 'adjustForTimeDifference': True}
})

# ==========================================
# [System] 상태 파일 로드 및 저장
# ==========================================
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except: pass
    return {}

def save_state(active_trades):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(active_trades, f, indent=4)
    except: pass

active_trades = load_state()

def check_api_connection():
    try:
        exchange.fetch_time()
        exchange.load_markets() 
        logging.info("✅ [Ver.6] 동적 지정가 매매 + MTF(Multi-Timeframe) 타겟팅 가동 시작")
        logging.info("-" * 60)
    except Exception as e: 
        logging.error(f"API 연결 에러: {e}")
        sys.exit()

# ==========================================
# [Data] OHLCV 데이터 수집
# ==========================================
def get_ohlcv(symbol, tf, limit=50):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=limit)
        return pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    except: return None

# ==========================================
# [Ledger] Bybit 공식 Closed PnL 동기화
# ==========================================
def sync_official_ledger():
    try:
        logging.info("🔄 [Ledger Sync] Bybit 서버에서 공식 손익 내역을 동기화합니다.")
        response = exchange.privateGetV5PositionClosedPnl({'category': 'linear', 'limit': 100})
        trades = response.get('result', {}).get('list', [])
        
        if not trades: return

        history = []
        for t in trades:
            dt = datetime.fromtimestamp(int(t['updatedTime']) / 1000).strftime('%Y-%m-%d %H:%M:%S')
            history.append({
                "청산시간": dt,
                "종목": t['symbol'],
                "포지션": "SHORT" if t['side'] == "Buy" else "LONG",
                "평균진입가": round(float(t['avgEntryPrice']), 6),
                "평균청산가": round(float(t['avgExitPrice']), 6),
                "청산수량": t['closedSize'],
                "순수익(USDT)": round(float(t['closedPnl']), 4), 
            })

        df = pd.DataFrame(history)
        df.to_csv(HISTORY_FILE, index=False, encoding='utf-8-sig')
        logging.info(f"✅ 장부({HISTORY_FILE}) 공식 데이터 갱신 완료")
    except Exception as e:
        logging.error(f"장부 동기화 실패: {e}")

# ==========================================
# [Logic] 동적 지정가 타겟 갱신 (Dynamic TP)
# ==========================================
def update_dynamic_tp():
    """1시간봉 및 4시간봉 볼린저 밴드 중앙선을 추적하여 TP1, TP2 주문을 갱신합니다."""
    if not active_trades: return
    updated = False
    for sym, trade in active_trades.items():
        try:
            df_mid = get_ohlcv(sym, '1h', limit=25)
            df_big = get_ohlcv(sym, '4h', limit=25)
            
            if df_mid is not None and df_big is not None:
                bb_mid = BollingerBands(close=df_mid['close'], window=20, window_dev=2)
                new_bbm_1h = bb_mid.bollinger_mavg().iloc[-1]
                
                bb_big = BollingerBands(close=df_big['close'], window=20, window_dev=2)
                new_bbm_4h = bb_big.bollinger_mavg().iloc[-1]
                
                # 4H 타겟이 1H보다 높을 경우 1H 타겟의 95% 지점으로 조정 (역추세 보정)
                if new_bbm_4h >= new_bbm_1h:
                    new_bbm_4h = new_bbm_1h * 0.95
                
                # 목표가가 변경되었을 경우 기존 주문 취소 및 재등록
                if round(trade['tp1'], 4) != round(new_bbm_1h, 4) or round(trade['tp2'], 4) != round(new_bbm_4h, 4):
                    trade['tp1'] = new_bbm_1h
                    trade['tp2'] = new_bbm_4h
                    updated = True
                    
                    if not trade.get('tp1_hit', False):
                        if trade.get('tp1_id'):
                            try: exchange.cancel_order(trade['tp1_id'], sym)
                            except: pass
                        
                        tp1_qty = trade.get('tp1_qty', trade['qty'] / 2.0)
                        tp1_price = float(exchange.price_to_precision(sym, trade['tp1']))
                        try:
                            order = exchange.create_limit_buy_order(sym, tp1_qty, tp1_price, params={'reduceOnly': True})
                            trade['tp1_id'] = order['id']
                        except: pass
                    else:
                        if trade.get('tp2_id'):
                            try: exchange.cancel_order(trade['tp2_id'], sym)
                            except: pass
                        
                        tp2_price = float(exchange.price_to_precision(sym, trade['tp2']))
                        try:
                            order = exchange.create_limit_buy_order(sym, trade['qty'], tp2_price, params={'reduceOnly': True})
                            trade['tp2_id'] = order['id']
                        except: pass
        except: pass
            
    if updated: save_state(active_trades)

# ==========================================
# [Logic] 실시간 포지션 및 손절/익절 감시
# ==========================================
def manage_active_trades(print_status=False):
    """현재 보유 중인 포지션의 체결 여부 및 손절 도달 여부를 감시합니다."""
    if not active_trades: return
    if print_status: print(f"\n[실시간 포지션 감시 중] ----------------------")
    
    remove_list = []
    state_changed = False 
    ledger_needs_update = False
    
    actual_positions = {}
    try:
        pos_data = exchange.fetch_positions()
        for p in pos_data:
            actual_positions[p['symbol']] = float(p.get('contracts', 0))
    except: return

    for sym, trade in list(active_trades.items()):
        try:
            cur = exchange.fetch_ticker(sym)['last']
            roi = ((trade['entry'] - cur) / trade['entry']) * 100 * LEVERAGE 
            
            actual_qty = actual_positions.get(sym, 0.0)
            expected_qty = trade['qty']
            
            # 수량 감소 감지 (부분 익절 또는 전량 익절 발생)
            if actual_qty < expected_qty:
                if actual_qty == 0:
                    logging.info(f"🎉 [{sym}] 포지션 전량 체결 완료 (종료)")
                    remove_list.append(sym)
                    cooldowns[sym] = time.time()
                else:
                    logging.info(f"🎉 [{sym}] 부분 체결(TP1) 감지. 잔여 수량: {actual_qty}")
                    trade['qty'] = actual_qty
                    trade['tp1_hit'] = True
                    
                    # 수익 보존 방어막 (Trailing Stop): 손절선을 진입가와 TP1의 중앙값으로 상향
                    trade['sl'] = (trade['entry'] + trade['tp1']) / 2.0 
                    
                    tp2_price = float(exchange.price_to_precision(sym, trade['tp2']))
                    try:
                        order2 = exchange.create_limit_buy_order(sym, actual_qty, tp2_price, params={'reduceOnly': True})
                        trade['tp2_id'] = order2['id']
                    except: pass
                
                ledger_needs_update = True
                state_changed = True
                continue 

            # 손절선 돌파 시 시장가 청산
            if cur >= trade['sl']:
                res_msg = "본절(수익보존) 구역 이탈" if trade.get('tp1_hit') else "손절(SL) 라인 도달"
                logging.info(f"⚡ [{sym}] {res_msg} - 시장가 청산 실행")
                try: exchange.create_market_buy_order(sym, actual_qty, params={'reduceOnly': True})
                except: pass
                continue

            if print_status:
                phase_msg = "[TP2 대기 중]" if trade.get('tp1_hit') else "[TP1 대기 중]"
                print(f" {sym:<12} | 진입가:{trade['entry']:.5f} | 현재가:{cur:.5f} | ROI: {roi:+.2f}% {phase_msg}")

        except Exception as e: 
            logging.error(f"[{sym}] 모니터링 에러: {e}")
    
    if remove_list:
        for s in remove_list: del active_trades[s]
    if state_changed: save_state(active_trades)
    
    if ledger_needs_update:
        sync_official_ledger()
        
    if print_status: print("-" * 60)

# ==========================================
# [Logic] 신규 타점 탐색 및 필터링
# ==========================================
def analyze_symbol(symbol):
    """지표 및 손익비를 분석하여 진입 여부를 결정합니다."""
    if symbol in active_trades: return None
    if symbol in cooldowns and (time.time() - cooldowns[symbol]) < COOLDOWN_SEC: return None 
    
    df_big = get_ohlcv(symbol, '4h')
    df_mid = get_ohlcv(symbol, '1h')
    df_trig = get_ohlcv(symbol, '15m')
    if df_big is None or df_mid is None or df_trig is None: return None

    # 지표 계산
    rsi_big = RSIIndicator(close=df_big['close'], window=12)
    df_big['rsi'] = rsi_big.rsi()
    bb_big = BollingerBands(close=df_big['close'], window=20, window_dev=2)
    df_big['bbu'] = bb_big.bollinger_hband()
    df_big['bbm'] = bb_big.bollinger_mavg() 

    bb_mid = BollingerBands(close=df_mid['close'], window=20, window_dev=2)
    df_mid['bbm'] = bb_mid.bollinger_mavg()
    last_mid = df_mid.iloc[-1]

    rsi_trig = RSIIndicator(close=df_trig['close'], window=12)
    df_trig['rsi'] = rsi_trig.rsi()
    sma_trig = SMAIndicator(close=df_trig['close'], window=7)
    df_trig['ma7'] = sma_trig.sma_indicator()

    last_big = df_big.iloc[-1]
    last_trig = df_trig.iloc[-1]

    # 조건 1: 4H 기준 과매수 상태 (Upper Band 상향 돌파 및 RSI > 70)
    s1_pass = (last_big['close'] > last_big['bbu']) and (last_big['rsi'] > 70)
    if not s1_pass: return None

    # 조건 3: 15m 기준 하락 다이버전스/모멘텀 감소 확인
    s3_cond1 = last_trig['close'] < last_trig['ma7']
    s3_cond2 = last_trig['rsi'] < 70
    s3_pass = s3_cond1 and s3_cond2
    if not s3_pass: return None

    # 조건 2: 롱/숏 비율 및 미결제약정(OI) 확인
    try:
        raw_sym = symbol.replace('/', '').split(':')
        lsr_res = exchange.publicGetV5MarketAccountRatio({'category':'linear','symbol':raw_sym,'period':'1h','limit':1})
        lsr_val = float(lsr_res['result']['list']['buyRatio']) / float(lsr_res['result']['list']['sellRatio']) if lsr_res['result']['list'] else 0
        oi_res = exchange.publicGetV5MarketOpenInterest({'category':'linear','symbol':raw_sym,'intervalTime':'1h'})
        oi_down = float(oi_res['result']['list']['openInterest']) < float(oi_res['result']['list']['openInterest'])
        s2_pass = (lsr_val >= 1.5) and oi_down
    except: s2_pass = False

    res = {'symbol': symbol, 'trade': None}

    if s1_pass and s2_pass and s3_pass:
        entry = last_trig['close']
        recent_high = df_big['high'].tail(3).max()
        sl = recent_high * (1 + SL_BUFFER)
        
        tp1 = last_mid['bbm']
        tp2 = last_big['bbm']
        if tp2 >= tp1: tp2 = tp1 * 0.95

        # 손익비 (Risk/Reward) 계산 및 필터링
        risk = sl - entry        
        reward = entry - tp1      
        ratio = (risk / reward) if reward > 0 else 999.0
        
        if ratio > 1.5:  
            logging.info(f"🚫 [{symbol}] 진입 포기 (손익비 불량): Risk가 Reward의 {ratio:.2f}배")
            cooldowns[symbol] = time.time()
            return res
        
        # 최대 리스크 퍼센트 초과 확인
        risk_pct = ((sl - entry) / entry) * 100 * LEVERAGE
        if risk_pct > MAX_RISK_PERCENT:
            logging.info(f"🚫 [{symbol}] 진입 포기 (리스크 초과): 손절폭 {risk_pct:.1f}%")
            cooldowns[symbol] = time.time()
            return res
        
        try:
            raw_qty = (TRADE_MARGIN_USDT * LEVERAGE) / entry
            formatted_qty = float(exchange.amount_to_precision(symbol, raw_qty))
        except: return res 
        
        res['trade'] = {'entry': entry, 'sl': sl, 'tp1': tp1, 'tp2': tp2, 'qty': formatted_qty, 'tp1_hit': False}
        logging.info(f"🎯 [{symbol}] 조건 부합 및 진입 승인 (R/R Ratio: {ratio:.2f})")
        
    return res

# ==========================================
# [Main] 메인 루프 실행
# ==========================================
def main():
    check_api_connection()
    while True:
        update_dynamic_tp() 
        manage_active_trades(print_status=True)
        try:
            tickers = exchange.fetch_tickers()
            symbols = [s for s, t in tickers.items() if 'USDT' in s and t.get('percentage', 0) >= MIN_RISE_PERCENT]
        except: symbols = []

        for symbol in symbols:
            try:
                r = analyze_symbol(symbol)
                if not r or not r['trade']: continue 
                
                t = r['trade']
                logging.info(f"🚀 [{symbol}] 타점 포착. 시장가 진입 시도.")
                
                try:
                    try: exchange.set_leverage(LEVERAGE, symbol)
                    except: pass
                    
                    # 숏 진입
                    exchange.create_market_sell_order(symbol, t['qty'])
                    logging.info(f"✅ [{symbol}] 시장가 숏 진입 완료")
                    
                    # 1차 TP 주문 등록
                    tp1_qty = float(exchange.amount_to_precision(symbol, t['qty'] / 2.0))
                    if tp1_qty <= 0: tp1_qty = t['qty']
                    tp1_price = float(exchange.price_to_precision(symbol, t['tp1']))
                    
                    try:
                        tp1_order = exchange.create_limit_buy_order(symbol, tp1_qty, tp1_price, params={'reduceOnly': True})
                        t['tp1_id'] = tp1_order['id']
                        t['tp1_qty'] = tp1_qty
                        logging.info(f"✅ [{symbol}] TP1 지정가 주문 등록 완료")
                    except Exception as e:
                        logging.error(f"[{symbol}] TP1 설정 에러: {e}")

                    # 상태 저장
                    t['current_price'] = t['entry']
                    t['roi_percent'] = 0.0
                    active_trades[symbol] = t
                    save_state(active_trades) 
                    cooldowns[symbol] = time.time()
                except Exception as e:
                    logging.error(f"[{symbol}] 진입 체결 에러: {e}")
                    
            except Exception as e: continue
        
        # 포지션 감시 모드 전환 (10초 단위 반복 대기)
        loops = SCAN_INTERVAL // FAST_TICK
        for i in range(loops):
            manage_active_trades(print_status=False) 
            time.sleep(FAST_TICK)

if __name__ == "__main__":
    main()