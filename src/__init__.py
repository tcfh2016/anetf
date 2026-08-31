# -*- coding:utf-8 -*-
"""src —— ETF 估值分析与报告的主包。

分层结构：
- models：数据模型（dataclass）
- constants / config：常量与配置
- db：Repository 层，封装 SQLite 访问
- datasources：外部数据源适配（韭圈儿/中证/国证/Sina 等）
- services：业务编排（估值更新、报告生成）
- notifiers / renderers：通知与渲染（邮件/HTML）
"""
