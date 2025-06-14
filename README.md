# anetf

查询ETF的估值。

- 第一步，获取ETF列表（隔段时间手动更新）。
- 第二步，更新估值信息（每天）。
- 第三步，发送邮件（每天）。


## 更新估值信息：`etf.py`

从韭圈儿里面获取ETF列表，并且查找到ETF对应的指数，然后存储到`tmp/index.csv`。


## 更新估值信息：`pe.py`

首先，读取`tmp/index.csv`，这个是上一步通过ETF列表生成的对应的指数信息。

其次，遍历每个指数，并且更新指数对应的db文件，那里存储历史的估值信息。更新过程会先后查询三个数据源：

1. 查询韭圈儿的估值信息
2. 查询中证官网的估值信息
3. 查询国证网站的估值信息

最后，是将估值信息进行排序，并且输出到`etf_overseas_sorted.csv`、`etf_diversify_sorted.csv`和`etf_others_sorted.csv`。


## 发送邮件：`main.py`

邮件参照的源数据是前面生成的`etf_overseas_sorted.csv`、`etf_diversify_sorted.csv`和`etf_others_sorted.csv`。


参考：

- [ETF基金实时行情-东财](https://akshare.akfamily.xyz/data/fund/fund_public.html#etf)
- [基金持仓](https://akshare.akfamily.xyz/data/fund/fund_public.html#id40)