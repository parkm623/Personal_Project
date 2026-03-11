# Bybit V5 Quantitative Trading Bot

Bybit V5 API를 기반으로 동작하는 암호화폐 선물 숏(Short) 전용 자동 매매 봇입니다. 
급등락이 심한 알트코인 시장에서 발생할 수 있는 슬리피지와 휩쏘(Whipsaw)에 대응하기 위해, 철저한 손익비 계산과 유동성 필터링을 거친 후 지정가 매매를 수행하도록 설계되었습니다.

## 핵심 매매 전략 (Trading Strategy)

본 봇은 단기 급등한 알트코인의 역추세 하락을 노리는 **BOTH (Bollinger & Trend Reversal) 전략**을 사용합니다. 다중 타임프레임(MTF) 분석과 시장 심리 지표를 복합적으로 활용하여 고승률 타점만 선별합니다.

### 1. 진입 조건 (Entry Criteria)
포지션 진입(Short)은 아래의 기술적/심리적 조건이 모두 충족될 때 시장가로 실행됩니다.
* **과매수 상태 (4H):** 4시간봉 기준 종가가 볼린저 밴드 상단(Upper Band)을 돌파하고, RSI가 70 이상일 것.
* **단기 모멘텀 둔화 (15m):** 15분봉 기준 종가가 7일 단기 이동평균선(MA7) 아래로 이탈하고, RSI가 70 미만으로 꺾일 것.
* **시장 심리 과열 (1H):** 롱/숏 비율(Long/Short Ratio)이 1.5 이상으로 대중의 롱(매수) 쏠림이 심하며, 미결제약정(Open Interest)이 감소 추세일 것.

### 2. 청산 조건 (Exit Criteria)
* **1차 목표가 (TP1):** 1시간봉 볼린저 밴드 중앙선 도달 시 전체 물량의 50% 지정가 익절.
* **2차 목표가 (TP2):** 4시간봉 볼린저 밴드 중앙선 도달 시 잔여 물량 지정가 익절.
* **수익 보존 방어막 (Trailing Stop):** TP1 체결 시 잔여 물량의 손절가(SL)를 '진입가와 TP1의 중앙값'으로 강제 하향 조정하여 수익 마감을 목표.
  
## 주요 기능 (Core Features)

* **Risk/Reward Filtering**: 진입 전 타점의 손익비를 계산하여, R/R 비율이 1.5배를 초과하는 비효율적인 타점을 사전 차단합니다.
* **Liquidity Check (Anti-Slippage)**: 24시간 거래대금(10M USDT)을 검사하여 호가창이 비어있는 소형 알트코인의 강제 청산 슬리피지를 방지합니다.
* **Dynamic MTF Targeting**: 1시간봉 및 4시간봉 볼린저 밴드 중앙선을 실시간으로 추적하여 1차, 2차 목표가(TP1, TP2) 지정가 주문을 동적으로 갱신합니다.
* **Profit-Preserving Stop Loss**: 1차 목표가 달성 시, 잔여 물량의 손절선을 수익 구간(진입가와 1차 목표가의 50% 지점)으로 상향 조정하여 확정 수익을 보존합니다.
* **Accurate Ledger Sync**: Bybit 서버의 Closed PnL 데이터를 실시간으로 가져와 수수료가 포함된 정확한 회계 장부(CSV)를 유지합니다.

## 시스템 요구사항 (Requirements)

* Python 3.8+
* `ccxt` (Bybit V5 API 연동)
* `pandas` (데이터 프레임 및 장부 관리)
* `ta` (Technical Analysis 지표 계산)

## 데이터 및 로그 관리 (Data Management)

본 시스템은 구글 클라우드 환경에서 다음 파일들을 통해 상태와 데이터를 관리합니다.

* `active_trades_live.json`: 현재 유지 중인 포지션의 상태 및 지정가 주문 ID 정보 저장
* `trade_history_live.csv`: 바이비트 공식 서버와 동기화된 전체 매매 이력 및 순수익(PnL) 데이터
* `bot_trading.log`: 실시간 타점 분석, 진입 승인/거절 사유, 시스템 에러 로그 기록
