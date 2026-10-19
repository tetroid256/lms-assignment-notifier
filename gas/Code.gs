/**
 * LMS(Moodle)の課題をDiscordへ通知するGAS版。
 *
 * 設定はすべて「プロジェクトの設定 → スクリプト プロパティ」に入れる(README参照)。
 *   LMS_BASE             例: https://lms.example.ac.jp
 *   LMS_TOKEN            Moodleのモバイル用トークン
 *   DISCORD_WEBHOOK_URL  通知先チャンネルのWebhook URL
 *   DAYS_AHEAD           定時通知で何日先まで出すか(省略時 7)
 *   WORKLIST_PAST_DAYS   一覧で提出済みを何日前まで遡るか(省略時 14)
 *   WORKLIST_FUTURE_DAYS 一覧で何日先まで出すか(省略時 30)
 *   EXCLUDE_KEYWORDS     名前に含まれていたら除外する語(カンマ区切り)
 *   NOTIFY_HOUR          定時通知の時刻(0-23、省略時 7)
 */

const TZ = 'Asia/Tokyo';
const WEEKDAYS = '月火水木金土日';
const DISCORD_LIMIT = 1900;

// ===== 公開関数(エディタの実行ボタンやトリガーから呼ぶ) =====

/** 初回だけ実行する。トークンが有効かを確認する。 */
function checkToken() {
  const c = conf_();
  const info = callApi_(c, 'core_webservice_get_site_info', {});
  Logger.log('OK: ' + info.sitename + ' / ユーザーID ' + info.userid);
}

/** 毎朝の定時通知。未提出だけをまとめて送る。 */
function dailyNotify() {
  const c = conf_();
  try {
    const data = fetchWorklist_(c, 0, c.daysAhead);
    postDiscord_(c, formatWorklist_(data, 'todo', '定時通知', c.daysAhead, 0));
  } catch (e) {
    postDiscord_(c, ['課題通知の取得に失敗しました: ' + e.message]);
    throw e;
  }
}

/** 未提出と提出済みの両方を、今すぐDiscordへ送る。 */
function sendWorklistNow() {
  const c = conf_();
  const data = fetchWorklist_(c, c.pastDays, c.futureDays);
  postDiscord_(c, formatWorklist_(data, 'both', '課題一覧', c.futureDays, c.pastDays));
}

/** 毎朝 NOTIFY_HOUR 時の定時通知トリガーを登録する(再実行しても重複しない)。 */
function installDailyTrigger() {
  removeTriggers();
  const hour = conf_().hour;
  ScriptApp.newTrigger('dailyNotify').timeBased().everyDays(1).atHour(hour).create();
  Logger.log('毎日 ' + hour + ' 時台に dailyNotify を実行します。');
}

function removeTriggers() {
  ScriptApp.getProjectTriggers().forEach(function (t) { ScriptApp.deleteTrigger(t); });
}

/** ウェブアプリとして公開した場合の画面。アクセスは「自分のみ」にすること。 */
function doGet() {
  const c = conf_();
  const data = fetchWorklist_(c, c.pastDays, c.futureDays);
  const text = formatWorklist_(data, 'both', '課題一覧', c.futureDays, c.pastDays).join('\n');
  return ContentService.createTextOutput(text).setMimeType(ContentService.MimeType.TEXT);
}

// ===== 設定とAPI =====

function conf_() {
  const p = PropertiesService.getScriptProperties().getProperties();
  ['LMS_BASE', 'LMS_TOKEN', 'DISCORD_WEBHOOK_URL'].forEach(function (key) {
    if (!p[key]) throw new Error('スクリプト プロパティ ' + key + ' が未設定です。');
  });
  return {
    base: p.LMS_BASE.replace(/\/+$/, ''),
    token: p.LMS_TOKEN,
    webhook: p.DISCORD_WEBHOOK_URL,
    daysAhead: Number(p.DAYS_AHEAD || 7),
    pastDays: Number(p.WORKLIST_PAST_DAYS || 14),
    futureDays: Number(p.WORKLIST_FUTURE_DAYS || 30),
    excludes: (p.EXCLUDE_KEYWORDS || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean),
    hour: Number(p.NOTIFY_HOUR || 7)
  };
}

function callApi_(c, fn, params) {
  const payload = Object.assign({ wstoken: c.token, wsfunction: fn, moodlewsrestformat: 'json' }, params);
  const res = UrlFetchApp.fetch(c.base + '/webservice/rest/server.php', {
    method: 'post',
    payload: payload,
    muteHttpExceptions: true
  });
  if (res.getResponseCode() >= 400) throw new Error('HTTP ' + res.getResponseCode());
  const data = JSON.parse(res.getContentText());
  if (data && data.exception) throw new Error(data.errorcode + ': ' + data.message);
  return data;
}

// ===== 取得 =====

function cleanName_(name) {
  return name.trim().replace(/の(提出期限|期限|終了)$/, '').trim().replace(/^[「」 ]+|[「」 ]+$/g, '');
}

function shortCourse_(name) {
  return name.split('（')[0].split('(')[0].trim();
}

function isExcluded_(c, name) {
  return c.excludes.some(function (w) { return name.indexOf(w) >= 0; });
}

/** カレンダーの行動イベント(操作が必要なもの)。未提出の課題や小テストが入る。 */
function fetchActionEvents_(c, days, onlyNonAssign) {
  const now = Math.floor(Date.now() / 1000);
  const data = callApi_(c, 'core_calendar_get_action_events_by_timesort', {
    timesortfrom: now,
    timesortto: now + days * 86400,
    limitnum: 50
  });
  const tasks = [];
  (data.events || []).forEach(function (e) {
    const action = e.action || {};
    if (action.actionable === false) return;
    if (onlyNonAssign && e.modulename === 'assign') return;
    const name = cleanName_(e.name || '');
    if (isExcluded_(c, name)) return;
    tasks.push({ name: name, due: new Date(e.timesort * 1000), course: shortCourse_((e.course || {}).fullname || '') });
  });
  return tasks;
}

function submissionState_(status) {
  const attempt = status.lastattempt || {};
  let submitted = !!attempt.submitted;
  ['submission', 'teamsubmission'].forEach(function (key) {
    const sub = attempt[key] || {};
    if (sub.status === 'submitted') submitted = true;
  });
  return submitted;
}

/** {todo, done, note} を返す。課題APIが使えなければ、未提出のみで続行する。 */
function fetchWorklist_(c, pastDays, futureDays) {
  const now = Math.floor(Date.now() / 1000);
  const from = now - pastDays * 86400;
  const to = now + futureDays * 86400;
  let todo = [], done = [], note = '';
  try {
    const userid = callApi_(c, 'core_webservice_get_site_info', {}).userid;
    const courses = callApi_(c, 'core_enrol_get_users_courses', { userid: userid })
      .filter(function (x) { return !x.enddate || x.enddate > from; });
    const params = {};
    courses.forEach(function (x, i) { params['courseids[' + i + ']'] = x.id; });
    const listing = callApi_(c, 'mod_assign_get_assignments', params);

    (listing.courses || []).forEach(function (course) {
      (course.assignments || []).forEach(function (a) {
        const name = (a.name || '').trim();
        if (!a.duedate || a.duedate < from || a.duedate > to || isExcluded_(c, name)) return;
        const status = callApi_(c, 'mod_assign_get_submission_status', { assignid: a.id });
        const item = { name: name, due: new Date(a.duedate * 1000), course: shortCourse_(course.fullname || '') };
        (submissionState_(status) ? done : todo).push(item);
      });
    });
    todo = todo.concat(fetchActionEvents_(c, futureDays, true));
  } catch (e) {
    note = '提出済みの取得に失敗したため、未提出のみ表示しています (' + e.message + ')';
    done = [];
    todo = fetchActionEvents_(c, futureDays, false);
  }
  todo.sort(function (a, b) { return a.due - b.due; });
  done.sort(function (a, b) { return b.due - a.due; });
  return { todo: todo, done: done, note: note };
}

// ===== 整形と送信 =====

function fmtDue_(d) {
  const wd = WEEKDAYS.charAt(Number(Utilities.formatDate(d, TZ, 'u')) - 1);
  return Utilities.formatDate(d, TZ, 'MM/dd') + '(' + wd + ') ' + Utilities.formatDate(d, TZ, 'HH:mm');
}

function dayDiff_(due, now) {
  const key = function (d) { return Date.parse(Utilities.formatDate(d, TZ, 'yyyy-MM-dd') + 'T00:00:00Z'); };
  return Math.round((key(due) - key(now)) / 86400000);
}

/** Discordの文字数制限に収まるよう、複数メッセージに分けて返す。 */
function formatWorklist_(data, show, title, futureDays, pastDays) {
  const now = new Date();
  const wd = WEEKDAYS.charAt(Number(Utilities.formatDate(now, TZ, 'u')) - 1);
  const lines = [Utilities.formatDate(now, TZ, 'MM/dd') + '(' + wd + ') ' + title];
  if (data.note) lines.push('注意: ' + data.note);

  if (show === 'both' || show === 'todo') {
    lines.push('', '【未提出】' + data.todo.length + '件 (今後' + futureDays + '日以内 / 期限超過を含む)');
    if (!data.todo.length) lines.push('なし');
    data.todo.forEach(function (t) {
      const left = dayDiff_(t.due, now);
      const when = t.due < now ? '期限超過' : left === 0 ? '今日' : left === 1 ? '明日' : left + '日後';
      lines.push('・' + t.name, '　' + fmtDue_(t.due) + ' (' + when + ')  ' + t.course);
    });
  }
  if (show === 'both' || show === 'done') {
    lines.push('', '【提出済み】' + data.done.length + '件 (期限が過去' + pastDays + '日〜今後' + futureDays + '日のもの)');
    if (!data.done.length) lines.push('なし');
    data.done.forEach(function (t) {
      lines.push('・' + t.name, '　期限 ' + fmtDue_(t.due) + '  ' + t.course);
    });
  }

  const chunks = [];
  let current = '';
  lines.forEach(function (line) {
    if (current.length + line.length + 1 > DISCORD_LIMIT) { chunks.push(current); current = ''; }
    current += line + '\n';
  });
  chunks.push(current);
  return chunks;
}

function postDiscord_(c, chunks) {
  chunks.forEach(function (content) {
    const res = UrlFetchApp.fetch(c.webhook, {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify({ content: content }),
      muteHttpExceptions: true
    });
    if (res.getResponseCode() >= 300) throw new Error('Discord送信に失敗 HTTP ' + res.getResponseCode());
  });
}
