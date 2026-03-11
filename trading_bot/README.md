\# Bybit V5 Quantitative Trading Bot (BOTH Strategy)



Bybit V5 API를 기반으로 동작하는 암호화폐 선물 숏(Short) 전용 자동 매매 봇입니다. 

급등락이 심한 알트코인 시장에서 발생할 수 있는 슬리피지와 휩쏘(Whipsaw)에 대응하기 위해, 철저한 손익비 계산과 유동성 필터링을 거친 후 지정가 매매를 수행하도록 설계되었습니다.



\## 주요 기능 (Core Features)



\* \*\*Risk/Reward Filtering\*\*: 진입 전 타점의 손익비를 계산하여, R/R 비율이 1:1.5 이하인 비효율적인 타점을 사전 차단합니다.

\* \*\*Liquidity Check (Anti-Slippage)\*\*: 24시간 거래대금(10M USDT)을 검사하여 호가창이 비어있는 소형 알트코인의 강제 청산 슬리피지를 방지합니다.

\* \*\*Dynamic MTF Targeting\*\*: 1시간봉 및 4시간봉 볼린저 밴드 중앙선을 실시간으로 추적하여 1차, 2차 목표가(TP1, TP2) 지정가 주문을 동적으로 갱신합니다.

\* \*\*Profit-Preserving Stop Loss\*\*: 1차 목표가 달성 시, 잔여 물량의 손절선을 수익 구간(진입가와 1차 목표가의 중앙값)으로 상향 조정하여 확정 수익을 보존합니다.

\* \*\*Accurate Ledger Sync\*\*: Bybit 서버의 Closed PnL 데이터를 실시간으로 가져와 수수료가 포함된 정확한 회계 장부(CSV)를 유지합니다.



\## 시스템 요구사항 (Requirements)



\* Python 3.8+

\* `ccxt` (Bybit V5 API 연동)

\* `pandas` (데이터 프레임 및 장부 관리)

\* `ta` (Technical Analysis 지표 계산)




