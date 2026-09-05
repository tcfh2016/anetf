# -*- coding:utf-8 -*-
"""Flask 应用工厂与路由。

页面（服务端渲染 Jinja2）：
  GET  /                      仪表盘（统计卡片 + 热力图 + 推荐榜）
  GET  /etfs                  ETF 列表（搜索/分类筛选/分页）
  GET  /index/<index_id>      指数详情（估值通道图 + 点位走势 + 跟踪 ETF）
  GET  /watchlist             关注列表

JSON API（供页面 JS fetch）：
  GET    /api/overview
  GET    /api/etfs?q=&category=&page=
  GET    /api/index/<index_id>
  GET    /api/watchlist
  POST   /api/watchlist            {code, note?, alert_low?, alert_high?}
  PATCH  /api/watchlist/<code>     {note?, alert_low?, alert_high?}
  DELETE /api/watchlist/<code>

约束：纯读 anetf.db，不发网络请求；所有接口异常返回 {"error": ...}，不静默吞错。
"""

import logging
import math

from flask import Flask, jsonify, render_template, request

from src.constants import CATEGORIES
from src.db.connection import Database
from src.web.service import WebSnapshotService

logger = logging.getLogger(__name__)

PAGE_SIZE = 50


def create_app(db: Database = None) -> Flask:
    app = Flask(__name__)
    app.config['JSON_AS_ASCII'] = False
    app.json.ensure_ascii = False   # Flask 3：JSON 响应中文不转义

    # 单例服务：快照按库内最新日期缓存（sqlite threadsafety=3，连接可跨线程共享）
    svc = WebSnapshotService(db or Database())

    # ---------- 页面 ----------
    @app.route('/')
    def dashboard():
        return render_template('dashboard.html', data=svc.overview(),
                               categories=CATEGORIES)

    @app.route('/etfs')
    def etfs():
        q = request.args.get('q', '').strip()
        category = request.args.get('category', '').strip()
        try:
            page = max(1, int(request.args.get('page', 1)))
        except ValueError:
            page = 1

        rows = svc.search_etfs(q, category)
        total = len(rows)
        pages = max(1, math.ceil(total / PAGE_SIZE))
        page = min(page, pages)
        subset = rows[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
        return render_template('etfs.html', rows=subset, q=q,
                               category=category, page=page, pages=pages,
                               total=total, categories=CATEGORIES)

    @app.route('/index/<index_id>')
    def index_detail(index_id):
        detail = svc.index_detail(index_id)
        if detail is None:
            return render_template('index_detail.html', detail=None,
                                   index_id=index_id), 404
        return render_template('index_detail.html', detail=detail)

    @app.route('/watchlist')
    def watchlist():
        return render_template('watchlist.html', rows=svc.watchlist_view())

    # ---------- JSON API ----------
    @app.route('/api/overview')
    def api_overview():
        try:
            return jsonify(svc.overview())
        except Exception as e:
            logger.exception('api_overview failed')
            return jsonify({'error': str(e)}), 500

    @app.route('/api/etfs')
    def api_etfs():
        try:
            q = request.args.get('q', '').strip()
            category = request.args.get('category', '').strip()
            try:
                page = max(1, int(request.args.get('page', 1)))
            except ValueError:
                page = 1
            rows = svc.search_etfs(q, category)
            total = len(rows)
            pages = max(1, math.ceil(total / PAGE_SIZE))
            page = min(page, pages)
            return jsonify({
                'total': total, 'page': page, 'pages': pages,
                'rows': rows[(page - 1) * PAGE_SIZE: page * PAGE_SIZE],
            })
        except Exception as e:
            logger.exception('api_etfs failed')
            return jsonify({'error': str(e)}), 500

    @app.route('/api/index/<index_id>')
    def api_index(index_id):
        try:
            detail = svc.index_detail(index_id)
            if detail is None:
                return jsonify({'error': 'index not found: %s' % index_id}), 404
            return jsonify(detail)
        except Exception as e:
            logger.exception('api_index failed')
            return jsonify({'error': str(e)}), 500

    @app.route('/api/watchlist', methods=['GET'])
    def api_watchlist():
        return jsonify(svc.watchlist_view())

    @app.route('/api/watchlist', methods=['POST'])
    def api_watchlist_add():
        data = request.get_json(silent=True) or request.form
        code = (data.get('code') or '').strip()
        if not code:
            return jsonify({'error': 'code is required'}), 400
        try:
            alert_low = _opt_float(data.get('alert_low'))
            alert_high = _opt_float(data.get('alert_high'))
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        if not svc.add_watch(code, note=data.get('note') or '',
                             alert_low=alert_low, alert_high=alert_high):
            return jsonify({'error': 'ETF not found: %s' % code}), 404
        return jsonify({'ok': True, 'code': code}), 201

    @app.route('/api/watchlist/<code>', methods=['PATCH'])
    def api_watchlist_update(code):
        data = request.get_json(silent=True) or request.form
        try:
            fields = {}
            if 'note' in data:
                fields['note'] = data.get('note') or None
            if 'alert_low' in data:
                fields['alert_low'] = _opt_float(data.get('alert_low'))
            if 'alert_high' in data:
                fields['alert_high'] = _opt_float(data.get('alert_high'))
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        # 传入的键一律写入（空串清除阈值），未传入的不改动
        ok = svc.update_watch(code, fields)
        return jsonify({'ok': ok}) if ok else (jsonify({'error': 'update failed'}), 400)

    @app.route('/api/watchlist/<code>', methods=['DELETE'])
    def api_watchlist_remove(code):
        ok = svc.remove_watch(code)
        return jsonify({'ok': ok}) if ok else (jsonify({'error': 'remove failed'}), 400)

    # ---------- 模板辅助 ----------
    @app.context_processor
    def inject_latest_date():
        """所有模板可用 latest_date（页脚展示）。"""
        try:
            return {'latest_date': svc.snapshot()['latest_date']}
        except Exception:
            return {'latest_date': None}

    @app.template_filter('pct')
    def pct_filter(v, digits=2):
        """0.1234 → '12.34%'；None → '-'。"""
        return '-' if v is None else ('%.' + str(digits) + 'f%%') % (v * 100)

    @app.template_filter('num')
    def num_filter(v, digits=2):
        return '-' if v is None else ('%.' + str(digits) + 'f') % v

    @app.template_filter('pct_color')
    def pct_color_filter(v):
        """百分位 → 背景色（绿→黄→红渐变），热力图用。"""
        if v is None:
            return '#eee'
        v = max(0.0, min(1.0, v))
        if v < 0.5:
            # 绿(46,139,87) → 黄(255,215,0)
            t = v / 0.5
            r = int(46 + t * (255 - 46))
            g = int(139 + t * (215 - 139))
            b = int(87 + t * (0 - 87))
        else:
            # 黄(255,215,0) → 红(178,34,34)
            t = (v - 0.5) / 0.5
            r = int(255 + t * (178 - 255))
            g = int(215 + t * (34 - 215))
            b = int(0 + t * (34 - 0))
        return 'rgb(%d,%d,%d)' % (r, g, b)

    @app.template_filter('eva_status')
    def eva_status_filter(stats):
        """着色规则与邮件报告 eva_status 一致：low（绿）/ high（红）/ normal。"""
        if not stats or stats.get('percentile') is None:
            return 'normal'
        p, v, vt = stats['percentile'], stats.get('value'), stats.get('value_type')
        if vt == 'PE' and v is not None and 0 < v < 15:
            return 'low'
        if p < 0.10:
            return 'low'
        if vt == 'PE' and v is not None and v > 50:
            return 'high'
        if p > 0.90:
            return 'high'
        return 'normal'

    return app


def _opt_float(v):
    """可空数字解析：None/空串 → None；非法数字抛 ValueError。"""
    if v is None or v == '':
        return None
    return float(v)
