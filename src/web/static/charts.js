/* 指数详情页：PE 估值通道 + 点位走势合并双坐标图。
   数据由模板注入 window.PE_DATA / PE_BANDS / POINT_DATA（[[date, value], ...]）。
   左 Y 轴 = PE，右 Y 轴 = 点位；点击图例切换显示/隐藏对应系列。 */

(function () {
  'use strict';

  function showAllBoxesMessage(html) {
    document.querySelectorAll('.chart-box').forEach(function (box) {
      box.innerHTML = html;
    });
  }

  if (typeof Chart === 'undefined') {
    showAllBoxesMessage('<p class="empty">图表库未加载（chart.umd.min.js 缺失或加载失败），请检查 static/vendor/ 目录。</p>');
    return;
  }

  function toChartSeries(series) {
    var labels = [], values = [];
    series.forEach(function (p) { labels.push(p[0]); values.push(p[1]); });
    return {labels: labels, values: values};
  }

  function constant(v, len) {
    return Array(len).fill(v);
  }

  try {
    var el = document.getElementById('combinedChart');
    if (!el) return;

    var hasPE = window.PE_DATA && window.PE_DATA.length;
    var hasPT = window.POINT_DATA && window.POINT_DATA.length;
    if (!hasPE && !hasPT) return;

    // 以 PE 为主序列确定 X 轴标签，PE 缺失时用点位
    var main = hasPE ? toChartSeries(window.PE_DATA) : toChartSeries(window.POINT_DATA);
    var labels = main.labels;

    // 对齐点位序列到 PE 的日期轴：若两序列日期不完全一致，
    // Chart.js 按 index 对齐可能错位 → 用 label → index 映射补齐 null
    var ptMap = {};
    if (hasPT) {
      window.POINT_DATA.forEach(function (p) { ptMap[p[0]] = p[1]; });
    }
    var ptValues = labels.map(function (d) {
      return (d in ptMap) ? ptMap[d] : null;
    });

    var datasets = [];

    // PE 主线（左轴）
    if (hasPE) {
      datasets.push({
        label: 'PE',
        data: main.values,
        borderColor: '#1f6fb2',
        borderWidth: 1.5,
        tension: 0,
        yAxisID: 'y',
        pointRadius: 0,
        hitRadius: 4,
      });
    }

    // PE 分位虚线（左轴，与 PE 同轴）
    if (hasPE && window.PE_BANDS && window.PE_BANDS.values) {
      var bandColors = ['#2e8b57', '#7cb342', '#999999', '#d84315'];
      window.PE_BANDS.values.forEach(function (v, i) {
        if (v === null) return;
        datasets.push({
          label: window.PE_BANDS.labels[i] + ' 分位',
          data: constant(v, labels.length),
          borderColor: bandColors[i] || '#bbb',
          borderDash: [6, 4],
          borderWidth: 1,
          pointRadius: 0,
          yAxisID: 'y',
        });
      });
    }

    // 点位线（右轴）
    if (hasPT) {
      datasets.push({
        label: '点位',
        data: ptValues,
        borderColor: '#c77700',
        borderWidth: 1.5,
        tension: 0,
        yAxisID: 'y1',
        pointRadius: 0,
        hitRadius: 4,
        spanGaps: true,   // PE 有但点位缺失的日期不连线打断
      });
    }

    new Chart(el, {
      type: 'line',
      data: {labels: labels, datasets: datasets},
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: {mode: 'index', intersect: false},
        elements: {point: {radius: 0, hitRadius: 4}},
        scales: {
          x: {ticks: {maxTicksLimit: 10, maxRotation: 0}, grid: {display: false}},
          y: {
            position: 'left',
            title: {display: hasPE, text: 'PE', color: '#1f6fb2'},
            ticks: {color: '#1f6fb2'},
          },
          y1: {
            position: 'right',
            title: {display: hasPT, text: '点位', color: '#c77700'},
            ticks: {color: '#c77700'},
            grid: {drawOnChartArea: false},  // 右轴不画水平网格线，避免与左轴重叠
          },
        },
        plugins: {
          legend: {
            display: true,
            position: 'top',
            // 点击图例切换显示/隐藏（Chart.js 默认行为已支持，这里显式声明）
            onClick: function (_e, legendItem, legend) {
              var ci = legend.chart;
              var ds = ci.data.datasets[legendItem.datasetIndex];
              ds.hidden = !ds.hidden;
              ci.update();
            },
          },
          tooltip: {
            callbacks: {title: function (items) { return items[0].label; }},
          },
        },
      },
    });
  } catch (e) {
    showAllBoxesMessage('<p class="empty">图表绘制出错：' + e.message + '</p>');
  }
})();
