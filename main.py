import akshare as ak
import datetime as dt

# 获得ETF列表
fund_etf_spot_em_df = ak.fund_etf_spot_em()
fund_etf_spot_em_df.to_csv('fund_etf.csv')
print(fund_etf_spot_em_df)

# 使用`fund_portfolio_hold_em`获取单个ETF的持仓信息，基本都会失败
#for etf in fund_etf_spot_em_df['代码']:
#    try:
#        year = str(dt.date.today().year)        
#        fund_portfolio_hold_em_df = ak.fund_portfolio_hold_em(symbol=etf, date=year)
#        print(len(fund_portfolio_hold_em_df))
#    except Exception as e:
#        print('failed with: '+ str(e))

index_value_name_funddb_df = ak.index_value_name_funddb()
index_value_name_funddb_df.to_csv('index_value.csv')
print(index_value_name_funddb_df)

index_all_cni_df = ak.index_all_cni()
index_all_cni_df.to_csv('index_all.csv')
print(index_all_cni_df)

index_stock_info_df = ak.index_stock_info()
index_stock_info_df.to_csv('index_stock.csv')
print(index_stock_info_df)

# 根据单个ETF的持仓股，计算综合市盈率

# 计算ETF对应的市盈率百分位
# 1）需要创建存储结构，去保存每只股票的估值信息
# 2）设计存储结构