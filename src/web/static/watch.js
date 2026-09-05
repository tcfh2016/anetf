/* 关注列表交互：加关注 / 保存备注阈值 / 删除（fetch JSON API） */

function api(url, method, body) {
  return fetch(url, {
    method: method,
    headers: {'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : undefined,
  }).then(function (resp) {
    return resp.json().then(function (data) {
      if (!resp.ok) throw new Error(data.error || ('HTTP ' + resp.status));
      return data;
    });
  });
}

function toast(msg) {
  var el = document.createElement('div');
  el.className = 'toast';
  el.textContent = msg;
  Object.assign(el.style, {
    position: 'fixed', top: '60px', right: '20px', zIndex: 999,
    background: '#333', color: '#fff', padding: '8px 14px',
    borderRadius: '6px', fontSize: '13px',
  });
  document.body.appendChild(el);
  setTimeout(function () { el.remove(); }, 2200);
}

/* 所有页面通用：☆ 关注 按钮 */
document.addEventListener('click', function (ev) {
  var btn = ev.target.closest('.watch-btn');
  if (!btn) return;
  var code = btn.dataset.code;
  if (!code) { toast('该行没有 ETF 代码'); return; }
  api('/api/watchlist', 'POST', {code: code})
    .then(function () {
      btn.textContent = '★ 已关注';
      btn.disabled = true;
      toast('已加入关注: ' + code);
    })
    .catch(function (err) { toast('关注失败: ' + err.message); });
});

/* 关注列表页：保存 / 删除 */
document.addEventListener('click', function (ev) {
  var row = ev.target.closest('tr[data-code]');
  if (!row) return;
  var code = row.dataset.code;

  if (ev.target.closest('.remove-btn')) {
    if (!confirm('确定从关注列表删除 ' + code + ' ？')) return;
    api('/api/watchlist/' + code, 'DELETE')
      .then(function () { row.remove(); toast('已删除 ' + code); })
      .catch(function (err) { toast('删除失败: ' + err.message); });
    return;
  }

  var saveBtn = ev.target.closest('.save-btn');
  if (!saveBtn) return;
  var note = row.querySelector('.w-note').value.trim();
  var lowRaw = row.querySelector('.w-low').value.trim();
  var highRaw = row.querySelector('.w-high').value.trim();
  var body = {note: note, alert_low: lowRaw, alert_high: highRaw};
  api('/api/watchlist/' + code, 'PATCH', body)
    .then(function () { toast('已保存 ' + code); })
    .catch(function (err) { toast('保存失败: ' + err.message); });
});
